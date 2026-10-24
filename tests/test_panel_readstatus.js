const fs=require('fs'),assert=require('assert/strict'),path=require('path');
const html=fs.readFileSync(path.join(__dirname,'../nicktrail/panel.html'),'utf8');
function line(name){const start=html.indexOf('function '+name+'(');assert.ok(start>=0,name);return html.slice(start,html.indexOf('\n',start));}
function element(tag){return {tag,children:[],textContent:'',append(n){this.children.push(n)}}}
const document={createElement:element};
const source=[line('el'),line('readStatusOf'),line('readStatusNote')].join('\n');
const run=new Function('document','readStatuses','node',`${source};let box=element('div');readStatusNote(box,node);return box;function element(t){return document.createElement(t)}`);
function all(n){return [n,...n.children.flatMap(all)]}
const gone={'1':{code:'404',label:'Nie znaleziono',kind:'missing',kind_label:'Konto może nie istnieć',meaning:'Serwis nie ma strony.',may_be_missing:true,detail:'HTTP 404',observed:''}};
let text=all(run(document,gone,{id:1,ownership:'mine'})).map(n=>n.textContent).join('|');
assert.ok(text.includes('404 · Nie znaleziono — Konto może nie istnieć'),text);
assert.ok(text.includes('mogło już zostać usunięte'),'own account gets the deletion hint');
const blocked={'2':{code:'403',label:'Odmowa dostępu',kind:'access',kind_label:'Konto może istnieć, odczyt zablokowany',meaning:'x',may_be_missing:false,detail:'HTTP 403',observed:''}};
text=all(run(document,blocked,{id:2,ownership:'unknown'})).map(n=>n.textContent).join('|');
assert.ok(text.includes('sprawdzić profil ręcznie')&&!text.includes('usunięte'),text);
assert.equal(run(document,{},{id:3,ownership:'mine'}).children.length,0,'no note without a problem');
assert.ok(/<button id="stopSearch" disabled>Zatrzymaj<\/button>/.test(html),'stop button next to search');
assert.ok(html.includes("for(let id of ['stopSearch','navStop'])$(id).onclick=()=>action('stop',{});"),'stop buttons call /api/stop');
assert.ok(line('renderFocus').includes("$('stopSearch').disabled=!jobState.running"),'stop enabled only while running');
console.log('UI read status: codes, meaning, own-account hint, stop buttons passed.');
