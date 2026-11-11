'use strict';
// Régressions de session avec réponses différées ; aucun navigateur ou NAS réel.
const assert=require('node:assert/strict');
const {test}=require('node:test');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../console/static/app.js'),'utf8');
function fixture(fetch){
 const elements=new Map(),listeners=new Map();
 function element(){return {textContent:'',className:'',open:false,disabled:false,addEventListener(){},querySelector(){return null;}};}
 const app=element();
 Object.defineProperty(app,'innerHTML',{set(value){
  for(const key of ['#content','#crumb','#topclock','#login-error'])elements.delete(key);
  for(const [key,marker] of [['#content','id="content"'],['#crumb','id="crumb"'],['#topclock','id="topclock"'],['#login-error','id="login-error"']]){
   if(value.includes(marker))elements.set(key,element());
  }
  if(elements.has('#login-error'))elements.get('#login-error').textContent=value.match(/id="login-error">([^<]*)/)[1];
 }});
 elements.set('#app',app);elements.set('#toast',element());elements.set('#modal',element());
 const document={querySelector:s=>elements.get(s)||null,querySelectorAll:()=>[],addEventListener:(name,fn)=>{if(!listeners.has(name))listeners.set(name,[]);listeners.get(name).push(fn);}};
 const context=vm.createContext({document,fetch,location:{hash:'#snapshots'},window:{addEventListener(){}},
  setTimeout:()=>1,clearTimeout(){},setInterval:()=>1,clearInterval(){},
  FormData:class{constructor(form){return new Map(Object.entries(form.values));}},console});
 vm.runInContext(source,context);
 return {elements,context,listeners,run:code=>vm.runInContext(code,context),submit:async()=>{
  const button=element(),form={id:'login-form',getAttribute:()=> 'login-form',values:{username:'admin',password:'fixture-only'},querySelector:()=>button};
  for(const fn of listeners.get('submit'))await fn({target:form,preventDefault(){}});
  assert.equal(button.disabled,false);
 }};
}
const response=(status,data)=>({ok:status===200,status,json:async()=>data});
const account={name:'admin',role:'admin',csrf:'synthetic'};
test('expiration during navigation keeps login visible without null DOM access',async()=>{
 const f=fixture(async()=>response(401,{error:'Session expirée.'}));
 f.run('user={name:"admin",role:"admin"};shell();render=async()=>api("overview");');
 await f.run('go("home")');
 assert.equal(f.elements.has('#content'),false);
 assert.equal(f.elements.get('#login-error').textContent,'Session expirée.');
});
test('response from an abandoned session is discarded',async()=>{
 let complete;const f=fixture(()=>new Promise(resolve=>{complete=resolve;}));
 f.run('user={name:"admin"};shell();');
 const pending=f.run('api("overview")');f.run('login()');
 complete(response(200,{private:'obsolete'}));
 await assert.rejects(pending,{name:'AbortError'});
 assert.equal(f.elements.has('#content'),false);
});
test('accepted password without returned session shows a useful message',async()=>{
 const f=fixture(async url=>url==='/api/login'?response(200,account):response(401,{error:'Connexion requise.'}));
 f.run('login()');await f.submit();
 assert.match(f.elements.get('#login-error').textContent,/ne transmet pas la session/);
 assert.equal(f.elements.has('#content'),false);
});
test('wrong password remains a login error',async()=>{
 const f=fixture(async()=>response(401,{error:'Identifiant ou mot de passe refusé.'}));
 f.run('login()');await f.submit();
 assert.equal(f.elements.get('#login-error').textContent,'Identifiant ou mot de passe refusé.');
});
test('valid session reaches the requested page after password login',async()=>{
 const calls=[];const f=fixture(async url=>{calls.push(url);return response(200,account);});
 f.run('login();render=async()=>{$("#content").innerHTML="ready";};');
 await f.submit();
 assert.deepEqual(calls,['/api/login','/api/me']);
 assert.equal(f.elements.get('#content').innerHTML,'ready');
 assert.equal(f.elements.has('#login-error'),false);
});
test('fresh administrator is guided to setup even from an old bookmark',async()=>{
 const f=fixture(async()=>response(200,{}));
 f.run('user={name:"admin",role:"admin",setup_required:true};shell();render=async()=>{};');
 await f.run('go("snapshots")');
 assert.equal(f.run('page'),'setup');
});
test('setup detection completing after navigation does not overwrite the new page',async()=>{
 let complete;const f=fixture(()=>new Promise(resolve=>{complete=resolve;}));
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/onboarding.js'),'utf8'),f.context);
 f.run('user={name:"admin",role:"admin"};page="setup";shell();');
 const pending=f.run('renderSetup()');
 f.run('page="files";$("#content").innerHTML="files remain visible";');
 complete(response(200,{phase:'system'}));await pending;
 assert.equal(f.elements.get('#content').innerHTML,'files remain visible');
});
test('camera identifier field cannot shadow modal form id and cause a native GET',async()=>{
 const f=fixture(async()=>response(200,{}));
 let submitted=false,prevented=false;
 f.elements.get('#modal').close=()=>{};
 f.run('user={name:"admin"};render=async()=>{};');
 f.context.recordSubmission=()=>{submitted=true;};
 f.run('modalSubmit=async()=>recordSubmission();');
 const button={disabled:false};
 const form={id:{value:'atelier'},getAttribute:attribute=>attribute==='id'?'modal-form':null,values:{id:'atelier'},querySelector:()=>button};
 for(const listener of f.listeners.get('submit'))await listener({target:form,preventDefault(){prevented=true;}});
 assert.equal(prevented,true);assert.equal(submitted,true);assert.equal(button.disabled,false);
 assert.match(source,/<form id="modal-form" method="post">/);
});

