"""No network or credentials: the S3 contract is exercised by an injected fake."""
from disk_test_support import DiskIndependentTestCase

import hashlib
import io
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from cloud import storage


class FakeS3Error(Exception):
    def __init__(self, code):
        self.response = {'Error': {'Code': code}}


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.uploads = 0
        self.lock = threading.Lock()

    def get_object(self, *, Bucket, Key):
        with self.lock:
            if (Bucket, Key) not in self.objects:
                raise FakeS3Error('NoSuchKey')
            body = self.objects[Bucket, Key]
        return {'Body': io.BytesIO(body), 'ContentLength': len(body)}

    def put_object(self, *, Bucket, Key, Body, IfNoneMatch, **kwargs):
        assert IfNoneMatch == '*'
        with self.lock:
            if (Bucket, Key) in self.objects:
                raise FakeS3Error('PreconditionFailed')
            self.objects[Bucket, Key] = Body.read()
            self.uploads += 1
        return {}


class StorageTests(DiskIndependentTestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / '.scratch'
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.client = FakeS3()

    def backends(self):
        return [storage.LocalStorage(self.root / 'objects'),
                storage.S3Storage(self.client, 'fake', prefix='test', go=True,
                                  credit_cap='0', costs={'get': '0', 'put': '0'})]

    def test_round_trip_upload_once_and_integrity(self):
        src = self.root / 'clip.bin'; src.write_bytes(b'footage' * 100)
        for backend in self.backends():
            with self.subTest(backend=type(backend).__name__):
                ref = backend.put(src)
                self.assertEqual(ref.sha256, hashlib.sha256(src.read_bytes()).hexdigest())
                self.assertEqual(backend.put(src), ref)
                dest = self.root / 'output.bin'
                backend.get(ref, dest)
                self.assertEqual(dest.read_bytes(), src.read_bytes())
                with self.assertRaises(storage.IntegrityError):
                    backend.put(src, expected_sha256='0' * 64)
        self.assertEqual(self.client.uploads, 1)

    def test_concurrent_upload_once(self):
        src = self.root / 'source'; src.write_bytes(b'x' * 10000)
        for backend in self.backends():
            with ThreadPoolExecutor(max_workers=12) as pool:
                refs = list(pool.map(lambda _: backend.put(src), range(30)))
            self.assertEqual(len(set(refs)), 1)
        self.assertEqual(self.client.uploads, 1)

    def test_safe_keys_and_manifest_paths(self):
        backend = storage.LocalStorage(self.root / 'store')
        for digest in ('../x', 'a' * 63, 'A' * 64, 'z' * 64, '/tmp/x'):
            with self.assertRaises(ValueError):
                storage.ObjectRef(digest, 1)
        for name in ('../x', '/x', 'a/../x', 'a//x', 'a\\x', '.', 'a/./b', 'x\x00'):
            with self.assertRaises(ValueError):
                storage.Manifest({name: storage.ObjectRef('a' * 64, 1)})
        for prefix in ('../bucket', '/root', 'a//b', 'a\\b'):
            with self.assertRaises(ValueError):
                storage.S3Storage(self.client, 'fake', prefix=prefix)
        outside = self.root / 'outside'; outside.write_bytes(b'outside')
        source = self.root / 'source'; source.mkdir(); (source / 'escape').symlink_to(outside)
        with self.assertRaises(ValueError):
            storage.sync_files(backend, source, ['escape'])

    def test_manifest_deduplicates_and_is_atomic(self):
        src = self.root / 'source'; src.mkdir()
        (src / 'a').write_bytes(b'same'); (src / 'b').write_bytes(b'same')
        backend = self.backends()[1]
        path = self.root / 'manifest.json'
        manifest = storage.sync_files(backend, src, ['a', 'b'], manifest_path=path)
        self.assertEqual(self.client.uploads, 1)
        self.assertEqual(manifest.entries['a'], manifest.entries['b'])
        self.assertEqual(storage.Manifest.from_json(path.read_text()), manifest)
        self.assertNotIn(str(src), path.read_text())
        before = path.read_bytes()
        with self.assertRaises(FileNotFoundError):
            storage.sync_files(backend, src, ['missing'], manifest_path=path)
        self.assertEqual(path.read_bytes(), before)
        malformed = json.loads(before); malformed['entries']['a']['key'] = '../unsafe'
        with self.assertRaises(ValueError):
            storage.Manifest.from_json(json.dumps(malformed))

    def test_corruption_does_not_replace_download_destination(self):
        source = self.root / 'source'; source.write_bytes(b'good')
        for backend in self.backends():
            ref = backend.put(source)
            if isinstance(backend, storage.LocalStorage):
                (backend.root / ref.key).write_bytes(b'evil')
            else:
                self.client.objects['fake', 'test/' + ref.key] = b'evil'
            dest = self.root / 'dest'; dest.write_bytes(b'preserved')
            with self.assertRaises(storage.IntegrityError):
                backend.get(ref, dest)
            self.assertEqual(dest.read_bytes(), b'preserved')
            with self.assertRaises(storage.IntegrityError):
                backend.put(source)

    def test_atomic_local_failure_and_symlink_refusal(self):
        backend = storage.LocalStorage(self.root / 'store')
        src = self.root / 'src'; src.write_bytes(b'data')
        with patch('cloud.storage.os.link', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                backend.put(src)
        self.assertEqual(list(backend.root.rglob('*.tmp')), [])
        backend = storage.LocalStorage(self.root / 'symlink-store')
        outside = self.root / 'outside'; outside.mkdir()
        (backend.root / 'objects').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            backend.put(src)
        self.assertEqual(list(outside.iterdir()), [])

    def test_s3_go_and_known_budget_are_required(self):
        src = self.root / 'src'; src.write_bytes(b'data')
        for kwargs in ({}, {'go': True}, {'go': True, 'credit_cap': '0'},
                       {'go': True, 'credit_cap': '1', 'costs': {'get': '0'}}):
            backend = storage.S3Storage(self.client, 'fake', **kwargs)
            with self.assertRaises(storage.StorageAuthorizationError):
                backend.put(src)
        self.assertEqual(self.client.uploads, 0)
        backend = storage.S3Storage(self.client, 'fake', go=True, credit_cap='1',
                                    costs={'get': '1', 'put': '1'})
        with self.assertRaises(storage.StorageAuthorizationError):
            backend.put(src)
        self.assertEqual(self.client.uploads, 0)


if __name__ == '__main__':
    unittest.main()
