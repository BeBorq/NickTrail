import tempfile,json,unittest
from pathlib import Path
from unittest.mock import patch
from nicktrail.storage import Store
from nicktrail.search import discover,results
from nicktrail.diagnostics import completeness
from nicktrail.protocol import begin,record,summary
class Protocol19Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=Path.cwd());self.addCleanup(self.tmp.cleanup);self.s=Store(Path(self.tmp.name)/'fixture.db');self.addCleanup(self.s.db.close);self.p=self.s.project('Synthetic')
 def client(self):
  class Client:count=0;events_truncated=0
  c=Client();c.events=[];return c
 def test_policy_block_cache_and_http_response_are_distinct_and_durable(self):
  c=self.client()
  def lookup(platform,term,client):
   if term=='fictional':client.events.append({'kind':'policy_block'});return {'state':'blocked','detail':'ROBOTS_RESTRICTED'}
   client.count+=1;client.events.extend([{'kind':'request_sent','purpose':'content'},{'kind':'response','status':404},{'kind':'cache_hit'}]);return {'state':'not_found','matches':[]}
  with patch('nicktrail.search.lookup',side_effect=lookup):id=discover(self.s,self.p,'fictional',aliases=['another'],platforms=['GitHub'],client=c)
  item=results(self.s,self.p)[0];report=completeness(item,self.s,self.s.snapshot(self.p));events=report['protocol']['events']
  self.assertEqual(events['policy_block'],1);self.assertEqual(events['request_sent'],1);self.assertEqual(events['response'],1);self.assertEqual(events['cache_hit'],1);self.assertTrue(report['protocol']['attribution_complete'])
  self.assertEqual(events['request_sent'],events['policy_requests_sent']+events['content_requests_sent']+events['uncategorized_requests_sent'])
  self.s.execute('delete from search_task_protocol where search=?',(id,));unknown=completeness(item,self.s,self.s.snapshot(self.p))['protocol'];self.assertEqual(unknown['terminal_tasks_without_protocol'],2);self.assertFalse(unknown['attribution_complete'])
 def test_resume_accumulates_counts_without_reclassifying_cached_payload_as_http(self):
  c=self.client();id=discover(self.s,self.p,'fictional',platforms=['GitHub'],client=c,stopped=lambda:True);task=self.s.rows('select * from search_tasks where search=?',(id,))[0]
  start=begin(c);c.events.extend([{'kind':'request_sent','purpose':'content'},{'kind':'response','status':200}]);record(self.s,id,'GitHub','fictional','exact',c,start)
  record(self.s,id,'GitHub','fictional','exact',c,begin(c),True)
  result=summary(self.s,id,[task]);self.assertEqual(result['events']['request_sent'],1);self.assertEqual(result['events']['payload_reuse'],1);self.assertFalse(result['attribution_complete'])
 def test_budget_stop_before_request_is_not_a_checked_site(self):
  from nicktrail.network import Client
  c=Client(queries=0)
  with patch('nicktrail.network.public_addresses') as dns:id=discover(self.s,self.p,'fictional',platforms=['GitHub'],client=c)
  dns.assert_not_called();item=results(self.s,self.p)[0];r=completeness(item,self.s,self.s.snapshot(self.p))
  self.assertEqual(r['protocol']['events']['budget_block'],1);self.assertEqual(r['protocol']['events']['request_sent'],0);self.assertEqual(r['outcome_report']['confirmed_absent_exact_tasks'],0);self.assertFalse(r['protocol']['attribution_complete'])