test('component status distinguishes container health and names installation jobs',()=>{
 const f=fixture(async()=>response(200,account));
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/components.js'),'utf8'),f.context);
 assert.equal(f.run('componentState({}, {state:"running",health:"starting"})'),'Démarrage en cours');
 assert.equal(f.run('componentState({}, {state:"running",health:"unhealthy"})'),'À vérifier');
 assert.equal(f.run('componentState({}, {state:"running",health:"healthy"})'),'En service');
 assert.match(f.run('deploymentRows([{ts:0,kind:"component_install",component:"video",status:"done",result:{},progress:{}}])[0]'),/Installation · Frigate/);
});
test('late alert response does not overwrite another page or a logged out session',async()=>{
 let complete;const f=fixture(()=>new Promise(resolve=>{complete=resolve;}));
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/alerts.js'),'utf8'),f.context);
 f.run('user={name:"admin",role:"admin"};shell();page="alerts";');
 const pending=f.run('renderAlerts()');f.run('page="files";$("#content").innerHTML="files remain visible";');
 complete(response(200,{}));await pending;
 assert.equal(f.elements.get('#content').innerHTML,'files remain visible');
 const badge=f.run('refreshAlertBadge()');f.run('login()');complete(response(200,{attention:1}));
 await assert.rejects(badge,{name:'AbortError'});
});
test('alert card escapes labels and acknowledgement does not pretend to resolve',()=>{
 const f=fixture(async()=>response(200,{}));
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/alerts.js'),'utf8'),f.context);
 const html=f.run('alertCard({id:"abc",title:"<script>x</script>",message:"<img>",page:"camera",first:1,acknowledged:2,ackby:"<admin>",severity:"warning"})');
 assert.match(html,/Pris en compte/);assert.doesNotMatch(html,/>Résolu</);
 assert.doesNotMatch(html,/<script>|<img>|<admin>/);assert.match(html,/&lt;script&gt;/);
});
test('late notification response cannot overwrite navigation or logout',async()=>{
 let complete;const f=fixture(()=>new Promise(resolve=>{complete=resolve;}));
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/notifications.js'),'utf8'),f.context);
 f.run('user={name:"admin",role:"admin"};shell();page="notifications";');
 const pending=f.run('renderNotifications()');f.run('page="files";$("#content").innerHTML="files";');
 complete(response(200,{}));await pending;assert.equal(f.elements.get('#content').innerHTML,'files');
 f.run('page="notifications";');const expired=f.run('renderNotifications()');f.run('login()');complete(response(200,{}));
 await assert.rejects(expired,{name:'AbortError'});
});
test('notification history escapes text and only current failed deliveries can retry',()=>{
 const f=fixture(async()=>response(200,{}));
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/notifications.js'),'utf8'),f.context);
 f.context.deliveries=[{id:'x',event:'test',created:1,title:'<script>bad</script>',result:'<img>',status:'failed',attempts:1,config_version:2}];
 const html=f.run('deliveryRows({config:{version:2},deliveries})[0]');
 assert.doesNotMatch(html,/<script>|<img>/);assert.match(html,/notification-retry/);
 assert.doesNotMatch(f.run('deliveryRows({config:{version:3},deliveries})[0]'),/notification-retry/);
});
test('notification configuration never fills saved secrets and submits explicit choices',async()=>{
 const f=fixture(async()=>response(200,{}));
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/notifications.js'),'utf8'),f.context);
 f.context.capture={};
 f.run('notificationState={config:{version:4,kind:"ntfy",configured:true,enabled:false,recovery:true,minimum:"critical",has_token:true,destination:"https://ntfy.example"}};modal=(title,html,label,submit)=>{capture.html=html;capture.submit=submit;};api=async(route,body)=>{capture.route=route;capture.body=body;};notificationConfigModal();');
 assert.doesNotMatch(f.context.capture.html,/value="https:/);assert.match(f.context.capture.html,/type="password"/);
 await f.context.capture.submit(new Map([['kind','ntfy'],['url',''],['token',''],['minimum','critical'],['recovery','on']]));
 assert.equal(f.context.capture.body.enabled,false);assert.equal(f.context.capture.body.recovery,true);assert.equal(f.context.capture.body.version,4);assert.equal(f.context.capture.body.url,'');
});
test('SMTP modal never prefills password and submits one recipient with TLS',async()=>{
 const f=fixture(async()=>response(200,{}));
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/notifications.js'),'utf8'),f.context);
 f.context.capture={};
 f.run('notificationState={config:{version:5,kind:"smtp",configured:true,destination:"mail.example.test:587",smtp:{host:"<mail>",port:587,security:"starttls",username:"<user>",has_password:true,sender:"a@example.test",recipient:"b@example.test"}}};modal=(title,html,label,submit)=>{capture.html=html;capture.submit=submit;};api=async(route,body)=>{capture.body=body;};notificationConfigModal();');
 assert.doesNotMatch(f.context.capture.html,/<mail>|<user>/);assert.match(f.context.capture.html,/id="notification-http" hidden disabled/);assert.doesNotMatch(f.context.capture.html,/Laisser vide pour conserver la destination|Destination actuelle/);
 assert.match(f.context.capture.html,/id="smtp-password"[^>]*type="password"[^>]*>/);assert.doesNotMatch(f.context.capture.html,/id="smtp-password"[^>]*value=/);
 await f.context.capture.submit(new Map([['kind','smtp'],['smtp_host','mail.example.test'],['smtp_port','465'],['smtp_security','tls'],['smtp_username',''],['smtp_password',''],['smtp_sender','a@example.test'],['smtp_recipient','b@example.test'],['minimum','warning']]));
 assert.equal(f.context.capture.body.smtp.port,465);assert.equal(f.context.capture.body.smtp.security,'tls');assert.equal(f.context.capture.body.smtp.recipient,'b@example.test');assert.equal(f.context.capture.body.enabled,false);
});
test('transport choice disables irrelevant inputs and preserves custom SMTP ports',async()=>{
 const f=fixture(async()=>response(200,{}));
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/notifications.js'),'utf8'),f.context);
 const smtp={},http={},port={value:'587'};f.elements.set('#notification-smtp',smtp);f.elements.set('#notification-http',http);f.elements.set('#smtp-port',port);
 for(const fn of f.listeners.get('change'))await fn({target:{id:'notification-kind',value:'smtp'}});
 assert.equal(smtp.disabled,false);assert.equal(http.disabled,true);
 for(const fn of f.listeners.get('change'))await fn({target:{id:'smtp-security',value:'tls'}});
 assert.equal(port.value,'465');port.value='2465';
 for(const fn of f.listeners.get('change'))await fn({target:{id:'smtp-security',value:'starttls'}});
 assert.equal(port.value,'2465');
});

test('retention preview returning after navigation cannot paint another page',async()=>{
 let complete;const f=fixture(()=>new Promise(resolve=>{complete=resolve;}));
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/retention.js'),'utf8'),f.context);
 f.run('user={name:"admin",role:"admin"};page="retention";shell();');
 const submit={disabled:false};
 const form={getAttribute:()=> 'retention-form',querySelector:()=>submit,values:{repo:'fixture',keep_last:'2'}};
 f.elements.set('#retention-result',{innerHTML:''});f.elements.set('#retention-error',{textContent:''});
 const fn=f.listeners.get('submit').at(-1);
 const pending=fn({target:form,preventDefault(){}});
 f.run('page="files";$("#content").innerHTML="files preserved";');
 complete(response(200,{name:'fixture',remove:[]}));await pending;
 assert.equal(f.elements.get('#content').innerHTML,'files preserved');
 assert.equal(f.run('retentionProposal'),null);assert.equal(submit.disabled,false);
});

test('retention summary escapes repository names and disables empty deletion',()=>{
 const f=fixture(async()=>response(200,{}));
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/retention.js'),'utf8'),f.context);
 const html=f.run('retentionSummary({name:"<img src=x>",keep:[],remove:[],protected:[],groups:0,keep_last:7,expires:100})');
 assert.ok(html.includes('&lt;img src=x&gt;'));assert.ok(!html.includes('<img src=x>'));
 assert.match(html,/data-action="retention-confirm" disabled/);
});

test('automatic retention can be activated from an empty deletion proposal',()=>{
 const f=fixture(async()=>response(200,{}));
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/retention.js'),'utf8'),f.context);
 const html=f.run('retentionSummary({name:"fixture",keep:[],remove:[],protected:[],groups:0,keep_last:7,expires:100,policy_version:0})');
 assert.match(html,/data-action="retention-confirm" disabled/);
 assert.match(html,/data-action="retention-enable" >|data-action="retention-enable"\s*>/);
});

test('suspended automatic policy exposes a safe disable action and escapes its reason',()=>{
 const f=fixture(async()=>response(200,{}));
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/retention.js'),'utf8'),f.context);
 const html=f.run('retentionPolicies([{repo:"fixture",name:"Fixture",keep_last:2,version:4,enabled:false,reason:"<script>private</script>"}])');
 assert.ok(html.includes('Suspendue'));assert.ok(html.includes('&lt;script&gt;private&lt;/script&gt;'));
 assert.match(html,/data-action="retention-disable"/);assert.match(html,/data-version="4"/);
});

test('cleanup confirmation escapes labels and requires consent without deleting snapshots',()=>{
 const f=fixture(async()=>response(200,{}));
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/retention.js'),'utf8'),f.context);
 const html=f.run('cleanupConfirmation({name:"<img>",expires:100,points:[{id:"<script>",time:"2020-01-01T00:00:00Z"}]})');
 assert.doesNotMatch(html,/<img>|<script>/);assert.match(html,/name="confirm" required/);assert.match(html,/Aucun point encore présent ne sera supprimé/);
});

test('cleanup history refresh preserves form and discards a replaced view',async()=>{
 let complete;const f=fixture(()=>new Promise(resolve=>{complete=resolve;}));
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/retention.js'),'utf8'),f.context);
 f.run('user={name:"admin",role:"admin"};page="retention";shell();$("#content").innerHTML="form draft";');
 const target={innerHTML:'old history'};f.elements.set('#retention-history',target);
 const pending=f.run('refreshRetentionHistory()');complete(response(200,[]));await pending;
 assert.equal(f.elements.get('#content').innerHTML,'form draft');assert.match(target.innerHTML,/Aucune rétention/);
 const stale=f.run('refreshRetentionHistory()');f.elements.set('#retention-history',{innerHTML:'new view'});
 complete(response(200,[]));await stale;assert.equal(f.elements.get('#retention-history').innerHTML,'new view');
});

test('late cleanup review cannot open a modal after navigation',async()=>{
 let complete;const f=fixture(()=>new Promise(resolve=>{complete=resolve;}));
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/retention.js'),'utf8'),f.context);
 f.run('user={name:"admin",role:"admin"};page="retention";shell();modal=()=>{throw new Error("stale modal");};');
 const pending=f.listeners.get('click').at(-1)({target:{closest:()=>({dataset:{action:'cleanup-review',job:'fixture'}})}});
 f.run('page="files";');complete(response(200,{name:'fixture',points:[],expires:1}));await pending;
 assert.equal(f.elements.get('#toast').textContent,'');
});

test('calendar form submits all tiers and invalidates its preview when a tier changes',async()=>{
 const f=fixture(async()=>response(200,{}));
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/retention.js'),'utf8'),f.context);
 f.context.capture={};
 f.run('user={name:"admin",role:"admin",timezone:"UTC"};page="retention";shell();api=async(route,body)=>{capture.body=body;return {name:"fixture",keep_last:1,calendar:body.calendar,groups:1,keep:[],remove:[],protected:[],expires:100};};');
 f.elements.set('#retention-result',{innerHTML:''});f.elements.set('#retention-error',{textContent:''});
 const button={disabled:false},form={getAttribute:()=> 'retention-form',querySelector:()=>button,values:{repo:'fixture',keep_last:'1',daily:'7',weekly:'4',monthly:'12',timezone:'America/Cayenne'}};
 await f.listeners.get('submit').at(-1)({target:form,preventDefault(){}});
 assert.equal(f.context.capture.body.calendar.daily,7);assert.equal(f.context.capture.body.calendar.weekly,4);assert.equal(f.context.capture.body.calendar.monthly,12);assert.equal(f.context.capture.body.calendar.timezone,'America/Cayenne');
 assert.ok(f.run('retentionProposal'));
 for(const fn of f.listeners.get('input'))await fn({target:{id:'retention-weekly'}});
 assert.equal(f.run('retentionProposal'),null);assert.equal(f.elements.get('#retention-result').innerHTML,'');
});

test('calendar reasons and timezone are escaped in the exact simulation summary',()=>{
 const f=fixture(async()=>response(200,{}));
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/retention.js'),'utf8'),f.context);
 const html=f.run('retentionSummary({name:"fixture",keep_last:1,calendar:{monthly:3,timezone:"<img>"},groups:1,keep:[{id:"abcd",time:"2024-01-01T00:00:00Z",reasons:["<script>"]}],remove:[],protected:[],expires:100})');
 assert.match(html,/3 mois/);assert.match(html,/&lt;img&gt;/);assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<img>|<script>/);
});

