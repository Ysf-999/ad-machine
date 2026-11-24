
from disk_test_support import DiskIndependentTestCase
import pathlib,tempfile,unittest
from cloud.worker.fonts import configuration,ass_filter
from hygiene import SCRATCH
class FontTests(DiskIndependentTestCase):
 def test_private_fontconfig_has_no_system_includes_and_escapes_paths(self):
  with tempfile.TemporaryDirectory(dir=SCRATCH) as td:
   p=pathlib.Path(td);fonts=p/'fonts & test';fonts.mkdir();env=configuration(fonts,p/'private')
   text=pathlib.Path(env['FONTCONFIG_FILE']).read_text();self.assertIn('fonts &amp; test',text);self.assertNotIn('<include',text);self.assertNotIn('/System/',text);self.assertEqual(env['ADMACHINE_FONTS_DIR'],str(fonts))
 def test_filter_rejects_unescaped_ass_path(self):
  self.assertEqual(ass_filter('/work/c.ass','/runtime/fonts'),'ass=/work/c.ass:fontsdir=/runtime/fonts')
  with self.assertRaises(ValueError):ass_filter('/work/a:b.ass','/runtime/fonts')

class ManifestFontPolicyTests(DiskIndependentTestCase):
 def test_bundled_font_mode_requires_declared_font_input(self):
  from runner import Manifest
  with self.assertRaises(ValueError):Manifest('rawedit','captions',['plan.json'],fonts_dir='library/fonts').validate()
  Manifest('rawedit','captions',['plan.json'],root_inputs=['library/fonts'],fonts_dir='library/fonts').validate()
 def test_bundled_mode_strengthens_mac_file_policy(self):
  from cloud.worker.isolation import MacSeatbelt
  policy=MacSeatbelt('/usr/bin/sandbox-exec').prefix('/work','/root',deny_system_fonts=True)[2]
  self.assertIn('/System/Library/Fonts',policy);self.assertIn('/Library/Fonts',policy)
