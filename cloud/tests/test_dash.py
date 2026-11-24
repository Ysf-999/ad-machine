"""The ad board (cloud/dash.py): every ad lands in the right lane, with the right link, from files alone."""
import json
import os
import pathlib
import sys
import tempfile
import time
import unittest

C = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(C.parent), str(C)]
import claude_job  # noqa: E402
import dash  # noqa: E402
import deliver  # noqa: E402
import frame_review  # noqa: E402

NOW = 1_800_000_000.0


def iso(t):
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(t))


class Board(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.saved = (dash.ROOT, dash.STATE, dash.OUT)
        self.saved_fr = (frame_review.ROOT, frame_review.STATE)
        dash.ROOT, dash.STATE, dash.OUT = root, root / 'cloud/controller', root / 'cloud/.scratch/dashboard'
        frame_review.ROOT, frame_review.STATE = root, dash.STATE
        self.saved_dv = (deliver.ROOT, deliver.STATE, deliver.RECORD, deliver.LOG)
        deliver.ROOT, deliver.STATE, deliver.RECORD, deliver.LOG = root, dash.STATE, dash.STATE / 'deliveries.json', root / 'deliver.log'
        self.saved_cj = (claude_job.ROOT, claude_job.STATE, claude_job.TRANSCRIPTS)   # the board asks it who is working on what
        claude_job.ROOT, claude_job.STATE, claude_job.TRANSCRIPTS = root, dash.STATE, root / 'sessions'
        dash.STATE.mkdir(parents=True)
        (root / 'frameio').mkdir()
        (root / 'frameio/config.json').write_text(json.dumps({'project_id': 'PROJ'}))
        (root / 'feedback').mkdir()
        self.root, self.runs = root, {}

    def tearDown(self):
        dash.ROOT, dash.STATE, dash.OUT = self.saved
        frame_review.ROOT, frame_review.STATE = self.saved_fr
        deliver.ROOT, deliver.STATE, deliver.RECORD, deliver.LOG = self.saved_dv
        claude_job.ROOT, claude_job.STATE, claude_job.TRANSCRIPTS = self.saved_cj
        self.tmp.cleanup()

    def project(self, ad, master_at=None, plan=None, frameio=None, preflight=None, preflight_at=None, review=False):
        p = self.root / 'projects' / ad
        p.mkdir(parents=True)
        (p / 'plan.json').write_text(json.dumps(plan or {}))
        if master_at:
            (p / 'MASTER.mp4').write_bytes(b'x')
            os.utime(p / 'MASTER.mp4', (master_at, master_at))
        if frameio is not None:
            (p / 'frameio.json').write_text(json.dumps(frameio))
        if preflight is not None:
            (p / 'PREFLIGHT.md').write_text(preflight)
            at = preflight_at or (master_at or NOW) + 5
            os.utime(p / 'PREFLIGHT.md', (at, at))
        if review:
            (p / 'REVIEW.html').write_text('<html></html>')
        return p

    def run_row(self, ad, recipe, submitted, **more):
        run = f'{ad}-{recipe}-{int(submitted)}'
        self.runs[run] = {'run': run, 'ad': ad, 'recipe': recipe, 'submitted': submitted, 'batch': more.pop('batch', 'B1'), **more}
        return self.runs[run]

    def cards(self, rows=None):
        (dash.STATE / 'runs.json').write_text(json.dumps(self.runs))
        data = dash.gather(rows, now=NOW, thumbs=False)
        return {c['ad']: c for c in data['cards']}, data

    def test_open_run_shows_its_step(self):
        self.project('couch-h1', plan={'shots': [1]})
        r = self.run_row('couch-h1', 'raw', NOW - 600)
        state = {'state': 'running', 'plan': [['claude', ['shotcheck']], ['plain', ['rawrender', 'padtail']]],
                 'steps': [{'kind': 'claude', 'stages': ['shotcheck'], 'seconds': 95}], 'current': {'kind': 'plain', 'stages': ['rawrender', 'padtail'], 'since': NOW - 240}}
        cards, data = self.cards([(r, state)])
        c = cards['couch-h1']
        self.assertEqual((c['tab'], c['status'], c['tone']), ('progress', 'Running', 'live'))
        self.assertEqual([(s['label'], s['state']) for s in c['steps']], [('Shot check', 'done'), ('Render', 'now')])
        self.assertEqual(c['kind'], 'Real footage')
        self.assertIn('Render · 4 min', dash.render(data))

    def test_open_run_without_step_detail_is_not_called_queued(self):
        self.project('couch-h1')
        self.run_row('couch-h1', 'ai', NOW - 300)
        cards, _ = self.cards(rows=None)
        self.assertEqual(cards['couch-h1']['tab'], 'progress')
        self.assertIn('Sent to the cloud', cards['couch-h1']['detail'])

    def test_step_detail_is_remembered_between_refreshes(self):
        self.project('couch-h1')
        r = self.run_row('couch-h1', 'ai', NOW - 300)
        self.cards([(r, {'state': 'running', 'plan': [['gen', ['vo']]], 'steps': [], 'current': {'kind': 'gen', 'stages': ['vo'], 'since': NOW - 60}})])
        cards, _ = self.cards(rows=None)
        self.assertEqual(cards['couch-h1']['status'], 'Running')
        self.assertEqual(cards['couch-h1']['steps'][0]['label'], 'Voice')

    def test_blocked_and_failed_runs_need_a_fix_in_progress(self):
        self.project('a-h1', master_at=NOW - 9000)
        self.project('b-h1')
        self.run_row('a-h1', 'raw', NOW - 3000, collected=True, collected_at=NOW - 2000, final_state='blocked', next='change shot 5')
        self.run_row('b-h1', 'ai', NOW - 3000, collected=True, collected_at=NOW - 2000, final_state='failed')
        cards, _ = self.cards()
        for ad in ('a-h1', 'b-h1'):
            self.assertEqual((cards[ad]['tab'], cards[ad]['status'], cards[ad]['tone']), ('progress', 'Claude to fix', 'wait'))
        self.assertIn('shot check', cards['a-h1']['detail'])

    def frames(self, proj, names):
        (proj / 'FRAMES').mkdir(exist_ok=True)
        for n in names:
            (proj / 'FRAMES' / n).write_bytes(b'png')
            os.utime(proj / 'FRAMES' / n, (NOW - 3600, NOW - 3600))

    def test_cloud_starting_frames_wait_for_the_owner(self):
        p = self.project('song-h1', review=True)
        self.frames(p, ['scene_01.png', 'scene_01_v2.png', 'scene_02.png', 'scene_02_thumb.jpg', 'scene_10.png'])
        self.run_row('song-h1', 'ai-frames', NOW - 3000, collected=True, collected_at=NOW - 2000, final_state='done')
        c = self.cards()[0]['song-h1']
        self.assertEqual((c['tab'], c['status']), ('frames', 'Waiting for you'))
        self.assertEqual(c['action'], ('Review frames', (p / 'REVIEW.html').as_uri()))
        self.assertEqual([f.name for f in c['frames']], ['scene_01_v2.png', 'scene_02.png', 'scene_10.png'])
        self.assertIn('3 starting frames', c['detail'])

    def test_frames_made_on_the_mac_show_too_until_clips_exist(self):
        base = self.project('xmas', master_at=NOW - 9000, frameio={'batch': 'Xmas Song', 'files': [{'id': 'F', 'v': 1, 'pushed': iso(NOW - 8000)}]})
        self.assertTrue(base.exists())
        p = self.project('xmas-h4', review=True)
        self.frames(p, ['scene_01.png', 'scene_02.png'])
        q = self.project('other-h1', review=True)
        self.frames(q, ['scene_01.png'])
        (q / 'CLIPS').mkdir()
        (q / 'CLIPS' / 'clip_01.mp4').write_bytes(b'x')
        old = self.project('old-h1', review=True)
        self.frames(old, ['scene_01.png'])
        os.utime(old / 'FRAMES' / 'scene_01.png', (NOW - 40 * 86400, NOW - 40 * 86400))
        cards, data = self.cards()
        c = cards['xmas-h4']
        self.assertEqual((c['tab'], c['batch'], c['frame_count']), ('frames', 'Xmas Song', 2))
        self.assertNotIn('other-h1', cards)
        self.assertNotIn('old-h1', cards)
        page = dash.render(data)
        self.assertIn('Leave notes', page)
        self.assertIn((p / 'REVIEW.html').as_uri(), page)

    def test_on_frameio_gives_the_link(self):
        self.project('rug-h1', master_at=NOW - 5000, frameio={'batch': 'Rug', 'files': [{'id': 'FILE1', 'v': 2, 'src': 'MASTER.mp4', 'pushed': iso(NOW - 4000)}]})
        c = self.cards()[0]['rug-h1']
        self.assertEqual((c['tab'], c['status']), ('review', 'Ready to review'))
        self.assertEqual(c['action'], ('Open in Frame.io', 'https://next.frame.io/project/PROJ/view/FILE1'))
        self.assertIn('Version 2', c['note'])
        self.assertEqual(c['batch'], 'Rug')

    def test_open_frameio_notes_are_work_in_progress_not_a_notes_section(self):
        self.project('rug-h1', master_at=NOW - 5000, frameio={'files': [{'id': 'F1', 'v': 1, 'pushed': iso(NOW - 9000)}, {'id': 'F2', 'v': 2, 'pushed': iso(NOW - 4000)}],
                                                              'logged': {'F1': ['a', 'b'], 'F2': ['c', 'd', 'e']}, 'completed': ['a', 'b', 'c']})
        c = self.cards()[0]['rug-h1']
        self.assertEqual((c['tab'], c['status'], c['tone']), ('progress', 'Revision to do', 'wait'))
        self.assertIn('2 notes on v2', c['detail'])
        self.assertEqual({key for key, *_ in dash.TABS}, {'progress', 'frames', 'prep', 'review', 'sent'})

    def test_finished_but_not_uploaded(self):
        ok = 'fingerprint: abc\n- PASS 9:16\n- [x] T01 fine\n- [n/a] T02\n'
        self.project('new-h1', master_at=NOW - 900, preflight=ok)
        self.project('new-h2', master_at=NOW - 900, preflight='- PASS a\n- [ ] T01\n- [ ] T02\n')
        self.project('new-h3', master_at=NOW - 900, preflight='- FAIL caption sync 0.4 s late\n')
        self.project('new-h4', master_at=NOW - 900, preflight=ok, preflight_at=NOW - 5000)
        self.project('stale-h1', master_at=NOW - 9 * 86400, preflight=ok)
        for ad in ('new-h1', 'new-h2', 'new-h3', 'new-h4'):
            self.run_row(ad, 'raw', NOW - 3000, collected=True, collected_at=NOW - 1000, final_state='done')
        self.run_row('stale-h1', 'raw', NOW - 10 * 86400, collected=True, collected_at=NOW - 9 * 86400, final_state='done')
        cards, _ = self.cards()
        self.assertEqual((cards['new-h1']['tab'], cards['new-h1']['status']), ('prep', 'Uploading next'))
        self.assertIn('It goes to Frame.io by itself', cards['new-h1']['detail'])
        self.assertEqual(cards['new-h2']['tab'], 'prep')
        self.assertIn('Claude is running the last checks', cards['new-h2']['detail'])
        self.assertEqual((cards['new-h3']['tab'], cards['new-h3']['status']), ('progress', 'Claude to fix'))
        self.assertIn('(caption timing)', cards['new-h3']['detail'])
        self.assertIn('Claude is running the last checks', cards['new-h4']['detail'])
        self.assertNotIn('stale-h1', cards)

    def test_rerender_after_upload_is_not_called_ready_for_review(self):
        self.project('rug-h1', master_at=NOW - 1000, preflight='- PASS a\n- [x] T01\n',
                     frameio={'files': [{'id': 'F1', 'v': 1, 'src': 'MASTER.mp4', 'pushed': iso(NOW - 5000)}]})
        c = self.cards()[0]['rug-h1']
        self.assertEqual(c['tab'], 'prep')
        self.assertIn('Re-rendered after v1 went to Frame.io', c['detail'])
        self.assertIsNone(c['action'])

    def test_approved_locked_and_test_ads_are_not_on_the_board(self):
        self.project('done-h1', master_at=NOW - 90000, frameio={'files': [], 'cleaned': iso(NOW - 80000)})
        self.project('live-h1', master_at=NOW - 5000, plan={'locked': True}, frameio={'files': [{'id': 'F', 'v': 1, 'pushed': iso(NOW - 4000)}]})
        self.project('zz-proof', master_at=NOW - 500)
        self.run_row('zz-proof', 'raw', NOW - 3000, collected=True, collected_at=NOW - 400, final_state='done')
        cards, data = self.cards()
        self.assertEqual(cards, {})
        self.assertNotIn('Approved', ''.join(name for _, name, *_ in dash.TABS))
        self.assertIn('Nothing is waiting for your review.', dash.render(data))

    def test_a_new_run_after_approval_wins(self):
        self.project('done-h1', master_at=NOW - 90000, frameio={'files': [], 'cleaned': iso(NOW - 80000)})
        r = self.run_row('done-h1', 'raw', NOW - 200)
        c = self.cards([(r, {'state': 'queued'})])[0]['done-h1']
        self.assertEqual((c['tab'], c['status']), ('progress', 'Queued'))

    def test_hide_takes_an_ad_or_a_batch_off_the_board(self):
        for ad in ('mitt-h1', 'mitt-h2'):
            self.project(ad, master_at=NOW - 5000, frameio={'batch': 'Fake Mitt', 'files': [{'id': ad, 'v': 1, 'pushed': iso(NOW - 4000)}]})
        self.project('rug-h1', master_at=NOW - 5000, frameio={'batch': 'Rug', 'files': [{'id': 'R', 'v': 1, 'pushed': iso(NOW - 4000)}]})
        self.assertEqual(set(self.cards()[0]), {'mitt-h1', 'mitt-h2', 'rug-h1'})
        self.assertEqual(dash.hide(['Fake Mitt']), {'ads': [], 'batches': ['Fake Mitt']})
        cards, data = self.cards()
        self.assertEqual(set(cards), {'rug-h1'})
        self.assertEqual(data['hidden'], 1)
        dash.hide(['rug-h1'])
        self.assertEqual(self.cards()[0], {})
        dash.hide(['Fake Mitt', 'rug-h1'], on=False)
        self.assertEqual(len(self.cards()[0]), 3)

    def test_one_broken_project_does_not_blank_the_board(self):
        self.project('good-h1', master_at=NOW - 5000, frameio={'files': [{'id': 'F', 'v': 1, 'pushed': iso(NOW - 4000)}]})
        p = self.project('bad-h1', frameio={'files': 'nonsense'})
        (p / 'plan.json').write_text('{not json')
        cards, data = self.cards()
        self.assertEqual(cards['good-h1']['tab'], 'review')
        self.assertTrue(dash.render(data).rstrip().endswith('</html>'))

    def test_page_is_escaped_and_written_whole(self):
        self.project('x-h1', master_at=NOW - 5000, plan={'title': '<script>alert(1)</script> & co'},
                     frameio={'batch': '"><img src=x>', 'files': [{'id': 'F', 'v': 1, 'pushed': iso(NOW - 4000)}]})
        (dash.STATE / 'runs.json').write_text('{}')
        (dash.STATE / 'GLOBAL_STOP.json').write_text('{}')
        page = dash.render(dash.gather(None, now=NOW, thumbs=False))
        self.assertNotIn('<script>alert(1)', page)
        self.assertNotIn('"><img src=x>', page)
        self.assertIn('&lt;script&gt;alert(1)', page)
        self.assertIn('The cloud is stopped', page)
        self.assertEqual(page.count('role="tab"'), 5)
        out = dash.write(None, thumbs=False)
        self.assertTrue(out.read_text().rstrip().endswith('</html>'))
        self.assertFalse((dash.OUT / 'index.html.part').exists())

    def test_header_reads_the_ledger_and_titles_read_well(self):
        month = time.strftime('%Y-%m', time.localtime(NOW))
        (dash.STATE / f'ledger-{month}.json').write_text(json.dumps({'estimated_total_usd': '1.2781', 'cap_usd': '10.00'}))
        _, data = self.cards()
        self.assertEqual((data['modal'], data['cap']), ('1.2781', '10.00'))
        self.assertIn('$1.28', dash.render(data))
        self.assertEqual(dash.pretty('washer-opt-mitt-option-a---green-sofa', {}), 'Option A · Green sofa')
        self.assertEqual(dash.pretty('rug-cleaner-h2', {}), 'Rug cleaner\u00a0·\u00a0Hook\u00a02')


    def test_a_stopped_ad_says_whose_job_the_fix_is(self):
        self.project('couch-h2', plan={'shots': [1]})
        self.run_row('couch-h2', 'raw', NOW - 900, collected=True, collected_at=NOW - 600, final_state='blocked')
        c = self.cards()[0]['couch-h2']
        self.assertEqual(c['status'], 'Claude to fix')
        self.assertIn('Nothing for you to do', c['detail'])

    def test_no_old_video_on_an_ad_that_is_being_made(self):
        self.project('couch-h3', master_at=NOW - 9000, plan={'shots': [1]})
        r = self.run_row('couch-h3', 'raw', NOW - 300)
        cards, data = self.cards([(r, {'state': 'running', 'current': {'kind': 'plain', 'stages': ['rawrender'], 'since': NOW - 60}})])
        self.assertIsNone(cards['couch-h3']['video'])
        self.assertNotIn('Play', dash.render(data))
        done = self.project('couch-h4', master_at=NOW - 500, plan={'shots': [1]}, preflight='0 FAIL')
        self.run_row('couch-h4', 'raw', NOW - 900, collected=True, collected_at=NOW - 400, final_state='done')
        cards, data = self.cards()
        self.assertEqual(cards['couch-h4']['tab'], 'prep')
        self.assertIsNone(cards['couch-h4']['video'])
        self.assertTrue(done.exists())

    def test_approved_frames_leave_the_frames_tab(self):
        p = self.project('song-h2', plan={'beats': [{'n': 1}, {'n': 2}]}, review=True)
        self.frames(p, ['scene_01.png', 'scene_02_v2.png'])
        cards, data = self.cards()
        self.assertEqual(cards['song-h2']['tab'], 'frames')
        page = dash.render(data)
        self.assertIn('>Approve frames</button>', page)
        self.assertIn('Leave notes', page)
        self.assertIn(frame_review.token(), page)
        frame_review.save('song-h2', {'approve_all': True, 'source': 'board'}, now=NOW - 120)
        c = self.cards()[0]['song-h2']
        self.assertEqual((c['tab'], c['status'], c['tone']), ('progress', 'Frames approved', 'wait'))
        self.assertIn('You approved the 2 starting frames 2 min ago. Clips are next.', c['detail'])
        frame_review.save('song-h2', {'beats': {'1': {'d': 'approve'}, '2': {'d': 'redo-frame', 'note': 'cat is the wrong colour'}}}, now=NOW - 60)
        c = self.cards()[0]['song-h2']
        self.assertEqual((c['tab'], c['status']), ('progress', 'Frame notes sent'))
        self.assertIn('1 of 2 frames to redo', c['detail'])
        # clips land after an approval: the ad stays visible as work in progress until its video exists
        frame_review.save('song-h2', {'approve_all': True}, now=NOW - 50)
        (p / 'CLIPS').mkdir()
        (p / 'CLIPS' / 'clip_01.mp4').write_bytes(b'x')
        c = self.cards()[0]['song-h2']
        self.assertEqual((c['tab'], c['status']), ('progress', 'Building'))
        (p / 'CLIPS' / 'clip_01.mp4').unlink()
        frame_review.save('song-h2', {'beats': {'1': {'d': 'approve'}, '2': {'d': 'redo-frame', 'note': 'cat is the wrong colour'}}}, now=NOW - 40)
        # the redone frame arrives: it is his turn again, with nothing carried over
        (p / 'FRAMES' / 'scene_02_v3.png').write_bytes(b'png')
        os.utime(p / 'FRAMES' / 'scene_02_v3.png', (NOW - 10, NOW - 10))
        c = self.cards()[0]['song-h2']
        self.assertEqual((c['tab'], c['status']), ('frames', 'Waiting for you'))

    def test_cloud_frames_say_that_approving_starts_the_clips(self):
        p = self.project('song-h3', plan={'beats': [{'n': 1}]}, review=True)
        self.frames(p, ['scene_01.png'])
        self.run_row('song-h3', 'ai-frames', NOW - 3000, collected=True, collected_at=NOW - 2000, final_state='done')
        cards, data = self.cards()
        self.assertIn('>Approve and start clips</button>', dash.render(data))
        d = frame_review.save('song-h3', {'approve_all': True}, now=NOW - 30)
        d['follow_up'] = {'cmd': 'ctl.py submit ai-clips song-h3 --go', 'started_at': NOW - 30}
        frame_review.write(p, d)
        c = self.cards()[0]['song-h3']
        self.assertEqual((c['status'], c['tone']), ('Frames approved', 'live'))
        d['follow_up']['exit'] = 1
        frame_review.write(p, d)
        c = self.cards()[0]['song-h3']
        self.assertEqual((c['status'], c['tone']), ('Claude to fix', 'wait'))


    def test_clip_options_wait_in_to_approve_and_never_as_a_video(self):
        p = self.project('washer-h3')
        clips = self.root / 'clips'
        clips.mkdir()
        for n in ('a.mp4', 'b.mp4'):
            (clips / n).write_bytes(b'x')
        sys.path.insert(0, str(C.parent / 'tools'))
        import option_picker
        saved, option_picker.ROOT = option_picker.ROOT, self.root
        try:
            option_picker.main([str(p), '--slot', 'Hook 3 opening', str(clips / 'a.mp4'), str(clips / 'b.mp4'), '--no-open'])
        finally:
            option_picker.ROOT = saved
        d = json.loads((p / 'OPTIONS.json').read_text())
        d['made_at'] = NOW - 600
        (p / 'OPTIONS.json').write_text(json.dumps(d))
        cards, data = self.cards()
        c = cards['washer-h3']
        self.assertEqual((c['tab'], c['status'], c['kind']), ('frames', 'Waiting for you', 'Clip picks'))
        self.assertIn('2 options for: Hook 3 opening', c['detail'])
        page = dash.render(data)
        self.assertIn('>Pick clips</a>', page)
        self.assertIn('>To approve<', page)
        frame_review.save_picks('washer-h3', {'sig': d['sig'], 'slots': [{'pick': '1a'}]}, now=NOW - 60)
        c = self.cards()[0]['washer-h3']
        self.assertEqual((c['tab'], c['status']), ('progress', 'Pick sent'))


if __name__ == '__main__':
    unittest.main()
