"""Final approval on the board -> Google Drive -> media buyer sheet tick (cloud/deliver.py + the helper's /approve, /sheet)."""
import hashlib
import json
import os
import pathlib
import sys
import tempfile
import time
import types
import unittest

C = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(C.parent), str(C)]
import claude_job  # noqa: E402
import dash  # noqa: E402
import deliver  # noqa: E402
import frame_review as fr  # noqa: E402

NOW = time.time()


def iso(t):
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(t))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.root = pathlib.Path(self.tmp.name)
        state = root / 'cloud/controller'
        state.mkdir(parents=True)
        (root / 'frameio').mkdir()
        (root / 'frameio/config.json').write_text(json.dumps({'project_id': 'PROJ'}))
        self.saved = [(m, {k: getattr(m, k) for k in ks}) for m, ks in (
            (fr, ('ROOT', 'STATE', 'LOG', 'refresh_board', 'start_delivery')),
            (deliver, ('ROOT', 'STATE', 'RECORD', 'LOG', 'notify')),
            (dash, ('ROOT', 'STATE', 'OUT')), (claude_job, ('ROOT', 'STATE', 'LOGS', 'TRANSCRIPTS')))]
        claude_job.ROOT, claude_job.STATE = root, state          # no test reads the real job records or settings
        claude_job.LOGS, claude_job.TRANSCRIPTS = root / 'cloud/.scratch/claude-jobs', root / 'sessions'
        self.started, self.slack = [], []
        fr.ROOT, fr.STATE, fr.LOG, fr.refresh_board = root, state, root / 'fr.log', lambda: None
        fr.start_delivery = self.started.append
        deliver.ROOT, deliver.STATE, deliver.RECORD, deliver.LOG = root, state, state / 'deliveries.json', root / 'deliver.log'
        deliver.notify = lambda t: self.slack.append(t) or True
        dash.ROOT, dash.STATE, dash.OUT = root, state, root / 'cloud/.scratch/dashboard'
        self.tok = fr.token()

    def tearDown(self):
        for m, vals in self.saved:
            for k, v in vals.items():
                setattr(m, k, v)
        self.tmp.cleanup()

    def ad(self, name, batch='Couch V1', fid=None, notes=(), pushed=NOW - 3600, master_at=None):
        p = self.root / 'projects' / name
        p.mkdir(parents=True)
        (p / 'plan.json').write_text('{}')
        (p / 'MASTER.mp4').write_bytes(name.encode() * 50)
        t = master_at or pushed - 60
        os.utime(p / 'MASTER.mp4', (t, t))
        fid = fid or f'file-{name}'
        st = {'files': [{'id': fid, 'v': 1, 'src': 'MASTER.mp4', 'pushed': iso(pushed)}], 'logged': {fid: list(notes)},
              'folder_id': 'F1', 'stack_id': None}
        if batch:
            st['batch'] = batch
        (p / 'frameio.json').write_text(json.dumps(st))
        return p

    def approve(self, **body):
        return fr.handle_approve({'token': self.tok, **body})


class Approve(Base):
    def test_last_hook_of_the_batch_starts_the_drive_upload(self):
        self.ad('couch-h1'), self.ad('couch-h2')
        code, r = self.approve(ad='couch-h1')
        self.assertEqual((code, r['delivering']), (200, False))
        self.assertIn('1 more in this batch', r['message'])
        self.assertEqual(self.started, [])
        code, r = self.approve(ad='couch-h2')
        self.assertEqual((code, r['delivering']), (200, True))
        self.assertEqual(self.started, ['Couch V1'])

    def test_approve_all_sends_the_rows_he_sees(self):
        self.ad('couch-h1'), self.ad('couch-h2'), self.ad('other', batch='Other')
        code, r = self.approve(ads=['couch-h1', 'other'])
        self.assertEqual(code, 400)
        code, r = self.approve(ads=['couch-h1', 'couch-h2'])
        self.assertEqual((code, self.started), (200, ['Couch V1']))

    def test_a_new_version_voids_the_approval(self):
        p = self.ad('couch-h1')
        self.approve(ad='couch-h1')
        self.assertTrue(deliver.approved_now(p))
        st = json.loads((p / 'frameio.json').read_text())
        st['files'].append({'id': 'v2', 'v': 2, 'src': 'MASTER.mp4', 'pushed': iso(NOW)})
        (p / 'frameio.json').write_text(json.dumps(st))
        self.assertFalse(deliver.approved_now(p))

    def test_an_ad_pushed_alone_is_its_own_batch(self):
        self.ad('solo', batch=None)
        code, r = self.approve(ad='solo')
        self.assertEqual((code, self.started), (200, ['solo']))

    def test_take_back_works_until_the_upload_starts(self):
        p = self.ad('couch-h1')
        self.ad('couch-h2')
        self.approve(ad='couch-h1')
        self.assertEqual(self.approve(ad='couch-h1', undo=True)[0], 200)
        self.assertFalse((p / 'APPROVED.json').exists())
        self.approve(ad='couch-h1')
        deliver.save_record('Couch V1', {'state': 'uploading'})
        code, r = self.approve(ad='couch-h1', undo=True)
        self.assertEqual(code, 400)
        self.assertTrue((p / 'APPROVED.json').exists())

    def test_wrong_token_and_unknown_ad_are_refused(self):
        self.assertEqual(fr.handle_approve({'token': 'nope', 'ad': 'x'})[0], 403)
        self.assertEqual(self.approve(ad='not-there')[0], 400)


