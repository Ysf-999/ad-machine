import pathlib,tempfile,types,unittest
from disk_test_support import DiskIndependentTestCase
from cloud.ocr import OCRFailure
try:
    from cloud.ocr.paddle_backend import PaddleBackend,thread_limited_config
except ImportError:
    PaddleBackend=None;thread_limited_config=None
class PaddleBackendTests(DiskIndependentTestCase):
    def setUp(self):
        super().setUp();self.assertIsNotNone(PaddleBackend,'Second candidate needs explicit fail-closed backend')
    def test_missing_default_model_stops_before_runtime_import(self):
        with self.assertRaises(OCRFailure):PaddleBackend({'models':[{'members':[{'file':'missing.pdmodel','bytes':1,'sha256':'0'*64}]}]},'/missing/config.json')
    def test_cpu_threads_are_fixed_even_when_upstream_skips_mkldnn_branch(self):
        self.assertIsNotNone(thread_limited_config)
        class Config:
            def __init__(self,*args):self.args=args;self.threads=None
            def set_cpu_math_library_num_threads(self,value):self.threads=value
        obj=thread_limited_config(Config)('model','params')
        self.assertEqual(obj.threads,2);self.assertEqual(obj.args,('model','params'))
    def test_detector_error_none_and_corrupt_image_never_pass(self):
        from PIL import Image
        import numpy as np
        with tempfile.TemporaryDirectory(dir=pathlib.Path(__file__).resolve().parents[1]/'.scratch') as td:
            p=pathlib.Path(td);Image.new('RGB',(10,10),'white').save(p/'blank.png');(p/'empty.png').write_bytes(b'')
            b=PaddleBackend.__new__(PaddleBackend);b.engine=types.SimpleNamespace(text_detector=lambda _:(None,.1))
            for path in [p/'blank.png',p/'empty.png',p/'missing.png']:
                with self.assertRaises(OCRFailure):b.read(path)
            b.engine.text_detector=lambda _:(np.array([]),.1)
            self.assertEqual(b.read(p/'blank.png'),[])
            def broken(_):raise RuntimeError('native inference failure')
            b.engine.text_detector=broken
            with self.assertRaises(OCRFailure):b.read(p/'blank.png')
    def test_low_score_and_original_polygon_are_not_filtered_or_rectified(self):
        from PIL import Image
        import numpy as np
        with tempfile.TemporaryDirectory(dir=pathlib.Path(__file__).resolve().parents[1]/'.scratch') as td:
            p=pathlib.Path(td)/'input.png';Image.new('RGB',(720,1280),'white').save(p)
            boxes=np.array([[[100,100],[400,90],[401,120],[101,130]]],dtype=np.float32)
            b=PaddleBackend.__new__(PaddleBackend)
            b.engine=types.SimpleNamespace(text_detector=lambda _:(boxes,.1),text_recognizer=lambda _:([('CATS',.499)],.1))
            b.sort=lambda rows:rows;b.crop=lambda image,box:image
            row=b.read(p)[0];self.assertEqual(row[1],.499);self.assertGreater(row[2],1.5)
            self.assertEqual(b.raw[0]['polygon'],boxes[0].tolist())
