"""Content-addressed files; no credentials, SDK construction, or implicit network.

S3Storage accepts a boto3-shaped client, including a fully offline fake. Each
external operation requires explicit authorization and caller-supplied known
cost bounds. Storage roots and download directories must be private to workers.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping

_CHUNK = 1024 * 1024


class IntegrityError(ValueError):
    pass


class StorageAuthorizationError(PermissionError):
    pass


def _digest(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError('expected a lowercase SHA-256 digest')
    return value


def _relative(value: str) -> str:
    if (not isinstance(value, str) or not value or '\\' in value or
            any(ord(c) < 32 for c in value) or
            any(p in ('', '.', '..') for p in value.split('/'))):
        raise ValueError('expected a safe relative POSIX path')
    return value


def _money(value) -> Decimal:
    try:
        if isinstance(value, (bool, float)):
            raise ValueError('use integer, string, or Decimal cost bounds')
        result = Decimal(value)
    except (InvalidOperation, TypeError):
        raise ValueError('invalid cost bound') from None
    if not result.is_finite() or result < 0:
        raise ValueError('cost bounds must be finite and nonnegative')
    return result


@dataclass(frozen=True)
class ObjectRef:
    sha256: str
    size: int

    def __post_init__(self):
        _digest(self.sha256)
        if type(self.size) is not int or self.size < 0:
            raise ValueError('size must be a nonnegative integer')

    @property
    def key(self) -> str:
        return f'objects/sha256/{self.sha256[:2]}/{self.sha256}'

    def to_dict(self):
        return {'sha256': self.sha256, 'size': self.size, 'key': self.key}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != {'sha256', 'size', 'key'}:
            raise ValueError('invalid object reference')
        result = cls(value['sha256'], value['size'])
        if value['key'] != result.key:
            raise ValueError('object key does not match its digest')
        return result


@dataclass(frozen=True)
class Manifest:
    entries: Mapping[str, ObjectRef]

    def __post_init__(self):
        entries = dict(self.entries)
        for name, ref in entries.items():
            _relative(name)
            if not isinstance(ref, ObjectRef):
                raise ValueError('manifest entries must be ObjectRefs')
        # Copy caller data so later caller mutation cannot change a saved manifest.
        from types import MappingProxyType
        object.__setattr__(self, 'entries', MappingProxyType(entries))

    def to_json(self) -> str:
        return json.dumps({'version': 1, 'entries': {
            name: ref.to_dict() for name, ref in sorted(self.entries.items())}},
            sort_keys=True, separators=(',', ':')) + '\n'

    @classmethod
    def from_json(cls, raw: str):
        value = json.loads(raw)
        if (not isinstance(value, dict) or set(value) != {'version', 'entries'} or
                type(value['version']) is not int or value['version'] != 1 or
                not isinstance(value['entries'], dict)):
            raise ValueError('invalid manifest')
        return cls({name: ObjectRef.from_dict(ref) for name, ref in value['entries'].items()})

    def save(self, path):
        with _atomic_file(Path(path)) as stream:
            stream.write(self.to_json().encode())


def _fsync_dir(path: Path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _no_symlinks(path: Path):
    # Private directories are a requirement: this check is not protection against
    # another OS user concurrently replacing ancestors between syscalls.
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('symlinks are not allowed in storage paths')


@contextmanager
def _atomic_file(path: Path):
    _no_symlinks(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.storage-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w+b') as stream:
            yield stream
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        _fsync_dir(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def _copy(stream, dest) -> ObjectRef:
    digest = hashlib.sha256(); size = 0
    while chunk := stream.read(_CHUNK):
        digest.update(chunk); size += len(chunk)
        dest.write(chunk)
    return ObjectRef(digest.hexdigest(), size)


def _verify(stream, expected: ObjectRef, dest=None):
    class Sink:
        def write(self, data):
            pass
    actual = _copy(stream, dest if dest is not None else Sink())
    if actual != expected:
        raise IntegrityError('object bytes do not match SHA-256 and size')


@contextmanager
def _snapshot(path, expected_sha256=None):
    from hygiene import require_space,SCRATCH
    require_space(write_bytes=2*Path(path).stat().st_size)
    if expected_sha256 is not None:
        _digest(expected_sha256)
    # Snapshot first: a source changing while it is copied still produces a
    # self-consistent object, and expected_sha256 detects stale input manifests.
    _no_symlinks(Path(path).absolute())
    with open(path, 'rb') as src, tempfile.TemporaryFile(dir=SCRATCH) as stream:
        ref = _copy(src, stream)
        if expected_sha256 is not None and ref.sha256 != expected_sha256:
            raise IntegrityError('source hash does not match expected SHA-256')
        stream.seek(0)
        yield ref, stream


class LocalStorage:
    def __init__(self, root):
        self.root = Path(root).absolute()
        _no_symlinks(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, ref: ObjectRef):
        if not isinstance(ref, ObjectRef):
            raise ValueError('expected ObjectRef')
        path = self.root / ref.key
        _no_symlinks(path)
        return path

    def put(self, source, *, expected_sha256=None) -> ObjectRef:
        with _snapshot(source, expected_sha256) as (ref, stream):
            path = self._path(ref)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                with path.open('rb') as existing:
                    _verify(existing, ref)
                return ref
            fd, name = tempfile.mkstemp(prefix='.storage-', suffix='.tmp', dir=path.parent)
            try:
                with os.fdopen(fd, 'wb') as output:
                    _verify(stream, ref, output)
                    output.flush(); os.fsync(output.fileno())
                try:
                    # An atomic, no-overwrite publication. Concurrent identical
                    # puts converge; partially copied objects are never visible.
                    os.link(name, path)
                    _fsync_dir(path.parent)
                except FileExistsError:
                    with path.open('rb') as existing:
                        _verify(existing, ref)
            finally:
                Path(name).unlink(missing_ok=True)
            return ref

    def get(self, ref: ObjectRef, destination) -> Path:
        path = self._path(ref)
        from hygiene import require_space
        require_space(write_bytes=ref.size)
        with path.open('rb') as source, _atomic_file(Path(destination)) as dest:
            _verify(source, ref, dest)
        return Path(destination)


class S3Storage:
    """Injected client supports get_object and conditional put_object.

    No SDK is imported, no environment is read. ``costs`` contains caller-known
    upper bounds in the same credit unit as credit_cap, for 'get' and 'put'.
    Bounds include requests/transfer/storage as applicable; unknown != zero.
    Reservations are conservative, instance-local, and not refunded on errors.
    A real distributed deployment must use a shared budget authority instead.
    """
    def __init__(self, client, bucket: str, *, prefix='', go=False,
                 credit_cap=None, costs=None):
        if not isinstance(bucket, str) or not bucket or '/' in bucket or '\\' in bucket:
            raise ValueError('expected a bucket name')
        self.client = client; self.bucket = bucket
        self.prefix = _relative(prefix) if prefix else ''
        self.go = go is True
        self.credit_cap = _money(credit_cap) if credit_cap is not None else None
        self.costs = {k: _money(v) for k, v in (costs or {}).items()}
        self.reserved = Decimal(0)
        self._lock = threading.Lock()

    def _authorize(self, operation):
        with self._lock:
            if not self.go or self.credit_cap is None or operation not in self.costs:
                raise StorageAuthorizationError('explicit go, credit cap and known operation cost required')
            amount = self.costs[operation]
            if self.reserved + amount > self.credit_cap:
                raise StorageAuthorizationError('storage credit cap exceeded')
            self.reserved += amount

    def _key(self, ref):
        if not isinstance(ref, ObjectRef):
            raise ValueError('expected ObjectRef')
        return f'{self.prefix}/{ref.key}' if self.prefix else ref.key

    @staticmethod
    def _error_code(exc):
        return str(getattr(exc, 'response', {}).get('Error', {}).get('Code', ''))

    def _existing(self, ref, *, missing_ok=False, dest=None):
        self._authorize('get')
        try:
            result = self.client.get_object(Bucket=self.bucket, Key=self._key(ref))
        except Exception as exc:
            if missing_ok and self._error_code(exc) in ('NoSuchKey', '404', 'NotFound'):
                return False
            raise
        stream = result['Body']
        try:
            _verify(stream, ref, dest)
        finally:
            stream.close()
        return True

    def put(self, source, *, expected_sha256=None) -> ObjectRef:
        with _snapshot(source, expected_sha256) as (ref, stream):
            if self._existing(ref, missing_ok=True):
                return ref
            self._authorize('put')
            try:
                self.client.put_object(Bucket=self.bucket, Key=self._key(ref), Body=stream,
                                       ContentLength=ref.size, IfNoneMatch='*',
                                       Metadata={'sha256': ref.sha256})
            except Exception as exc:
                if self._error_code(exc) not in ('PreconditionFailed', '412'):
                    # In particular, permission/auth/network errors never become
                    # 'missing' and never trigger an unconditional overwrite.
                    raise
                self._existing(ref)
            return ref

    def get(self, ref: ObjectRef, destination) -> Path:
        self._key(ref)  # Validate before touching a destination.
        with _atomic_file(Path(destination)) as dest:
            self._existing(ref, dest=dest)
        return Path(destination)


def sync_files(backend, root, names, *, manifest_path=None) -> Manifest:
    """Sync explicitly declared relative files, then atomically publish manifest.

    Objects already written are harmless if a later file fails. The previous
    manifest remains intact. Repeated bytes share one CAS object across ads.
    """
    root = Path(root).absolute()
    _no_symlinks(root)
    entries = {}
    for name in names:
        _relative(name)
        if name in entries:
            raise ValueError('duplicate manifest path')
        path = root / name
        _no_symlinks(path)
        entries[name] = backend.put(path)
    manifest = Manifest(entries)
    if manifest_path is not None:
        manifest.save(manifest_path)
    return manifest
