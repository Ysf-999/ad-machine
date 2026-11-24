"""tools/vision_qc.py: items are asked in parallel, results stay in beat order, unchanged items are not asked twice."""
import json
import pathlib
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools')]
import vision_qc  # noqa: E402
from PIL import Image  # noqa: E402


class FakeClient:
    def __init__(self, verdict=None):
        self.calls, self.lock, self.verdict = [], threading.Lock(), verdict or (lambda text: 'PASS')
        self.messages = types.SimpleNamespace(create=self.create)

    def create(self, **kw):
        text = kw['messages'][0]['content'][-1]['text']
        with self.lock:
            self.calls.append({'text': text, 'effort': kw.get('output_config'), 'system': kw.get('system')})
        v = self.verdict(text)
        body = json.dumps({'verdict': v, 'defects': ['T10 hair too thick'] if v == 'FAIL' else [], 'severity': 'minor' if v == 'FAIL' else 'none'})
        return types.SimpleNamespace(stop_reason='end_turn', content=[types.SimpleNamespace(type='text', text=body)])


class VisionQC(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = pathlib.Path(self.tmp.name) / 'ad'
        (self.proj / 'FRAMES').mkdir(parents=True)
        (self.proj / 'CLIPS').mkdir()
        beats = [{'n': n, 'visual': f'beat {n} visual'} for n in (1, 2, 3, 4, 5)]
        (self.proj / 'plan.json').write_text(json.dumps({'ad': 'ad', 'style': 'claymation', 'beats': beats}))
        for n in (1, 2, 3, 4, 5):
            Image.new('RGB', (64, 64), (n * 40, 10, 10)).save(self.proj / 'FRAMES' / f'scene_{n:02d}.png')

    def tearDown(self):
        self.tmp.cleanup()

    def run_qc(self, client, *extra):
        with mock.patch.object(vision_qc.anthropic, 'Anthropic', lambda: client), mock.patch.object(sys, 'argv', ['vision_qc.py', str(self.proj), '--stage', 'frames', *extra]), \
                mock.patch('builtins.print'):
            vision_qc.main()
        return json.loads((self.proj / 'QC/qc_report.json').read_text())

    def test_order_effort_rules_and_report(self):
        client = FakeClient(lambda text: 'FAIL' if 'beat 3 visual' in text else 'PASS')
        rows = self.run_qc(client)
        self.assertEqual([r['item'] for r in rows], [f'scene_{n:02d}.png' for n in (1, 2, 3, 4, 5)])
        self.assertEqual([r['verdict'] for r in rows], ['PASS', 'PASS', 'FAIL', 'PASS', 'PASS'])
        self.assertEqual(len(client.calls), 5)
        self.assertTrue(all(c['effort'] == {'effort': 'medium'} for c in client.calls))
        self.assertTrue(all('T' in c['system'] and 'owner' in c['system'].lower() for c in client.calls))
        self.assertIn('5 items checked, 1 failed', (self.proj / 'QC/qc_report.md').read_text())

    def test_unchanged_items_are_not_asked_again(self):
        self.run_qc(FakeClient())
        again = FakeClient()
        rows = self.run_qc(again)
        self.assertEqual(len(again.calls), 0)
        self.assertEqual(len(rows), 5)
        # a redo makes a new file for beat 2: only that one is asked
        Image.new('RGB', (64, 64), (1, 200, 1)).save(self.proj / 'FRAMES' / 'scene_02_v2.png')
        third = FakeClient()
        rows = self.run_qc(third)
        self.assertEqual(len(third.calls), 1)
        self.assertIn('beat 2 visual', third.calls[0]['text'])
        self.assertEqual(rows[1]['item'], 'scene_02_v2.png')
        forced = FakeClient()
        self.run_qc(forced, '--force')
        self.assertEqual(len(forced.calls), 5)

    def test_plan_or_rule_change_asks_again_and_fail_is_kept(self):
        self.run_qc(FakeClient(lambda text: 'FAIL'))
        plan = json.loads((self.proj / 'plan.json').read_text())
        plan['beats'][0]['visual'] = 'a different shot'
        (self.proj / 'plan.json').write_text(json.dumps(plan))
        client = FakeClient()
        rows = self.run_qc(client)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual([r['verdict'] for r in rows], ['PASS', 'FAIL', 'FAIL', 'FAIL', 'FAIL'])
        with mock.patch.object(vision_qc.taste_rules, 'stage_hash', lambda stage: 'new-rules'):
            changed = FakeClient()
            self.run_qc(changed)
        self.assertEqual(len(changed.calls), 5)


if __name__ == '__main__':
    unittest.main()
