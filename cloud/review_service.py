"""Stdlib review endpoint. Pure application tests; no listener started on import."""
from __future__ import annotations
import argparse,json,mimetypes,os
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import unquote,urlsplit
from cloud.volume_cli import open_flow
MAX_BODY=65536
class Application:
 def __init__(self,workflow,*,key):self.flow=workflow;self.key=key
 def handle(self,method,path,body=b''):
  headers={'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'self'; script-src 'none'; frame-ancestors 'none'"}
  def reply(code,value):return code,headers,json.dumps(value).encode()
  if len(body)>MAX_BODY:return reply(413,{'error':'Body too large'})
  path=unquote(urlsplit(path).path)
  if method=='POST' and path=='/decision':
   try:return reply(200,self.flow.apply(json.loads(body),key=self.key))
   except (ValueError,KeyError,TypeError):return reply(409,{'error':'Signed decision rejected; see local rejection log'})
  if method!='GET':return reply(405,{'error':'Method not allowed'})
  if path=='/':file=self.flow.board()
  elif path.startswith('/ads/'):
   # Serve ONLY assets in the declared review bundle, never plan/queue/key files.
   parts=path.split('/')
   if len(parts)<4 or any(p in {'.','..',''} for p in parts[1:]):return reply(404,{'error':'Not found'})
   try:
    from cloud.approval import _review_files
    project=self.flow.project(parts[2]);files=_review_files(project);rel='/'.join(parts[3:])
    if rel not in files:return reply(404,{'error':'Not found'})
    file=files[rel]
   except (ValueError,KeyError,OSError):return reply(404,{'error':'Not found'})
  else:return reply(404,{'error':'Not found'})
  headers['Content-Type']=mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
  return 200,headers,file.read_bytes()

def handler_for(application):
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass # never log request bodies or signed payloads
  def _serve(self):
   try:
    raw=self.headers.get('Content-Length','0');length=int(raw)
    if length<0 or length>MAX_BODY or self.headers.get('Transfer-Encoding'):code,headers,body=413,{},b'Body refused'
    elif getattr(application,'requires_headers',False):code,headers,body=application.handle(self.command,self.path,self.rfile.read(length),headers=dict(self.headers),peer=self.client_address[0])
    else:code,headers,body=application.handle(self.command,self.path,self.rfile.read(length))
   except (ValueError,TypeError):code,headers,body=400,{},b'Bad request'
   self.send_response(code)
   for k,v in headers.items():self.send_header(k,v)
   self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
  do_GET=_serve;do_POST=_serve
 return Handler


def authenticated_application(workflow,*,decision_key,access_key,database,origin):
 """Pure factory. No server binding; the two keys must be distinct."""
 from cloud.review_auth import Auth,SecureApplication
 from cloud import approval
 application=Application(workflow,key=decision_key)
 def workspace_for(ad):
  project,plan=approval._load(workflow.project(ad))
  return plan[approval.STATE_KEY]['id']
 return SecureApplication(application,Auth(database,key=access_key),origin=origin,workspace_for=workspace_for)

def main(argv=None):
 p=argparse.ArgumentParser();p.add_argument('workflow');p.add_argument('--bind',default='127.0.0.1',choices=['127.0.0.1']);p.add_argument('--port',type=int,default=8765);p.add_argument('--go',action='store_true');a=p.parse_args(argv)
 if not a.go:print(json.dumps({'dry_run':True,'bind':a.bind,'port':a.port,'listener_started':False}));return 0
 from cloud.approval import _key
 key=_key(os.environ.get('CLOUD_APPROVAL_KEY','').encode())
 with ThreadingHTTPServer((a.bind,a.port),handler_for(Application(open_flow(a.workflow),key=key))) as server:server.serve_forever()
if __name__=='__main__':main()
