"""No-spend real Queue -> subprocess provider -> OS-isolated original ad status."""
from disk_test_support import DiskIndependentTestCase

import dataclasses,json,pathlib,tempfile,unittest
from cloud.orchestrator import Queue
from runner import Manifest
from runner.stage import digest
from providers.local import LocalSubprocessProvider
ROOT=pathlib.Path(__file__).resolve().parents[2]
class IntegrationTests(DiskIndependentTestCase):
 def test_durable_queue_real_status_and_unchanged_input_reuse(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'cloud/.scratch') as d:
   p=pathlib.Path(d);project=p/'staged';project.mkdir();plan=project/'plan.json'
   plan.write_text('{"ad":"offline-integration","beats":[],"locked":false}')
   m=Manifest('ad','status',['plan.json']);q=Queue(p/'queue.sqlite',provider_limits={'ffmpeg':1})
   inputs={'request':{'root':str(ROOT),'project':str(project),'manifest':dataclasses.asdict(m),'result_dir':str(p/'result')},
           'tool_hashes':{f.name:digest(f) for f in (ROOT/'tools').glob('*.py')}}
   dry=q.create_run();dryjob=q.enqueue(dry,'dry','status',inputs,plan_path=plan)
   self.assertIsNone(q.claim('dryworker',run_id=dry))
   run=q.create_run(go=True);job=q.enqueue(run,'ad','status',inputs,plan_path=plan)
   class Adapter:
    def run(self,record):return LocalSubprocessProvider().run(record['inputs']['request'])
   result=q.run_once({'ffmpeg':Adapter()},run_id=run,lease_seconds=60)
   self.assertEqual(result['state'],'done');self.assertFalse(result['result']['deliverable'])
   self.assertEqual(q.enqueue(run,'ad','status',inputs,plan_path=plan)['id'],job['id'])
   self.assertEqual(json.loads(plan.read_text())['beats'],[]);self.assertTrue((p/'result/plan.patch.json').exists())
if __name__=='__main__':unittest.main()
