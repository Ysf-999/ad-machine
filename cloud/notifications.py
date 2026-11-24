"""Pure Slack preview builder. Never executes bin/slack-post or any transport."""
import pathlib
import sys
from urllib.parse import urlsplit
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import names  # noqa: E402
POSTER = str(pathlib.Path(__file__).resolve().parents[1] / 'bin' / 'slack-post')


def owner():
 """The @-mention of the owner, from "slack_user_id" in cloud/controller/config.json ('' when Slack is off)."""
 user = str(names.config().get('slack_user_id') or '').strip()
 return f'<@{user}>' if user else ''


def build(ad,event,url,*,gate=None,channel='OWNER_MUST_SUPPLY_CHANNEL'):
 for v in [ad,gate or '',channel]:
  if not isinstance(v,str) or any(ord(c)<32 for c in v) or any(c in v for c in '<>'):raise ValueError('Plain one-line labels required')
 parsed=urlsplit(url)
 if parsed.scheme not in {'http','https'} or not parsed.netloc or parsed.username or parsed.password or any(c in url for c in '\r\n<>'):raise ValueError('Public review URL without credentials required')
 if event=='awaiting_approval' and gate in {'frames','final'}:message=f'Ad {ad} awaiting approval at gate {gate}.'
 elif event=='failed':message=f'Ad {ad} failed.'
 else:raise ValueError('Unknown event or missing gate')
 text=' '.join(x for x in (owner(), message, f'Review: {url}') if x)
 return {'dry_run':True,'text':text,'link':url,'command':[POSTER,channel,'-'],'stdin':text,'sent':False}
