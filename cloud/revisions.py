"""Offline Frame.io-feedback batch planning on the existing Queue/Controller.

Only synthetic, explicitly mock projects are executable here. No shared tools,
CLI, media, credentials, network, approvals or review hosting are used.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cloud import approval
from cloud.orchestrator import Queue, GateError, inputs_hash
from cloud.providers.paid import JournalAdapter, MockTransport
from cloud.worker.controller import Controller


def plan_feedback(projects, entries):
    """Group explicit redo decisions by ad/beat; park everything uncertain.

    projects is {ad: plan-dict}. Frame.io's existing logged text has a bracketed
    prefix and an empty decision; only an explicit leading redo token is read.
    Timestamps deliberately aren't guessed against VO windows/master edits.
    """
    grouped, parked, seen = {}, [], {}
    for raw in entries:
        entry = dict(raw)
        identity = (entry.get('ad'), entry.get('frameio_comment', entry.get('id')))
        digest = inputs_hash(entry)
        if identity[1] is not None:
            if identity in seen:
                if seen[identity] != digest:
                    raise ValueError('Conflicting duplicate feedback identity')
                continue
            seen[identity] = digest
        ad, beat = entry.get('ad'), entry.get('beat')
        project = projects.get(ad)
        reason = None
        if project is None:
            reason = 'unknown_ad'
        elif project.get('locked'):
            reason = 'locked_refused'
        elif entry.get('status', 'open') != 'open':
            reason = 'not_open'
        elif type(beat) is not int:
            reason = 'master_timestamp_ambiguous' if entry.get('time') is not None else 'beat_required'
        elif beat not in [b['n'] for b in project.get('beats', [])]:
            reason = 'unknown_beat'
        decision = entry.get('decision', '')
        if not decision:
            text = re.sub(r'^\[frame\.io [^\]]+\]\s*', '', entry.get('text', ''))
            match = re.match(r'^(redo-frame|redo-clip)(?=\s|$|[—:])', text)
            decision = match.group(1) if match else ''
        if reason is None and decision not in {'redo-frame', 'redo-clip'}:
            reason = 'explicit_redo_required'
        if reason is None and not entry.get('text', '').strip():
            reason = 'note_required'
        if reason is None and next(b for b in project['beats'] if b['n'] == beat).get('lib'):
            reason = 'library_asset_refused'
        if reason:
            parked.append({'entry': entry, 'reason': reason})
            continue
        key = (ad, beat)
        group = grouped.setdefault(key, {'ad': ad, 'beat': beat, 'kind': 'clip', 'notes': []})
        if decision == 'redo-frame':
            group['kind'] = 'frame'
        group['notes'].append(entry)
    return {'jobs': list(grouped.values()), 'parked': parked, 'preserve_vo': True}


def _atomic(path, value):
    approval._atomic(path, approval._json(value) + b'\n')


class MockJournalAdapter(JournalAdapter):
    """Explicit controller mock marker; real JournalAdapter path stays disabled."""
    mock = True


class RevisionBatch:
    """Persist a small redo graph; dispatch its actual jobs with Controller.

    Frame approvals are never minted here. Existing approved frame job IDs can
    be bound using bind_frames; Queue verifies ad/workflow/beat and approval.
    Mock local checks are domain-labelled simulation, never media evidence.
    Native gate is blocked until an explicit synthetic receipt is recorded.
    """
    def __init__(self, root, *, clock=None):
        self.root = Path(root).absolute()
        scratch = Path(__file__).parent / '.scratch'
        if not self.root.resolve().is_relative_to(scratch.resolve()):
            raise ValueError('Revision workspace must be inside cloud/.scratch')
        self.state_path = self.root / 'revisions.json'
        self.state = json.loads(self.state_path.read_text())
        if self.state.get('mock') is not True:
            raise ValueError('Only explicit mock batches supported')
        self.clock_args = {} if clock is None else {'clock': clock}
        self.q = Queue(self.root / 'queue.sqlite', backoff_base=0, **self.clock_args)

    @classmethod
    def create(cls, root, projects, entries, *, limits, cap, clock=None):
        root = Path(root).absolute()
        scratch = Path(__file__).parent / '.scratch'
        if not root.resolve().is_relative_to(scratch.resolve()):
            raise ValueError('Revision workspace must be inside cloud/.scratch')
        if root.exists():
            raise FileExistsError('Fresh batch workspace required')
        if set(limits) != {'kie', 'ffmpeg'} or any(type(v) is not int or v < 1 for v in limits.values()):
            raise ValueError('Explicit positive mock provider limits required')
        for ad, plan in projects.items():
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', ad):
                raise ValueError('Safe ad identifier required')
            if plan.get('cloud_mock') is not True:
                raise ValueError('Only synthetic cloud_mock projects supported')
            beats = [b['n'] for b in plan['beats']]
            if not beats or any(type(b) is not int or b < 1 for b in beats) or len(set(beats)) != len(beats):
                raise ValueError('Unique positive beats required')
        planned = plan_feedback(projects, entries)
        args = {} if clock is None else {'clock': clock}
        root.mkdir(parents=True)
        q = Queue(root / 'queue.sqlite', provider_limits=limits, backoff_base=0, **args)
        run = q.create_run(go=True, credit_cap=cap)
        state = {'mock': True, 'run': run, 'workflow': inputs_hash({'projects': projects, 'plan': planned}),
                 'planned': planned, 'ads': {}, 'limits': limits}
        for item in planned['jobs']:
            ad = item['ad']
            if ad not in state['ads']:
                path = root / ad / 'plan.json'
                path.parent.mkdir()
                _atomic(path, projects[ad])
                state['ads'][ad] = {'plan_hash': inputs_hash(projects[ad]), 'nodes': {}, 'sources': {}}
            nodes = state['ads'][ad]['nodes']
            beat = item['beat']
            previous = []
            if item['kind'] == 'frame':
                name = 'frames:' + str(beat)
                nodes[name] = {'stage': 'frames', 'beat': beat, 'deps': [], 'notes': item['notes']}
                previous = [name]
            nodes['clips:' + str(beat)] = {'stage': 'clips', 'beat': beat, 'deps': previous, 'notes': item['notes']}
        for ad, data in state['ads'].items():
            nodes = data['nodes']
            deps = [n for n in nodes if n.startswith('clips:')]
            for name in ('qc', 'stitch', 'masterqc', 'preflight', 'native_mac'):
                nodes[name] = {'stage': 'status' if name == 'native_mac' else name,
                               'beat': None, 'deps': deps, 'notes': []}
                deps = [name]
        _atomic(root / 'revisions.json', state)
        batch = cls(root, clock=clock)
        batch.refresh()
        return batch

    def _save(self):
        _atomic(self.state_path, self.state)

    def _check(self, ad):
        plan = json.loads((self.root / ad / 'plan.json').read_text())
        if plan.get('locked') or inputs_hash(plan) != self.state['ads'][ad]['plan_hash']:
            raise GateError('Locked or changed staged project refused')

    def bind_frames(self, ad, beat, source_ids):
        """Bind prior mock frame provenance; Queue checks it before dispatch."""
        self._check(ad)
        self.state['ads'][ad]['sources'][str(beat)] = list(source_ids)
        self._save()
        self.refresh()

    def refresh(self):
        # Re-enqueue is idempotent if a process died before saving the job ID.
        for ad, data in self.state['ads'].items():
            self._check(ad)
            nodes = data['nodes']
            for name, node in nodes.items():
                if not all(nodes[d].get('job') and self.q.get(nodes[d]['job'])['state'] in
                           ({'done'} if nodes[d]['stage'] == 'frames' else {'done', 'awaiting_approval'})
                           for d in node['deps']):
                    continue
                if not node.get('job'):
                    identity = {'workflow': self.state['workflow'], 'ad': ad, 'node': name,
                                'deps': {d: nodes[d]['job'] for d in node['deps']}, 'notes': node['notes']}
                    revision = inputs_hash(identity)
                    gates = []
                    if name == 'stitch': gates = ['qc']
                    if name == 'masterqc': gates = ['caption_sync']
                    if name == 'preflight': gates = ['masterqc']
                    if name == 'native_mac': gates = ['preflight', 'native_mac']
                    # Separate namespaces prevent another beat's approval
                    # from unlocking this beat.
                    job = self.q.enqueue(self.state['run'], ad + '/' + name, node['stage'],
                                         {'mock': True, 'graph': identity, 'preserve_vo': True},
                                         plan_path=self.root / ad / 'plan.json',
                                         provider='kie' if node['beat'] else 'ffmpeg',
                                         known_cost='.1' if node['beat'] else None,
                                         revision=revision,
                                         required_gates=gates, max_attempts=100)
                    node['job'] = job['id']
                    self._save()
                target = self.q.get(node['job'])
                for gate in target['required_gates']:
                    if gate in {'frames_approved', 'plan_review', 'native_mac'}:
                        continue
                    for dep in node['deps']:
                        source = self.q.get(nodes[dep]['job'])
                        with self.q._tx() as db:
                            receipt = db.execute('SELECT passed,evidence FROM gates WHERE ad_id=? AND revision=? AND name=?',
                                                 (source['ad_id'], source['revision'], gate)).fetchone()
                        if receipt and receipt['passed']:
                            self.q.record_gate(target['ad_id'], target['revision'], gate, passed=True,
                                               evidence='MOCK dependency ' + source['id'] + ': ' + receipt['evidence'])
                if name.startswith('clips:') or name == 'stitch':
                    sources = []
                    for n, sibling in nodes.items():
                        if n.startswith('clips:') and (name == 'stitch' or sibling['beat'] == node['beat']):
                            frame = nodes.get('frames:' + str(sibling['beat']))
                            sources.extend([frame['job']] if frame and frame.get('job') else
                                           data['sources'].get(str(sibling['beat']), []))
                    if sources:
                        self.q.inherit_frames(node['job'], sources)
        return self.status()

    def adapters(self):
        transport = MockTransport(self.root / 'mock-service.sqlite')
        batch = self

        class Local:
            def run(self, job):
                name = job['inputs']['graph']['node']
                gate = {'qc': 'qc', 'stitch': 'caption_sync', 'masterqc': 'masterqc',
                        'preflight': 'preflight'}.get(name)
                if gate:
                    batch.q.record_gate(job['ad_id'], job['revision'], gate, passed=True,
                                        evidence='SYNTHETIC MOCK check; no media examined')
                return {'status': 'done', 'mock': True, 'deliverable': False, 'approved': False}

        return {'kie': MockJournalAdapter(self.q, 'kie', transport, mock=True), 'ffmpeg': Local()}

    def run_parallel(self, *, workers=3, rounds=1):
        """Bounded parallel controller steps; no background processes or paid path."""
        if type(workers) is not int or not 1 <= workers <= 32 or type(rounds) is not int or not 1 <= rounds <= 10000:
            raise ValueError('Bounded workers/rounds required')
        rows = []
        adapters = self.adapters()
        for _ in range(rounds):
            self.refresh()
            with ThreadPoolExecutor(max_workers=workers) as pool:
                steps = list(pool.map(lambda _: Controller(self.q, adapters).step(), range(workers)))
            rows.extend(row for row in steps if row is not None)
            if not any(steps):
                break
        self.refresh()
        return rows

    def status(self):
        ads = {}
        for ad, data in self.state['ads'].items():
            nodes = data['nodes']
            states = {n: self.q.get(v['job'])['state'] if v.get('job') else 'blocked_dependencies'
                      for n, v in nodes.items()}
            state = ('await_owner' if states['native_mac'] == 'done' else
                     'failed' if 'failed' in states.values() else 'blocked_gates_or_dependencies')
            ads[ad] = {'state': state, 'nodes': states}
        return {'mock': True, 'deliverable': False, 'approved': False, 'ads': ads,
                'parked': self.state['planned']['parked'], 'spend': self.q.run_status(self.state['run'])}

    def push_dry_run(self, ad):
        if ad not in self.state['ads']:
            raise KeyError(ad)
        return {'action': 'Frame.io push', 'mode': 'DRYRUN', 'network': False,
                'ad': ad, 'state': self.status()['ads'][ad]['state'],
                'approved': False, 'deliverable': False,
                'blocked': 'owner approval and unchanged delivery/all-three-hooks gates required'}
