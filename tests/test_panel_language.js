const fs=require('fs'),vm=require('vm'),assert=require('assert/strict'),path=require('path');
const html=fs.readFileSync(path.join(__dirname,'../nicktrail/panel.html'),'utf8');
const script=[...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)][0][1];
function run({lang='en',query='',saved=null,denied=false}={}){
 let onchange,assigned,replaced,written;const select={value:'',addEventListener(e,f){onchange=f}},project={value:'2',append(){}};
 const ctx={URL,location:{href:'http://127.0.0.1:8770/'+query,assign(x){assigned=x},replace(x){replaced=x}},localStorage:{getItem(){if(denied)throw Error();return saved},setItem(k,v){if(denied)throw Error();written=[k,v]}},document:{documentElement:{lang},getElementById(id){return id==='languageSelect'?select:project},createElement(){return {}}}};
 vm.runInNewContext(script,ctx);return {select,change:()=>onchange(),result:()=>({assigned,replaced,written})};
}
let a=run();assert.equal(a.select.value,'en');
for(const lang of ['pl']){let x=run();x.select.value=lang;x.change();const r=x.result();assert.equal(new URL(r.assigned).searchParams.get('lang'),lang);assert.equal(new URL(r.assigned).searchParams.get('project'),'2');assert.equal(r.written[0],'nicktrail.language');assert.equal(r.written[1],lang)}
assert.equal(new URL(run({saved:'pl'}).result().replaced).searchParams.get('lang'),'pl');
assert.equal(run({saved:'de'}).result().replaced,undefined,'removed languages are ignored');
assert.equal(run({query:'?lang=en',saved:'pl',lang:'en'}).result().replaced,undefined);
assert.equal(run({saved:'javascript:alert(1)'}).result().replaced,undefined);
let x=run({denied:true});x.select.value='pl';x.change();assert.equal(new URL(x.result().assigned).searchParams.get('lang'),'pl');
console.log('Language selector: English default, two choices, persistence, project retention and unavailable storage PASS.');