test('switching repository loads its saved calendar without copying another rule',async()=>{
 const f=fixture(async()=>response(200,{}));
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/retention.js'),'utf8'),f.context);
 f.run('user={role:"admin",timezone:"UTC"};retentionPolicyList=[{repo:"one",keep_last:2,calendar:{daily:7,monthly:12,timezone:"America/Cayenne"}},{repo:"two",keep_last:4}];');
 for(const key of ['count','daily','weekly','monthly','timezone'])f.elements.set('#retention-'+key,{value:'stale'});
 f.run('retentionLoadPolicy("one")');assert.equal(f.elements.get('#retention-monthly').value,12);
 f.run('retentionLoadPolicy("two")');assert.equal(f.elements.get('#retention-count').value,4);assert.equal(f.elements.get('#retention-monthly').value,0);assert.equal(f.elements.get('#retention-timezone').value,'UTC');
});

test('maintenance window is explicit in preview and submitted with exact times',async()=>{
 const f=fixture(async()=>response(200,{}));
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/retention.js'),'utf8'),f.context);
 f.context.capture={};
 f.run('user={name:"admin",role:"admin"};page="retention";shell();api=async(route,body)=>{capture.body=body;return {name:"fixture",keep_last:1,calendar:body.calendar,window:body.window,groups:1,keep:[],remove:[],protected:[],expires:100};};');
 f.elements.set('#retention-result',{innerHTML:''});f.elements.set('#retention-error',{textContent:''});
 const form={getAttribute:()=> 'retention-form',querySelector:()=>({disabled:false}),values:{repo:'fixture',keep_last:'1',timezone:'America/Cayenne',window_enabled:'on',window_start:'22:00',window_end:'05:00'}};
 await f.listeners.get('submit').at(-1)({target:form,preventDefault(){}});
 assert.equal(f.context.capture.body.window.enabled,true);assert.equal(f.context.capture.body.window.start,'22:00');assert.equal(f.context.capture.body.window.end,'05:00');
 assert.match(f.elements.get('#retention-result').innerHTML,/22:00 à 05:00/);
 for(const fn of f.listeners.get('input'))await fn({target:{id:'retention-window-end'}});
 assert.equal(f.run('retentionProposal'),null);
});

