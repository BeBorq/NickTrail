const fs=require('fs'),assert=require('assert/strict'),path=require('path');
const html=fs.readFileSync(path.join(__dirname,'../nicktrail/panel.html'),'utf8');
function line(name){const start=html.indexOf('function '+name+'(');assert.ok(start>=0,name);return html.slice(start,html.indexOf('\n',start));}
assert.ok(!html.includes('<option value="HISTORICAL">'),'historical is a checkbox, not a scan mode');
for(const id of ['historicalSearch','historicalDate','historicalLimit','showHistorical','readingSettings','saveSettings','forgetRobots'])assert.ok(html.includes('id="'+id+'"'),id);
const eta=new Function('searchEta',line('etaText')+';return etaText();');
assert.equal(eta(null),'');
assert.equal(eta({state:'done'}),'');
assert.ok(eta({state:'warming_up'}).includes('Szacowanie'));
const text=eta({state:'estimate',eta_seconds:7500,finish_at:'2026-10-22T20:05:00+00:00',tasks_per_minute:140.2,stalled:false});
assert.ok(text.includes('za 2 h 5 min')&&text.includes('140.2 zadań/min'),text);
assert.ok(eta({state:'estimate',eta_seconds:30,finish_at:'2026-10-22T20:05:00+00:00',tasks_per_minute:3,stalled:true}).includes('wstrzymane'));
const day=new Function(line('historicalDefault')+';return historicalDefault();')();
assert.match(day,/^\d{4}-\d{2}-\d{2}$/);assert.equal(Number(day.slice(0,4)),new Date().getFullYear()-5);
// Hidden historical data: archive rows collapse to a single note.
const controls=new Map();function element(tag){return {tag,children:[],textContent:'',checked:true,append(n){this.children.push(n)},replaceChildren(){this.children=[]}}}
const $=id=>{if(!controls.has(id))controls.set(id,element('div'));return controls.get(id)};
const document={createElement:element};
const render=new Function('document','$','historicalRows',[line('el'),line('renderHistorical')].join('\n')+';return renderHistorical;')(document,$,[{original_url:'https://a.example',state:'available',captured_at:'2015',detail:'x',snapshot_url:''}]);
$('showHistorical').checked=false;render();
assert.equal($('archiveResults').children.length,1);assert.ok($('archiveResults').children[0].textContent.includes('Ukryto 1'));
assert.ok(html.includes("settingsData.choices?.[key]"),'choice settings render as a select');
console.log('UI reading settings: ETA text, historical checkbox and display switch passed.');
