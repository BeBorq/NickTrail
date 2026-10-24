"""Endpoint-specific public API errors; never expose arbitrary error payloads."""
import json,re
from urllib.parse import urlsplit,parse_qs

def public_error(url,status,content_type,payload):
 if status!=400 or content_type!='application/json' or len(payload)>16384:return None
 p=urlsplit(url)
 if p.scheme!='https' or p.username or p.password:return None
 try:body=json.loads(payload)
 except (ValueError,UnicodeError):return None
 if not isinstance(body,dict):return None
 if p.hostname=='public.api.bsky.app' and p.path=='/xrpc/app.bsky.actor.getProfile':
  actors=parse_qs(p.query).get('actor',[])
  if len(actors)!=1:return None
  actor=actors[0]
  valid_handle=len(actor)<=253 and len(actor.split('.'))>=2 and all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?',part) for part in actor.split('.'))
  if not valid_handle and not re.fullmatch(r'did:plc:[a-z2-7]{24}',actor):return None
  if body.get('error')=='InvalidRequest' and body.get('message')=='Profile not found':
   return {'state':'not_found','detail':'PUBLIC_API_PROFILE_NOT_FOUND: profile absent from this public resolver; not proof of global account absence'}
  if body.get('error') in ('AccountTakedown','AccountDeactivated'):
   return {'state':'partial','detail':'PUBLIC_API_ACCOUNT_UNAVAILABLE: suspended or deactivated; not missing'}
 if p.hostname=='codeforces.com' and p.path=='/api/user.info':return codeforces_error(body,parse_qs(p.query).get('handles',[]))
 return None

def codeforces_error(body,handles):
 if not isinstance(body,dict) or body.get('status')!='FAILED':return None
 comment=body.get('comment')
 if comment=='Call limit exceeded':return {'state':'blocked','detail':'RATE_LIMITED: Codeforces API call limit; retry after cooldown'}
 if len(handles)==1 and re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',handles[0]) and comment=='handles: User with handle '+handles[0]+' not found':
  return {'state':'not_found','detail':'PUBLIC_API_PROFILE_NOT_FOUND: exact requested Codeforces handle missing'}
 return None