class Deliver(Base):
    def drive(self, corrupt=()):
        self.uploaded, self.shared, store = [], [], {}

        def upload(path, name, folder):
            self.uploaded.append(name)
            data = pathlib.Path(path).read_bytes() + (b'!' if name in corrupt else b'')
            store[name] = {'id': 'd-' + name, 'name': name, 'md5Checksum': hashlib.md5(data).hexdigest()}
        return {'create_folder': lambda name: {'id': 'FOLDER'}, 'list': lambda fid: list(store.values()),
                'upload': upload, 'share': self.shared.append}

    def runner(self, late_note_on=None):
        self.calls = []

        def run(cmd, **kw):
            self.calls.append(cmd[2:4])
            if cmd[2] == 'pull' and cmd[3] == late_note_on:
                f = self.root / 'projects' / late_note_on / 'frameio.json'
                st = json.loads(f.read_text())
                st['logged'][st['files'][-1]['id']].append('late-note')
                f.write_text(json.dumps(st))
            return types.SimpleNamespace(returncode=0, stdout='', stderr='')
        return run

    def both_approved(self):
        self.ad('couch-h1', notes=['old-note']), self.ad('couch-h2')
        self.approve(ads=['couch-h1', 'couch-h2'])

    def test_happy_path_uploads_checks_shares_cleans_and_tells_him(self):
        self.both_approved()
        e = deliver.deliver('Couch V1', runner=self.runner(), drive=self.drive())
        self.assertEqual(e['state'], 'delivered')
        self.assertEqual(e['url'], 'https://drive.google.com/drive/folders/FOLDER')
        self.assertEqual(sorted(self.uploaded), ['couch-h1.mp4', 'couch-h2.mp4'])
        self.assertEqual(self.shared, ['FOLDER'])
        self.assertEqual(self.calls[-1], ['clean', 'couch-h1'])
        self.assertFalse(e['in_sheet'])
        self.assertIn('drive.google.com', (self.root / 'deliver.log').read_text())   # no Slack note per delivery: the log and the board carry it
        # a second run does nothing new
        again = deliver.deliver('Couch V1', runner=self.runner(), drive=self.drive())
        self.assertEqual((again['state'], self.calls), ('delivered', []))

    def test_a_note_after_approve_stops_before_any_upload(self):
        self.both_approved()
        with self.assertRaisesRegex(RuntimeError, 'new Frame.io note'):
            deliver.deliver('Couch V1', runner=self.runner(late_note_on='couch-h2'), drive=self.drive())
        self.assertEqual(self.uploaded, [])
        self.assertEqual(deliver.records()['Couch V1']['state'], 'failed')

    def test_a_bad_drive_copy_keeps_frameio(self):
        self.both_approved()
        with self.assertRaisesRegex(RuntimeError, 'does not match'):
            deliver.deliver('Couch V1', runner=self.runner(), drive=self.drive(corrupt={'couch-h2.mp4'}))
        self.assertNotIn(['clean', 'couch-h1'], self.calls)

    def test_a_render_newer_than_the_approved_upload_stops(self):
        self.ad('couch-h1', master_at=NOW)
        self.approve(ad='couch-h1')
        with self.assertRaisesRegex(RuntimeError, 're-rendered'):
            deliver.deliver('Couch V1', runner=self.runner(), drive=self.drive())

    def test_not_every_hook_approved_refuses(self):
        self.ad('couch-h1'), self.ad('couch-h2')
        self.approve(ad='couch-h1')
        with self.assertRaisesRegex(RuntimeError, 'couch-h2'):
            deliver.deliver('Couch V1', runner=self.runner(), drive=self.drive())


