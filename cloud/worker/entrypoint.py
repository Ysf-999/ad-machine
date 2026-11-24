"""Explicit local-CAS CLI; remote storage is supplied by a trusted provider adapter."""
import argparse,json,pathlib,sys

def main(argv=None):
 from cloud.storage import LocalStorage
 from cloud.worker.protocol import execute
 p=argparse.ArgumentParser();p.add_argument('--runtime-root',required=True);p.add_argument('--workspace',required=True);p.add_argument('--local-cas',required=True);a=p.parse_args(argv)
 result=execute(json.load(sys.stdin),LocalStorage(a.local_cas),a.workspace,runtime_root=a.runtime_root)
 print(json.dumps(result,allow_nan=False));return result['exit_status']
if __name__=='__main__':raise SystemExit(main())
