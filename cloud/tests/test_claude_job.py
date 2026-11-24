"""Unattended Claude jobs (cloud/claude_job.py) and the honest board: a batch only says "Claude is on it" while one is,
one job per batch, a time limit, a log, and the watcher starting what waits. No test starts a real Claude."""
import fcntl
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

C = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(C.parent), str(C)]
import claude_job as cj  # noqa: E402
import dash  # noqa: E402
import deliver  # noqa: E402
import frame_review as fr  # noqa: E402

NOW = 1_800_000_000.0
MIN = 60.0


def iso(t):
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(t))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        state = root / 'cloud/controller'
        self.saved = {m: {k: getattr(m, k) for k in keys} for m, keys in (
            (cj, ('ROOT', 'STATE', 'LOGS', 'TRANSCRIPTS', 'refresh_board', 'kill_tree')), (dash, ('ROOT', 'STATE', 'OUT')),
            (fr, ('ROOT', 'STATE', 'LOG', 'refresh_board')), (deliver, ('ROOT', 'STATE', 'RECORD', 'LOG')))}
        cj.ROOT, cj.STATE, cj.LOGS, cj.TRANSCRIPTS = root, state, root / 'cloud/.scratch/claude-jobs', root / 'sessions'
        cj.refresh_board, self.killed = (lambda: None), []
        cj.kill_tree = self.killed.append
        dash.ROOT, dash.STATE, dash.OUT = root, state, root / 'cloud/.scratch/dashboard'
        fr.ROOT, fr.STATE, fr.LOG, fr.refresh_board = root, state, root / 'cloud/.scratch/fr.log', lambda: None
        deliver.ROOT, deliver.STATE, deliver.RECORD, deliver.LOG = root, state, state / 'deliveries.json', root / 'deliver.log'
        state.mkdir(parents=True)
        (root / 'frameio').mkdir()
        (root / 'frameio/config.json').write_text(json.dumps({'project_id': 'PROJ'}))
        self.root, self.state, self.runs, self.spawned = root, state, {}, []

    def tearDown(self):
        for m, vals in self.saved.items():
            for k, v in vals.items():
                setattr(m, k, v)
        self.tmp.cleanup()

    def config(self, **keys):
        (self.state / 'config.json').write_text(json.dumps(keys))

    def ad(self, name, batch='Rug B1', pushed=NOW - 5 * 3600, touched=NOW - 5 * 3600, logged=('c1', 'c2')):
        """An ad on Frame.io (v1 pushed 5 h ago) whose folder was last touched at `touched`."""
        p = self.root / 'projects' / name
        p.mkdir(parents=True)
        (p / 'plan.json').write_text(json.dumps({'shots': [1]}))
        (p / 'frameio.json').write_text(json.dumps({'batch': batch, 'files': [{'id': f'f-{name}', 'v': 1, 'pushed': iso(pushed)}],
                                                    'logged': {f'f-{name}': list(logged)}}))
        for f in p.iterdir():
            os.utime(f, (touched, touched))
        return p

    def request(self, batch='Rug B1', ads=('rug-h1', 'rug-h2'), state='working', pressed=NOW - 4 * 3600, **more):
        d = cj.load(self.state / 'revision-requests.json', {}) or {}
        d[batch] = {'batch': batch, 'ads': list(ads), 'pressed_at': pressed, 'pulled_at': pressed + 20, 'state': state,
                    'notes': {a: 2 for a in ads}, **more}
        (self.state / 'revision-requests.json').write_text(json.dumps(d))
        return d[batch]

    def cards(self):
        (self.state / 'runs.json').write_text(json.dumps(self.runs))
        data = dash.gather(None, now=NOW, thumbs=False)
        return {c['ad']: c for c in data['cards']}, data

    def session(self, command, at):
        """A Claude Code transcript whose newest tool call ran `command` at `at`."""
        f = cj.TRANSCRIPTS / 'proj' / f'{len(list(cj.TRANSCRIPTS.rglob("*.jsonl")))}.jsonl'
        f.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(at)) + '.000Z'
        f.write_text(json.dumps({'type': 'user', 'cwd': str(self.root / 'projects/rug-h1'), 'message': {'content': 'look at projects/rug-h1 and rug-h2'}}) + '\n'
                     + json.dumps({'type': 'assistant', 'timestamp': stamp, 'cwd': str(self.root / 'projects/rug-h1'),
                                   'message': {'content': [{'type': 'tool_use', 'name': 'Bash', 'input': {'command': command}}]}}) + '\n')
        os.utime(f, (at, at))

    def hold(self, key):
        """Stand in for a running job: hold the batch's lock the way the runner does."""
        (self.state / 'claude-jobs').mkdir(exist_ok=True)
        lk = open(cj.lock_path(key), 'a')
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.addCleanup(lk.close)
        return lk