class Board(Base):
    def cards(self):
        (deliver.STATE / 'runs.json').write_text('{}')
        return {c['ad']: c for c in dash.gather(None, now=NOW, thumbs=False)['cards']}

    def test_review_rows_carry_approve_and_the_batch_gets_approve_all(self):
        self.ad('couch-h1'), self.ad('couch-h2')
        cs = self.cards()
        self.assertTrue(cs['couch-h1']['can_approve'])
        page = dash.render({'now': NOW, 'cards': list(cs.values())})
        self.assertIn('data-ads="couch-h1,couch-h2"', page)
        self.assertIn('Approve all 2', page)

    def test_lanes_follow_the_hand_off(self):
        self.ad('couch-h1'), self.ad('couch-h2')
        self.approve(ad='couch-h1')
        cs = self.cards()
        self.assertEqual((cs['couch-h1']['tab'], cs['couch-h1']['status']), ('review', 'Approved'))
        deliver.save_record('Couch V1', {'state': 'uploading', 'ads': ['couch-h1', 'couch-h2']})
        self.assertEqual(self.cards()['couch-h2']['status'], 'Uploading to Drive')
        self.approve(ad='couch-h2')
        deliver.save_record('Couch V1', {'state': 'failed', 'error': 'Drive said no.'})
        c = self.cards()['couch-h2']
        self.assertEqual((c['tab'], c['status'], c['detail'], c.get('retry')), ('progress', 'Drive upload stopped', 'Drive said no.', True))
        deliver.save_record('Couch V1', {'state': 'delivered', 'url': 'https://drive.google.com/drive/folders/X', 'delivered_at': NOW - 60,
                                         'files': [{}, {}], 'in_sheet': False})
        cs = self.cards()
        self.assertNotIn('couch-h1', cs)
        sent = cs['sent:Couch V1']
        self.assertEqual((sent['tab'], sent['batch'], sent['kind']), ('sent', 'Not in the sheet yet', '2 videos'))
        page = dash.render({'now': NOW, 'cards': list(cs.values())})
        self.assertIn('class="sheet" data-batch="Couch V1"', page)
        self.assertIn('Open in Drive', page)

    def test_a_late_note_offers_approve_again_on_that_ad_only(self):
        self.ad('couch-h1'), self.ad('couch-h2')
        self.approve(ads=['couch-h1', 'couch-h2'])
        deliver.save_record('Couch V1', {'state': 'failed', 'error': 'couch-h2 got 1 new Frame.io note(s) after you approved it, so nothing was uploaded.'})
        cs = self.cards()
        self.assertEqual((cs['couch-h2'].get('approve_label'), cs['couch-h2'].get('retry')), ('Approve again', None))
        self.assertFalse(cs['couch-h1'].get('can_approve') or cs['couch-h1'].get('retry'))
        code, r = self.approve(ad='couch-h2')   # the first try started once already; approving again starts it again
        self.assertEqual((code, self.started), (200, ['Couch V1', 'Couch V1']))

    def test_sheet_tick_folds_the_row_away_then_drops_after_thirty_days(self):
        deliver.save_record('Rug', {'state': 'delivered', 'ads': ['rug-h1'], 'url': 'u', 'delivered_at': NOW - 40 * 86400})
        self.assertEqual(self.cards()['sent:Rug']['batch'], 'Not in the sheet yet')   # unticked: never drops off
        code, r = fr.handle_sheet({'token': self.tok, 'batch': 'Rug', 'on': True})
        self.assertEqual(code, 200)
        cs = self.cards()
        self.assertEqual(cs['sent:Rug']['batch'], 'In the sheet')
        page = dash.render({'now': NOW, 'cards': list(cs.values())})
        self.assertIn('<details class="group fold"><summary><h2><span class="gname">In the sheet <em>1</em>', page)
        self.assertIn('data-tab="sent" aria-selected="false" aria-controls="p-sent"><span class="n">0</span>', page)   # done rows are not counted
        deliver.save_record('Rug', {'in_sheet_at': NOW - 31 * 86400})
        self.assertNotIn('sent:Rug', self.cards())
        self.assertEqual(fr.handle_sheet({'token': self.tok, 'batch': 'Nope', 'on': True})[0], 400)


