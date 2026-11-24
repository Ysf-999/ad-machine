"""Existing T13 contract plus numeric backend parity; never relaxes original gates."""
from __future__ import annotations
import ast,math,pathlib,re
from runner.stage import digest
SOURCE=pathlib.Path(__file__).resolve().parents[2]/'tools/preflight.py'
class OCRFailure(RuntimeError):pass

def tuples(rows):
 if not isinstance(rows,(list,tuple)):raise OCRFailure('OCR rows unavailable')
 result=[]
 for r in rows:
  if len(r)!=4 or not isinstance(r[0],str) or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in r[1:]) or not 0<=r[1]<=1 or not 0<=r[3]<=2:raise OCRFailure('Invalid OCR geometry/confidence')
  result.append(tuple(r))
 return result
class Backend:
 name='abstract'
 def infer(self,path):raise NotImplementedError
 def read(self,path):
  try:return tuples(self.infer(path))
  except OCRFailure:raise
  except Exception as error:raise OCRFailure('Backend inference failed; not checked') from error

def _checked_vision(result):
 ok=result[0] if isinstance(result,tuple) else result
 if ok is not True and ok!=1:raise OCRFailure('Vision request failed; not checked')
 return result
class CheckedRequest(ast.NodeTransformer):
 def visit_Call(self,node):
  self.generic_visit(node)
  if isinstance(node.func,ast.Attribute) and node.func.attr=='performRequests_error_':return ast.copy_location(ast.Call(func=ast.Name(id='_checked_vision',ctx=ast.Load()),args=[node],keywords=[]),node)
  return node

def original_functions():
 tree=ast.parse(SOURCE.read_text());keep=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ['ocr_boxes','check_tilt'] or isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='TILT_MAX' for t in n.targets)]
 module=ast.Module(body=keep,type_ignores=[]);module=ast.fix_missing_locations(CheckedRequest().visit(module));g={'math':math,'re':re,'_checked_vision':_checked_vision};exec(compile(module,str(SOURCE),'exec'),g);return g
class AppleVision(Backend):
 name='apple-vision-original'
 def __init__(self):self.functions=original_functions();self.source_sha256=digest(SOURCE)
 def infer(self,path):return self.functions['ocr_boxes'](path)
def tilt(frames,step=1.):
 data=[tuples(rows) for rows in frames];g=original_functions();g['ocr_boxes']=lambda index:data[index];return g['check_tilt'](list(range(len(data))),step)
def compare_outputs(baseline,candidate,*,angle_tolerance=.25,confidence_tolerance=.05,height_tolerance=.002):
 # Diagnostic tuple tolerances never change the actual eligibility or T13 rule.
 if len(baseline)!=len(candidate):raise OCRFailure('Frame count differs')
 differences=[]
 for i,(base,other) in enumerate(zip(baseline,candidate)):
  base=tuples(base);other=tuples(other);remaining=list(other)
  for row in base:
   text=' '.join(row[0].casefold().split());options=[v for v in remaining if ' '.join(v[0].casefold().split())==text]
   if not options:differences.append({'frame':i,'reason':'missing text','text':row[0]});continue
   v=min(options,key=lambda a:abs(a[2]-row[2]));remaining.remove(v)
   if abs(v[2]-row[2])>angle_tolerance or abs(v[1]-row[1])>confidence_tolerance or abs(v[3]-row[3])>height_tolerance:differences.append({'frame':i,'reason':'tuple tolerance','text':row[0]})
  if remaining:differences.append({'frame':i,'reason':'extra text','count':len(remaining)})
 a=tilt(baseline);b=tilt(candidate);groups=lambda rows:{r.rsplit(', ',1)[0].casefold() for r in rows}
 missed=bool(groups(a)-groups(b));extra=bool(groups(b)-groups(a))
 return {'parity':not differences and not missed and not extra,'tuple_differences':differences,'baseline_tilt':a,'candidate_tilt':b,'missed_baseline_violation':missed,'extra_candidate_violation':extra,'diagnostic_tolerances':{'angle_degrees':angle_tolerance,'confidence':confidence_tolerance,'normalized_height':height_tolerance},'gate_thresholds':'UNCHANGED from original T13 source; no tolerance applied to gate'}