test('maintenance waiting state escapes values and does not look like a failure',()=>{
 const f=fixture(async()=>response(200,{}));
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/retention.js'),'utf8'),f.context);
 f.run('user={role:"admin"};');
 const html=f.run('retentionPolicies([{repo:"fixture",name:"Fixture",keep_last:2,version:1,enabled:true,reason:"",pending:3,window_open:false,window:{enabled:true,start:"<img>",end:"05:00"},calendar:{timezone:"<script>"}}])');
 assert.match(html,/Hors créneau/);assert.match(html,/3 capture\(s\) en attente/);assert.doesNotMatch(html,/<img>|<script>/);
 const row=f.run('jobRows([{kind:"retention_auto",status:"deferred",id:"fixture",ts:1,result:"{}",progress:"{}"}])[0]');
 assert.match(row,/En attente du créneau/);assert.doesNotMatch(row,/Échec|job-cancel/);
});

test('manual confirmation states that it bypasses the automatic window',async()=>{
 const f=fixture(async()=>response(200,{}));
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/retention.js'),'utf8'),f.context);
 f.context.capture={};f.run('retentionProposal={name:"Fixture",keep_last:1,keep:[],protected:[],remove:[{}],window:{enabled:true,start:"02:00",end:"05:00"}};modal=(title,html)=>{capture.html=html;};');
 await f.listeners.get('click').at(-1)({target:{closest:()=>({dataset:{action:'retention-confirm'}})}});
 assert.match(f.context.capture.html,/même hors du créneau automatique/);
});

