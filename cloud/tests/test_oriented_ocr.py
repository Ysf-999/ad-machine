"""Geometry, original gate boundaries and fail-closed worker substitution."""
import hashlib,importlib,math,pathlib,tempfile,types,unittest
from disk_test_support import DiskIndependentTestCase
from cloud.ocr import OCRFailure,SOURCE,tilt
try:
    from cloud.ocr import oriented
except ImportError:
    oriented=None

class OrientedOCRTests(DiskIndependentTestCase):
    def setUp(self):
        super().setUp();self.assertIsNotNone(oriented,'Oriented backend must exist before candidate inference')
    def test_portrait_geometry_retains_signed_angle_and_corner_edge_height(self):
        angle=10.;w,h=720,1280;length=300.;height=30.;a=math.radians(angle)
        tl=(100.,300.);tr=(100+length*math.cos(a),300-length*math.sin(a));bl=(100+height*math.sin(a),300+height*math.cos(a));br=(tr[0]+bl[0]-tl[0],tr[1]+bl[1]-tl[1])
        row=oriented.polygon_tuple('CATS',.499,[tl,tr,br,bl],w,h)
        self.assertAlmostEqual(row[2],10.,10);self.assertAlmostEqual(row[3],30/1280,10);self.assertEqual(row[1],.499)
        normalized=[(x/w,y/h) for x,y in [tl,tr,br,bl]]
        converted=oriented.polygon_tuple('CATS',.499,normalized,w,h,normalized=True)
        self.assertEqual(row[:2],converted[:2]);self.assertAlmostEqual(row[2],converted[2],10);self.assertAlmostEqual(row[3],converted[3],10)
    def test_angle_confidence_height_letters_and_gap_boundaries_use_original_rule(self):
        for a in [0,1.49,1.5,1.51,2,10,24.99,25,25.01,90]:
            for sign in [1,-1]:
                self.assertEqual(bool(tilt([[('CATS',.5,sign*a,.022)]]*2)),1.5<a<25)
        for conf in [.499,.5,.501]:
            for height in [.0219,.022,.0221]:
                for word in ['CAT','CATS','C4A7T!','C4A7T!S','1234','!!!']:
                    letters=sum(c.isascii() and c.isalpha() for c in word)
                    self.assertEqual(bool(tilt([[(word,conf,2,height)]]*2)),conf>=.5 and height>=.022 and letters>=4)
        hit=[('CATS',.8,2,.1)]
        self.assertFalse(tilt([hit]));self.assertTrue(tilt([hit,hit]));self.assertFalse(tilt([hit,[],hit]))
        self.assertTrue(tilt([hit+hit]))
        # Exercise the unchanged <= comparator with synthetic hit timestamps;
        # real1fps samples themselves have only integer-second gaps.
        from cloud.ocr import original_functions
        for gap,expected in [(1.5,True),(1.500001,False)]:
            functions=original_functions();functions['ocr_boxes']=lambda _:hit
            functions['enumerate']=lambda _,gap=gap:iter([(0,'a'),(gap,'b')])
            self.assertEqual(bool(functions['check_tilt'](['a','b'],1.)),expected)
    def test_invalid_geometry_nonfinite_and_bad_confidence_are_not_checked(self):
        for poly in [[],[[0,0]]*3,[[0,0],[float('nan'),0],[3,3],[0,3]]]:
            with self.assertRaises(OCRFailure):oriented.polygon_tuple('CATS',.8,poly,720,1280)
        with self.assertRaises(OCRFailure):oriented.polygon_tuple('CATS',2,[[0,0],[30,0],[30,5],[0,5]],720,1280)
    def test_missing_models_fail_before_engine_import_or_inference(self):
        with self.assertRaises(OCRFailure):oriented.RapidBackend('/not/a/model/root',{'models':[{'file':'missing.onnx','sha256':'0'*64,'bytes':1}]},'/not/a/config')
    def test_empty_corrupt_images_and_inference_exceptions_fail_closed(self):
        from PIL import Image
        with tempfile.TemporaryDirectory(dir=pathlib.Path(__file__).resolve().parents[1]/'.scratch') as td:
            p=pathlib.Path(td);(p/'empty.png').write_bytes(b'');(p/'corrupt.png').write_bytes(b'not a png')
            Image.new('RGB',(720,1280),'white').save(p/'blank.png')
            backend=oriented.RapidBackend.__new__(oriented.RapidBackend)
            class Broken:
                def load_img(self,path):raise ValueError('failed inference')
            backend.engine=Broken()
            for filename in ['missing.png','empty.png','corrupt.png','blank.png']:
                with self.assertRaises(OCRFailure):backend.read(p/filename)
    def test_unexpected_detector_none_is_not_empty_success(self):
        from PIL import Image
        import numpy as np
        with tempfile.TemporaryDirectory(dir=pathlib.Path(__file__).resolve().parents[1]/'.scratch') as td:
            p=pathlib.Path(td)/'blank.png';Image.new('RGB',(10,10),'white').save(p)
            engine=types.SimpleNamespace(load_img=lambda _:np.zeros((10,10,3)),preprocess=lambda a:(a,1.,1.),maybe_add_letterbox=lambda a,r:(a,r),text_det=lambda a:(None,0.))
            b=oriented.RapidBackend.__new__(oriented.RapidBackend);b.engine=engine
            with self.assertRaises(OCRFailure):b.read(p)
            engine.text_det=lambda a:(np.array([]),.1)
            self.assertEqual(b.read(p),[])
    def test_worker_substitution_preserves_original_file_and_raises_on_backend_failure(self):
        before=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
        class Broken:
            def read(self,path):raise OCRFailure('not checked')
        namespace,receipt=oriented.inject_preflight(SOURCE,before,Broken())
        with self.assertRaises(OCRFailure):namespace['check_tilt'](['input'],1.)
        self.assertEqual(before,hashlib.sha256(SOURCE.read_bytes()).hexdigest());self.assertEqual(receipt['source_sha256'],before)
        with self.assertRaises(OCRFailure):oriented.inject_preflight(SOURCE,'0'*64,Broken())

class OCRAcceptanceTests(DiskIndependentTestCase):
    def test_diagnostic_tuple_difference_does_not_change_predeclared_group_verdict_rule(self):
        self.assertIsNotNone(oriented)
        base=[[('AcmeBrand',.8,2,.1)]]*2;other=[[('AcmeBrand',.7,2.4,.11)]]*2
        r=oriented.accept_master('bad',base,other)
        self.assertTrue(r['acceptance']);self.assertFalse(r['strict_diagnostic_parity'])
        self.assertFalse(oriented.accept_master('bad',base,[[],[]])['acceptance'])
        self.assertFalse(oriented.accept_master('clean',[[],[]],other)['acceptance'])
