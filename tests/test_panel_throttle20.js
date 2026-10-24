const fs=require('fs'),assert=require('assert/strict'),path=require('path');
const html=fs.readFileSync(path.join(__dirname,'../nicktrail/panel.html'),'utf8');
function line(name){const start=html.indexOf('function '+name+'(');assert.ok(start>=0,name);return html.slice(start,html.indexOf('\n',start));}
const all=[];
function element(tag){const n={tag,children:[],dataset:{},className:'',textContent:'',append(c){this.children.push(c)}};all.push(n);return n}
const document={createElement:element,querySelectorAll:sel=>sel==='.countdown'?all.filter(n=>n.className==='countdown'):[]};
const make=new Function('document','el','throttle0',`
let throttling=throttle0;
function el(tag,text,parent){return globalThis.__el(tag,text,parent)}
${line('countdownEl')}
${line('renderThrottleInto')}
${line('tickCooldowns')}
return {renderThrottleInto,tickCooldowns}`);
globalThis.__el=(tag,text,parent)=>{let n=element(tag);if(text!==undefined)n.textContent=text;if(parent)parent.append(n);return n};
// two services on cooldown; server clock 5s behind the client to prove skew correction
const now=1000000;
const t=make(document,null,{now_epoch:now,total_blocks:9,hosts:[{host:'users.roblox.com',until_epoch:now+62,blocks:6},{host:'x.com',until_epoch:now+8,blocks:3}]});
const box=element('div');
assert.equal(t.renderThrottleInto(box),true);
function walk(n){return [n,...n.children.flatMap(walk)]}
let text=walk(box).map(n=>n.textContent).join('|');
assert.ok(text.includes('program czeka, nie zatrzymał się'),'reassures it is not frozen');
assert.ok(text.includes('users.roblox.com')&&text.includes('x.com'),'lists each blocking service');
assert.ok(text.includes('zablokował 6×')&&text.includes('zablokował 3×'),'per-service block counts');
// countdown shows remaining time; data-now is server epoch so skew is corrected
const cds=all.filter(n=>n.className==='countdown');
assert.equal(cds.length,2);
assert.equal(Number(cds[0].dataset.until)-Number(cds[0].dataset.now),62);
t.tickCooldowns();
assert.ok(/min/.test(cds[0].textContent)&&/ s$/.test(cds[0].textContent),cds[0].textContent);
assert.ok(/^\d+ s$/.test(cds[1].textContent),cds[1].textContent);
// empty throttling renders nothing
const box2=element('div');
assert.equal(make(document,null,null).renderThrottleInto(box2),false);
assert.equal(make(document,null,{now_epoch:now,total_blocks:0,hosts:[]}).renderThrottleInto(box2),false);
console.log('UI throttle banner: not-frozen message, per-service block counts, live skew-corrected countdown passed.');