test('weekly form submits only selected days and invalidates an earlier preview',async()=>{
 const f=fixture(async()=>response(200,{}));
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/retention.js'),'utf8'),f.context);
 f.context.capture={};f.run('user={name:"admin",role:"admin"};page="retention";shell();api=async(route,body)=>{capture.body=body;return {name:"fixture",keep_last:1,calendar:body.calendar,window:body.window,groups:1,keep:[],remove:[],protected:[],expires:100};};');
 f.elements.set('#retention-result',{innerHTML:''});f.elements.set('#retention-error',{textContent:''});
 const form={getAttribute:()=> 'retention-form',querySelector:()=>({disabled:false}),values:{repo:'fixture',keep_last:'1',timezone:'America/Cayenne',window_enabled:'on',window_mode:'weekly',window_day_0:'on',window_start_0:'22:00',window_end_0:'02:00',window_start_1:'09:00',window_end_1:'10:00',window_day_4:'on',window_start_4:'23:00',window_end_4:'05:00'}};
 await f.listeners.get('submit').at(-1)({target:form,preventDefault(){}});
 assert.deepEqual(JSON.parse(JSON.stringify(f.context.capture.body.window.week)),[{day:0,start:'22:00',end:'02:00'},{day:4,start:'23:00',end:'05:00'}]);
 assert.match(f.elements.get('#retention-result').innerHTML,/Lundi de 22:00 à 02:00 le lendemain/);
 assert.match(f.elements.get('#retention-result').innerHTML,/Vendredi de 23:00 à 05:00 le lendemain/);
 for(const fn of f.listeners.get('input'))await fn({target:{id:'retention-window-start-4'}});
 assert.equal(f.run('retentionProposal'),null);assert.equal(f.elements.get('#retention-result').innerHTML,'');
});

