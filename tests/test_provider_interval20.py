import unittest
from unittest.mock import patch
from nicktrail.network import Client
class ProviderInterval20Tests(unittest.TestCase):
 def test_codeforces_documented_interval_survives_zero_caller_delay(self):
  class Response:status=404
  class Conn:
   def __init__(self,*a,**kw):pass
   def request(self,*a,**kw):pass
   def getresponse(self):return Response()
   def close(self):pass
  with patch.dict('nicktrail.network.PROCESS_COOLDOWNS',{},clear=True),patch('nicktrail.network.time.monotonic',return_value=100),patch('nicktrail.network.time.sleep') as sleep,patch('nicktrail.network.public_addresses',return_value=['93.184.216.34']),patch('nicktrail.network.PinnedTLS',Conn):
   client=Client(delay=0);client.get('https://codeforces.com/api/user.info?handles=fictional-one');client.get('https://codeforces.com/api/user.info?handles=fictional-two')
   self.assertEqual(sleep.call_args.args[0],2)
