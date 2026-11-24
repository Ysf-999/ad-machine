"""Original-image oriented OCR and fail-closed injection; no shared-tool mutation."""
from __future__ import annotations
import hashlib,json,math,pathlib,re
from cloud.ocr import Backend,OCRFailure,tuples,tilt,compare_outputs

def sha(path):
    with pathlib.Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def polygon_tuple(text,confidence,polygon,width,height,*,normalized=False):
    try:
        if width<=0 or height<=0 or len(polygon)!=4 or any(len(p)!=2 for p in polygon):raise ValueError()
        points=[(float(p[0])*(width if normalized else 1),float(p[1])*(height if normalized else 1)) for p in polygon]
        if not all(math.isfinite(v) for p in points for v in p):raise ValueError()
        tl,tr,br,bl=points
        if math.dist(tl,tr)<=0 or math.dist(tl,bl)<=0:raise ValueError()
        if isinstance(confidence,bool):raise ValueError()
        row=(text,float(confidence),math.degrees(math.atan2(-(tr[1]-tl[1]),tr[0]-tl[0])),math.dist(tl,bl)/height)
        return tuples([row])[0]
    except (TypeError,ValueError,IndexError,OverflowError):raise OCRFailure('Invalid oriented polygon; not checked') from None

class RapidBackend(Backend):
    name='rapidocr-onnxruntime-1.4.4-cpu-original-polygons'
    def __init__(self,package_root,manifest,config):
        try:
            self.root=pathlib.Path(package_root);self.manifest=manifest
            self.verify_models()
            if sha(config)!=manifest['config_sha256']:raise OCRFailure('OCR config hash mismatch; not checked')
            import rapidocr_onnxruntime as package
            from rapidocr_onnxruntime import RapidOCR
            if pathlib.Path(package.__file__).resolve().parent!=self.root.resolve():raise OCRFailure('Unverified OCR package/model root')
            # RapidOCR updates relative paths against its package. All models were
            # verified above and packaged there; the fixed YAML sets all options.
            self.engine=RapidOCR(config_path=str(config))
            sessions=[self.engine.text_det.infer.session,self.engine.text_rec.session.session,self.engine.text_cls.infer.session]
            for session in sessions:
                if session.get_providers()!=['CPUExecutionProvider']:raise OCRFailure('Unapproved OCR provider')
                opts=session.get_session_options()
                if (opts.intra_op_num_threads,opts.inter_op_num_threads)!=(2,1):raise OCRFailure('OCR thread configuration differs')
            self.raw=[]
        except OCRFailure:raise
        except Exception:raise OCRFailure('OCR model/config/runtime unavailable; not checked') from None
    def verify_models(self):
        for row in self.manifest['models']:
            path=self.root/'models'/row['file']
            if not path.is_file() or path.stat().st_size!=row['bytes'] or sha(path)!=row['sha256']:
                raise OCRFailure('OCR model missing/hash mismatch; not checked')
    def infer(self,path):
        from PIL import Image
        with Image.open(path) as image:
            image.verify()
        image=self.engine.load_img(str(path));height,width=image.shape[:2]
        if not width or not height:raise OCRFailure('Empty decoded image; not checked')
        image,rh,rw=self.engine.preprocess(image)
        image,ops=self.engine.maybe_add_letterbox(image,{'preprocess':{'ratio_h':rh,'ratio_w':rw}})
        # Call the detector directly: its None means preprocessing failed. A
        # completed empty ndarray means successful no-text inference. RapidOCR's
        # high-level (None,None) merges those cases and is deliberately not used.
        boxes,elapsed=self.engine.text_det(image)
        if boxes is None or not math.isfinite(float(elapsed)):raise OCRFailure('Detection did not complete; not checked')
        if len(boxes)==0:self.raw=[];return []
        boxes=self.engine.sorted_boxes(boxes)
        crops=self.engine.get_crop_img_list(image,boxes)
        recognized,_=self.engine.text_rec(crops,False)
        if recognized is None or len(recognized)!=len(boxes):raise OCRFailure('Recognition incomplete; not checked')
        polygons=self.engine._get_origin_points(boxes,ops,height,width)
        self.raw=[];rows=[]
        for poly,result in zip(polygons,recognized):
            if len(result)<2:raise OCRFailure('Recognition schema unavailable')
            row=polygon_tuple(result[0],result[1],poly,width,height)
            self.raw.append({'polygon':[[float(x),float(y)] for x,y in poly],'text':row[0],'confidence':row[1]})
            rows.append(row)  # No confidence/height/text/angle prefilter.
        return rows

def inject_preflight(source,expected_sha256,backend):
    source=pathlib.Path(source)
    if sha(source)!=expected_sha256:raise OCRFailure('Original preflight hash mismatch; not checked')
    namespace={'__file__':str(source),'__name__':'task13_injected_preflight'}
    exec(compile(source.read_bytes(),str(source),'exec'),namespace)
    namespace['ocr_boxes']=backend.read
    if sha(source)!=expected_sha256:raise OCRFailure('Original preflight changed; not checked')
    return namespace,{'source_sha256':expected_sha256,'injected_adapter_sha256':sha(__file__),'substituted_function':'ocr_boxes','all_other_source_unchanged':True}

def group_keys(messages):
    keys=[]
    for message in messages:
        match=re.match(r"^FAIL T13 tilted text '(.*)' at ",message)
        if not match:raise OCRFailure('Unexpected original T13 output')
        keys.append(re.sub('[^a-z]','',match[1].lower())[:12])
    return set(keys)

def accept_master(name,baseline,candidate):
    diagnostic=compare_outputs(baseline,candidate)
    a=diagnostic['baseline_tilt'];b=diagnostic['candidate_tilt'];ka=group_keys(a);kb=group_keys(b)
    missed=ka-kb;extra=kb-ka
    return {'name':name,'acceptance':not missed and (bool(a)==bool(b)) and (bool(a) or not extra),
            'baseline_T13':a,'candidate_T13':b,'missed_groups':sorted(missed),'extra_groups':sorted(extra),
            'strict_diagnostic_parity':diagnostic['parity'],'diagnostic':diagnostic}