test('weekly controls disable unchecked hours and restore daily mode for legacy policy',()=>{
 const f=fixture(async()=>response(200,{}));
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/retention.js'),'utf8'),f.context);
 f.run('user={role:"admin",timezone:"UTC"};retentionPolicyList=[{repo:"weekly",window:{enabled:true,mode:"weekly",week:[{day:6,start:"23:00",end:"02:00"}]}},{repo:"legacy",window:{enabled:true,start:"03:00",end:"06:00"}}];');
 for(const key of ['count','daily','weekly','monthly','timezone','window','window-enabled','window-mode','window-daily','window-weekly','window-start','window-end'])f.elements.set('#retention-'+key,{});
 for(let day=0;day<7;day++)for(const key of ['day','start','end'])f.elements.set('#retention-window-'+key+'-'+day,{});
 f.run('retentionLoadPolicy("weekly")');
 assert.equal(f.elements.get('#retention-window-mode').value,'weekly');assert.equal(f.elements.get('#retention-window-daily').hidden,true);
 assert.equal(f.elements.get('#retention-window-start-0').disabled,true);assert.equal(f.elements.get('#retention-window-start-6').disabled,false);assert.equal(f.elements.get('#retention-window-start-6').value,'23:00');
 f.elements.get('#retention-window-day-6').checked=false;f.run('retentionWindowVisibility()');assert.equal(f.elements.get('#retention-window-end-6').disabled,true);
 f.run('retentionLoadPolicy("legacy")');assert.equal(f.elements.get('#retention-window-mode').value,'daily');assert.equal(f.elements.get('#retention-window-start').value,'03:00');assert.equal(f.elements.get('#retention-window-start').disabled,false);assert.equal(f.elements.get('#retention-window-weekly').hidden,true);
 for(let day=0;day<7;day++)assert.equal(f.elements.get('#retention-window-day-'+day).checked,false);
});

