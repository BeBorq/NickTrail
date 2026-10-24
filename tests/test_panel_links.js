// Optional Node.js check of the actual UI link helper, without network or a browser.
const fs = require('fs');
const assert = require('assert/strict');
const path = require('path');
const html = fs.readFileSync(path.join(__dirname,'../nicktrail/panel.html'),'utf8');
const el = html.slice(html.indexOf('function el('),html.indexOf('function externalLink('));
const helper = html.slice(html.indexOf('function externalLink('),html.indexOf('function foundReasons('));
const document = {createElement(tag){return {tag,children:[],append(child){this.children.push(child)}}}};
const link = new Function('document', el + helper + ';return externalLink;')(document);
const good = link(null,'https://github.com/fictional','<img src=x onerror=alert(1)>');
assert.equal(good.tag,'a');
assert.equal(good.target,'_blank');
assert.equal(good.rel,'noopener noreferrer');
assert.equal(good.referrerPolicy,'no-referrer');
assert.equal(good.textContent,'<img src=x onerror=alert(1)>');
assert.equal(good.innerHTML,undefined);
for(const value of ['javascript:alert(1)','data:text/html,test','file:///tmp/test','https://user:password@example.com','https://example.com/\nscript']){
  assert.equal(link(null,value).tag,'span',value);
}
console.log('UI links: valid URLs open separately; unsafe URLs remain plain text; labels are text.');
