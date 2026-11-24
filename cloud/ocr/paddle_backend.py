"""PaddleOCR2 original detector geometry, explicit offline CPU models only."""
import json,math,pathlib
from cloud.ocr import Backend,OCRFailure
from cloud.ocr.oriented import polygon_tuple,sha
C=pathlib.Path(__file__).resolve().parents[1]
def thread_limited_config(factory):
    def configured(*args,**kwargs):
        config=factory(*args,**kwargs);config.set_cpu_math_library_num_threads(2);return config
    return configured
class PaddleBackend(Backend):
    name='paddleocr-2.10.0-paddle3-cpu-original-polygons'
    def __init__(self,manifest,config):
        self.manifest=manifest;self.verify_models()
        try:
            if sha(config)!=manifest['config_sha256']:raise OCRFailure('Paddle config hash mismatch; not checked')
            settings=json.loads(pathlib.Path(config).read_text())
            for name in ['det_model_dir','rec_model_dir']:settings[name]=str(C/settings[name])
            import cv2,paddle
            import importlib
            package=importlib.import_module('paddleocr.paddleocr')
            from paddleocr.tools.infer.predict_system import TextSystem,sorted_boxes,get_rotate_crop_image
            cv2.setNumThreads(2);paddle.set_device('cpu')
            if settings['use_angle_cls'] is not False:raise OCRFailure('Orientation classifier must stay disabled')
            params=package.parse_args(mMain=False);vars(params).update(settings)
            params.rec_image_shape='3, 48, 320'
            params.rec_char_dict_path=str(pathlib.Path(package.__file__).parent/package.get_model_config('OCR','PP-OCRv4','rec','ch')['dict_path'])
            # Native TextSystem conditionally creates the classifier only when
            # enabled. Avoid the convenience wrapper's unconditional download of
            # a classifier that this fixed experiment never invokes.
            # Upstream sets cpu_threads only in its MKLDNN branch. Keep MKLDNN
            # disabled on Mac and set the same supported Config field before
            # predictor creation, without changing any detector/model setting.
            original=paddle.inference.Config
            paddle.inference.Config=thread_limited_config(original)
            try:self.engine=TextSystem(params)
            finally:paddle.inference.Config=original
            self.sort=sorted_boxes;self.crop=get_rotate_crop_image;self.raw=[]
        except OCRFailure:raise
        except Exception as exc:raise OCRFailure(f'Paddle runtime unavailable; not checked ({type(exc).__name__}: {str(exc)[:400]})') from None
    def verify_models(self):
        if {m.get('kind') for m in self.manifest['models']}!={'det','rec'}:raise OCRFailure('Exact required Paddle detector/recognizer manifest missing; not checked')
        for model in self.manifest['models']:
            for row in model['members']:
                path=C/row['file']
                if not path.is_file() or path.stat().st_size!=row['bytes'] or sha(path)!=row['sha256']:raise OCRFailure('Paddle model missing/hash mismatch; not checked')
    def infer(self,path):
        from PIL import Image
        import numpy as np
        with Image.open(path) as image:
            image.load();img=np.asarray(image.convert('RGB'))[:,:,::-1].copy()
        h,w=img.shape[:2]
        if not h or not w:raise OCRFailure('Empty decoded image; not checked')
        boxes,elapsed=self.engine.text_detector(img)
        if boxes is None or not math.isfinite(float(elapsed)):raise OCRFailure('Paddle detection failed; not checked')
        if len(boxes)==0:self.raw=[];return []
        boxes=self.sort(boxes)
        # Recognition rectifies only crop pixels. The original detector boxes
        # below are never replaced by the rectified crop's rectangle.
        crops=[self.crop(img,box.copy()) for box in boxes]
        recognized,_=self.engine.text_recognizer(crops)
        if recognized is None or len(recognized)!=len(boxes):raise OCRFailure('Paddle recognition incomplete; not checked')
        self.raw=[];rows=[]
        for polygon,result in zip(boxes,recognized):
            row=polygon_tuple(result[0],result[1],polygon,w,h)
            self.raw.append({'polygon':[[float(x),float(y)] for x,y in polygon],'text':row[0],'confidence':row[1]});rows.append(row)
        return rows
