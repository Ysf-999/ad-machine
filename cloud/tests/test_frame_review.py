"""Frame approvals from the browser (cloud/frame_review.py): what is accepted, what is stored, what starts by itself."""
import json
import os
import pathlib
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

C = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(C.parent), str(C)]
import frame_review as fr  # noqa: E402

NOW = 1_800_000_000.0


class Decisions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.saved = (fr.ROOT, fr.STATE, fr.LOG, fr.refresh_board)
        fr.ROOT, fr.STATE, fr.LOG, fr.refresh_board = root, root / 'cloud/controller', root / 'cloud/.scratch/fr.log', lambda: None
        fr.STATE.mkdir(parents=True)
        self.root, self.runs = root, {}

    def tearDown(self):
        fr.ROOT, fr.STATE, fr.LOG, fr.refresh_board = self.saved
        self.tmp.cleanup()

    def project(self, ad, frames=('scene_01.png', 'scene_02.png', 'scene_02_v2.png'), at=NOW - 3600):
        p = self.root / 'projects' / ad
        (p / 'FRAMES').mkdir(parents=True)
        (p / 'plan.json').write_text(json.dumps({'ad': ad, 'beats': [{'n': 1}, {'n': 2}]}))
        for n in frames:
            (p / 'FRAMES' / n).write_bytes(b'png')
            os.utime(p / 'FRAMES' / n, (at, at))
        return p

    def run_row(self, ad, recipe, **more):
        self.runs[f'{ad}-{recipe}'] = {'run': f'{ad}-{recipe}', 'ad': ad, 'recipe': recipe, 'submitted': NOW - 5000, 'batch': 'Song B', **more}
        (fr.STATE / 'runs.json').write_text(json.dumps(self.runs))

    def test_approve_all_is_stored_with_the_frames_he_saw(self):
        p = self.project('song')
        d = fr.save('song', {'approve_all': True, 'source': 'board'}, now=NOW)
        self.assertEqual((d['verdict'], d['redo'], d['source']), ('approved', [], 'board'))
        self.assertEqual(d['frames'], {'1': 'scene_01.png', '2': 'scene_02_v2.png'})
        self.assertEqual(fr.read(p)['beats']['2'], {'decision': 'approve', 'note': '', 'rule': False})
        self.assertEqual((p / 'FRAME_REVIEW.txt').read_text(), 'REVIEW song\nbeat 1: approve\nbeat 2: approve\n')
        self.assertEqual(len((p / 'FRAME_REVIEW.log.jsonl').read_text().splitlines()), 1)

    def test_notes_make_it_changes_and_keep_his_words(self):
        self.project('song')
        d = fr.save('song', {'beats': {'1': {'d': 'approve', 'frame': 'scene_01.png'},
                                       '2': {'d': 'redo-frame', 'note': '  cats off\n the seat ', 'rule': True, 'frame': 'scene_02_v2.png'}}}, now=NOW)
        self.assertEqual((d['verdict'], d['redo']), ('changes', [2]))
        self.assertEqual(fr.text_form(d), 'REVIEW song\nbeat 1: approve\nbeat 2: redo-frame — cats off the seat [RULE]\n')

    def test_refusals_are_in_plain_words(self):
        self.project('song')
        for payload, word in (({'beats': {'1': {'d': 'approve'}}}, 'No choice yet for beat 2'),
                              ({'beats': {'1': {'d': 'approve'}, '2': {'note': 'hmm'}}}, 'Beat 2 has a note but no choice'),
                              ({'beats': {'1': {'d': 'approve', 'frame': 'scene_01.png'}, '2': {'d': 'approve', 'frame': 'scene_02.png'}}}, 'Beat 2 has a newer frame'),
                              ({'beats': {'x': {}}}, 'unreadable')):
            with self.assertRaises(ValueError) as e:
                fr.save('song', payload, now=NOW)
            self.assertIn(word, str(e.exception))
        for ad in ('../etc', 'nope', ''):
            with self.assertRaises(ValueError):
                fr.save(ad, {'approve_all': True})
        self.assertIsNone(fr.read(self.root / 'projects' / 'song'))

    def test_a_decision_stands_until_newer_frames_exist(self):
        p = self.project('song')
        fr.save('song', {'approve_all': True}, now=NOW)
        self.assertEqual(fr.current(p)['verdict'], 'approved')
        self.assertEqual([ad for ad, _ in fr.pending()], ['song'])
        (p / 'FRAMES' / 'scene_01_v2.png').write_bytes(b'png')
        os.utime(p / 'FRAMES' / 'scene_01_v2.png', (NOW + 60, NOW + 60))
        self.assertIsNone(fr.current(p))
        self.assertEqual(fr.pending(), [])

    def test_pending_ends_when_it_is_used_or_marked(self):
        p = self.project('song')
        q = self.project('other')
        fr.save('song', {'approve_all': True}, now=NOW)
        fr.save('other', {'approve_all': True}, now=NOW)
        (p / 'CLIPS').mkdir()
        (p / 'CLIPS' / 'clip_01.mp4').write_bytes(b'x')
        self.assertEqual([ad for ad, _ in fr.pending()], ['other'])
        self.assertTrue(fr.mark_handled('other', now=NOW + 5))
        self.assertEqual(fr.pending(), [])
        self.assertFalse(fr.mark_handled('missing'))
        self.assertTrue(q.exists())

    def test_only_a_finished_cloud_frame_run_continues_by_itself(self):
        self.project('song')
        ok = fr.save('song', {'approve_all': True}, now=NOW)
        self.assertIsNone(fr.follow_up('song', ok))                      # made by hand on the Mac
        self.run_row('song', 'ai-frames', collected=True, collected_at=NOW - 900, final_state='done')
        self.assertEqual(fr.follow_up('song', ok), ['submit', 'ai-clips', 'song', '--go', '--batch', 'Song B'])
        redo = fr.save('song', {'beats': {'1': {'d': 'approve'}, '2': {'d': 'redo-frame', 'note': 'make it: a grey cat'}}}, now=NOW)
        self.assertEqual(fr.follow_up('song', redo), ['submit', 'ai-frames-revise', 'song', '--go', '--batch', 'Song B', '--redo', 'song:2:frame:make it: a grey cat'])
        bare = fr.save('song', {'beats': {'1': {'d': 'approve'}, '2': {'d': 'redo-frame'}}}, now=NOW)
        self.assertIsNone(fr.follow_up('song', bare))                    # a redo with no note needs a person
        clip = fr.save('song', {'beats': {'1': {'d': 'approve'}, '2': {'d': 'redo-clip', 'note': 'x'}}}, now=NOW)
        self.assertIsNone(fr.follow_up('song', clip))
        for state in ({'final_state': 'failed', 'collected': True}, {'collected': False}):
            self.runs.clear()
            self.run_row('song', 'ai-frames', **state)
            self.assertIsNone(fr.follow_up('song', ok))
        self.runs.clear()
        self.run_row('song', 'raw', collected=True, final_state='done')
        self.assertIsNone(fr.follow_up('song', ok))

    def test_redo_notes_survive_the_controller_parser(self):
        os.environ.setdefault('PP_NO_BOARD_HELPER', '1')
        import ctl
        self.assertEqual(ctl.parse_redos(['song:2:frame:make it: a grey cat'], ['song']), {'song': [[2, 'frame', 'make it: a grey cat']]})

    def test_handle_needs_the_token_and_reports_what_happens_next(self):
        self.project('song')
        code, out = fr.handle({'ad': 'song', 'approve_all': True, 'token': 'wrong'}, start=False)
        self.assertEqual((code, out['ok']), (403, False))
        code, out = fr.handle({'ad': 'song', 'approve_all': True, 'token': fr.token()}, start=False)
        self.assertEqual((code, out['verdict'], out['auto']), (200, 'approved', False))
        self.assertIn('Approved and saved', out['message'])
        self.run_row('song', 'ai-frames', collected=True, collected_at=time.time() - 900, final_state='done')
        code, out = fr.handle({'ad': 'song', 'approve_all': True, 'token': fr.token()}, start=False)
        self.assertTrue(out['auto'])
        self.assertIn('starting in the cloud', out['message'])
        d = fr.read(self.root / 'projects' / 'song')
        self.assertEqual(d['follow_up']['cmd'], 'ctl.py submit ai-clips song --go --batch Song B')
        code, out = fr.handle({'ad': 'song', 'token': fr.token(), 'beats': {'1': {'d': 'approve'}}}, start=False)
        self.assertEqual(code, 400)

    def test_follow_up_result_is_written_back(self):
        p = self.project('song')
        d = fr.save('song', {'approve_all': True}, now=NOW)
        d['follow_up'] = {'cmd': 'ctl.py submit ai-clips song --go', 'started_at': NOW}
        fr.write(p, d)
        seen = []

        class Done:
            returncode, stdout, stderr = 3, 'refused: over the kie cap', ''

        fr.run_follow_up('song', ['submit', 'ai-clips', 'song', '--go'], runner=lambda cmd, **k: seen.append(cmd) or Done())
        self.assertEqual(seen[0][2:], ['submit', 'ai-clips', 'song', '--go'])
        back = fr.read(p)['follow_up']
        self.assertEqual(back['exit'], 3)
        self.assertIn('over the kie cap', back['tail'])
        self.assertEqual([ad for ad, _ in fr.pending()], ['song'])       # a failed start still waits for someone

    def test_the_server_over_http(self):
        self.project('song')
        srv = fr.http.server.ThreadingHTTPServer((fr.HOST, 0), fr.Handler)
        srv.version = 'T'
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            self.assertEqual(fr.ping(port)['version'], 'T')

            def post(obj):
                req = urllib.request.Request(f'http://{fr.HOST}:{port}/frames', data=json.dumps(obj).encode(), headers={'Content-Type': 'text/plain'})
                try:
                    with urllib.request.urlopen(req, timeout=5) as r:
                        return r.status, json.loads(r.read()), r.headers.get('Access-Control-Allow-Origin')
                except urllib.error.HTTPError as e:
                    return e.code, json.loads(e.read()), e.headers.get('Access-Control-Allow-Origin')

            self.assertEqual(post({'ad': 'song', 'approve_all': True})[0], 403)
            code, out, cors = post({'ad': 'song', 'approve_all': True, 'token': fr.token(), 'source': 'board'})
            self.assertEqual((code, out['ok'], cors), (200, True, '*'))
            self.assertEqual(fr.read(self.root / 'projects' / 'song')['source'], 'board')
        finally:
            srv.shutdown()
            srv.server_close()