class Revisions(Base):
    def cards(self):
        (deliver.STATE / 'runs.json').write_text('{}')
        data = dash.gather(None, now=NOW, thumbs=False)
        return {c['ad']: c for c in data['cards']}, data

    def runner(self, notes):
        """Fake `frameio.py pull <ad>`: logs `notes[ad]` comment ids on the newest version and prints the count."""
        def run(cmd, **kw):
            ad = cmd[3]
            f = self.root / 'projects' / ad / 'frameio.json'
            st = json.loads(f.read_text())
            new = notes.get(ad, [])
            st['logged'].setdefault(st['files'][-1]['id'], []).extend(new)
            f.write_text(json.dumps(st))
            return types.SimpleNamespace(returncode=0, stdout=f'{ad}: {len(new)} new comment(s)\n{len(new)} new comment(s) across 1 ad(s)', stderr='')
        return run

    def test_one_press_pulls_every_ad_and_marks_the_batch_waiting(self):
        self.ad('couch-h1'), self.ad('couch-h2'), self.ad('couch-h3')
        code, r = fr.handle_revisions({'token': self.tok, 'batch': 'Couch V1'}, start=False)
        self.assertEqual(code, 200)
        self.assertEqual(fr.revision_requests()['Couch V1']['state'], 'pulling')
        e = fr.collect_revisions('Couch V1', runner=self.runner({'couch-h1': ['a', 'b'], 'couch-h3': ['c']}))
        self.assertEqual((e['state'], e['notes']), ('waiting', {'couch-h1': 2, 'couch-h2': 0, 'couch-h3': 1}))
        self.assertEqual(e['new'], {'couch-h1': 2, 'couch-h2': 0, 'couch-h3': 1})

    def test_no_notes_on_frameio_says_so(self):
        self.ad('couch-h1')
        fr.handle_revisions({'token': self.tok, 'batch': 'Couch V1'}, start=False)
        self.assertEqual(fr.collect_revisions('Couch V1', runner=self.runner({}))['state'], 'no-notes')
        cs, data = self.cards()
        page = dash.render(data)
        self.assertIn('No notes were found on Frame.io last time.', page)
        self.assertIn('data-do="revisions"', page)

    def test_unknown_batch_and_bad_token_are_refused(self):
        self.assertEqual(fr.handle_revisions({'token': self.tok, 'batch': 'Nope'})[0], 400)
        self.assertEqual(fr.handle_revisions({'token': 'x', 'batch': 'Couch V1'})[0], 403)

    def test_board_one_button_per_batch_then_every_ad_is_claudes_work_until_its_new_version(self):
        self.ad('couch-h1'), self.ad('couch-h2')
        cs, data = self.cards()
        page = dash.render(data)
        self.assertEqual(page.count('data-do="revisions" data-batch="Couch V1"'), 1)   # one for the batch, on its header
        self.assertEqual(page.count('data-do="revisions" data-ad='), 2)                # and a quiet one on each video
        fr.handle_revisions({'token': self.tok, 'batch': 'Couch V1'}, start=False)
        fr.collect_revisions('Couch V1', runner=self.runner({'couch-h1': ['a']}))
        cs, data = self.cards()
        self.assertEqual({cs[a]['status'] for a in ('couch-h1', 'couch-h2')}, {'Revisions sent'})
        self.assertIn('1 note on this video', cs['couch-h1']['detail'])
        page = dash.render(data)
        self.assertNotIn('data-do="revisions"', page)
        self.assertIn('Revisions sent · Claude is on it', page)
        # a new version of h1 goes up: h1 is back to review, h2 still being revised
        f = self.root / 'projects/couch-h1/frameio.json'
        st = json.loads(f.read_text())
        st['files'].append({'id': 'h1-v2', 'v': 2, 'src': 'MASTER.mp4', 'pushed': iso(NOW + 60)})
        f.write_text(json.dumps(st))
        fr.save_revision('Couch V1', {'pressed_at': NOW})
        cs, _ = self.cards()
        self.assertEqual((cs['couch-h1']['tab'], cs['couch-h2']['status']), ('review', 'Revisions sent'))

    def test_a_session_marks_it_working_then_done(self):
        self.ad('couch-h1')
        fr.handle_revisions({'token': self.tok, 'batch': 'Couch V1'}, start=False)
        fr.mark_revisions('Couch V1', 'working')
        cs, _ = self.cards()
        self.assertIn('Claude is applying them', cs['couch-h1']['detail'])
        fr.mark_revisions('Couch V1', 'done')
        cs, _ = self.cards()
        self.assertEqual(cs['couch-h1']['tab'], 'review')
        with self.assertRaises(ValueError):
            fr.mark_revisions('Nope', 'done')

    # ---- one video at a time, and never an approved one ------------------------------------------

    def pulls(self, notes):
        """The fake pull, plus the list of ads it was asked for."""
        asked, run = [], self.runner(notes)
        return asked, lambda cmd, **kw: asked.append(cmd[3]) or run(cmd, **kw)

    def test_the_row_button_sends_only_that_video(self):
        self.ad('couch-h1'), self.ad('couch-h2'), self.ad('couch-h3')
        page = dash.render(self.cards()[1])
        self.assertIn('class="lnk rev" data-do="revisions" data-ad="couch-h2"', page)   # a text link: second to "Open in Frame.io"
        self.assertIn('Revisions done for this video', page)
        code, r = fr.handle_revisions({'token': self.tok, 'ad': 'couch-h2'}, start=False)
        self.assertEqual((code, 'this video' in r['message']), (200, True))
        asked, run = self.pulls({'couch-h2': ['a', 'b']})
        e = fr.collect_revisions('Couch V1', runner=run, single=True)
        self.assertEqual((e['ads'], e['state'], e['notes'], asked), (['couch-h2'], 'waiting', {'couch-h2': 2}, ['couch-h2']))
        cs, data = self.cards()
        self.assertEqual((cs['couch-h2']['tab'], cs['couch-h2']['status']), ('progress', 'Revisions sent'))
        for other in ('couch-h1', 'couch-h3'):                       # the rest of the batch is still his to review
            self.assertEqual((cs[other]['tab'], cs[other]['status'], cs[other].get('can_approve')), ('review', 'Ready to review', True))
        page = dash.render(data)
        self.assertNotIn('data-do="revisions" data-ad="couch-h2"', page)
        self.assertIn('data-do="revisions" data-ad="couch-h1"', page)

    def test_a_second_video_is_added_to_the_open_request_not_a_reset(self):
        self.ad('couch-h1'), self.ad('couch-h2'), self.ad('couch-h3')
        fr.handle_revisions({'token': self.tok, 'ad': 'couch-h1'}, start=False)
        fr.collect_revisions('Couch V1', runner=self.runner({'couch-h1': ['a']}), single=True)
        first = fr.revision_requests()['Couch V1']
        fr.handle_revisions({'token': self.tok, 'ad': 'couch-h2'}, start=False)
        asked, run = self.pulls({'couch-h2': ['b', 'c']})
        e = fr.collect_revisions('Couch V1', runner=run, only=['couch-h2'], single=True)
        self.assertEqual((e['ads'], e['notes'], asked), (['couch-h1', 'couch-h2'], {'couch-h1': 1, 'couch-h2': 2}, ['couch-h2']))
        self.assertEqual((e['pressed_at'], e['state']), (first['pressed_at'], 'waiting'))   # h1 keeps its press
        self.assertGreater(e['ad_pressed']['couch-h2'], first['pressed_at'])
        # the row button on a video with no notes: it is not sent, and its row says why
        fr.handle_revisions({'token': self.tok, 'ad': 'couch-h3'}, start=False)
        e = fr.collect_revisions('Couch V1', runner=self.runner({}), only=['couch-h3'], single=True)
        self.assertEqual((e['ads'], e['state']), (['couch-h1', 'couch-h2'], 'waiting'))
        cs, data = self.cards()
        self.assertEqual({cs[a]['status'] for a in ('couch-h1', 'couch-h2')}, {'Revisions sent'})
        self.assertEqual((cs['couch-h3']['tab'], cs['couch-h3']['status']), ('review', 'Ready to review'))
        self.assertIn('No notes were found on Frame.io for this video.', dash.render(data))

    def test_the_batch_button_leaves_approved_and_locked_videos_out(self):
        self.ad('couch-h1'), self.ad('couch-h2'), self.ad('couch-h3')
        (self.ad('couch-h4') / 'plan.json').write_text(json.dumps({'locked': True}))
        self.approve(ad='couch-h1'), self.approve(ad='couch-h2')
        page = dash.render(self.cards()[1])
        self.assertEqual(page.count('data-do="revisions" data-ad='), 1)                # approved rows have no link of their own
        self.assertIn('data-do="revisions" data-ad="couch-h3"', page)
        code, r = fr.handle_revisions({'token': self.tok, 'batch': 'Couch V1'}, start=False)
        self.assertEqual(code, 200)
        self.assertIn('approved videos are left alone', r['message'])
        asked, run = self.pulls({'couch-h3': ['a']})
        e = fr.collect_revisions('Couch V1', runner=run)
        self.assertEqual((e['ads'], e['notes'], asked), (['couch-h3'], {'couch-h3': 1}, ['couch-h3']))
        cs, data = self.cards()
        for done in ('couch-h1', 'couch-h2'):
            self.assertEqual((cs[done]['tab'], cs[done]['status'], cs[done].get('approved'), cs[done].get('revising')), ('review', 'Approved', True, None))
        self.assertEqual(cs['couch-h3']['status'], 'Revisions sent')
        page = dash.render(data)
        self.assertEqual(page.count('class="row live done"'), 2)                       # approved: listed, dimmed, not counted
        self.assertIn('data-tab="review" aria-selected="false" aria-controls="p-review"><span class="n">0</span>', page)

    def test_nothing_left_to_revise_is_said_in_words(self):
        self.ad('couch-h1'), self.ad('couch-h2')
        self.approve(ad='couch-h1')
        code, r = fr.handle_revisions({'token': self.tok, 'ad': 'couch-h1'}, start=False)   # an old page: the row is approved
        self.assertEqual((code, 'You approved this video' in r['error']), (400, True))
        self.approve(ad='couch-h2')
        code, r = fr.handle_revisions({'token': self.tok, 'batch': 'Couch V1'}, start=False)
        self.assertEqual((code, 'nothing to revise' in r['error']), (400, True))
        self.assertNotIn('Couch V1', fr.revision_requests())
        self.assertNotIn('data-do="revisions"', dash.render(self.cards()[1]))          # and the board offers no button for it
        self.assertEqual(fr.handle_revisions({'token': self.tok, 'ad': 'nope'}, start=False)[0], 400)

    def test_an_approved_video_is_never_shown_as_revisions_sent(self):
        """2026-11-23: v1-v4 approved, notes on v5 only; the board showed all five as "Revisions sent"."""
        for n in ('v1', 'v2', 'v3', 'v5'):
            self.ad(f'up-{n}', batch='Up 5')
        self.approve(ad='up-v1'), self.approve(ad='up-v2')
        # the request lists v5 only: v3 (not approved, not sent) and the approved ones are not Claude's work
        fr.save_revision('Up 5', {'batch': 'Up 5', 'ads': ['up-v5'], 'pressed_at': NOW, 'state': 'working', 'notes': {'up-v5': 8}})
        cs, data = self.cards()
        self.assertEqual([cs[f'up-{n}']['status'] for n in ('v1', 'v2', 'v3', 'v5')], ['Approved', 'Approved', 'Ready to review', 'Revisions sent'])
        # even a request that names an approved video (an old press, a hand-made file) cannot show it as sent
        fr.save_revision('Up 5', {'ads': ['up-v1', 'up-v2', 'up-v3', 'up-v5']})
        cs, data = self.cards()
        self.assertEqual([cs[f'up-{n}']['status'] for n in ('v1', 'v2', 'v3', 'v5')], ['Approved', 'Approved', 'Revisions sent', 'Revisions sent'])
        self.assertEqual([cs[f'up-{n}']['tab'] for n in ('v1', 'v2')], ['review', 'review'])
        page = dash.render(data)
        self.assertEqual(page.count('class="row live done"'), 2)

if __name__ == '__main__':
    unittest.main()
