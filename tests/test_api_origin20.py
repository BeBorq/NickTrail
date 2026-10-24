import unittest
from unittest.mock import patch
from nicktrail.network import Client
from nicktrail.engines import lookup_platform
class ApiOrigin20Tests(unittest.TestCase):
 def test_api_foreign_origin_and_downgrade_block_before_second_connection(self):
  class Response:
   status=302;target='https://other.example/api/v1/users/fictional'
   def getheader(self,k,default=''):return self.target if k=='Location' else default
  class Conn:
   def __init__(self,*a,**kw):pass
   def request(self,*a,**kw):pass
   def getresponse(self):return Response()
   def close(self):pass
  with patch.dict('nicktrail.network.PROCESS_COOLDOWNS',{},clear=True),patch('nicktrail.network.public_addresses',return_value=['93.184.216.34']) as dns,patch('nicktrail.network.PinnedTLS',Conn):
   for target in ('https://other.example/api/v1/users/fictional','http://forge.example/api/v1/users/fictional'):
    Response.target=target;c=Client(delay=0)
    self.assertIn('REDIRECT_POLICY_BLOCKED',c.get('https://forge.example/api/v1/users/fictional')['detail']);self.assertEqual(c.count,1)
   self.assertEqual(dns.call_count,2)
 def test_configured_engine_rejects_transport_reporting_http_origin(self):
  class C:
   def get(self,url):return {'state':'found','url':url.replace('https:','http:'),'text':'{"id":1,"login":"fictional"}'}
  r=lookup_platform('','fictional',C(),instance={'host':'forge.example','engine':'gitea'})
  self.assertEqual(r['state'],'partial');self.assertEqual(r['matches'],[])
