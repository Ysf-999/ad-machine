"""The usage page (cloud/usage.py): credits, dollars, revision rounds and make time come from files alone, measured."""
import json
import pathlib
import sys
import tempfile
import time
import unittest

C = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(C.parent), str(C)]
import dash  # noqa: E402
import frame_review  # noqa: E402
import usage  # noqa: E402

NOW = 1_800_000_000.0


def iso(t):
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(t))


def utc(t):
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(t)) + '.000Z'


class Usage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.saved = (usage.ROOT, usage.STATE, usage.OUT, usage.TRANSCRIPTS)
        self.saved_fr = (frame_review.ROOT, frame_review.STATE)
        usage.ROOT, usage.STATE, usage.OUT, usage.TRANSCRIPTS = root, root / 'cloud/controller', root / 'cloud/.scratch/dashboard', root / 'transcripts'
        frame_review.ROOT, frame_review.STATE = root, usage.STATE
        usage.STATE.mkdir(parents=True)
        (root / 'feedback').mkdir()
        (root / 'projects').mkdir()
        (usage.STATE / 'config.json').write_text(json.dumps({'kie_pack_usd': 500, 'kie_pack_credits': 105000}))
        self.root = root

    def tearDown(self):
        usage.ROOT, usage.STATE, usage.OUT, usage.TRANSCRIPTS = self.saved
        frame_review.ROOT, frame_review.STATE = self.saved_fr
        self.tmp.cleanup()

    # ---- helpers ----
    def ad(self, name, jobs=(), pushes=(), batch=None, master=True, plan=None, cleaned=None):
        proj = self.root / 'projects' / name
        proj.mkdir(parents=True, exist_ok=True)
        (proj / 'plan.json').write_text(json.dumps(plan or {'skill': 'animated-ad-machine'}))
        if master:
            (proj / 'MASTER.mp4').write_bytes(b'x')
        lines = []
        for i, (key, credits, start, end) in enumerate(jobs):
            tid = f'{name}-{key}'
            lines.append({'key': key, 'taskId': tid, 'model': 'kling-3.0/video' if 'clip' in key else 'nano-banana-pro', 'state': 'submitted', **({'ts': iso(start)} if start else {})})
            lines.append({'key': key, 'taskId': tid, 'state': 'success', 'creditsConsumed': credits, **({'ts': iso(end)} if end else {})})
        if lines:
            (proj / 'jobs.jsonl').write_text('\n'.join(json.dumps(x) for x in lines) + '\n')
        if pushes or batch:
            files = [{'id': f'f{i}', 'v': i + 1, 'pushed': iso(t)} for i, t in enumerate(pushes)]
            st = {'files': files, 'batch': batch}
            if cleaned:
                st = {'files': [], 'history': files, 'batch': batch, 'cleaned': iso(cleaned)}
            (proj / 'frameio.json').write_text(json.dumps(st))
        return proj

    def cover(self, t):
        """Say when the first saved Claude session began (what make time needs to be whole)."""
        (usage.STATE / 'usage').mkdir(parents=True, exist_ok=True)
        (usage.STATE / 'usage/claude-index.json').write_text(json.dumps({'v': 1, 'files': {}, 'agg': {}, 'segs': {}, 'pending': 0, 'first': t}))

    def batch(self, name, **kw):
        data = usage.gather(now=NOW, fetch=lambda: None, **kw)
        return next(b for b in data['batches'] if b['name'] == name)

    # ---- credits and dollars ----
    def test_rate_is_the_owners_real_pack_price(self):
        per, usd, credits = usage.rate()
        self.assertEqual((usd, credits), (500, 105000))
        self.assertAlmostEqual(per * 105000, 500)
        self.assertAlmostEqual(per * 1000, 4.7619, places=4)

    def test_first_pass_is_before_the_first_frameio_push_and_revisions_after(self):
        push = NOW - 5000
        self.ad('mitt-ad', jobs=[('frame_1', 18, push - 900, push - 800), ('clip_1', 110, push - 700, push - 400),
                                  ('clip_1_v2', 110, push + 600, push + 900)], pushes=[push, push + 1500], batch='Mitt Ad')
        b = self.batch('Mitt Ad')
        self.assertEqual((b['f'], b['r']), (128.0, 110.0))
        self.assertEqual((b['videos'], b['rounds'], b['status']), (1, 1, 'On Frame.io'))
        self.assertEqual(b['cats'], {'Video clips': 220.0, 'Images': 18.0})
        self.assertEqual(sum(v[0] for v in b['days'].values()), 128.0)
        self.assertEqual(sum(v[1] for v in b['days'].values()), 110.0)

    def test_hooks_share_a_batch_and_a_copied_job_log_is_not_counted_twice(self):
        push = NOW - 5000
        base = self.ad('song', jobs=[('frame_1', 18, push - 900, push - 800)], pushes=[push], batch='Song')
        hook = self.ad('song-h2', pushes=[push, push + 50, push + 99], batch='Song')
        (hook / 'jobs.jsonl').write_text((base / 'jobs.jsonl').read_text()
                                         + json.dumps({'key': 'hook', 'taskId': 'h2-only', 'state': 'success', 'creditsConsumed': 40, 'ts': iso(push - 100)}) + '\n')
        b = self.batch('Song')
        self.assertEqual((b['f'], b['videos'], b['rounds']), (58.0, 2, 2))
        self.assertEqual({a['ad']: a['f'] for a in b['ads']}, {'song': 18.0, 'song-h2': 40.0})

    def test_an_ad_with_no_batch_sits_with_its_base_and_a_hub_folder_with_its_only_batch(self):
        push = NOW - 5000
        self.ad('brandx5-v1', jobs=[('frame_1', 18, push - 900, push - 800)], pushes=[push], batch='Brandx 5')
        self.ad('brandx5-v1-h2', jobs=[('frame_2', 18, push - 900, push - 800)])
        self.ad('brandx5-hub', jobs=[('voice', 30, push - 950, push - 940), ('voice_fix', 7, push + 500, push + 520)], master=False)
        b = self.batch('Brandx 5')
        self.assertEqual({a['ad'] for a in b['ads']}, {'brandx5-v1', 'brandx5-v1-h2', 'brandx5-hub'})
        # hook 2 never went to Frame.io: its spend, and the hub's spend after the first push, have no split
        self.assertEqual((b['videos'], b['f'], b['r'], b['x']), (2, 48.0, 0.0, 25.0))
        self.ad('brandx5-v1-h2', jobs=[('frame_2', 18, push - 900, push - 800)], pushes=[push + 100], batch='Brandx 5')
        b = self.batch('Brandx 5')   # every video has reached Frame.io: the hub's later spend is revision work on the batch
        self.assertEqual((b['f'], b['r'], b['x']), (66.0, 7.0, 0.0))

    def test_the_folder_the_hooks_were_cut_from_joins_their_batch(self):
        push = NOW - 5000
        self.ad('washer-horse-v2', jobs=[('clip_1', 110, push - 900, push - 800)], master=False)   # all the kie spend sits here
        for h in ('washer-horse-v2-h1', 'washer-horse-v2-h2'):
            self.ad(h, pushes=[push], batch='Washer Horse v2')
        self.ad('washer-v1', jobs=[('f', 18, push - 900, push - 800)], pushes=[push], batch='Washer v1')   # shares the first name part
        b = self.batch('Washer Horse v2')
        self.assertEqual((b['videos'], b['f'], len(b['ads'])), (2, 110.0, 3))

    def test_shared_work_between_the_first_and_the_last_first_push_has_no_split(self):
        push = NOW - 5000
        self.ad('duo-v1', jobs=[('frame_1', 18, push - 900, push - 800)], pushes=[push], batch='Duo')
        self.ad('duo-v2', jobs=[('frame_2', 18, push + 100, push + 200)], pushes=[push + 1000], batch='Duo')
        self.ad('duo-hub', jobs=[('voice_v2', 30, push + 300, push + 320)], master=False)   # made for v2 while v1 was in review
        b = self.batch('Duo')
        self.assertEqual((b['f'], b['r'], b['x']), (36.0, 0.0, 30.0))

    def test_undated_credits_are_in_the_total_only_never_called_first_pass(self):
        self.ad('old-ad', jobs=[('frame_1', 18, None, None)], pushes=[NOW - 50], batch='Old')
        b = self.batch('Old')
        self.assertEqual((b['f'], b['r'], b['x'], b['u'], b['days'], b['s']), (0.0, 0.0, 18.0, 18.0, {}, None))

    def test_job_logs_are_read_at_any_depth_and_the_product_kit_is_its_own_item(self):
        proj = self.ad('deep-ad', jobs=[('frame_1', 18, NOW - 900, NOW - 800)], pushes=[NOW - 700], batch='Deep')
        (proj / 'hooks/FIX3').mkdir(parents=True)
        (proj / 'hooks/FIX3/jobs_fix.jsonl').write_text(json.dumps({'key': 'fix', 'taskId': 'deep-fix', 'state': 'success', 'creditsConsumed': 75.5, 'ts': iso(NOW - 600)}) + '\n')
        kit = self.root / 'product-kit/acme-product/styled'
        kit.mkdir(parents=True)
        (kit / 'jobs.jsonl').write_text(json.dumps({'key': 'still', 'taskId': 'kit-1', 'state': 'success', 'creditsConsumed': 18, 'ts': iso(NOW - 500)}) + '\n')
        b = self.batch('Deep')
        self.assertEqual((b['f'], b['r']), (18.0, 75.5))
        k = self.batch('Product kit')
        self.assertEqual((k['videos'], k['x'], k['ads'][0]['title']), (0, 18.0, 'Product kit: acme-product'))

    def test_a_finished_video_needs_proof_on_disk_and_hook_cuts_in_one_folder_each_count(self):
        self.ad('plain-ad', jobs=[('f', 18, NOW - 900, NOW - 800)])                                  # MASTER.mp4
        moved = self.ad('moved-ad', jobs=[('f', 18, NOW - 900, NOW - 800)], master=False)          # archived: master moved out
        (moved / 'EDIT_KIT').mkdir()
        (moved / 'EDIT_KIT/ORDER.txt').write_text('01_retimed.mp4')                                   # written right after the master is rendered
        hub = self.ad('hub-ad', jobs=[('f', 18, NOW - 900, NOW - 800)], master=False)              # a storyboard-only folder: nothing rendered
        (hub / 'DELIVERY.md').write_text('storyboard written')
        (hub / 'EDIT_KIT').mkdir()
        many = self.ad('industry-remake', jobs=[('f', 18, NOW - 900, NOW - 800)], master=False)
        for n in (1, 2, 3):
            (many / f'industry-ironbark-h{n}.mp4').write_bytes(b'x')
        (many / 'clip_h9.mp4').write_bytes(b'x')                                                    # a clip, not a finished hook cut
        opt = self.ad('washer-opt-a---green-sofa', jobs=[('f', 18, NOW - 900, NOW - 800)])           # a clip option is never a video
        self.ad('zz-test-ad', jobs=[('f', 18, NOW - 900, NOW - 800)])
        data = usage.gather(now=NOW, fetch=lambda: None)
        got = {b['name']: b['videos'] for b in data['batches']}
        self.assertEqual((got['Plain ad'], got['Moved ad'], got['Hub ad'], got['Industry remake']), (1, 1, 0, 3))
        self.assertEqual([b['videos'] for b in data['batches'] if b['name'] not in ('Plain ad', 'Moved ad', 'Hub ad', 'Industry remake')], [0, 0])
        self.assertTrue(opt.is_dir())

    def test_format_comes_from_the_plan_never_from_the_kie_models_used(self):
        f = usage.format_of
        self.assertEqual(f('hw8-clay-xray-dog', {'mode': 'A_material'}, ['music-v4', 'kling-3.0/video']), 'Animated')   # a music bed is not a song ad
        self.assertEqual(f('petlab-04-signs-couch', {'skill': 'raw-ugc-editor', 'song': {'x': 1}}), 'Real footage edit')
        self.assertEqual(f('divorce-dog-song', {}), 'Song ad')
        self.assertEqual(f('lady-older-1106', {}, ['kling/ai-avatar-pro']), 'Other')
        self.assertEqual(f('zz-anything', {'skill': 'song-ad-machine'}), 'Tests')
        base = self.ad('ugc-ad', jobs=[('f', 18, NOW - 900, NOW - 800)], pushes=[NOW - 700], batch='UGC', plan={'skill': 'ugc-talking-head'})
        for h in ('ugc-ad-h2', 'ugc-ad-h3'):
            self.ad(h, pushes=[NOW - 600], batch='UGC', plan={'note': 'hook'})
        self.assertEqual(self.batch('UGC')['fmt'], 'AI UGC')   # the hooks carry no plan of their own: they are their base ad's format
        self.assertTrue(base.is_dir())

    # ---- checked against kie's own record ----
    def test_kies_own_record_replaces_the_log_and_dates_an_old_task(self):
        push = NOW - 5000
        proj = self.ad('kie-ad', jobs=[('frame_1', 18, None, None), ('clip_1', 110, push + 10, push + 90)], pushes=[push], batch='Kie')
        with open(proj / 'jobs.jsonl', 'a') as f:   # one the log never saw finish, one that failed, one still running
            for key in ('lost', 'bad', 'busy'):
                f.write(json.dumps({'key': key, 'taskId': f'kie-ad-{key}', 'model': 'kling-3.0/video', 'state': 'submitted'}) + '\n')
            f.write(json.dumps({'key': 'bad', 'taskId': 'kie-ad-bad', 'state': 'fail'}) + '\n')
        self.assertEqual(self.batch('Kie')['x'], 18.0)   # undated until kie is asked; the unfinished ones count nothing
        answers = {'kie-ad-frame_1': ['success', 18.0, push - 900, push - 860], 'kie-ad-clip_1': ['success', 112.0, push + 10, push + 88],
                   'kie-ad-lost': ['success', 80.0, push + 200, push + 300], 'kie-ad-bad': ['fail', 0.0, push + 5, push + 6], 'kie-ad-busy': ['generating', None, push, None]}
        asked = []
        got = usage.verify(lookup=lambda tid: asked.append(tid) or answers[tid], now=NOW)
        self.assertEqual((got, sorted(asked)), ((4, 1, 0), sorted(answers)))
        data = usage.gather(now=NOW, fetch=lambda: None)
        b = next(x for x in data['batches'] if x['name'] == 'Kie')
        self.assertEqual((b['f'], b['r'], b['x'], b['u']), (18.0, 192.0, 0.0, 0.0))   # kie's 112 replaced the logged 110; the lost 80 is back
        self.assertEqual({k: data['audit'][k] for k in ('tasks', 'checked', 'waiting', 'differ', 'differ_credits', 'recovered', 'recovered_credits')},
                         {'tasks': 3, 'checked': 3, 'waiting': 0, 'differ': 1, 'differ_credits': 2.0, 'recovered': 1, 'recovered_credits': 80.0})
        again = []
        usage.verify(lookup=lambda tid: again.append(tid) or answers[tid], now=NOW)
        self.assertEqual(again, ['kie-ad-busy'])   # only the one still running is asked about again

    def test_a_failed_lookup_changes_nothing_and_a_task_kie_forgot_keeps_the_logged_credits(self):
        self.ad('calm-ad', jobs=[('frame_1', 18, NOW - 900, NOW - 800), ('frame_2', 18, NOW - 700, NOW - 600)], pushes=[NOW - 500], batch='Calm')

        def lookup(tid):
            if tid.endswith('frame_1'):
                raise OSError('down')
            return ['none', None, None, None]
        self.batch('Calm')   # the first rebuild files the tasks; the next one asks kie about them
        self.assertEqual(usage.verify(lookup=lookup, now=NOW), (1, 1, 1))
        data = usage.gather(now=NOW, fetch=lambda: None)
        self.assertEqual(next(x for x in data['batches'] if x['name'] == 'Calm')['f'], 36.0)
        self.assertEqual((data['audit']['waiting'], data['audit']['unknown'], data['audit']['checked']), (1, 1, 0))

    def test_no_key_means_no_task_lookups(self):
        self.ad('quiet-ad', jobs=[('frame_1', 18, NOW - 900, NOW - 800)])
        self.assertEqual(usage.verify(now=NOW), (0, 0, 0))

    def test_approved_comes_from_the_drive_record_or_the_frameio_clean(self):
        push = NOW - 9000
        self.ad('sent-ad', jobs=[('f', 18, push - 90, push - 80)], pushes=[push], batch='Sent')
        (usage.STATE / 'deliveries.json').write_text(json.dumps({'Sent': {'batch': 'Sent', 'ads': ['sent-ad'], 'state': 'delivered', 'delivered_at': NOW - 100}}))
        self.ad('cleaned-ad', jobs=[('f', 18, push - 90, push - 80)], pushes=[push, push + 9], batch='Cleaned', cleaned=push + 500)
        self.assertEqual(self.batch('Sent')['status'], 'Approved')
        b = self.batch('Cleaned')
        self.assertEqual((b['status'], b['rounds']), ('Approved', 1))

    def test_a_project_that_left_the_disk_keeps_its_history(self):
        import shutil
        self.ad('gone-ad', jobs=[('frame_1', 18, NOW - 900, NOW - 800)], pushes=[NOW - 700], batch='Gone')
        self.assertEqual(self.batch('Gone')['f'], 18.0)
        shutil.rmtree(self.root / 'projects' / 'gone-ad')
        b = self.batch('Gone')
        self.assertEqual((b['f'], b['videos'], b['status']), (18.0, 1, 'Archived'))

    # ---- time ----
    def test_make_time_counts_overlaps_once_and_splits_at_the_first_push(self):
        push = NOW - 5000
        self.ad('timed', jobs=[('frame_1', 18, push - 1000, push - 900), ('frame_2', 18, push - 950, push - 850),   # 150 s together
                               ('clip_v2', 110, push + 100, push + 400)], pushes=[push], batch='Timed')
        (usage.STATE / 'runs.json').write_text(json.dumps({'timed-ai-1': {'run': 'timed-ai-1', 'ad': 'timed', 'recipe': 'ai-revise', 'submitted': push + 300, 'batch': 'Timed'}}))
        (usage.STATE / 'ledger-2027-01.json').write_text(json.dumps({'calls': [
            {'id': 'timed-ai-1-pipeline', 'wall_seconds': 200, 'estimate_usd': '0.0100'}, {'id': 'timed-ai-1-s0-claude', 'wall_seconds': 200, 'estimate_usd': '0.0020'}]}))
        b = self.batch('Timed')
        self.assertEqual((b['fs'], b['rs']), (150, 400))   # 100..400 kie, 300..500 cloud run -> 400 s
        self.assertEqual((b['runs'], b['modal']), (1, 0.012))
        self.assertIsNone(b['s'])   # no saved Claude session at all: the Claude part is unknown, so no make time is shown
        self.cover(push - 1000 - usage.COVER_S)
        self.assertEqual(self.batch('Timed')['s'], 550)
        self.cover(push - 2000)   # the ad began too close to the first saved session: earlier work may be missing
        self.assertIsNone(self.batch('Timed')['s'])

    def test_a_kie_task_resumed_hours_later_is_not_hours_of_work(self):
        self.ad('slow', jobs=[('clip', 110, NOW - 90000, NOW - 100)])
        self.assertEqual(self.batch('Slow')['fs'], 0)

    def test_spans(self):
        self.assertEqual(usage.union([(5, 9), (0, 3), (2, 6)]), [[0, 9]])
        self.assertEqual(usage.split([(0, 10)], 4), ([(0, 4)], [(4, 10)]))
        self.assertEqual(usage.split([(0, 10)], None), ([(0, 10)], []))

    # ---- never on Frame.io ----
    def test_a_video_that_never_went_to_frameio_has_no_split_and_no_rounds_only_its_total_and_notes(self):
        self.ad('hand-ad', jobs=[('f', 18, NOW - 300000, NOW - 299000), ('f_v2', 18, NOW - 100000, NOW - 99990)])
        rows = [{'ad': 'hand-ad', 'text': 'fix', 'src': 'chat', 'ts': iso(NOW - 200000), 'status': 'learned'},
                {'ad': 'hand-ad', 'text': 'fix 2', 'src': 'chat', 'ts': iso(NOW - 199000), 'status': 'learned'},
                {'ad': 'hand-ad', 'text': 'old import', 'src': 'chat-history', 'ts': iso(NOW - 400000), 'status': 'learned'},
                {'ad': 'hand-ad', 'text': 'love it', 'src': 'chat', 'ts': iso(NOW - 1000), 'status': 'like'}]
        (self.root / 'feedback/log.jsonl').write_text('\n'.join(json.dumps(r) for r in rows) + '\n')
        b = self.batch('Hand ad')
        self.assertEqual((b['notes'], b['f'], b['r'], b['x'], b['rounds']), (3, 0.0, 0.0, 36.0, None))
        self.assertEqual((b['ads'][0]['rounds'], sum(sum(v) for v in b['days'].values())), (None, 36.0))

    # ---- the balance ----
    def test_balance_is_read_live_kept_and_reused_while_fresh(self):
        calls = []

        def fetch():
            calls.append(1)
            return 19733.0
        a = usage.balance(max_age=60, fetch=fetch, now=NOW)
        b = usage.balance(max_age=60, fetch=fetch, now=NOW + 30)
        self.assertEqual((a['credits'], b['credits'], len(calls)), (19733.0, 19733.0, 1))
        c = usage.balance(max_age=60, fetch=lambda: 19000.0, now=NOW + 100)
        self.assertEqual((c['credits'], c['error']), (19000.0, None))
        self.assertEqual([r[1] for r in usage.balance_rows()], [19733.0, 19000.0])

    def test_a_failed_read_keeps_the_last_reading_and_says_so(self):
        usage.balance(max_age=60, fetch=lambda: 500.0, now=NOW)

        def down():
            raise OSError('offline')
        b = usage.balance(max_age=60, fetch=down, now=NOW + 999)
        self.assertEqual((b['credits'], b['t'], b['error']), (500.0, NOW, 'OSError'))

    def test_no_key_means_no_network_call(self):
        self.assertIsNone(usage.kie_key())
        self.assertIsNone(usage.fetch_balance())
        self.assertEqual(usage.balance(now=NOW)['credits'], None)

    def test_topups_are_seen_in_the_readings(self):
        tops, fell = usage.balance_story([(1, 20000.0), (2, 19000.0), (3, 124000.0), (4, 123500.0)])
        self.assertEqual(([t['credits'] for t in tops], fell), ([105000.0], 1500.0))

    def test_low_balance(self):
        self.assertTrue(usage.low_now({'bal': {'credits': 2000}, 'week': 7000, 'low': None}))     # 2 days left
        self.assertFalse(usage.low_now({'bal': {'credits': 20000}, 'week': 7000, 'low': None}))
        self.assertTrue(usage.low_now({'bal': {'credits': 20000}, 'week': 0, 'low': 25000}))      # the owner's own line
        self.assertFalse(usage.low_now({'bal': {'credits': None}, 'week': 7000, 'low': None}))

    # ---- Claude ----
    def transcript(self, name, rows):
        f = usage.TRANSCRIPTS / '-Users-x' / name
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, 'a') as out:
            for kind, t, extra in rows:
                if kind == 'a':
                    msg = {'id': extra.get('id', f'm{t}'), 'model': 'claude-opus', 'role': 'assistant', 'usage': {'input_tokens': 10, 'output_tokens': extra.get('out', 100), 'cache_read_input_tokens': 1000},
                           'content': [{'type': 'tool_use', 'name': 'Bash', 'input': {'command': extra['cmd']}}] if extra.get('cmd') else [{'type': 'text', 'text': 'ok'}]}
                    out.write(json.dumps({'parentUuid': 'p', 'message': msg, 'type': 'assistant', 'timestamp': utc(t), 'cwd': '/home/x/' + usage.REPO_NAME}, separators=(',', ':')) + '\n')
                else:
                    content = [{'tool_use_id': 't', 'type': 'tool_result', 'content': 'done'}] if kind == 'r' else 'please fix the hook'
                    out.write(json.dumps({'parentUuid': 'p', 'type': 'user', 'message': {'role': 'user', 'content': content}, 'timestamp': utc(t)}, separators=(',', ':')) + '\n')
        return f

    def test_claude_time_and_tokens_go_to_the_ad_it_worked_in_and_waiting_is_not_counted(self):
        t = NOW - 50000
        self.transcript('s1.jsonl', [('u', t, {}), ('a', t + 10, {'cmd': 'tools/ad.py projects/my-ad stitch'}), ('r', t + 610, {}),   # a 10 minute render
                                     ('a', t + 640, {}), ('u', t + 9000, {}),                                                         # he came back hours later
                                     ('a', t + 9020, {'cmd': 'ls projects/my-ad'}), ('r', t + 9030, {})])
        idx = usage.claude_index({'my-ad'}, budget=None)
        self.assertEqual(usage.seconds(idx['segs']['my-ad']), 10 + 600 + 30 + 20 + 10)
        row = [sum(v[i] for v in idx['agg']['my-ad'].values()) for i in range(5)]
        self.assertEqual(row, [30, 300, 3000, 0, 3])

    def test_the_index_only_reads_what_is_new_and_a_sweep_over_many_ads_is_nobodys_work(self):
        t = NOW - 50000
        f = self.transcript('s2.jsonl', [('u', t, {}), ('a', t + 10, {'cmd': 'ad.py projects/my-ad qc'}), ('r', t + 70, {})])
        known = {'my-ad'} | {f'ad-{i}' for i in range(9)}
        usage.claude_index(known, budget=None)
        size = f.stat().st_size
        self.transcript('s2.jsonl', [('a', t + 2000, {'cmd': 'for a in ' + ' '.join(sorted(known)) + '; do ls projects/$a; done', 'id': 'sweep'}), ('r', t + 2400, {})])
        idx = usage.claude_index(known, budget=None)
        self.assertGreater(idx['files']['-Users-x/s2.jsonl']['off'], size)
        self.assertEqual(usage.seconds(idx['segs']['my-ad']), 70)
        self.assertEqual(list(idx['segs']), ['my-ad'])
        self.assertEqual(sum(v[1] for v in idx['agg']['my-ad'].values()), 100)

    def test_moving_a_project_to_the_icloud_archive_is_not_work_on_it(self):
        t = NOW - 5000
        self.transcript('move.jsonl', [('a', t, {'cmd': 'mv projects/old-ad-1 "/home/x/Library/Mobile Documents/com~apple~CloudDocs/Archive/ad-projects/"'}),
                                       ('r', t + 600, {}), ('a', t + 610, {})])
        idx = usage.claude_index({'old-ad-1'}, budget=None, now=NOW)
        self.assertEqual(idx['segs'], {})

    def test_a_note_that_only_lists_ads_is_not_work_on_them(self):
        d = {'cwd': '/x/' + usage.REPO_NAME, 'message': {'content': [{'type': 'tool_use', 'input': {'file_path': '/x/HANDOFF.md', 'content': 'my-ad is done'}}]}}
        self.assertEqual(usage.named_ads(d, {'my-ad'}), [])
        d['message']['content'][0]['input'] = {'file_path': '/x/' + usage.REPO_NAME + '/projects/my-ad/plan.json', 'content': '{}'}
        self.assertEqual(usage.named_ads(d, {'my-ad'}), ['my-ad'])

    def test_claude_work_shows_up_in_the_batch(self):
        push = NOW - 5000
        self.ad('my-ad', jobs=[('frame_1', 18, push - 500, push - 400)], pushes=[push], batch='Mine')
        self.transcript('s3.jsonl', [('u', push - 1000, {}), ('a', push - 990, {'cmd': 'ad.py projects/my-ad frames'}), ('r', push - 390, {})])
        b = self.batch('Mine', scan=None)
        self.assertEqual((b['fs'], b['cs'], b['cl'][1]), (610, 610, 100))   # the kie task ran inside Claude's own span

    # ---- the page ----
    def test_page_is_written_with_the_numbers_and_never_the_key(self):
        (self.root / '.env').write_text('KIE_API_KEY=sk-secret-123\n')
        self.ad('mitt-ad', jobs=[('frame_1', 18, NOW - 900, NOW - 800)], pushes=[NOW - 700], batch='Mitt <Ad>')
        page = usage.write(fetch=lambda: 19733.0, now=NOW)
        text = page.read_text()
        self.assertIn('"credits":19733.0', text)
        self.assertIn('Mitt <Ad>', json.loads(text.split('const D=', 1)[1].split(',BASE=', 1)[0])['batches'][0]['name'])
        self.assertNotIn('sk-secret-123', text)
        self.assertNotIn('<Ad>', text.split('<script>')[0])
        self.assertEqual(usage.pill()['credits'], 19733.0)

    def test_the_helper_refuses_a_page_without_the_token(self):
        code, reply = usage.handle({'token': 'nope'})
        self.assertEqual((code, reply['ok']), (403, False))
        code, reply = usage.handle({'token': frame_review.token()})
        self.assertEqual((code, reply['ok'], reply['rebuilt']), (200, True, False))

    def test_the_board_button_only_shows_when_the_board_and_the_usage_page_look_at_the_same_repo(self):
        self.assertIsNone(dash.usage_page())   # the board still points at the real repo here: nothing is touched
        html = dash.render({'now': NOW, 'cards': [], 'kie': {'credits': 19733.4, 'low': False}})
        self.assertIn('href="usage.html"', html)
        self.assertIn('<b>19,733</b> credits', html)
        self.assertNotIn('usage.html', dash.render({'now': NOW, 'cards': [], 'kie': None}))


if __name__ == '__main__':
    unittest.main()
