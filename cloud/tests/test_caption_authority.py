from disk_test_support import DiskIndependentTestCase
import pathlib,tempfile,hashlib
from cloud.post_cloud import PostCloudGate
C=pathlib.Path(__file__).resolve().parents[1]
class CaptionAuthorityTests(DiskIndependentTestCase):
 def gate(self,local,remote):
  with tempfile.TemporaryDirectory(dir=C/'.scratch') as td:
   p=pathlib.Path(td);m=p/'MASTER.mp4';m.write_bytes(b'synthetic');sha=hashlib.sha256(m.read_bytes()).hexdigest();pf=p/'PREFLIGHT.md';pf.write_text('## Automatic checks\n- PASS T13 no tilted text found\n## Owner taste rules\n- [ ] review\n')
   checks={'caption_sync':{'returncode':0 if local else 1,'output':'CAPTION SYNC '+('PASS' if local else 'FAIL')},'av_check':{'returncode':0,'output':'PASS: sound and picture in sync'},'preflight':{'returncode':0,'output':'0 FAIL'},'preflight_path':str(pf)}
   remote={'master_sha256':sha,'returncode':0 if remote else 1}
   g=PostCloudGate(p/'receipts');a=g.run(m,sha,'unit',lambda:checks,linux_caption=remote);b=g.run(m,sha,'unit',lambda:self.fail('replay must not rerun'),linux_caption=remote);self.assertEqual(a,b);self.assertFalse(a['approved']);return a
 def test_linux_fail_local_pass_is_reported_and_not_override(self):
  r=self.gate(True,False);self.assertEqual(r['status'],'RENDERED_PREFLIGHT_COMPLETE_NOT_APPROVED');self.assertTrue(r['caption_comparison']['disagreement']);self.assertEqual(r['caption_comparison']['authority'],'native-mac-mlx')
 def test_linux_pass_cannot_override_local_fail(self):
  r=self.gate(False,True);self.assertEqual(r['status'],'BLOCKED_LOCAL_GATE');self.assertTrue(r['caption_comparison']['disagreement'])
 def test_matching_results_are_labelled(self):self.assertFalse(self.gate(True,True)['caption_comparison']['disagreement'])
