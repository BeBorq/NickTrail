"""Persist provider Retry-After across workers sharing one project database."""
import time,math,threading
from .storage import SCHEMA_LOCK

def schema(store):
 with SCHEMA_LOCK:
  initialized=getattr(store,'_initialized_schemas',set())
  if 'provider_cooldowns' in initialized:return
  store.execute('CREATE TABLE IF NOT EXISTS provider_cooldowns(host TEXT PRIMARY KEY,until_epoch REAL,updated REAL,blocks INTEGER DEFAULT 0)')
  if 'blocks' not in {r['name'] for r in store.rows('PRAGMA table_info(provider_cooldowns)')}:store.execute('ALTER TABLE provider_cooldowns ADD COLUMN blocks INTEGER DEFAULT 0')
  store._initialized_schemas=initialized|{'provider_cooldowns'}

def active(store):
 schema(store)
 return store.rows('SELECT host,until_epoch,updated FROM provider_cooldowns WHERE until_epoch>? ORDER BY until_epoch',(time.time(),))

def robots_schema(store):
 with SCHEMA_LOCK:
  store.execute('CREATE TABLE IF NOT EXISTS robots_decisions(host TEXT PRIMARY KEY,detail TEXT,until_epoch REAL,updated REAL)')

def _write(client,store,sql,args):
 # SQLite connections belong to one thread; parallel readers queue their writes.
 if threading.get_ident()==getattr(client,'_owner_thread',threading.get_ident()):store.execute(sql,args)
 else:
  queue=getattr(client,'persist_queue',None)
  if isinstance(queue,list):queue.append((sql,args))

def flush(client,store):
 queue=getattr(client,'persist_queue',None)
 while isinstance(queue,list) and queue:
  sql,args=queue.pop(0);store.execute(sql,args)

def bind(client,store):
 if not callable(getattr(client,'defer_host',None)) or not isinstance(getattr(client,'cooldowns',None),dict):return False
 if getattr(client,'_cooldown_store',None) is store:return True
 schema(store);original=getattr(client,'_unpersisted_defer_host',client.defer_host)
 client._owner_thread=threading.get_ident()
 for row in active(store):original(row['host'],max(0,row['until_epoch']-time.time()))
 def defer(host,seconds):
  if type(seconds) not in (int,float) or not math.isfinite(seconds) or seconds<0:return
  original(host,seconds);until=time.time()+seconds
  _write(client,store,'INSERT INTO provider_cooldowns(host,until_epoch,updated,blocks) VALUES(?,?,?,1) ON CONFLICT(host) DO UPDATE SET until_epoch=MAX(provider_cooldowns.until_epoch,excluded.until_epoch),updated=excluded.updated,blocks=provider_cooldowns.blocks+1',(host,until,time.time()))
 client._unpersisted_defer_host=original;client._cooldown_store=store;client.defer_host=defer
 if hasattr(client,'robots_memory'):
  robots_schema(store)
  remembered={r['host']:(r['detail'],r['until_epoch']) for r in store.rows('SELECT host,detail,until_epoch FROM robots_decisions WHERE until_epoch>?',(time.time(),))}
  def memory(action,host,detail=None):
   from .network import setting
   if action=='get':
    value=remembered.get(host)
    return value[0] if value and value[1]>time.time() else None
   until=time.time()+3600*setting('robots_memory_hours');remembered[host]=(detail,until)
   _write(client,store,'INSERT INTO robots_decisions(host,detail,until_epoch,updated) VALUES(?,?,?,?) ON CONFLICT(host) DO UPDATE SET detail=excluded.detail,until_epoch=excluded.until_epoch,updated=excluded.updated',(host,detail,until,time.time()))
  client.robots_memory=memory
 return True

def waiting(store):
 """Active provider pauses with their cumulative block count, for the panel countdown."""
 schema(store);now=time.time()
 rows=store.rows('SELECT host,until_epoch,blocks FROM provider_cooldowns WHERE until_epoch>? ORDER BY until_epoch',(now,))
 return {'now_epoch':now,'hosts':[{'host':r['host'],'until_epoch':r['until_epoch'],'blocks':r['blocks'] or 0} for r in rows],
         'total_blocks':store.rows('SELECT COALESCE(SUM(blocks),0) n FROM provider_cooldowns')[0]['n']}

def forget_robots(store):
 """Clear remembered robots.txt refusals (panel/CLI action)."""
 robots_schema(store);count=store.rows('SELECT count(*) n FROM robots_decisions')[0]['n']
 store.execute('DELETE FROM robots_decisions');return count