class HonestBoard(Base):
    def test_a_working_batch_nobody_touches_for_30_minutes_says_stalled(self):
        self.ad('rug-h1'); self.ad('rug-h2')
        self.request(working_at=NOW - 4 * 3600 + 30)
        cards, data = self.cards()
        for ad in ('rug-h1', 'rug-h2'):
            self.assertEqual((cards[ad]['tab'], cards[ad]['status'], cards[ad]['tone']), ('progress', 'Stalled', 'bad'))
            self.assertIn('Stalled — no Claude working on it', cards[ad]['detail'])
            self.assertNotIn('Claude is applying them', cards[ad]['detail'])
        page = dash.render(data)
        self.assertIn('Stalled — no Claude working on it</span>', page)
        self.assertNotIn('Claude is on it', page)

    def test_a_batch_being_worked_on_still_says_claude_is_applying_them(self):
        self.ad('rug-h1'); self.ad('rug-h2', touched=NOW - 10 * MIN)   # a file of one hook changed 10 minutes ago
        self.request()
        cards, data = self.cards()
        self.assertEqual((cards['rug-h1']['status'], cards['rug-h1']['tone']), ('Revisions sent', 'wait'))
        self.assertIn('Claude is applying them', cards['rug-h1']['detail'])
        self.assertIn('Revisions sent · Claude is on it', dash.render(data))

    def test_an_open_cloud_run_or_a_fresh_press_is_not_stalled(self):
        self.ad('rug-h1'); self.ad('rug-h2')
        self.request(batch='Rug B1')
        self.runs['r1'] = {'run': 'r1', 'ad': 'rug-h2', 'recipe': 'raw', 'submitted': NOW - 2 * 3600, 'batch': 'Rug B1'}   # still open
        self.assertEqual(self.cards()[0]['rug-h1']['status'], 'Revisions sent')
        self.runs.clear()
        self.request(state='waiting', pressed=NOW - 5 * MIN)   # pressed five minutes ago: nothing is late yet
        c = self.cards()[0]['rug-h1']
        self.assertEqual(c['status'], 'Revisions sent')
        self.assertIn('Claude starts on them next', c['detail'])

    def test_a_session_working_in_the_ad_folder_counts_and_a_mere_mention_does_not(self):
        self.ad('rug-h1'); self.ad('rug-h2')
        self.request()
        self.session('ls projects/other-ad && echo rug-h1 rug-h2', NOW - 5 * MIN)   # names them, works elsewhere
        self.assertEqual(self.cards()[0]['rug-h1']['status'], 'Stalled')
        self.session('.venv/bin/python tools/preflight.py projects/rug-h2', NOW - 5 * MIN)
        self.assertEqual(self.cards()[0]['rug-h1']['status'], 'Revisions sent')
        self.assertEqual(cj.session_activity(['rug-h'], NOW - 30 * MIN), 0.0)   # 'rug-h' is not the ad 'rug-h2'

    def test_the_owners_own_button_presses_are_not_claude_working(self):
        p = self.ad('rug-h1'); self.ad('rug-h2')
        self.request()
        (p / 'APPROVED.json').write_text('{}')
        os.utime(p / 'APPROVED.json', (NOW - 60, NOW - 60))
        self.assertEqual(self.cards()[0]['rug-h1']['status'], 'Stalled')

    def test_a_live_job_shows_as_working_and_a_job_that_needs_him_says_so(self):
        self.ad('rug-h1'); self.ad('rug-h2')
        req = self.request(auto=True)
        cj.save('Rug B1', kind='revision', ads=['rug-h1', 'rug-h2'], state='running', started_at=NOW - 50 * MIN, anchor=req['pressed_at'], tries=1)
        lk = self.hold('Rug B1')
        cards, data = self.cards()
        self.assertEqual((cards['rug-h1']['status'], cards['rug-h1']['tone']), ('Revisions sent', 'live'))
        self.assertIn('Claude is applying them now', cards['rug-h1']['detail'])
        self.assertIn('Claude is on it', dash.render(data))
        lk.close()
        cj.blocked('Rug B1', 'Note 3 asks for a new voice line. Record it or tell me to skip it.', now=NOW - 5 * MIN)
        cards, data = self.cards()
        self.assertEqual((cards['rug-h1']['status'], cards['rug-h1']['tone']), ('Needs you', 'you'))
        self.assertIn('new voice line', cards['rug-h1']['detail'])
        self.assertIn('Claude needs you', dash.render(data))

    def test_a_stalled_batch_offers_start_claude_only_when_nothing_restarts_it(self):
        self.ad('rug-h1'); self.ad('rug-h2')
        self.request()                                   # taken by a session before the switch-on: never taken over
        page = dash.render(self.cards()[1])
        self.assertIn('data-restart="1"', page)
        self.assertIn('Start Claude on it', page)
        self.request(auto=True)                          # pressed since: the watcher starts Claude again by itself
        cards, data = self.cards()
        self.assertIn('started on it again within 10 minutes', cards['rug-h1']['detail'])
        self.assertNotIn('data-restart="1"', dash.render(data))
        self.config(claude_auto=False)                   # switched off: the truth, and no button that would do nothing
        cards, data = self.cards()
        self.assertEqual(cards['rug-h1']['status'], 'Stalled')
        self.assertNotIn('Start Claude on it', dash.render(data))

    def test_a_new_version_on_frameio_clears_the_ad(self):
        self.ad('rug-h1', pushed=NOW - 3600); self.ad('rug-h2')
        self.request()
        cards, _ = self.cards()
        self.assertNotEqual(cards['rug-h1']['status'], 'Stalled')
        self.assertEqual(cards['rug-h2']['status'], 'Stalled')

    def test_a_failed_check_row_only_promises_a_fix_while_someone_is_on_it(self):
        p = self.root / 'projects' / 'couch-h1'
        p.mkdir(parents=True)
        (p / 'plan.json').write_text(json.dumps({'shots': [1]}))
        os.utime(p / 'plan.json', (NOW - 5 * 3600, NOW - 5 * 3600))
        self.runs['r'] = {'run': 'r', 'ad': 'couch-h1', 'recipe': 'raw', 'submitted': NOW - 3 * 3600, 'collected': True,
                          'collected_at': NOW - 3 * 3600 + 600, 'final_state': 'blocked', 'batch': 'Couch'}
        c = self.cards()[0]['couch-h1']
        self.assertEqual(c['status'], 'Claude to fix')
        self.assertIn('No Claude is working on it right now', c['detail'])
        self.assertNotIn('Nothing for you to do', c['detail'])
        self.runs['r']['collected_at'] = NOW - 10 * MIN                      # just came back: the promise stands
        self.assertIn('Nothing for you to do', self.cards()[0]['couch-h1']['detail'])
        self.runs['r']['collected_at'] = NOW - 3 * 3600 + 600
        cj.save(cj.fix_key('Couch'), kind='fix', ads=['couch-h1'], state='running', started_at=NOW - 4 * MIN)
        self.hold(cj.fix_key('Couch'))
        c = self.cards()[0]['couch-h1']
        self.assertEqual(c['tone'], 'live')
        self.assertIn('Claude is on it now', c['detail'])


