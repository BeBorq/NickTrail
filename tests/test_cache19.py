import unittest,json
from unittest.mock import patch
from nicktrail.network import Client
class Cache19Tests(unittest.TestCase):
 def test_negative_cache_expires_and_new_account_can_be_seen(self):
  class Response:
   def __init__(self,status):self.status=status;self.done=False
   def getheader(self,key,default=''):return 'application/json' if key=='Content-Type' else default
   def read1(self,*args):
    if self.done:return b''
    self.done=True;return b'{}'
  class Connection:
   status=404;sent=0
   def __init__(self,*a,**kw):pass
   def request(self,*a,**kw):Connection.sent+=1
   def getresponse(self):return Response(Connection.status)
   def close(self):pass
  with patch.dict('nicktrail.network.PROCESS_COOLDOWNS',{},clear=True),patch('nicktrail.network.public_addresses',return_value=['93.184.216.34']),patch('nicktrail.network.PinnedTLS',Connection),patch('nicktrail.network.time.monotonic',return_value=100) as clock:
   client=Client(delay=0,seconds=300)
   self.assertEqual(client.get('https://api.example/profile?token=secret-query')['state'],'not_found')
   Connection.status=200
   self.assertEqual(client.get('https://api.example/profile?token=secret-query')['state'],'not_found');self.assertEqual(Connection.sent,1)
   clock.return_value=161
   self.assertEqual(client.get('https://api.example/profile?token=secret-query')['state'],'found');self.assertEqual(Connection.sent,2)
   self.assertEqual(sum(e['kind']=='cache_hit' for e in client.events),1);self.assertNotIn('secret-query',json.dumps(client.events))
 def test_cache_and_accounting_are_bounded(self):
  c=Client()
  for i in range(600):c.remember(('fictional',i),{'state':'not_found'},60)
  self.assertEqual(len(c.cache),512);self.assertEqual(len(c.cache_expiry),512)
  for i in range(5000):c.event('response',host='fictional.example',status=200)
  self.assertEqual(len(c.events),4096);self.assertEqual(c.events_truncated,904)
