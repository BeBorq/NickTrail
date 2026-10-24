const fs=require('fs'),assert=require('assert/strict'),path=require('path');
const html=fs.readFileSync(path.join(__dirname,'../nicktrail/panel.html'),'utf8');
function line(name){const start=html.indexOf('function '+name+'(');assert.ok(start>=0);return html.slice(start,html.indexOf('\n',start));}
const controls=new Map();
function element(tag){return {tag,children:[],dataset:{},value:'',checked:false,append(n){this.children.push(n)},replaceChildren(){this.children=[]}}}
const document={createElement:element,querySelectorAll(){return []}};
const $=id=>{if(!controls.has(id))controls.set(id,element('div'));return controls.get(id)};
$('project').value='1';$('distance').value='10';
const snapshot={nodes:Array.from({length:120},(_,i)=>({id:i+1,url:'https://synthetic.example/profile'+i,data:'{}',kind:'page',platform:'Strona',ownership:'unknown',depth:0,seed:0})),evidence:[],addresses:[],scans:[]};
const source=[line('el'),line('button'),line('render')].join('\n');
const render=new Function('document','$','snapshot',`
let nodeWindow={key:'',limit:50},ranking={order:[]},opened='',nodeLabels={},names={},states={},rels={},levels={};
function plat(p){return p} function externalLink(){} function foundReasons(){} function readStatusOf(){return null} function readStatusNote(){} function buildRail(){} function isSensitive(){return false} function captureOpen(){return new Set()} function restoreOpen(){} function profileHeader(){} function showProfileHistory(){}
function renderActiveReview(){} function renderIdentity(){} function renderDeadEnds(){} function renderHistorical(){} function renderManualQueue(){} function renderSearches(){} function renderFocus(){} function renderAuditExtras(){} function renderHints(){} function graph(){}
${source};return render;`)(document,$,snapshot);
function cards(){return $('nodes').children.filter(n=>n.tag==='details').length}
render();assert.equal(cards(),50);
(function find(n){return n.tag==='button'&&n.textContent.startsWith('Pokaż kolejne')?n:n.children.map(find).find(Boolean)})($('nodes')).onclick();assert.equal(cards(),100);
$('search').value='profile119';render();assert.equal(cards(),1);
$('search').value='';render();assert.equal(cards(),50);
console.log('UI pagination: bounded initial render, show more, filtering across full data and reset passed.');