class FakeProc:
    def __init__(self, code=0, hang=False, during=None):
        self.pid, self.code, self.hang, self.during, self.waits = 4242, code, hang, during, 0

    def wait(self, timeout=None):
        self.waits += 1
        if self.during:
            self.during()
        if self.hang and timeout is not None:
            raise subprocess.TimeoutExpired('claude', timeout)
        return self.code


class Jobs(Base):
    def popen(self, proc, lines=()):
        def start(cmd, **kw):
            self.cmd, self.kw = cmd, kw
            for d in lines:
                kw['stdout'].write((json.dumps(d) + '\n').encode())
            kw['stdout'].flush()
            return proc
        return start

    def started(self, key='Rug B1', **more):
        self.assertEqual(cj.start('revision', key, ['rug-h1', 'rug-h2'], spawn=self.spawned.append, now=NOW, anchor=NOW - 60, **more), 'started')
        return cj.record(key)

    def test_start_writes_the_record_and_hands_the_batch_to_one_runner(self):
        rec = self.started(notes={'rug-h1': 2})
        self.assertEqual(self.spawned, ['Rug B1'])
        self.assertEqual((rec['state'], rec['tries'], rec['ads'], rec['kind']), ('starting', 1, ['rug-h1', 'rug-h2'], 'revision'))
        self.assertTrue(rec['log'].startswith(str(cj.LOGS)))
        self.hold('Rug B1')                                    # its runner is alive
        self.assertEqual(cj.start('revision', 'Rug B1', ['rug-h1'], spawn=self.spawned.append, anchor=NOW - 60), 'running')
        self.assertEqual(self.spawned, ['Rug B1'])             # no second Claude on the same batch

    def test_a_second_runner_for_the_same_batch_refuses(self):
        self.started()
        self.hold('Rug B1')
        ran = []
        self.assertEqual(cj.run('Rug B1', popen=lambda *a, **k: ran.append(a)), 'running')
        self.assertEqual(ran, [])

    def test_nothing_starts_when_switched_off_or_from_a_test_without_a_spawn(self):
        self.assertEqual(cj.start('revision', 'Rug B1', ['rug-h1']), 'off')        # a test run never starts the real thing
        self.config(claude_auto=False)
        self.assertEqual(cj.start('revision', 'Rug B1', ['rug-h1'], spawn=self.spawned.append), 'off')
        self.assertEqual(self.spawned, [])
        self.assertIsNone(cj.record('Rug B1'))

    def test_tries_per_request_and_jobs_at_once_are_limited(self):
        self.config(claude_job_tries=2, claude_max_jobs=1)
        self.started(); self.started()
        self.assertEqual(cj.start('revision', 'Rug B1', ['rug-h1'], spawn=self.spawned.append, anchor=NOW - 60), 'tries')
        self.assertEqual(cj.start('revision', 'Rug B1', ['rug-h1'], spawn=self.spawned.append, anchor=NOW), 'started')   # a new press counts from one
        self.assertEqual(cj.record('Rug B1')['tries'], 1)
        self.hold('Rug B1')
        self.assertEqual(cj.start('revision', 'Other', ['x-h1'], spawn=self.spawned.append, anchor=1), 'busy')

    def test_the_call_is_headless_on_his_login_with_no_paid_key_and_no_bypass(self):
        self.started()
        os.environ['ANTHROPIC_API_KEY'] = 'sk-test-not-real'
        self.addCleanup(os.environ.pop, 'ANTHROPIC_API_KEY', None)
        self.assertEqual(cj.run('Rug B1', popen=self.popen(FakeProc(0), [{'type': 'result', 'is_error': False, 'result': 'all three pushed'}])), 'done')
        cmd = self.cmd
        self.assertIn('-p', cmd)
        self.assertEqual(cmd[cmd.index('--permission-mode') + 1], 'auto')
        self.assertEqual(cmd[cmd.index('--permission-prompts') + 1], 'none')
        self.assertFalse([x for x in cmd if 'dangerously' in x or x == 'bypassPermissions'])
        self.assertNotIn('ANTHROPIC_API_KEY', self.kw['env'])
        self.assertEqual(self.kw['cwd'], str(self.root))
        prompt = cmd[cmd.index('-p') + 1]
        for words in ('"Rug B1"', 'rug-h1, rug-h2', 'reviews --working', 'reviews --revised', 'claude_job.py blocked', 'Never ask'):
            self.assertIn(words, prompt)
        rec = cj.record('Rug B1')
        self.assertEqual((rec['state'], rec['exit'], rec['result']), ('done', 0, 'all three pushed'))
        self.assertIn('"type": "job"', pathlib.Path(rec['log']).read_text())
        self.assertFalse(cj.live('Rug B1'))                     # the lock went with the runner

    def test_a_job_that_runs_past_the_time_limit_is_stopped_and_says_so(self):
        self.config(claude_job_timeout_s=5)
        self.started()
        self.assertEqual(cj.run('Rug B1', popen=self.popen(FakeProc(-9, hang=True))), 'timeout')
        self.assertEqual(self.killed, [4242])
        rec = cj.record('Rug B1')
        self.assertEqual(rec['state'], 'timeout')
        self.assertIn('time limit', rec['ended_why'])

    def test_a_failed_run_keeps_its_reason_and_a_blocked_one_keeps_his_sentence(self):
        self.started()
        self.assertEqual(cj.run('Rug B1', popen=self.popen(FakeProc(1), [{'type': 'result', 'is_error': True, 'result': 'Claude usage limit reached'}])), 'failed')
        self.assertIn('usage limit', cj.record('Rug B1')['ended_why'])
        self.started()                                          # second try of the same request
        rec = cj.record('Rug B1')
        self.assertEqual(rec['tries'], 2)
        self.assertIn('earlier unattended run', cj.prompt_for(rec))
        said = lambda: cj.blocked('Rug B1', 'The kie cap is too low for note 2.   Raise it or drop the note.')
        self.assertEqual(cj.run('Rug B1', popen=self.popen(FakeProc(0, during=said), [{'type': 'result', 'is_error': False, 'result': 'stopped'}])), 'blocked')
        self.assertEqual(cj.record('Rug B1')['blocked'], 'The kie cap is too low for note 2. Raise it or drop the note.')

    def test_a_fix_job_gets_the_rows_it_must_finish(self):
        cj.start('fix', 'Couch', ['couch-h1'], spawn=self.spawned.append, anchor=5, rows={'couch-h1': 'Claude to fix: caption timing'})
        p = cj.prompt_for(cj.record('Couch'))
        self.assertIn('couch-h1: Claude to fix: caption timing', p)
        self.assertIn('history --next', p)

    def test_a_job_spends_no_kie_credits_unless_the_owner_switched_that_on(self):
        cj.start('revision', 'Rug B1', ['rug-b1-h1'], spawn=self.spawned.append, anchor=5)
        rec = cj.record('Rug B1')
        self.assertIs(cj.DEFAULTS['claude_job_paid'], False)
        self.assertIn('start NOTHING that spends kie credits', cj.prompt_for(rec))
        self.assertNotIn('is fine inside the kie cap', cj.prompt_for(rec))
        with mock.patch.object(cj, 'cfg', lambda: {**cj.DEFAULTS, 'claude_job_paid': True}):
            self.assertIn('is fine inside the kie cap', cj.prompt_for(rec))
            self.assertNotIn('start NOTHING', cj.prompt_for(rec))
        with mock.patch.object(cj, 'cfg', lambda: {**cj.DEFAULTS, 'claude_job_paid': 'yes'}):     # only a real true counts
            self.assertIn('start NOTHING', cj.prompt_for(rec))
        for text in (cj.prompt_for(rec),):
            self.assertIn('never use a paid Anthropic API key', text)
            self.assertNotIn('{money}', text)


