
from disk_test_support import DiskIndependentTestCase
import pathlib,tempfile,unittest
from cloud.worker.isolation import Runtime,select_backend,MacSeatbelt,Container,Bubblewrap,Unavailable
from unittest.mock import patch
class IsolationTests(DiskIndependentTestCase):
 def runtime(self):return Runtime('/runtime/python','/runtime/ffmpeg','/runtime/ffprobe','/runtime/fonts','/runtime/models','/work/tmp',image='pipeline@sha256:'+'a'*64)
 def test_container_policy_and_manifest_environment(self):
  r=self.runtime();p=Container('/usr/bin/docker').plan(r,'/input','/output',['/runtime/python','-I','/input/task.py']);a=p.argv
  for part in ['--network=none','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--pids-limit=256','--memory=4g','--cpus=2']:self.assertIn(part,a)
  self.assertIn('/input:/input:ro',a);self.assertIn('/runtime:/runtime:ro',a);self.assertIn('/output:/work:rw',a);self.assertNotIn('SECRET',p.env);self.assertIn('TMPDIR=/work/tmp',a);self.assertIn('HF_HUB_CACHE=/runtime/models',a);self.assertEqual(p.env,{})
 def test_bwrap_and_unshare_network_and_readonly(self):
  p=Bubblewrap('/bin/bwrap','/usr/bin/unshare').plan(self.runtime(),'/input','/output',['/runtime/python','-I','/input/task.py'])
  self.assertEqual(p.argv[:4],['/usr/bin/unshare','--user','--map-root-user','--net']);self.assertIn('--unshare-all',p.argv);self.assertIn('--die-with-parent',p.argv);self.assertIn('--clearenv',p.argv);self.assertIn('--ro-bind',p.argv);self.assertNotIn('--share-net',p.argv)
 def test_capability_selection_fail_closed_no_binary_execution(self):
  with patch('shutil.which',return_value=None):
   with self.assertRaises(Unavailable):select_backend('linux',{'container':False,'userns':False})
  self.assertIsInstance(select_backend('linux',{'container':True,'docker':'/bin/docker'}),Container)
  self.assertIsInstance(select_backend('linux',{'userns':True,'bwrap':'/bin/bwrap','unshare':'/bin/unshare'}),Bubblewrap)
  with self.assertRaises(Unavailable):select_backend('linux',{'container':True})
 def test_no_shell_or_unmanifested_runtime(self):
  with self.assertRaises(ValueError):Runtime('python','ffmpeg','ffprobe','fonts','models','tmp')
  with self.assertRaises(ValueError):Container('/bin/docker').plan(self.runtime(),'/input','/output',['/bin/sh','-c','curl bad'])
 def test_seatbelt_keeps_original_source_boundary(self):
  p=MacSeatbelt('/usr/bin/sandbox-exec').plan(self.runtime(),'/input','/output',['/runtime/python','-I','/input/task.py'],source_root='/original')
  self.assertIn('(deny network*)',p.argv[2]);self.assertIn('/original',p.argv[2]);self.assertIn('file-write*',p.argv[2])
 def test_process_executor_receives_argv_without_shell(self):
  from cloud.worker.isolation import run
  p=Container('/bin/docker').plan(self.runtime(),'/input','/output',['/runtime/python','-I','/input/task.py'])
  calls=[]
  run(p,executor=lambda a,**kw:calls.append((a,kw)))
  self.assertFalse(calls[0][1]['shell']);self.assertTrue(calls[0][1]['check'])

 def test_host_root_is_never_a_runtime_mount(self):
  with self.assertRaises(ValueError):Runtime('/usr/bin/python','/usr/bin/ffmpeg','/usr/bin/ffprobe','/usr/fonts','/models','/work/tmp',directory='/',rootfs='/')
