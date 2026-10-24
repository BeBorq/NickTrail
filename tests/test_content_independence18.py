import json,unittest
from nicktrail.independence import repeated_descriptions
class ContentIndependence18Tests(unittest.TestCase):
 def node(self,id,url,bio,state='found',ownership='unknown'):
  return {'id':id,'url':url,'kind':'profile','platform':'Fictional','data':json.dumps({'bio':bio}),'state':state,'ownership':ownership}
 def test_long_identical_descriptions_count_once_without_identity_claim(self):
  text=' '.join('fictional public project description number '+str(i) for i in range(20))
  result=repeated_descriptions([self.node(1,'https://one.example/a',text),self.node(2,'https://two.example/b',text.upper())])
  self.assertEqual(result[0]['members'],[1,2]);self.assertFalse(result[0]['identity_evidence']);self.assertFalse(result[0]['origin_known']);self.assertEqual(result[0]['independent_content_observations'],1)
 def test_short_different_stale_and_rejected_text_not_grouped(self):
  text=' '.join('long fictional public description '+str(i) for i in range(24))
  nodes=[self.node(1,'https://one.example/a',text),self.node(2,'https://two.example/b',text,state='blocked'),self.node(3,'https://three.example/c',text,ownership='not_mine'),self.node(4,'https://four.example/d',text+' different')]
  self.assertEqual(repeated_descriptions(nodes),[])
  self.assertEqual(repeated_descriptions([self.node(1,'https://one.example/a','Software developer'),self.node(2,'https://two.example/b','Software developer')]),[])
