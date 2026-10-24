const fs=require('fs'),assert=require('assert/strict'),path=require('path');
const html=fs.readFileSync(path.join(__dirname,'../nicktrail/panel.html'),'utf8');
function line(name){const start=html.indexOf('function '+name+'(');assert.ok(start>=0,name);return html.slice(start,html.indexOf('\n',start));}
assert.ok(!line('renderIdentity').includes('innerHTML'),'cluster view must render text only');
const controls=new Map();
function element(tag){return {tag,children:[],textContent:'',append(n){this.children.push(n)},replaceChildren(){this.children=[]}}}
const document={createElement:element};
const $=id=>{if(!controls.has(id))controls.set(id,element('div'));return controls.get(id)};
const calls=[],links=[];
const source=['function plat(p){return p}',line('el'),line('button'),line('renderIdentity')].join('\n');
const run=new Function('document','$','action','externalLink','data',`let identityClusters=data;${source};renderIdentity();`);
function all(n){return [n,...n.children.flatMap(all)]}
const member=(id,ownership,platform)=>({id,url:'https://'+platform.toLowerCase()+'.example/u'+id,platform,ownership,alias:'u'+id,focus:false});
const bridge={a:1,b:2,tier:'cluster',probability:.82,independent_signals:1,contradiction_evidence:[],facts:[{why:'Ten sam publiczny adres e-mail na obu kontach',evidence:[10,11],stored_fields:[]}]};
run(document,$,(p,d)=>calls.push([p,d]),(parent,url)=>links.push(url),{clusters:[{members:[member(1,'mine','GitHub'),member(2,'unknown','GitLab')],bridges:[bridge],contains_your_account:true,same_platform_accounts:[],weakest_bridge_probability:.82}],clusters_total:1,review_pairs:[],review_pairs_total:0,note:'Sugestie.',skipped_popular_identifiers:0});
const nodes=all($('identityClusters'));
assert.ok(nodes.some(n=>n.tag==='h3'&&n.textContent.startsWith('Zawiera Twoje konto')));
const buttons=nodes.filter(n=>n.tag==='button');
assert.deepEqual(buttons.map(b=>b.textContent),['To moje','Nie moje','Nie należy do tej grupy'],'only the unreviewed account gets decision buttons and can be separated from the group');
buttons[0].onclick();assert.deepEqual(calls[0],['decide',{id:2,decision:'mine'}]);
buttons[2].onclick();assert.equal(calls[1][0],'separate');assert.equal(calls[1][1].a,2);assert.equal(calls[1][1].b,1,'separated from your account, the group anchor');
assert.equal(links.length,2);
assert.ok(nodes.some(n=>n.textContent.includes('dowody: 10, 11')));
const summary=nodes.find(n=>n.tag==='summary');assert.ok(summary.textContent.startsWith('GitHub u1 ↔ GitLab u2'),summary.textContent);assert.ok(!summary.textContent.includes('%'),'no percentages that read like identity probability');
$('identityClusters').replaceChildren();
run(document,$,()=>{},()=>{},{clusters:[],clusters_total:0,review_pairs:[],review_pairs_total:0,note:'',skipped_popular_identifiers:0});
assert.ok(all($('identityClusters')).some(n=>n.textContent.startsWith('Nie znaleziono')));
console.log('UI identity clusters: text-only cards, evidence IDs, decisions only for unreviewed accounts, empty state passed.');
