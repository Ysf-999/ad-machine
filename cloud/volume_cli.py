"""No-network batch CLI. Paid execution remains disabled."""
import argparse,json,os,pathlib
from cloud.workflow import Workflow

def open_flow(root):
 data=json.loads((pathlib.Path(root)/'workflow.json').read_text())
 if data.get('kind')=='real-project':raise ValueError('Real-project workflows are not part of this build; use cloud/ctl.py')
 return Workflow(root)

def main(argv):
 p=argparse.ArgumentParser(prog='cloud');sub=p.add_subparsers(dest='command',required=True)
 s=sub.add_parser('submit');s.add_argument('spec',type=pathlib.Path);s.add_argument('--workspace',required=True,type=pathlib.Path)
 x=sub.add_parser('real-work');x.add_argument('workflow');x.add_argument('--execute-local',action='store_true');x.add_argument('--keep-for')
 for name in ['board','mock-work','flow-status']:
  x=sub.add_parser(name);x.add_argument('workflow')
 x=sub.add_parser('flow-decision');x.add_argument('workflow');x.add_argument('ad');x.add_argument('gate',choices=['frames','final']);x.add_argument('beat');x.add_argument('action',choices=['approve','revise']);x.add_argument('--note',default='');x.add_argument('--kind',choices=['frame','clip']);x.add_argument('--out',required=True,type=pathlib.Path);x.add_argument('--sign-only',action='store_true')
 x=sub.add_parser('flow-apply');x.add_argument('workflow');x.add_argument('decision',type=pathlib.Path)
 a=p.parse_args(argv)
 if a.command=='submit':
  spec=json.loads(a.spec.read_text())
  if spec.get('kind')=='real-project':raise SystemExit('Real-project workflows are not part of this build; use cloud/ctl.py')
  f=Workflow.submit(a.workspace,spec);out={'workflow':str(f.root),'mock':True,'run':json.loads(f.state_path.read_text())['run']}
 else:
  f=open_flow(a.workflow)
  if a.command=='real-work':
   if not a.execute_local:out={'dry_run':True,'workflow':str(f.root),'no_paid_stages':True}
   else:out=f.execute(keep_for=a.keep_for)
  elif a.command=='board':out={'board':str(f.board())}
  elif a.command=='mock-work':f.drain_mock();out={'waiting':f.waiting()}
  elif a.command=='flow-status':out={'waiting':f.waiting(),'jobs':len(f.q.jobs())}
  else:
   key=os.environ.get('CLOUD_APPROVAL_KEY','').encode()
   if a.command=='flow-decision':
    d=f.sign(a.ad,a.gate,'all' if a.beat=='all' else int(a.beat),a.action,key=key,note=a.note,kind=a.kind)
    from hygiene import _scratch_path
    from cloud.approval import _atomic,_json
    target=_scratch_path(a.out)
    if target.exists():raise FileExistsError('Fresh decision filename required')
    target.parent.mkdir(parents=True,exist_ok=True);_atomic(target,_json(d)+b'\n')
    out={'decision_file':str(target)} if a.sign_only else f.apply(d,key=key)
   else:out=f.apply(json.loads(a.decision.read_text()),key=key)
 print(json.dumps(out,indent=2));return 0
