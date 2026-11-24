"""Recipes + the orchestrator core of the cloud ad controller (app `<app_prefix>-ads`, see cloud/controller/app.py).

A recipe is an ordered list of steps; each step runs in the one worker kind that holds only what the step needs:
  plain   no secret, network blocked     (render, pad, offline check)
  gen     kie + ElevenLabs secret        (voiceover, stills, clips, redos)       <- the only paid kind
  claude  Claude login token only        (shot check, plan review, QC, stitch, master QC)
run_pipeline() runs one ad's steps in order, stops at the first failure or blocked gate, and reports state after every
step. It has no Modal imports: the deployed app passes in `call` and `status`, tests pass fakes.

Paid work is one stage per step (voice, then stills, then clips): each step saves the project when it ends, and the paid
worker also checkpoints its generation records while it runs, so a crash or timeout never loses a paid task id. The kie
task cap belongs to the whole run: the worker keeps the run's task counter inside the project, so every paid step and
every retry counts against the same number.
"""
import json
import re
import time

KINDS = {
    'plain': {'check', 'rawrender', 'padtail', 'rawverify', 'preflight', 'status'},
    'gen': {'vo', 'frames', 'clips', 'redo'},
    'claude': {'shotcheck', 'plan_review', 'qc', 'stitch', 'masterqc'},
}
FINISH = ('claude', ['qc', 'stitch', 'masterqc'])
RECIPES = {
    # real-footage ad (rawedit): check every planned shot against its line, then render. Mac runs verify + preflight after.
    'raw': [('claude', ['shotcheck']), ('plain', ['rawrender', 'padtail'])],
    # AI / animated ad from an approved plan, straight through: reviewer pass, voice, stills, clips, QC + assemble.
    'ai': [('claude', ['plan_review']), ('gen', ['vo']), ('gen', ['frames']), ('gen', ['clips']), FINISH],
    # the same ad in two halves, with the owner's starting-frame review in between:
    #   ai-frames         reviewer pass, voice, stills, stills QC -> stop (collect builds REVIEW.html)
    #   ai-frames-revise  redo the named stills from his notes, stills QC -> stop again
    #   ai-clips          clips for the approved stills, QC + assemble
    'ai-frames': [('claude', ['plan_review']), ('gen', ['vo']), ('gen', ['frames']), ('claude', ['qc'])],
    'ai-frames-revise': [('gen', ['redo']), ('claude', ['qc'])],
    'ai-clips': [('gen', ['clips']), FINISH],
    # an ad whose voiceover already exists (a run that stopped part-way, or a song ad): the voice is never made twice.
    'ai-resume': [('gen', ['frames']), ('gen', ['clips']), FINISH],
    # owner revisions on a finished AI ad: redo the named beats (never the voiceover), then QC + assemble again.
    'ai-revise': [('gen', ['redo']), FINISH],
    # re-assemble only (caption / music / plan tweak): no generation.
    'ai-finish': [FINISH],
    # AI b-roll inserts for a real-footage ad: stills + clips + QC, no voiceover, no stitch.
    'inserts': [('gen', ['frames']), ('gen', ['clips']), ('claude', ['qc'])],
    'check': [('plain', ['check'])],
}
# Final checks on the finished video, run in the cloud as one more step when the submit asks for them (`checks`): the run
# then comes back already checked. They are ADVISORY: a check that fails, or a check worker that crashes,
# never fails the run (the video is made; the result says what the checks found). `preflight` here is the video-only part
# (tools/preflight.py --media-json); Apple Vision tilt, the banned list and the sibling-hook checks need the Mac.
CHECK_STEP = {'raw': ('plain', ['rawverify', 'preflight']),
              **{r: ('plain', ['preflight']) for r in ('ai', 'ai-resume', 'ai-clips', 'ai-revise', 'ai-finish')}}
QC_STAGE = {'ai-frames': 'frames', 'ai-frames-revise': 'frames'}   # these stop before any clip exists: QC the stills only
FRAME_REVIEW = set(QC_STAGE)                                       # done = waiting for the owner's frame review
NEEDS_REDOS = {'ai-revise', 'ai-frames-revise'}
PAID = {'gen'}
TERMINAL = {'done', 'failed', 'blocked', 'crashed'}
STAGE_TIMEOUT = {'plain': 2400, 'gen': 3300, 'claude': 2400}       # seconds all stages of one step may take together; the
#                                                                    cloud function's own limit is 5 minutes higher (setup + save)
RUN_ID = re.compile(r'[a-z0-9][a-z0-9-]{0,80}-[a-z-]{2,20}-\d{9,11}')


def is_paid(recipe):
    return any(kind in PAID for kind, _ in RECIPES[recipe])


def steps_of(recipe, checks=False):
    """The recipe's steps, plus the final-checks step when the run asked for it and the recipe ends in a finished video."""
    return list(RECIPES[recipe]) + ([CHECK_STEP[recipe]] if checks and recipe in CHECK_STEP else [])


