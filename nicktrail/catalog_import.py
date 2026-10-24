"""Sherlock MIT definitions normalized as untrusted discovery routes, never detector truth."""
import re,hashlib,json,datetime
from urllib.parse import urlsplit
from .identity import normalize

def convert(payload,revision,license_text,limit=1000,excluded_routes=()):
    if type(limit) is not int or not 1<=limit<=1500:raise ValueError('Limit importu 1–1500')
    if not isinstance(payload,dict) or len(payload)>5000 or not re.fullmatch('[a-f0-9]{40}',revision):raise ValueError('Wymagane dane Sherlock i przypięty SHA')
    if 'MIT License' not in license_text or 'Copyright (c) 2019 Sherlock Project' not in license_text:raise ValueError('Niezweryfikowana licencja źródła')
    services=[];rejected=[];seen={normalize(t.format(nick='nicktrail-fixture')) for t in excluded_routes};imported=datetime.datetime.now(datetime.timezone.utc).isoformat()
    for name,entry in payload.items():
        if name.startswith('$'):continue
        if not isinstance(entry,dict):rejected.append({'name':name,'reason':'schema'});continue
        template=entry.get('url','')
        if entry.get('isNSFW') or entry.get('request_method','GET')!='GET' or entry.get('request_payload') or entry.get('headers') or entry.get('urlProbe'):
            rejected.append({'name':name,'reason':'unsupported_request_or_explicit_content'});continue
        if not isinstance(template,str) or template.count('{}')!=1 or '{' in template.replace('{}','') or len(template)>400:
            rejected.append({'name':name,'reason':'unsafe_template'});continue
        try:url=normalize(template.format('nicktrail-fixture'));parts=urlsplit(url)
        except (ValueError,IndexError):rejected.append({'name':name,'reason':'unsafe_url'});continue
        if parts.scheme!='https' or parts.query or parts.hostname in ('localhost',) or re.fullmatch(r'[0-9.]+',parts.hostname):rejected.append({'name':name,'reason':'non_public_route'});continue
        converted=template.replace('{}','{nick}')
        if url in seen:continue
        if len(services)>=limit:rejected.append({'name':name,'reason':'selection_limit'});continue
        seen.add(url)
        services.append({'id':'Sherlock.'+hashlib.sha256(name.encode()).hexdigest()[:12],'name':name,'domain':parts.hostname,'profile_url':converted,'username_pattern':r'[A-Za-z0-9][A-Za-z0-9_.-]{0,62}','category':'imported','detection':{'strategy':'explicit_profile_metadata','redirect_policy':'same_normalized_url','not_found_titles':['404 not found','page not found','user not found']},'public_metadata':['explicit_profile_only'],'public_api':False,'rate_limits':{'policy':'robots_and_common_client'},'validation':{'live_status':'UNTESTED','coverage_claim':'definition_only_not_verified'},'provenance':{'repository':'https://github.com/sherlock-project/sherlock','revision':revision,'license':'MIT','source_name':name,'upstream_error_type':entry.get('errorType'),'upstream_regex_used':False}})
    for row in services:row['provenance'].update(imported_at=imported,modifications='URL normalization, strict metadata verification, upstream regex/probes not executed')
    return {'schema_version':1,'license':'MIT','license_text':license_text,'revision':revision,'source':'https://github.com/sherlock-project/sherlock','imported_at':imported,'services':services,'rejected':rejected}
