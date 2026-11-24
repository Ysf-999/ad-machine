"""Offline cloud build CLI; every real external provider remains disabled."""
import argparse,dataclasses,json,pathlib,sys,time
# Support both direct script and module invocations without global shell configuration.
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent.parent))
from runner import Manifest,run_stage
from runner.stage import digest
ROOT=pathlib.Path(__file__).resolve().parent.parent

def main(argv=None):
 argv = sys.argv[1:] if argv is None else argv
 if argv and argv[0] in {'real-work','submit','board','mock-work','flow-status','flow-decision','flow-apply'}:
  from cloud.volume_cli import main as volume_main
  return volume_main(argv)
 if argv and argv[0]=='serve':
  from cloud.review_service import main as service_main
  return service_main(argv[1:])
 if argv and argv[0]=='notify':
  from cloud.notifications import build
  np=argparse.ArgumentParser();np.add_argument('ad');np.add_argument('event',choices=['awaiting_approval','failed']);np.add_argument('url');np.add_argument('--gate',choices=['frames','final']);np.add_argument('--channel',required=True);na=np.parse_args(argv[1:]);print(json.dumps(build(na.ad,na.event,na.url,gate=na.gate,channel=na.channel),indent=2));return 0
 if argv and argv[0] in {'approve','revise','apply','gate','snapshot','redo-complete','publish','approval-status'}:
  from approval import main as approval_main
  return approval_main(['status',*argv[1:]] if argv[0]=='approval-status' else argv)
 if argv and argv[0] in {'disk','clean-scratch'}:
  from hygiene import disk_report,clean_scratch
  hp=argparse.ArgumentParser(prog='cloud '+argv[0]);hp.add_argument('--age-hours',type=float,default=24);hp.add_argument('--go',action='store_true');ha=hp.parse_args(argv[1:])
  data=disk_report() if argv[0]=='disk' else clean_scratch(age_hours=ha.age_hours,go=ha.go)
  print(json.dumps(data,indent=2));return 0
 p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest='command',required=True)
 for name in ['real-work','submit','board','mock-work','flow-status','flow-decision','flow-apply','serve','notify','disk','clean-scratch','approve','revise','apply','gate','snapshot','redo-complete','publish','approval-status']:
  sub.add_parser(name,help='Signed scratch-only approval workflow; use COMMAND --help')
 r=sub.add_parser('run');r.add_argument('project',type=pathlib.Path);r.add_argument('manifest',type=pathlib.Path)
 r.add_argument('--execute-local',action='store_true',help='Run offline locally instead of printing dry run')
 r.add_argument('--result',type=pathlib.Path);r.add_argument('--keep',action='store_true',help='Retain successful scratch outputs; failures never retain media')
 # Configure all copy/render guards with CLOUD_MIN_FREE_GB (minimum8).
 a=p.parse_args(argv)
 m=Manifest(**json.loads(a.manifest.read_text()));m.validate();project=a.project.resolve()
 plan=json.loads((project/'plan.json').read_text())
 if plan.get('locked'):p.error('LOCKED project refused')
 summary={'dry_run':not a.execute_local,'tool':m.tool,'stage':m.stage,'source_plan_sha256':digest(project/'plan.json'),
          'manifest':dataclasses.asdict(m),'outward_actions':False,'source_project_writes':False}
 if not a.execute_local:print(json.dumps(summary,indent=2));return 0
 out=a.result or ROOT/'cloud/.scratch'/('cli-'+str(time.time_ns()))
 from hygiene import require_space
 require_space()
 result=run_stage(ROOT,project,m,out,keep=a.keep);print(json.dumps({'result':str(out),'status':result['status'],'deliverable':False},indent=2))
 return 0 if result['status']=='done' else 1
if __name__=='__main__':sys.exit(main())
