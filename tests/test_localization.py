import unittest
from pathlib import Path
from html.parser import HTMLParser
from unittest.mock import patch
from nicktrail.localization import render_panel,catalog,LANGUAGES,localize_response,translate_message
PANEL=Path(__file__).parents[1]/'nicktrail/panel.html'
class LocalizationTests(unittest.TestCase):
 def test_default_english_and_all_languages(self):
  source=PANEL.read_text(encoding='utf-8')
  labels={'en':'My accounts','pl':'Moje konta'}
  for lang,label in labels.items():
   page=render_panel(source,lang)
   self.assertIn('lang="'+lang+'"',page);self.assertIn(label,page)
   self.assertIn('id="languageSelect"',page)
   self.assertIn("decision:'mine'",page);self.assertIn("'/api/state?project='",page)
   self.assertIn("node.data",page)
  self.assertIn('My accounts',render_panel(source));self.assertIn('lang="en"',render_panel(source,'../../fr'))
 def test_catalog_complete_for_each_language(self):
  c=catalog();keys=set(c['languages']['en'])
  self.assertGreater(len(keys),700)
  self.assertEqual(set(c['languages']),{'en'})
  self.assertTrue(all(c['languages']['en'].values()))
 def test_safe_html_attributes_whitespace_and_code_examples(self):
  page=render_panel('<html lang="pl"><p>  Moje konta  </p><input placeholder="Nazwa nowego projektu"><code>Moje konta</code><pre>Moje konta</pre>\n </html>')
  self.assertIn('<p>  My accounts  </p>',page);self.assertIn('placeholder="New project name"',page)
  self.assertIn('<code>Moje konta</code>',page);self.assertIn('<pre>Moje konta</pre>',page)
  self.assertIn('\n </html>',page)
 def test_translations_cannot_break_script_or_html(self):
  data={'languages':{'en':{'Moje':'</script><script>alert(1)</script>"'}},'literals':{"'Moje'":'Moje'}}
  with patch('nicktrail.localization.catalog',return_value=data):
   page=render_panel('<html lang="pl"><p>Moje</p><script nonce="__TOKEN__">const label=\'Moje\';</script>')
  self.assertEqual(page.count('<script'),1)
  self.assertIn('&lt;/script&gt;',page);self.assertIn(r'\u003c/script>',page)

class SystemLocalizationTests(unittest.TestCase):
 def test_system_metadata_translates_without_changing_profiles_evidence_or_input(self):
  import copy
  payload={'pools':{'1':{'reason':'Twoja deklaracja lub aktualne publiczne powiązanie','pool':'STRONG_RESULTS'}},'labels':{'1':{'text':'Własność potwierdzona przez Ciebie','color':'green'}},'read_status':{'1':{'label':'Odmowa dostępu','kind':'access','kind_label':'Konto może istnieć, odczyt zablokowany','meaning':'Serwis zablokował automatyczny odczyt. To nie oznacza braku konta.'}},'snapshot':{'nodes':[{'data':{'bio':'Odmowa dostępu','display':'Moje konta'},'ownership':'mine'}],'evidence':[{'snippet':'Twoja deklaracja lub aktualne publiczne powiązanie'}]},'indexed_provenance':[{'snippet':'Odmowa dostępu'}]}
  before=copy.deepcopy(payload);r=localize_response('/api/state',payload,'en')
  self.assertEqual(payload,before)
  self.assertEqual(r['snapshot'],before['snapshot']);self.assertEqual(r['indexed_provenance'],before['indexed_provenance'])
  self.assertEqual(r['read_status']['1']['label'],'Access denied');self.assertEqual(r['read_status']['1']['kind'],'access')
  self.assertEqual(r['labels']['1']['text'],'Ownership confirmed by you')
  self.assertEqual(r['pools']['1']['pool'],'STRONG_RESULTS');self.assertNotEqual(r['pools']['1']['reason'],before['pools']['1']['reason'])
  self.assertEqual(localize_response('/api/state',payload,'pl'),before)
 def test_key_help_and_reading_labels_only(self):
  r=localize_response('/api/settings',{'labels':{'robots_memory':'Pamiętaj odmowy robots.txt i nie pytaj ponownie'},'values':{'robots_memory':True},'choices':{'crawl_delay_long':[['skip','pomiń źródło']]}},'en')
  self.assertEqual(r['choices']['crawl_delay_long'][0],['skip','skip source']);self.assertTrue(r['values']['robots_memory'])
  r=localize_response('/api/keys',{'services':[{'used_for':'Odczyt publicznych profili Steam po nicku (vanity URL).','fields':[{'label':'Klucz API','preview':'Odmowa dostępu','env':'NICKTRAIL_KEY'}]}],'file':'Odmowa dostępu'},'en')
  self.assertEqual(r['services'][0]['fields'][0]['label'],'API key');self.assertEqual(r['services'][0]['fields'][0]['preview'],'Odmowa dostępu');self.assertEqual(r['file'],'Odmowa dostępu')
 def test_templates_preserve_identifiers_and_unknown_source_text(self):
  self.assertEqual(translate_message('Nick „fictional-Ą” odczytany z połączonego konta nie był jeszcze szukany.','en'),'Username “fictional-Ą” read from a connected account has not been searched yet.')
  self.assertEqual(translate_message('Original source text: Moje konta','en'),'Original source text: Moje konta')
  data={'error':'Odmowa dostępu','bio':'Odmowa dostępu'}
  self.assertEqual(localize_response('/api/export',data,'en'),data)
 def test_all_http_status_explanations_have_english_copy(self):
  from nicktrail.readstatus import classify
  import re
  for status in (202,204,400,401,403,404,405,408,409,410,429,451,503,521,302,499,101):
   report=localize_response('/api/state',{'read_status':{'1':classify('error','HTTP '+str(status))}},'en')['read_status']['1']
   for key in ('label','kind_label','meaning'):
    self.assertIsNone(re.search('[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]',report[key]),(status,key,report[key]))

 def test_additional_ranking_explanations(self):
  self.assertEqual(translate_message("Nazwa wyświetlana konta oznaczonego jako moje","en"),"Display name of an account marked as mine")
  self.assertEqual(translate_message("Jawny odnośnik; konto docelowe nadal wymaga weryfikacji","en"),"Explicit link; the target account still needs verification")

class ScreenshotRegressionTests(unittest.TestCase):
 def test_reported_labels_and_native_file_controls(self):
  page=render_panel(PANEL.read_text(encoding='utf-8'),'en')
  for value in ('Search results #','Status:','Tree #','Read:','Scan #','Choose file','No file selected'):
   self.assertIn(value,page)
  for value in ('Wyniki wyszukiwania #','Stan:','Drzewo #','Odczyt:','Skan #',' · zapytania '):
   self.assertNotIn(value,page)
  self.assertIn("n.platform==='Deklaracja'",page)
  data={'ranking':{'nodes':{'1':{'sort_reason':'Dokładny nick lub alias z zapytania'},'2':{'sort_reason':'Pozostały kandydat'}}}}
  localized=localize_response('/api/state',data,'en')
  self.assertEqual(localized['ranking']['nodes']['1']['sort_reason'],'Exact username or query alias')
  self.assertEqual(localized['ranking']['nodes']['2']['sort_reason'],'Other candidate')

if __name__=='__main__':unittest.main()