class Sweep(Base):
    def sweep(self, cards=None, **kw):
        marked = []
        got = cj.sweep(cards or [], now=NOW, spawn=self.spawned.append, mark=lambda b, s: marked.append((b, s)), **kw)
        return got, marked

    def test_a_waiting_auto_request_is_started_and_a_hand_taken_one_is_left_alone(self):
        self.ad('rug-h1'); self.ad('rug-h2'); self.ad('old-h1', batch='Old')
        self.request(state='waiting', pressed=NOW - 10 * MIN, auto=True)
        self.request(batch='Old', ads=('old-h1',), state='working')            # no auto flag: an open session took it
        got, _ = self.sweep()
        self.assertEqual(got, [('Rug B1', 'revision', 'started')])
        self.assertEqual(self.spawned, ['Rug B1'])
        rec = cj.record('Rug B1')
        self.assertEqual((rec['anchor'], rec['notes']), (NOW - 10 * MIN, {'rug-h1': 2, 'rug-h2': 2}))

    def test_the_helper_gets_two_minutes_first_and_a_live_job_is_not_doubled(self):
        self.ad('rug-h1'); self.ad('rug-h2')
        self.request(state='waiting', pressed=NOW - 90, auto=True)
        self.assertEqual(self.sweep()[0], [])
        self.request(state='waiting', pressed=NOW - 10 * MIN, auto=True)
        self.hold('Rug B1')
        self.assertEqual(self.sweep()[0], [])

    def test_a_job_that_stopped_part_way_is_started_again_only_after_the_quiet_time(self):
        self.ad('rug-h1'); self.ad('rug-h2')
        req = self.request(state='working', auto=True)
        cj.save('Rug B1', kind='revision', ads=req['ads'], state='failed', anchor=req['pressed_at'], tries=1, ended_why='usage limit')
        self.assertEqual(self.sweep()[0], [('Rug B1', 'revision', 'started')])
        self.assertEqual(cj.record('Rug B1')['tries'], 2)
        os.utime(self.root / 'projects/rug-h2/plan.json', (NOW - 5 * MIN, NOW - 5 * MIN))   # someone is on it again
        self.assertEqual(self.sweep()[0], [])
        os.utime(self.root / 'projects/rug-h2/plan.json', (NOW - 3600, NOW - 3600))
        cj.save('Rug B1', tries=3)
        self.assertEqual(self.sweep()[0], [('Rug B1', 'revision', 'tries')])              # three tries: it stays stalled on the board

    def test_a_batch_whose_new_versions_are_up_is_closed_not_started(self):
        self.ad('rug-h1', pushed=NOW - 600); self.ad('rug-h2', pushed=NOW - 500)
        self.request(state='working', auto=True)
        got, marked = self.sweep()
        self.assertEqual((got, marked, self.spawned), ([('Rug B1', 'revision', 'finished')], [('Rug B1', 'done')], []))

    def test_a_video_sent_later_is_closed_by_its_own_press_time(self):
        self.ad('rug-h1', pushed=NOW - 600); self.ad('rug-h2', pushed=NOW - 30 * MIN)
        self.request(state='working', auto=True, ad_pressed={'rug-h2': NOW - 10 * MIN})   # h2 was sent after its last upload
        got, marked = self.sweep()
        self.assertEqual((got, marked), ([('Rug B1', 'revision', 'started')], []))        # not "finished": h2 still waits

    def test_a_job_waiting_for_the_owner_is_not_started_again(self):
        self.ad('rug-h1'); self.ad('rug-h2')
        req = self.request(state='working', auto=True)
        cj.save('Rug B1', kind='revision', ads=req['ads'], anchor=req['pressed_at'], tries=1)
        cj.blocked('Rug B1', 'needs a voice line', now=NOW - 2 * 3600)
        self.assertEqual(self.sweep()[0], [])

    def test_stopped_ads_get_a_fix_job_only_when_made_since_the_switch_on_and_left_alone(self):
        card = lambda ad, when, status='Claude to fix', batch='Couch': {'ad': ad, 'status': status, 'batch': batch, 'when': when, 'detail': 'caption timing', 'test': False}
        for ad in ('couch-h1', 'couch-h2', 'old-h1', 'busy-h1'):
            self.ad(ad, batch='x')
        os.utime(self.root / 'projects/busy-h1/plan.json', (NOW - 5 * MIN, NOW - 5 * MIN))
        cards = [card('couch-h1', NOW - 2 * 3600), card('couch-h2', NOW - 3600, 'Final checks'), card('old-h1', NOW - 9 * 3600, batch='Old'),
                 card('busy-h1', NOW - 3600, batch='Busy'), card('fine-h1', NOW - 3600, 'Ready to review', 'Fine')]
        self.assertEqual(self.sweep(cards)[0], [])                                    # no switch-on time: fix jobs are off
        self.config(claude_auto_from=NOW - 4 * 3600)
        got, _ = self.sweep(cards)
        self.assertEqual(got, [('fix: Couch', 'fix', 'started')])                     # one job for both couch hooks
        rec = cj.record(cj.fix_key('Couch'))
        self.assertEqual((rec['kind'], rec['ads']), ('fix', ['couch-h1', 'couch-h2']))
        self.assertIn('Final checks', rec['rows']['couch-h2'])
        self.assertIsNone(cj.record('Couch'))                                         # the batch's own name stays free for its revision job
        self.assertNotEqual(cj.slug(cj.fix_key('Couch')), cj.slug('Couch'))
        self.assertNotEqual(cj.slug(cj.fix_key('Couch')), cj.slug('fix Couch'))

    def test_a_stopped_hook_of_a_batch_in_somebodys_hands_is_never_taken(self):
        """2026-11-22: hook 4 of a batch a live session was revising failed in the cloud; it was not in the request's ad
        list (never on Frame.io), sat untouched 39 minutes while the session waited on a sibling run, and got a fix job."""
        card = lambda ad, status='Claude to fix', batch='Song': {'ad': ad, 'status': status, 'batch': batch, 'when': NOW - 3600, 'detail': 'a step failed', 'test': False}
        for ad in ('song-h1', 'song-h4'):
            self.ad(ad, batch='Song')
        self.config(claude_auto_from=NOW - 4 * 3600)
        cards = [card('song-h4'), card('song-h1', 'Revisions sent')]
        self.request(batch='Song', ads=('song-h1',), state='working')                 # a session took the batch by hand; h4 is not in its list
        self.assertEqual((self.sweep(cards)[0], self.spawned), ([], []))
        self.assertEqual(cj.batch_busy('Song'), 'its batch is being revised')
        self.request(batch='Song', ads=('song-h1',), state='done')                    # revision closed, but a run of the batch is still open
        (self.state / 'runs.json').write_text(json.dumps({'r': {'run': 'r', 'ad': 'song-h1', 'batch': 'Song', 'submitted': NOW - 3000, 'collected': False}}))
        self.assertEqual((self.sweep(cards)[0], self.spawned), ([], []))
        self.assertEqual(cj.batch_busy('Song'), 'a cloud run of its batch is open')
        (self.state / 'runs.json').write_text(json.dumps({'r': {'run': 'r', 'ad': 'song-h1', 'batch': 'Song', 'submitted': NOW - 3000, 'collected': True, 'collected_at': NOW - 10 * MIN}}))
        self.assertEqual(self.sweep(cards)[0], [])                                    # a sibling's run came back 10 minutes ago: someone is on the batch
        (self.state / 'runs.json').write_text(json.dumps({'r': {'run': 'r', 'ad': 'song-h1', 'batch': 'Song', 'submitted': NOW - 3 * 3600, 'collected': True, 'collected_at': NOW - 2 * 3600}}))
        os.utime(self.root / 'projects/song-h1/plan.json', (NOW - 5 * MIN, NOW - 5 * MIN))
        self.assertEqual(self.sweep(cards)[0], [])                                    # a sibling's files moved 5 minutes ago
        os.utime(self.root / 'projects/song-h1/plan.json', (NOW - 3 * 3600, NOW - 3 * 3600))
        self.assertEqual(self.sweep(cards)[0], [('fix: Song', 'fix', 'started')])     # the whole batch is quiet and free: now it is ours
        self.assertEqual(cj.batch_busy(''), '')

    def test_switched_off_means_nothing_starts(self):
        self.ad('rug-h1'); self.ad('rug-h2')
        self.request(state='waiting', pressed=NOW - 10 * MIN, auto=True)
        self.config(claude_auto=False)
        self.assertEqual((self.sweep()[0], self.spawned), ([], []))


