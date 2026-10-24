import unittest
from nicktrail.adapters import extract
class BareLinks18Tests(unittest.TestCase):
 def urls(self,text):return {r['url'] for r in extract(text,'https://github.com/fictional') if 'url' in r}
 def test_explicit_root_websites_and_polish_labels(self):
  for text,url in [('www.fictional.example','https://www.fictional.example'),('website: fictional.example','https://fictional.example'),('Strona www = fictional.example','https://fictional.example'),('Portfolio: fictional.example','https://fictional.example')]:
   self.assertIn(url,self.urls(text))
 def test_email_code_and_unlabelled_prose_are_not_web_links(self):
  for text in ['mail: person@www.fictional.example','working on project.py','I like fictional.example','website: person@fictional.example']:
   self.assertEqual(self.urls(text),set(),text)


 def test_path_is_not_silently_shortened_to_an_extra_root(self):
  self.assertEqual(self.urls('website: fictional.example/profile'),{'https://fictional.example/profile'})
  self.assertEqual(self.urls('www.fictional.example/profile'),{'https://www.fictional.example/profile'})
  self.assertIn('https://www.fictional.example',self.urls('See www.fictional.example.'))