test('weekly activation confirmation lists days, overnight endings and escaped values',async()=>{
 const f=fixture(async()=>response(200,{}));
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/retention.js'),'utf8'),f.context);
 f.context.capture={};f.run('retentionProposal={name:"Fixture",keep_last:1,calendar:{timezone:"<script>"},window:{enabled:true,mode:"weekly",week:[{day:6,start:"23:00",end:"02:00"},{day:0,start:"<img>",end:"12:00"}]}};modal=(title,html)=>{capture.html=html;};');
 await f.listeners.get('click').at(-1)({target:{closest:()=>({dataset:{action:'retention-enable'}})}});
 assert.match(f.context.capture.html,/Dimanche de 23:00 à 02:00 le lendemain/);assert.match(f.context.capture.html,/Lundi/);assert.doesNotMatch(f.context.capture.html,/<img>|<script>/);
});

test('weekly fields expose labelled times and the starting-day convention',()=>{
 const f=fixture(async()=>response(200,{}));
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/retention.js'),'utf8'),f.context);
 const html=f.run('retentionWindowFields({window:{enabled:true,mode:"weekly",week:[{day:0,start:"22:00",end:"02:00"}]}})');
 assert.match(html,/id="retention-window-day-0"[^>]*checked/);assert.match(html,/for="retention-window-start-0">Début · lundi/);
 assert.match(html,/même si mardi n’est pas coché/);assert.match(html,/id="retention-window-start-1"[^>]*disabled/);
});

test('snapshot refresh finishing after navigation cannot overwrite retention form',async()=>{
 let complete;const f=fixture(async()=>response(200,{}));
 f.context.waiting=new Promise(resolve=>{complete=resolve;});
 f.run('user={name:"admin",role:"admin"};page="snapshots";shell();loadProtection=async()=>{};protectionRepos=[];api=async route=>route==="jobs"?await waiting:{};');
 const pending=f.run('renderSnapshots()');
 await new Promise(resolve=>setImmediate(resolve));
 f.run('page="retention";$("#content").innerHTML="weekly form in progress";');complete([]);await pending;
 assert.equal(f.elements.get('#content').innerHTML,'weekly form in progress');
});