def validate(job):
    for key in ('run', 'ad', 'recipe', 'code'):
        if not isinstance(job.get(key), str):
            raise ValueError(f'{key} required')
    if job['recipe'] not in RECIPES:
        raise ValueError('Known recipes only: ' + ', '.join(sorted(RECIPES)))
    if not RUN_ID.fullmatch(job['run']) or not job['run'].startswith(job['ad'] + '-'):
        raise ValueError('run id must be <ad>-<recipe>-<unix time>')
    if not re.fullmatch(r'[0-9a-f]{12,64}', job['code']):
        raise ValueError('code version must be a hex digest')
    if type(job.get('max_tasks', 0)) is not int or job.get('max_tasks', 0) < 0 or (job.get('max_tasks', 0) and not is_paid(job['recipe'])):
        raise ValueError('max_tasks only on a paid recipe')
    if (job['recipe'] in NEEDS_REDOS) != bool(job.get('redos')):
        raise ValueError('redos go with ai-revise / ai-frames-revise, and only with them')
    if job.get('timeout_s') is not None and (type(job['timeout_s']) is not int or not 60 <= job['timeout_s'] <= 3400):
        raise ValueError('timeout_s must be an int 60..3400')
    skip = job.get('skip', [])
    if not isinstance(skip, list) or any(s != 'vo' for s in skip):
        raise ValueError('only the voice step can be skipped (when the voiceover already exists)')
    if type(job.get('checks', False)) is not bool:
        raise ValueError('checks must be true or false')
    return steps_of(job['recipe'], job.get('checks', False))


def payload_for(job, kind, stages):
    limit = min(job.get('timeout_s') or STAGE_TIMEOUT[kind], STAGE_TIMEOUT[kind])   # a run may ask for less time, never more
    p = {'ad': job['ad'], 'stages': stages, 'code': job['code'], 'timeout_s': limit, 'run': job['run'],
         'max_tasks': job.get('max_tasks', 0) if kind in PAID else 0}   # the kie task cap only ever reaches the paid worker
    if 'redo' in stages:
        p['redos'] = job['redos']
    if 'qc' in stages and job['recipe'] in QC_STAGE:
        p['qc_stage'] = QC_STAGE[job['recipe']]
    if (kind, stages) == CHECK_STEP.get(job['recipe']) and job.get('checks'):
        p['advisory'] = True   # the worker reports what each check found instead of failing the step
    return p


def run_pipeline(job, call, status, now=time.time):
    """call(kind, payload) -> receipt JSON text from ad_job.run; status(state) persists the state dict (must not raise)."""
    steps = validate(job)
    skip = set(job.get('skip', []))
    state = {'run': job['run'], 'ad': job['ad'], 'recipe': job['recipe'], 'batch': job.get('batch'), 'state': 'running', 'steps': [],
             'plan': [[k, s] for k, s in steps], 'started': now(), 'updated': now()}
    for kind, stages in steps:
        if set(stages) <= skip:
            state['steps'].append({'kind': kind, 'stages': stages, 'skipped': True, 'seconds': 0})
            continue
        state.update(current={'kind': kind, 'stages': stages, 'since': now()}, updated=now())
        status(state)
        row = {'kind': kind, 'stages': stages, 'began': now()}
        payload = payload_for(job, kind, stages)
        receipt = None
        for attempt in (1, 2):
            try:
                receipt = json.loads(call(kind, payload))
                row['attempts'] = attempt
                break
            except Exception as error:
                # a worker that crashed, timed out or was refused. Unpaid steps get one more try. The paid kind is never
                # retried from here: an error on this side does not prove the paid container stopped, and two of them on
                # one ad would generate twice. Its task ids and finished files are checkpointed, so the next submit of
                # this ad (ai-resume / ai-clips) polls what was started instead of creating it again.
                row.update(error=f'{type(error).__name__}: {error}'[:400], seconds=round(now() - row['began'], 1), attempts=attempt)
                if kind in PAID or attempt == 2 or isinstance(error, ValueError):   # a refused payload stays refused
                    break
                row['retried'] = row.pop('error')
        if receipt is None:
            if payload.get('advisory'):   # the checks could not run (worker crash, or an app deployed before this step
                row['checks'] = None      # existed): the video is made, so the run is done and the Mac checks everything
                state['steps'].append(row)
                continue
            state['steps'].append(row); state['state'] = 'failed'
            break
        row.pop('error', None)
        bad = next((s for s in receipt.get('stages', []) if s.get('returncode') != 0), None)
        row.update(seconds=receipt.get('wall_seconds'), log=receipt.get('log'), gate=receipt.get('gate'),
                   kie_credits=receipt.get('kie_credits_consumed_this_run', 0), kie_tasks=receipt.get('kie_create_tasks_this_run', 0),
                   stage_seconds={s['stage']: s.get('seconds') for s in receipt.get('stages', [])}, checkpoints=receipt.get('checkpoints', 0))
        if receipt.get('not_done'):
            row['not_done'] = receipt['not_done']   # paid items the provider did not deliver (no charge): named for the owner
        if receipt.get('redos_done'):
            row['redos_done'] = receipt['redos_done']   # redos that are made and saved: never to be sent again
        if payload.get('advisory'):
            row['checks'] = receipt.get('checks') or {}   # {'rawverify': {...}, 'preflight': {...}}: what the cloud checks found
        if bad:
            row.update(failed=bad['stage'], returncode=bad['returncode'], tail=str(bad.get('tail', ''))[-900:])
        state['steps'].append(row)
        if receipt.get('gate') == 'blocked':
            state['state'] = 'blocked'
            break
        if bad:
            state['state'] = 'failed'
            break
    else:
        state['state'] = 'done'
    state.pop('current', None)
    state.update(finished=now(), updated=now())
    status(state)
    return state
