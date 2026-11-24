"""Independent owned process-group watchdog. Parent pipe closure is fatal."""
import os,select,signal,sys,time,pathlib
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from hygiene import disk_free_probe

def main():
 pid=int(sys.argv[1]);deadline=time.monotonic()+float(sys.argv[2]);sys.stdout.write('1');sys.stdout.flush()
 while True:
  ready,_,_=select.select([sys.stdin.buffer],[],[],.2)
  if ready:
   value=os.read(sys.stdin.fileno(),1)
   if value==b'D':return
   if not value:break
  if time.monotonic()>deadline or disk_free_probe(sys.argv[3])<8_000_000_000:break
 try:os.killpg(pid,signal.SIGKILL)
 except ProcessLookupError:pass
if __name__=='__main__':main()
