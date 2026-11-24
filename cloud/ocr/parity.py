"""Compare recorded candidate tuples on the exact Vision corpus, no inference guess."""
import argparse,json,pathlib
from cloud.ocr import compare_outputs,OCRFailure

def compare_corpus(baseline,candidate):
 if candidate.get('version')!=1 or not candidate.get('backend') or candidate.get('corpus_source_sha256')!=baseline['source_sha256']:raise OCRFailure('Candidate provenance required')
 by={r['name']:r for r in candidate['masters']}
 if len(by)!=len(candidate['masters']) or set(by)!={r['name'] for r in baseline['masters']}:raise OCRFailure('Candidate master set differs')
 results=[]
 for row in baseline['masters']:
  other=by[row['name']]
  if other['master_sha256']!=row['master_sha256'] or [f['sha256'] for f in row['frames']]!=[f['sha256'] for f in other['frames']]:raise OCRFailure('Candidate pixels do not match baseline')
  results.append({'name':row['name'],**compare_outputs([f['ocr'] for f in row['frames']],[f['ocr'] for f in other['frames']])})
 return {'version':1,'candidate_backend':candidate['backend'],'parity':all(r['parity'] for r in results),'results':results,'evidence':'comparison of supplied recorded tuples; candidate execution provenance must be reviewed separately','original_gate_thresholds':'unchanged'}
def main():
 p=argparse.ArgumentParser();p.add_argument('baseline');p.add_argument('candidate');p.add_argument('--out',required=True);a=p.parse_args();r=compare_corpus(json.loads(pathlib.Path(a.baseline).read_text()),json.loads(pathlib.Path(a.candidate).read_text()));pathlib.Path(a.out).write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r));return 0 if r['parity'] else 1
if __name__=='__main__':raise SystemExit(main())