class Button(Base):
    def press(self, **more):
        return fr.handle_revisions({'token': fr.token(), 'batch': 'Rug B1', **more}, start=False)

    def test_a_press_is_marked_for_claude_and_the_pull_starts_the_job(self):
        self.ad('rug-h1'); self.ad('rug-h2')
        code, reply = self.press()
        self.assertEqual(code, 200)
        self.assertIn('by itself', reply['message'])
        self.assertTrue(fr.revision_requests()['Rug B1']['auto'])
        pulled = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, '2 new comments', '')
        seen = []
        orig = cj.start
        cj.start = lambda *a, **k: seen.append((a, k)) or 'started'
        self.addCleanup(setattr, cj, 'start', orig)
        entry = fr.collect_revisions('Rug B1', runner=pulled, now=NOW)
        self.assertEqual(entry['state'], 'waiting')
        self.assertEqual(seen[0][0], ('revision', 'Rug B1', ['rug-h1', 'rug-h2']))
        self.assertEqual(seen[0][1]['anchor'], entry['pressed_at'])

    def test_no_notes_or_switched_off_starts_nothing(self):
        self.ad('rug-h1', logged=()); self.ad('rug-h2', logged=())
        seen = []
        orig = cj.start
        cj.start = lambda *a, **k: seen.append(a) or 'started'
        self.addCleanup(setattr, cj, 'start', orig)
        pulled = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, '0 new comments', '')
        self.press()
        self.assertEqual(fr.collect_revisions('Rug B1', runner=pulled, now=NOW)['state'], 'no-notes')
        self.config(claude_auto=False)
        (self.root / 'projects/rug-h1/frameio.json').write_text(json.dumps({'batch': 'Rug B1', 'files': [{'id': 'f', 'v': 1, 'pushed': iso(NOW)}], 'logged': {'f': ['c']}}))
        code, reply = self.press()
        self.assertNotIn('by itself', reply['message'])
        self.assertFalse(fr.revision_requests()['Rug B1']['auto'])
        self.assertEqual(fr.collect_revisions('Rug B1', runner=pulled, now=NOW)['state'], 'waiting')
        self.assertEqual(seen, [])

    def test_a_video_sent_while_a_job_runs_becomes_the_next_round(self):
        real = time.time()                                   # the helper stamps presses with the real clock
        self.ad('rug-h1', pushed=real - 5 * 3600); self.ad('rug-h2', pushed=real - 5 * 3600)
        pulled = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, '2 new comments', '')
        tok = fr.token()
        fr.handle_revisions({'token': tok, 'ad': 'rug-h1'}, start=False)                  # the row button on one video
        fr.collect_revisions('Rug B1', runner=pulled, single=True)
        req = fr.revision_requests()['Rug B1']
        self.assertEqual((req['ads'], req['state']), (['rug-h1'], 'waiting'))
        cj.save('Rug B1', kind='revision', ads=['rug-h1'], state='running', asked_at=req['pressed_at'], started_at=req['pressed_at'],
                anchor=req['pressed_at'], tries=3)
        lk = self.hold('Rug B1')                                                          # its job is running
        fr.mark_revisions('Rug B1', 'working')
        code, reply = fr.handle_revisions({'token': tok, 'ad': 'rug-h2'}, start=False)    # he sends a second video meanwhile
        self.assertEqual(code, 200)
        self.assertIn('right after', reply['message'])
        fr.collect_revisions('Rug B1', runner=pulled, only=['rug-h2'], single=True, spawn=self.spawned.append)
        mid = fr.revision_requests()['Rug B1']
        self.assertEqual((mid['ads'], mid['state'], mid['pressed_at'], list(mid['late'])), (['rug-h1', 'rug-h2'], 'working', req['pressed_at'], ['rug-h2']))
        self.assertEqual(self.spawned, [])                                                # the running job is left alone
        cards, _ = self.cards()
        self.assertIn('Claude is applying them now', cards['rug-h1']['detail'])
        self.assertEqual(cards['rug-h2']['status'], 'Revisions sent')
        self.assertIn('then starts on this one by itself', cards['rug-h2']['detail'])
        # the job pushes the new h1 and says the batch is revised: h2 is not lost, it is the next round
        f = self.root / 'projects/rug-h1/frameio.json'
        st = json.loads(f.read_text())
        st['files'].append({'id': 'h1-v2', 'v': 2, 'pushed': iso(time.time() + 60)})
        f.write_text(json.dumps(st))
        lk.close()
        nxt = fr.mark_revisions('Rug B1', 'done')
        self.assertEqual((nxt['state'], nxt['ads'], nxt['late'], nxt['notes']), ('waiting', ['rug-h2'], {}, {'rug-h2': 2}))
        self.assertEqual(nxt['pressed_at'], mid['late']['rug-h2'])
        got = cj.sweep([], now=time.time() + 300, spawn=self.spawned.append, mark=fr.mark_revisions)
        self.assertEqual((got, self.spawned), ([('Rug B1', 'revision', 'started')], ['Rug B1']))
        rec = cj.record('Rug B1')
        self.assertEqual((rec['ads'], rec['tries'], rec['anchor']), (['rug-h2'], 1, nxt['pressed_at']))   # a new round: its own tries
        # that job had h2 on its list, so its "done" closes the request
        self.assertEqual(fr.mark_revisions('Rug B1', 'done')['state'], 'done')

    def test_start_claude_on_a_stalled_batch_keeps_his_press_time(self):
        self.ad('rug-h1'); self.ad('rug-h2')
        pressed = time.time() - 4 * 3600                     # the helper stamps the restart with the real clock
        self.request(state='working', pressed=pressed)
        self.press(restart=True)
        req = fr.revision_requests()['Rug B1']
        self.assertEqual((req['pressed_at'], req['state'], req['auto']), (pressed, 'pulling', True))
        self.assertGreater(req['restarted_at'], pressed)
        self.assertEqual(fr.job_anchor(req), req['restarted_at'])


if __name__ == '__main__':
    unittest.main()
