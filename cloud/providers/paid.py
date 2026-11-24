"""Durable no-network paid-provider protocol. No credential reads or SDK imports.

Kie async tasks and ElevenLabs synchronous receipts are distinct contracts.
The latter's mock polling is LOCAL receipt replay, not an invented remote API.
"""
from __future__ import annotations
import json,sqlite3
from pathlib import Path
from contextlib import closing
from cloud.orchestrator import SubmissionAmbiguous,GateError,inputs_hash

class RealCallsDisabled(RuntimeError):pass

class JournalAdapter:
 def __init__(self,queue,provider,transport,*,mock=False):
  if provider not in {'kie','elevenlabs'}:raise ValueError('Unknown provider')
  if not mock:raise RealCallsDisabled('Real calls disabled; explicit --go would also be required')
  self.q=queue;self.provider=provider;self.transport=transport
  with self.q._tx() as db:
   db.execute('CREATE TABLE IF NOT EXISTS paid_intents(job_id TEXT PRIMARY KEY,provider TEXT,request_hash TEXT,receipt TEXT)')
  self.recover_pending()
 @staticmethod
 def real(provider,*,go=False):
  if not go:raise RealCallsDisabled('Explicit --go required; real path remains disabled')
  raise RealCallsDisabled('Real paid transport disabled in this build')
 def submit(self,job):
  fresh=self.q.get(job['id']);token=job['lease_token']
  with self.q._tx() as db:
   self.q._owned(db,job['id'],token)
   if not fresh['submission_started'] or not fresh['remote_open']:raise GateError('Reserved spend and provider slot required')
   if db.execute('SELECT 1 FROM paid_intents WHERE job_id=?',(job['id'],)).fetchone():raise SubmissionAmbiguous('Durable intent exists; never resubmit')
   db.execute('INSERT INTO paid_intents VALUES (?,?,?,NULL)',(job['id'],self.provider,inputs_hash(job['inputs'])))
  # Intent transaction fsynced BEFORE a transport can accept anything.
  receipt=self.transport.submit(fresh)
  with self.q._tx() as db:db.execute('UPDATE paid_intents SET receipt=? WHERE job_id=?',(receipt,job['id']))
  self.q.record_provider_job(job['id'],token,receipt) # ID+JSONL before any poll
  return receipt
 def poll(self,job,provider_id):
  if self.q.poll_ready(job['id'],job['lease_token'])!=provider_id:raise GateError('Receipt mismatch')
  with closing(self.q._connect()) as db:
   row=db.execute('SELECT receipt FROM paid_intents WHERE job_id=?',(job['id'],)).fetchone()
   if not row or row[0]!=provider_id:raise GateError('Missing durable adapter receipt')
  return self.transport.poll(job,provider_id)
 def recover_pending(self):
  """Repair only IDs already fsynced locally; unknown accepted calls stay blocked."""
  self.q.recover_expired()
  with closing(self.q._connect()) as db:
   rows=db.execute("SELECT p.* FROM paid_intents p JOIN jobs j ON j.id=p.job_id WHERE p.provider=? AND p.receipt IS NOT NULL AND j.state='failed' AND j.ambiguous=1 AND j.provider_job_id IS NULL",(self.provider,)).fetchall()
  for row in rows:
   job=self.q.get(row['job_id'])
   if inputs_hash(job['inputs'])!=row['request_hash']:raise GateError('Receipt input hash changed')
   self.q.reconcile(job['id'],row['receipt'],owner='verified durable local adapter receipt')
  return len(rows)
 def recover_receipt(self,job_id):
  """Local durable receipt only; never queries a network or guesses an accepted ID."""
  with closing(self.q._connect()) as db:
   row=db.execute('SELECT receipt FROM paid_intents WHERE job_id=?',(job_id,)).fetchone()
   return row[0] if row else None

class MockTransport:
 """Persistent deterministic fake service; survives queue process replacement."""
 def __init__(self,path):
  self.path=Path(path)
  with self.db() as db:db.execute('CREATE TABLE IF NOT EXISTS accepted(job TEXT PRIMARY KEY,id TEXT UNIQUE,polls INTEGER DEFAULT 0,failures INTEGER DEFAULT 0,terminal_fail INTEGER DEFAULT 0)')
 def db(self):
  db=sqlite3.connect(self.path);db.execute('PRAGMA synchronous=FULL');return db
 def submit(self,job):
  receipt='mock-'+job['input_hash'][:24]+'-'+job['id'][:8]
  fault=job['inputs'].get('mock_fault',{})
  with self.db() as db:
   if db.execute('SELECT 1 FROM accepted WHERE job=?',(job['id'],)).fetchone():raise AssertionError('DOUBLE SUBMISSION')
   db.execute('INSERT INTO accepted VALUES (?,?,0,?,?)',(job['id'],receipt,fault.get('poll_failures',0),int(fault.get('terminal_fail',False))))
  return receipt
 def poll(self,job,receipt):
  with self.db() as db:
   row=db.execute('SELECT polls,failures,terminal_fail FROM accepted WHERE job=? AND id=?',(job['id'],receipt)).fetchone()
   if not row:raise AssertionError('Unknown mock task')
   db.execute('UPDATE accepted SET polls=polls+1 WHERE job=?',(job['id'],))
  if row[0]<row[1]:raise RuntimeError('seeded polling failure')
  return {'status':'failed' if row[2] else 'done','result':{'status':'done','mock':True,'deliverable':False}}