class Picks(unittest.TestCase):
    """Clip / hook options in the local picker (tools/option_picker.py), saved by the helper; never Frame.io."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.saved = (fr.ROOT, fr.STATE, fr.LOG, fr.refresh_board)
        fr.ROOT, fr.STATE, fr.LOG, fr.refresh_board = root, root / 'cloud/controller', root / 'cloud/.scratch/fr.log', lambda: None
        fr.STATE.mkdir(parents=True)
        self.root = root
        sys.path.insert(0, str(C.parent / 'tools'))
        import option_picker
        self.op = option_picker
        self.saved_op = option_picker.ROOT
        option_picker.ROOT = root
        clips = root / 'clips'
        clips.mkdir()
        for n in ('green-sofa.mp4', 'grey_duvet.mp4', 'hook-a.mp4', 'hook-b.mp4'):
            (clips / n).write_bytes(b'x')
        self.proj = root / 'projects' / 'washer'
        option_picker.main([str(self.proj), '--slot', 'Mitt clip', str(clips / 'green-sofa.mp4'), str(clips / 'grey_duvet.mp4'),
                            '--slot', 'Hook 3 opening', str(clips / 'hook-a.mp4'), str(clips / 'hook-b.mp4'), '--why', 'Line: no water, no soap', '--no-open'])
        self.opts = json.loads((self.proj / 'OPTIONS.json').read_text())

    def tearDown(self):
        fr.ROOT, fr.STATE, fr.LOG, fr.refresh_board = self.saved
        self.op.ROOT = self.saved_op
        self.tmp.cleanup()

    def test_the_page_names_options_by_file_and_draws_nothing_on_them(self):
        page = (self.proj / 'OPTIONS.html').read_text()
        self.assertEqual([o['name'] for o in self.opts['slots'][0]['options']], ['Green sofa', 'Grey duvet'])
        self.assertIn('<b>Green sofa</b>', page)
        self.assertIn('Line: no water, no soap', page)
        self.assertIn(fr.token(), page)
        self.assertIn("API='http://127.0.0.1:8790/options'", page)
        self.assertNotIn('drawtext', page)

    def test_a_slot_needs_two_options(self):
        with self.assertRaises(SystemExit):
            self.op.parse(['--slot', 'Mitt', str(self.root / 'clips' / 'hook-a.mp4')])

    def test_picks_are_saved_and_checked(self):
        sig = self.opts['sig']
        good = {'ad': 'washer', 'token': fr.token(), 'sig': sig, 'slots': [{'pick': '1b', 'notes': {'1a': 'too dark'}}, {'pick': 'none', 'note': 'show the drum'}]}
        code, out = fr.handle_picks(dict(good, token='x'), start=False)
        self.assertEqual(code, 403)
        for bad, word in (({'sig': 'old'}, 'options changed'), ({'slots': [{'pick': ''}, {'pick': '2a'}]}, "Pick one option in 'Mitt clip'"),
                          ({'slots': [{'pick': '1a'}, {'pick': 'none'}]}, "look for instead in 'Hook 3 opening'")):
            code, out = fr.handle_picks(dict(good, **bad), start=False)
            self.assertEqual(code, 400)
            self.assertIn(word, out['error'])
        code, out = fr.handle_picks(good, start=False)
        self.assertEqual((code, out['ok']), (200, True))
        d = fr.picks_of(self.proj)
        self.assertEqual([(x['slot'], x['pick_name'], x['note']) for x in d['slots']], [('Mitt clip', 'Grey duvet', ''), ('Hook 3 opening', None, 'show the drum')])
        self.assertEqual(d['slots'][0]['notes'], {'Green sofa': 'too dark'})
        self.assertTrue(d['slots'][0]['pick_file'].endswith('grey_duvet.mp4'))
        self.assertEqual([ad for ad, _ in fr.pending_picks()], ['washer'])
        # new options replace the set: the old picks no longer count
        (self.root / 'clips' / 'green-sofa.mp4').write_bytes(b'new')
        os.utime(self.root / 'clips' / 'green-sofa.mp4', (2_000_000_000, 2_000_000_000))
        self.op.main([str(self.proj), '--rebuild', '--no-open'])
        self.assertIsNone(fr.picks_of(self.proj))


if __name__ == '__main__':
    unittest.main()
