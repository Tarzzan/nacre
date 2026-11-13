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

test('multiple slots and dated exceptions serialize without reviving closed-day hours',()=>{
 const f=fixture(async()=>response(200,{}));vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/retention.js'),'utf8'),f.context);
 const value=f.run(`retentionWindowValue(new Map(Object.entries({window_enabled:'on',window_mode:'weekly',window_day_0:'on',window_start_0:'08:00',window_end_0:'09:00',window_slot_day_0_3_start:'22:00',window_slot_day_0_3_end:'02:00',window_exception_1_date:'2026-12-25',window_exception_1_kind:'closed',window_slot_exception_1_5_start:'02:00',window_slot_exception_1_5_end:'05:00',window_exception_2_date:'2026-12-31',window_exception_2_kind:'custom',window_slot_exception_2_6_start:'12:00',window_slot_exception_2_6_end:'13:00',window_slot_exception_2_8_start:'22:00',window_slot_exception_2_8_end:'02:00'})))`);
 assert.deepEqual(JSON.parse(JSON.stringify(value.week)),[{day:0,start:'08:00',end:'09:00'},{day:0,start:'22:00',end:'02:00'}]);
 assert.deepEqual(JSON.parse(JSON.stringify(value.exceptions)),[{date:'2026-12-25',slots:[]},{date:'2026-12-31',slots:[{start:'12:00',end:'13:00'},{start:'22:00',end:'02:00'}]}]);
 const daily=f.run(`retentionWindowValue(new Map(Object.entries({window_mode:'daily',window_start:'08:00',window_end:'09:00',window_slot_daily_7_start:'15:00',window_slot_daily_7_end:'16:00'})))`);
 assert.equal(daily.extra[0].start,'15:00');assert.equal(daily.week.length,0);
});

test('empty custom exception is refused instead of silently closing the date',()=>{
 const f=fixture(async()=>response(200,{}));vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/retention.js'),'utf8'),f.context);
 assert.throws(()=>f.run(`retentionWindowValue(new Map(Object.entries({window_exception_1_date:'2026-12-25',window_exception_1_kind:'custom'})))`),/Ajoutez au moins une plage/);
});

test('adding and removing schedule rows invalidates the pending simulation',async()=>{
 const f=fixture(async()=>response(200,{}));vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/retention.js'),'utf8'),f.context);
 let added='',removed=false;f.elements.set('#retention-window-slots-daily',{insertAdjacentHTML:(_where,html)=>{added=html;}});
 f.elements.set('#retention-window-exceptions',{insertAdjacentHTML:(_where,html)=>{added=html;}});f.elements.set('#retention-window-slot-daily-1',{remove:()=>{removed=true;}});
 f.elements.set('#retention-result',{innerHTML:'old preview'});f.run('retentionProposal={token:"old"};');
 await f.listeners.get('click').at(-1)({target:{closest:()=>({dataset:{action:'retention-slot-add',scope:'daily',label:'chaque jour'}})}});
 assert.match(added,/window_slot_daily_1_start/);assert.equal(f.run('retentionProposal'),null);assert.equal(f.elements.get('#retention-result').innerHTML,'');
 await f.listeners.get('click').at(-1)({target:{closest:()=>({dataset:{action:'retention-slot-remove',target:'retention-window-slot-daily-1'}})}});assert.equal(removed,true);
 await f.listeners.get('click').at(-1)({target:{closest:()=>({dataset:{action:'retention-exception-add'}})}});assert.match(added,/Aucun démarrage/);assert.match(added,/type="date"/);
});

test('switching repositories clears additional ranges and exceptions from the previous rule',()=>{
 const f=fixture(async()=>response(200,{}));vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/retention.js'),'utf8'),f.context);
 for(const key of ['#retention-window-slots-daily','#retention-window-slots-day_0','#retention-window-exceptions'])f.elements.set(key,{innerHTML:''});
 f.run('retentionLoadExtras({extra:[{start:"12:00",end:"13:00"}],week:[{day:0,start:"08:00",end:"09:00"},{day:0,start:"22:00",end:"02:00"}],exceptions:[{date:"2026-12-25",slots:[]}]})');
 assert.match(f.elements.get('#retention-window-slots-day_0').innerHTML,/22:00/);assert.match(f.elements.get('#retention-window-exceptions').innerHTML,/2026-12-25/);
 f.run('retentionLoadExtras({})');for(const key of ['#retention-window-slots-daily','#retention-window-slots-day_0','#retention-window-exceptions'])assert.equal(f.elements.get(key).innerHTML,'');
});

test('exception summaries explain full-date priority and escape displayed data',()=>{
 const f=fixture(async()=>response(200,{}));vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/retention.js'),'utf8'),f.context);
 const html=f.run('retentionWindowText({window:{enabled:true,start:"08:00",end:"09:00",extra:[{start:"22:00",end:"02:00"}],exceptions:[{date:"<img>",slots:[]},{date:"2026-12-31",slots:[{start:"<script>",end:"02:00"}]}]}})');
 assert.match(html,/22:00 à 02:00 le lendemain/);assert.match(html,/aucun démarrage/);assert.match(html,/remplacent toute la date, y compris la continuation de la veille/);assert.doesNotMatch(html,/<img>|<script>/);
});

test('date and exception-mode edits invalidate a simulated schedule',async()=>{
 const f=fixture(async()=>response(200,{}));vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/retention.js'),'utf8'),f.context);f.elements.set('#retention-result',{innerHTML:''});
 for(const id of ['retention-window-exception-1-date','retention-window-exception-1-kind','retention-window-slot-exception_1-4-start']){
  f.run('retentionProposal={token:"old"};');f.elements.get('#retention-result').innerHTML='old preview';
  for(const fn of f.listeners.get('input'))await fn({target:{id}});
  assert.equal(f.run('retentionProposal'),null);assert.equal(f.elements.get('#retention-result').innerHTML,'');
 }
});

test('opening preview submits current form without activating or invalidating retention',async()=>{
 const f=fixture(async()=>response(200,{}));vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/retention.js'),'utf8'),f.context);
 f.context.capture={};f.run('page="retention";retentionProposal={token:"unchanged"};api=async(route,body)=>{capture.route=route;capture.body=body;return {generated_at:1704067200,until:1704672000,timezone:body.timezone,enabled:true,windows:[{start:1704074400,end:1704085200}]};};');
 f.elements.set('#retention-window-openings',{innerHTML:''});f.elements.set('#retention-form',{values:{timezone:'America/Cayenne',window_enabled:'on',window_start:'22:00',window_end:'02:00'}});
 await f.run('retentionShowOpenings({disabled:false})');
 assert.equal(f.context.capture.route,'protection/retention-openings');assert.equal(f.context.capture.body.window.start,'22:00');assert.equal(f.context.capture.body.timezone,'America/Cayenne');assert.equal(f.run('retentionProposal.token'),'unchanged');
 assert.match(f.elements.get('#retention-window-openings').innerHTML,/sans enregistrement ni activation/);
});

test('late opening result is discarded after form edit or navigation',async()=>{
 for(const action of ['retentionInvalidate()','page="home"']){
  let complete;const f=fixture(async()=>response(200,{}));vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/retention.js'),'utf8'),f.context);
  f.context.waiting=new Promise(resolve=>{complete=resolve;});f.run('page="retention";api=async()=>await waiting;');
  f.elements.set('#retention-window-openings',{innerHTML:''});f.elements.set('#retention-form',{values:{}});
  const pending=f.run('retentionShowOpenings({disabled:false})');f.run(action);
  complete({generated_at:1704067200,until:1704672000,timezone:'UTC',enabled:true,windows:[]});await pending;
  assert.equal(f.elements.get('#retention-window-openings').innerHTML,'');
 }
});

test('opening view distinguishes unrestricted empty ongoing and repeated local hours',()=>{
 const f=fixture(async()=>response(200,{}));vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/retention.js'),'utf8'),f.context);
 f.run('const openingBase={generated_at:1729987200,until:1730592000,timezone:"Europe/Paris",windows:[]};');
 assert.match(f.run('retentionOpenings({...openingBase,enabled:false})'),/Limitation désactivée/);
 assert.match(f.run('retentionOpenings({...openingBase,enabled:true})'),/Aucune ouverture/);
 const html=f.run('retentionOpenings({...openingBase,enabled:true,windows:[{start:1729988100,end:1729989900,ongoing:true},{start:1729991700,end:1729993500,continues:true}]})');
 assert.match(html,/Déjà ouvert/);assert.match(html,/au-delà de cet aperçu/);assert.match(html,/UTC\+2/);assert.match(html,/UTC\+1/);
});

function cameraFixture(fetch){
 const f=fixture(fetch);
 for(const name of ['components.js','playback.js','detection.js','search.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static',name),'utf8'),f.context);
 f.run('user={name:"admin",role:"admin"};shell();page="camera";');return f;
}
const cameraSamples=[{id:'entry',name:'Entrée',enabled:true,status:'receiving',online:true,fps:5,observed_at:1700000000,days:3},
 {id:'garage',name:'Garage',enabled:true,status:'no_frames',online:false,fps:0,observed_at:1700000000,days:1},
 {id:'pause',name:'Pause',enabled:false,status:'disabled',online:false,fps:null,observed_at:null,days:1},
 {id:'unknown',name:'Inconnue',enabled:true,status:'unknown',online:false,fps:null,observed_at:null,days:1}];
test('camera overview shows four states without live streams or detail requests',async()=>{
 const calls=[],f=cameraFixture(async url=>{calls.push(url);return response(200,cameraSamples);});
 await f.run('renderSurveillance()');const html=f.elements.get('#content').innerHTML;
 assert.deepEqual(calls,['/api/cameras']);assert.doesNotMatch(html,/<img|camera\/live|camera\/snapshot/);
 for(const text of ['Flux reçu','Aucune image reçue','En pause','État inconnu','5 images/s','Ouvrir Entrée'])assert.ok(html.includes(text),text);
 f.context.camera={...cameraSamples[0],name:'<script>bad</script>',id:'evil" data-x="yes'};
 assert.doesNotMatch(f.run('cameraOverview([camera],"")'),/<script>|data-x="yes/);
});
test('camera overview is available to viewers without configuration actions',async()=>{
 const f=cameraFixture(async()=>response(200,cameraSamples));f.run('user.role="viewer";');
 await f.run('renderSurveillance()');const html=f.elements.get('#content').innerHTML;
 assert.match(html,/camera-open/);assert.doesNotMatch(html,/camera-add|camera-edit|camera-settings/);
});
test('only the selected camera opens a live stream and returning removes it immediately',async()=>{
 const calls=[],f=cameraFixture(async url=>{calls.push(url);return response(200,url==='/api/cameras'?cameraSamples:url.includes('/info')?{features:['pt']}:url.includes('/settings')?{days:3,enabled:true}:[]);});
 f.run('selectedCamera="entry";cameraDetail=true;');await f.run('renderSurveillance()');
 assert.match(f.elements.get('#content').innerHTML,/src="\/api\/camera\/live\?camera=entry"/);
 assert.equal(calls.filter(u=>u.startsWith('/api/camera/')).length,4);
 assert.ok(calls.slice(1).every(u=>u.endsWith('?camera=entry')));
 f.run('cameraDetail=false;');const pending=f.run('renderSurveillance()');
 assert.doesNotMatch(f.elements.get('#content').innerHTML,/<img/);await pending;
 assert.doesNotMatch(f.elements.get('#content').innerHTML,/<img/);
});
test('late camera catalogs cannot override a newer refresh or navigation',async()=>{
 const complete=[],f=cameraFixture(()=>new Promise(resolve=>complete.push(resolve)));
 const old=f.run('renderSurveillance()'),fresh=f.run('renderSurveillance()');
 complete[1](response(200,[cameraSamples[0]]));await fresh;
 const html=f.elements.get('#content').innerHTML;complete[0](response(200,[cameraSamples[1]]));await old;
 assert.equal(f.elements.get('#content').innerHTML,html);assert.equal(f.run('cameraCatalog[0].id'),'entry');
 const abandoned=f.run('renderSurveillance()');f.run('page="files";$("#content").innerHTML="files";');
 complete[2](response(503,{error:'unavailable'}));await abandoned;assert.equal(f.elements.get('#content').innerHTML,'files');
});
test('late camera details cannot reopen a live stream after returning to overview',async()=>{
 const complete=[],f=cameraFixture(url=>url==='/api/cameras'?Promise.resolve(response(200,cameraSamples)):new Promise(resolve=>complete.push(resolve)));
 f.run('selectedCamera="entry";cameraDetail=true;');const detail=f.run('renderSurveillance()');
 for(let n=0;n<8&&!complete.length;n++)await Promise.resolve();assert.equal(complete.length,4);
 f.run('cameraDetail=false;');await f.run('renderSurveillance()');
 complete[0](response(200,{features:['pt']}));complete[1](response(200,[]));complete[2](response(200,{days:3}));complete[3](response(200,{enabled:true,tracked:['person'],groups:[]}));await detail;
 assert.match(f.elements.get('#content').innerHTML,/camera-catalog/);assert.doesNotMatch(f.elements.get('#content').innerHTML,/camera\/live/);
});
test('paused cameras have no live or enabled PTZ even with old metrics and capabilities',async()=>{
 const f=cameraFixture(async url=>response(200,url==='/api/cameras'?[cameraSamples[2]]:url.includes('/info')?{features:['pt']}:url.includes('/settings')?{days:1,enabled:false}:[]));
 f.run('selectedCamera="pause";cameraDetail=true;');await f.run('renderSurveillance()');
 const html=f.elements.get('#content').innerHTML;assert.match(html,/En pause/);assert.match(html,/PTZ indisponible/);assert.doesNotMatch(html,/camera\/live/);
});
test('hiding the overview or a viewer session does not send a PTZ command',async()=>{
 const calls=[],f=cameraFixture(async (url,options)=>{calls.push([url,options]);return response(200,{});});
 f.run('selectedCamera="entry";document.hidden=true;');
 for(const fn of f.listeners.get('visibilitychange'))fn();assert.equal(calls.length,0);
 f.run('cameraDetail=true;user.role="viewer";');
 for(const fn of f.listeners.get('visibilitychange'))fn();assert.equal(calls.length,0);
 f.run('user.role="admin";');
 for(const fn of f.listeners.get('visibilitychange'))fn();
 assert.equal(calls.length,1);assert.equal(calls[0][0],'/api/camera/ptz');
 assert.deepEqual(JSON.parse(calls[0][1].body),{action:'stop',camera:'entry'});
});

test('stale camera samples are labeled without opening a live stream',async()=>{
 const stale={...cameraSamples[0],status:'stale',online:false,fps:null};
 const f=cameraFixture(async url=>response(200,url==='/api/cameras'?[stale]:url.includes('/info')?{}:url.includes('/settings')?{days:1}:[]));
 await f.run('renderSurveillance()');assert.match(f.elements.get('#content').innerHTML,/Mesure périmée/);
 f.run('cameraDetail=true;selectedCamera="entry";');await f.run('renderSurveillance()');
 assert.doesNotMatch(f.elements.get('#content').innerHTML,/src="\/api\/camera\/live/);
});
test('live monitor removes image on stale health and ignores late replies after navigation',async()=>{
 const complete=[],f=cameraFixture(()=>new Promise(resolve=>complete.push(resolve)));
 const panel={innerHTML:'live'},badge={innerHTML:''};f.elements.set('#camera-live-panel',panel);f.elements.set('#camera-live-state',badge);
 f.run('cameraDetail=true;selectedCamera="entry";');
 const check=f.run('watchCamera("entry",()=>page==="camera")');
 const pending=check();complete[0](response(200,[{...cameraSamples[0],status:'stale',online:false}]));await pending;
 assert.match(panel.innerHTML,/direct n’est plus confirmé/);assert.match(badge.innerHTML,/Mesure périmée/);
 panel.innerHTML='new page';const late=check();f.run('page="files";');complete[1](response(200,[]));await late;
 assert.equal(panel.innerHTML,'new page');
});
test('live monitor does not overlap requests and rejects failed health checks',async()=>{
 let complete,calls=0;const f=cameraFixture(()=>{calls++;return new Promise(resolve=>{complete=resolve;});});
 const panel={innerHTML:'live'};f.elements.set('#camera-live-panel',panel);f.run('cameraDetail=true;selectedCamera="entry";');
 const check=f.run('watchCamera("entry",()=>true)');const pending=check();await check();assert.equal(calls,1);
 complete(response(503,{error:'offline'}));await pending;assert.match(panel.innerHTML,/direct n’est plus confirmé/);
});

const panelSample={name:'Atelier',timezone:'UTC',revision:0,setup_complete:true,version:'test',system:'Linux',architecture:'aarch64',accounts:[{name:'admin',role:'admin',active:1,current:true,valid_sessions:2},{name:'reader',role:'viewer',active:1,current:false,valid_sessions:1}]};
function panelFixture(fetch){
 const f=fixture(fetch);vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/control-panel.js'),'utf8'),f.context);
 f.run('user={name:"admin",role:"admin",timezone:"UTC"};page="settings";shell();');f.context.sample=JSON.parse(JSON.stringify(panelSample));return f;
}
function panelForm(f){
 const fieldset={disabled:false},values={name:'Mon NAS',timezone:'America/Cayenne'};
 const form={getAttribute:()=> 'control-preferences',querySelector:()=>fieldset,elements:{namedItem:name=>({value:values[name]})}};
 f.elements.set('#control-preferences',form);f.elements.set('#control-error',{textContent:''});f.elements.set('#side-host',{textContent:''});f.elements.set('#topclock',{textContent:''});
 f.context.form=form;f.run('controlState=sample;');return {form,fieldset,values};
}
test('control panel groups real administration routes and escapes values',async()=>{
 const f=panelFixture(async()=>response(200,{...panelSample,name:'<img src=x>',accounts:[{...panelSample.accounts[0],name:'<script>bad</script>'}]}));
 await f.run('renderControlPanel()');const html=f.elements.get('#content').innerHTML;
 for(const route of ['storage','shares','backups','services','notifications','users'])assert.match(html,new RegExp('data-page="'+route+'"'));
 assert.doesNotMatch(html,/<script>|<img src=x>/);assert.match(html,/&lt;img/);
 f.run('user.role="viewer";');await f.run('renderControlPanel()');assert.match(f.elements.get('#content').innerHTML,/réservé aux administrateurs/);
});
test('late control panel responses cannot replace another page',async()=>{
 let complete;const f=panelFixture(()=>new Promise(resolve=>complete=resolve));
 const pending=f.run('renderControlPanel()');f.run('page="files";$("#content").innerHTML="files";');
 complete(response(200,panelSample));await pending;assert.equal(f.elements.get('#content').innerHTML,'files');
});
test('control preferences save revision and update displayed identity and timezone',async()=>{
 const calls=[],f=panelFixture(async(url,options)=>{calls.push([url,options]);return response(200,{name:'Mon NAS',timezone:'America/Cayenne',revision:1});});
 const {fieldset}=panelForm(f);await f.run('saveControlPreferences(form)');
 assert.equal(calls[0][0],'/api/control-panel/configure');assert.deepEqual(JSON.parse(calls[0][1].body),{name:'Mon NAS',timezone:'America/Cayenne',revision:0});
 assert.equal(f.run('user.timezone'),'America/Cayenne');assert.equal(f.run('controlState.revision'),1);assert.equal(f.elements.get('#side-host').textContent,'Mon NAS');assert.equal(fieldset.disabled,false);
});
test('preferences conflict preserves typed values and allows correction',async()=>{
 const f=panelFixture(async()=>response(409,{error:'Les préférences ont changé.'}));const {values,fieldset}=panelForm(f);
 await f.run('saveControlPreferences(form)');assert.equal(values.name,'Mon NAS');assert.equal(f.run('controlState.revision'),0);assert.equal(fieldset.disabled,false);
 assert.equal(f.elements.get('#control-error').textContent,'Les préférences ont changé.');
});
test('session expiration while saving preferences keeps the login intact',async()=>{
 const f=panelFixture(async()=>response(401,{error:'Session expirée.'}));panelForm(f);
 await f.run('saveControlPreferences(form)');assert.equal(f.elements.has('#content'),false);assert.equal(f.elements.get('#login-error').textContent,'Session expirée.');
});
test('refreshing sessions preserves preference draft and its original revision',async()=>{
 const f=panelFixture(async()=>response(200,{...panelSample,revision:4,name:'Elsewhere',accounts:[]}));const {values}=panelForm(f);f.elements.set('#control-sessions',{innerHTML:''});
 await f.run('refreshControlSessions()');assert.equal(values.name,'Mon NAS');assert.equal(f.run('controlState.revision'),0);assert.equal(f.run('controlState.accounts.length'),0);
});
test('only other valid sessions can be selected for disconnection',()=>{
 const f=panelFixture(async()=>response(200,{}));
 assert.match(f.run('controlSessions([{...sample.accounts[0],valid_sessions:1}])'),/data-name="admin" disabled/);
 assert.doesNotMatch(f.run('controlSessions(sample.accounts)'),/data-name="admin" disabled/);
 assert.match(f.run('controlSessions(sample.accounts)'),/Déconnecter les autres/);
});

// Fuseau horaire : proposition au premier accès, champ avec liste, et garde d'affichage.
const zoneNow=Date.UTC(2026,10,13,0,31);
function zoneFixture(fetch,zone='America/Cayenne'){
 const f=panelFixture(fetch);vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/timezone.js'),'utf8'),f.context);
 f.context.zone=zone;f.run('browserZone=()=>zone;user={name:"admin",role:"admin",csrf:"synthetic",timezone:"UTC",nas_name:"Atelier",timezone_unset:true};page="home";shell();');
 f.elements.set('#zone-prompt',{innerHTML:'x'});f.context.rendered=0;f.run('render=async()=>{rendered++;};');
 f.click=(action,data={})=>f.listeners.get('click').at(-1)({target:{closest:()=>({dataset:{action,...data}})}});return f;
}
test('a console timezone unknown to the browser falls back to UTC instead of breaking every date',()=>{
 const f=fixture(async()=>response(200,{}));
 for(const zone of ['localtime','posixrules','Factory','Mars/Olympus','',null,undefined,7,{}])assert.equal(f.run('zoneKnown')(zone),false,String(zone));
 for(const zone of ['UTC','America/Cayenne','Europe/Paris'])assert.equal(f.run('zoneKnown')(zone),true);
 f.run('user={name:"admin",role:"admin",timezone:"UTC"};');const expected=[f.run('date(1794182400)'),f.run('clock(1794182400)')];
 f.run('user.timezone="Mars/Olympus";');assert.equal(f.run('consoleZone()'),'UTC');assert.deepEqual([f.run('date(1794182400)'),f.run('clock(1794182400)')],expected);
 f.run('shell()');assert.ok(f.elements.has('#content'));
 f.run('user.timezone="America/Cayenne";');assert.equal(f.run('consoleZone()'),'America/Cayenne');assert.notEqual(f.run('clock(1794182400)'),expected[1]);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/playback.js'),'utf8'),f.context);
 f.run('playbackData={timezone:"Mars/Olympus"};');assert.equal(f.run('pbZone()'),'UTC');assert.match(f.run('pbClock(1794182400)'),/^\d\d:\d\d:\d\d$/);
 f.run('playbackData={timezone:"America/Cayenne"};');assert.equal(f.run('pbZone()'),'America/Cayenne');
});
test('timezone prompt appears only for an administrator who never chose, with the browser zone',()=>{
 const f=zoneFixture(async()=>response(200,{}));f.context.now=zoneNow;
 const html=f.run('zonePrompt(now)');
 assert.match(html,/il est 00:31/);assert.match(html,/il est 21:31 chez vous \(America\/Cayenne\)/);
 assert.match(html,/data-action="zone-use" data-zone="America\/Cayenne"/);assert.match(html,/Utiliser America\/Cayenne/);
 assert.match(html,/data-action="zone-choose"[^>]*>(<[^>]*>)*Choisir un autre fuseau/);assert.match(html,/data-action="zone-keep"[^>]*>(<[^>]*>)*Garder UTC/);
 assert.doesNotMatch(html,/style=|role="alert"/);
 // La coquille réserve l'emplacement et le remplit dès l'ouverture.
 let shellHtml='';f.elements.set('#app',{set innerHTML(v){shellHtml=v;}});f.run('shell()');
 assert.match(shellHtml,/<div id="zone-prompt"><section class="notice zone-prompt"[\s\S]*<\/section><\/div><main class="content" id="content">/);
 for(const change of ['user.role="viewer"','user.timezone_unset=false','user.setup_required=true','user=null']){
  f.run('user={name:"admin",role:"admin",timezone:"UTC",timezone_unset:true};');assert.notEqual(f.run('zonePrompt(now)'),'');
  f.run(change);assert.equal(f.run('zonePrompt(now)'),'',change);
 }
 f.run('user={name:"admin",role:"admin",timezone:"UTC",timezone_unset:true};');
 // Navigateur en UTC, fuseau illisible ou nom piégé : aucune suggestion, le choix reste possible.
 for(const zone of ['UTC','Etc/UTC','GMT','Etc/GMT','Mars/Olympus','"><img src=x onerror=alert(1)>']){
  f.context.zone=zone;const plain=f.run('zonePrompt(now)');
  assert.doesNotMatch(plain,/zone-use|<img/,zone);assert.match(plain,/UTC \(00:31\)/);assert.match(plain,/>Choisir un fuseau</);assert.match(plain,/zone-keep/);
 }
 // Londres est à l'heure d'UTC en hiver, mais reste une vraie proposition.
 f.context.zone='Europe/London';assert.match(f.run('zonePrompt(now)'),/data-zone="Europe\/London"/);
});
test('accepting the proposal saves it once, redraws the page and removes the prompt',async()=>{
 const calls=[];let release;const f=zoneFixture((url,options)=>{calls.push([url,options?.body]);return new Promise(resolve=>{release=()=>resolve(response(200,{name:'Atelier',timezone:JSON.parse(options.body).timezone,revision:1}));});});
 await f.click('zone-use',{zone:'Europe/Paris'});assert.equal(calls.length,0);
 const first=f.click('zone-use',{zone:'America/Cayenne'}),second=f.click('zone-keep');await second;
 assert.equal(calls.length,1);release();await first;
 assert.deepEqual(calls,[['/api/control-panel/configure',JSON.stringify({name:'Atelier',timezone:'America/Cayenne',revision:0})]]);
 assert.deepEqual([f.run('user.timezone'),f.run('user.timezone_unset'),f.run('rendered'),f.run('page')],['America/Cayenne',false,1,'home']);
 assert.equal(f.elements.get('#zone-prompt').innerHTML,'');assert.match(f.elements.get('#toast').textContent,/America\/Cayenne/);
 assert.equal(f.elements.get('#topclock').textContent,f.run('date(Date.now()/1000)'));
 await f.click('zone-keep');assert.equal(calls.length,1);
 // « Garder UTC » enregistre aussi le choix.
 const g=zoneFixture(async(url,options)=>{calls.push([url,options?.body]);return response(200,{name:'Atelier',timezone:'UTC',revision:1});});
 await g.click('zone-keep');assert.deepEqual(calls.at(-1),['/api/control-panel/configure',JSON.stringify({name:'Atelier',timezone:'UTC',revision:0})]);
 assert.deepEqual([g.run('user.timezone'),g.run('user.timezone_unset'),g.run('rendered')],['UTC',false,1]);assert.match(g.elements.get('#toast').textContent,/restent affichées en UTC/);
 // « Choisir un autre fuseau » ouvre le panneau sans rien enregistrer.
 const h=zoneFixture(async()=>response(200,{}));let focused=0;h.elements.set('#field-timezone',{focus(){focused++;}});
 await h.click('zone-choose');assert.deepEqual([h.run('page'),h.run('rendered'),focused,h.run('user.timezone_unset')],['settings',1,1,true]);
});
test('a zone the server refuses is withdrawn, and a choice made elsewhere is adopted',async()=>{
 const f=zoneFixture(async()=>response(400,{error:'Fuseau horaire inconnu sur ce système.'}),'Asia/Calcutta');
 await f.click('zone-use',{zone:'Asia/Calcutta'});
 const html=f.elements.get('#zone-prompt').innerHTML;
 assert.match(html,/role="alert">Ce serveur ne connaît pas le fuseau Asia\/Calcutta/);assert.doesNotMatch(html,/zone-use/);assert.match(html,/>Choisir un fuseau</);
 assert.deepEqual([f.run('user.timezone'),f.run('user.timezone_unset'),f.run('rendered')],['UTC',true,0]);
 const calls=[],g=zoneFixture(async url=>{calls.push(url);return url.endsWith('/me')?response(200,{name:'admin',role:'admin',timezone:'Europe/Paris',nas_name:'Maison',timezone_unset:false}):response(409,{error:'Les préférences ont changé dans une autre session.'});});
 await g.click('zone-use',{zone:'America/Cayenne'});
 assert.deepEqual(calls,['/api/control-panel/configure','/api/me']);
 assert.deepEqual([g.run('user.timezone'),g.run('user.nas_name'),g.run('user.timezone_unset'),g.run('user.csrf'),g.run('rendered')],['Europe/Paris','Maison',false,'synthetic',1]);
 assert.equal(g.elements.get('#zone-prompt').innerHTML,'');
 // Panne du serveur : le message est montré, la proposition reste.
 const h=zoneFixture(async()=>response(500,{error:'Base indisponible.'}));await h.click('zone-use',{zone:'America/Cayenne'});
 assert.match(h.elements.get('#zone-prompt').innerHTML,/Base indisponible\./);assert.match(h.elements.get('#zone-prompt').innerHTML,/zone-use/);assert.equal(h.run('rendered'),0);
});
test('late or expired answers to the timezone prompt never touch another session',async()=>{
 let complete;const f=zoneFixture(()=>new Promise(resolve=>{complete=resolve;}));
 const pending=f.click('zone-use',{zone:'America/Cayenne'});f.run('login();');complete(response(200,{name:'Atelier',timezone:'America/Cayenne',revision:1}));await pending;
 assert.equal(f.run('user'),null);assert.equal(f.run('rendered'),0);assert.equal(f.run('zoneBusy'),false);
 const g=zoneFixture(async()=>response(401,{error:'Session expirée.'}));await g.click('zone-keep');
 assert.equal(g.run('user'),null);assert.equal(g.elements.get('#login-error').textContent,'Session expirée.');assert.equal(g.run('rendered'),0);
});
test('timezone field lists displayable names, previews the hour and refuses an unknown name before any request',async()=>{
 const calls=[],f=zoneFixture(async(url,options)=>{calls.push(url);return response(200,url.endsWith('/control-panel')?{...panelSample,timezone_unset:true,timezones:['UTC','America/Cayenne','Mars/Olympus','<b>x</b>',7,'Europe/Paris']}:{name:'Mon NAS',timezone:'America/Cayenne',revision:1});});
 f.run('page="settings";');await f.run('renderControlPanel()');const html=f.elements.get('#content').innerHTML;
 assert.match(html,/<input id="field-timezone" name="timezone" type="text" value="UTC" list="zone-list"/);
 assert.match(html,/<datalist id="zone-list"><option value="UTC"><\/option><option value="America\/Cayenne"><\/option><option value="Europe\/Paris"><\/option><\/datalist>/);
 assert.match(html,/id="zone-preview" aria-live="polite">Dans ce fuseau, il est \d\d:\d\d \(UTC\+0\)\./);assert.doesNotMatch(html,/<b>x|Olympus|style=/);
 f.context.now=zoneNow;assert.equal(f.run('zonePreview(" America/Cayenne ",now)'),'Dans ce fuseau, il est 21:31 (UTC−3).');
 assert.equal(f.run('zonePreview("Europe/Paris",now)'),'Dans ce fuseau, il est 01:31 (UTC+1).');
 assert.match(f.run('zonePreview("Cayenne",now)'),/^Choisissez un nom de la liste/);assert.equal(f.run('zonePreview("",now)'),'');
 const preview={textContent:''};f.elements.set('#zone-preview',preview);const input=f.listeners.get('input').at(-1);
 input({target:{id:'field-timezone',value:'Europe/Paris',closest:()=>null}});assert.equal(preview.textContent,'');
 input({target:{id:'field-other',value:'Europe/Paris',closest:()=>({})}});assert.equal(preview.textContent,'');
 input({target:{id:'field-timezone',value:'Europe/Paris',closest:()=>({})}});assert.match(preview.textContent,/^Dans ce fuseau, il est \d\d:\d\d \(UTC\+[12]\)\.$/);
 // Enregistrement depuis le panneau : nom illisible arrêté avant l'envoi, nom valide envoyé sans espaces et proposition retirée.
 const {values}=panelForm(f);values.timezone='localtime';const before=calls.length;await f.run('saveControlPreferences(form)');
 assert.equal(calls.length,before);assert.match(f.elements.get('#control-error').textContent,/Ce navigateur ne connaît pas ce fuseau/);assert.equal(f.run('user.timezone_unset'),true);
 values.timezone=' America/Cayenne ';f.elements.set('#zone-prompt',{innerHTML:'x'});await f.run('saveControlPreferences(form)');
 assert.equal(calls.at(-1),'/api/control-panel/configure');assert.deepEqual([f.run('user.timezone'),f.run('user.timezone_unset')],['America/Cayenne',false]);assert.equal(f.elements.get('#zone-prompt').innerHTML,'');
});
test('setup assistant offers the same timezone list and stops an unknown name before any request',async()=>{
 const calls=[],f=zoneFixture(async url=>{calls.push(url);return response(200,{});},'Europe/Paris');
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/onboarding.js'),'utf8'),f.context);
 f.run('page="setup";setupStep=2;setupState={phase:"system",name:"Nacre",timezone:"UTC",existing:false,timezones:["UTC","Europe/Paris","Mars/Olympus"]};drawSetup();');
 const html=f.elements.get('#content').innerHTML;
 assert.match(html,/id="field-timezone" name="timezone" type="text" value="Europe\/Paris" list="zone-list"/);assert.match(html,/<option value="Europe\/Paris"><\/option><\/datalist>/);assert.doesNotMatch(html,/Olympus/);
 const error={textContent:''};f.elements.set('#setup-error',error);const submit={disabled:false};
 const form={getAttribute:()=> 'setup-finish',values:{name:'Maison',timezone:'Factory'},querySelector:()=>submit};
 await f.listeners.get('submit').at(-1)({target:form,preventDefault(){}});
 assert.deepEqual(calls,[]);assert.match(error.textContent,/Ce navigateur ne connaît pas ce fuseau/);assert.equal(submit.disabled,false);
});

// Bureau : coquille à une fenêtre, applications à onglets, affichage classique conservé.
const overviewSample={host:'<b>Atelier</b>',services_available:true,services:[{name:'fichiers',state:'running'},{name:'video',state:'exited'}],disk:{total:4000,used:1000,free:3000},memory:{total:8000,used:2000},load:[0.5,0,0],cpus:4,camera:{id:'<i>entree</i>',camera_fps:5},events:[{ts:1794182400,username:'<u>admin</u>',action:'<script>x</script>',detail:''}]};
function deskFixture(fetch=async()=>response(200,overviewSample),role='admin'){
 const f=fixture(fetch);vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/desktop.js'),'utf8'),f.context);
 const store={};f.context.localStorage={getItem:k=>store[k]??null,setItem:(k,v)=>{store[k]=String(v);}};f.store=store;
 f.html='';const real=f.elements.get('#app');f.elements.set('#app',{set innerHTML(v){f.html=v;real.innerHTML=v;
  for(const id of ['dk-win','dk-name','dk-tile','dk-tabs','dk-widgets','side-host'])if(v.includes(`id="${id}"`))f.elements.set('#'+id,{hidden:false,textContent:'',innerHTML:'',style:{},classList:{toggle(name,on){this[name]=on;}}});else f.elements.delete('#'+id);}});
 f.context.rendered=[];f.run(`user={name:"admin",role:"${role}",csrf:"synthetic",nas_name:"<b>Atelier</b>",app_version:"test"};page="home";render=async()=>{rendered.push(page);};shell();`);
 f.click=(action,data={})=>f.listeners.get('click').at(-1)({target:{closest:()=>({dataset:{action,...data}})}});return f;
}
test('desktop shell replaces the sidebar, keeps the anchors pages rely on and escapes the NAS name',()=>{
 const f=deskFixture();
 assert.match(f.html,/^<div class="dk">/);assert.doesNotMatch(f.html,/class="sidebar"|<b>Atelier|style=/);assert.match(f.html,/&lt;b&gt;Atelier/);
 for(const id of ['content','crumb','topclock','side-host','side-version','alert-summary','zone-prompt','dk-win','dk-tabs','dk-widgets'])assert.match(f.html,new RegExp(`id="${id}"`),id);
 assert.equal((f.html.match(/class="dk-dockapp"/g)||[]).length,7);assert.equal((f.html.match(/class="dk-app"/g)||[]).length,7);
 assert.match(f.html,/data-action="shell-classic"/);assert.match(f.html,/data-action="logout"/);
 // Lecture seule : ni alertes ni onglets d'administration, et les applications gardent leurs pages ouvertes à tous.
 const g=deskFixture(undefined,'viewer');assert.doesNotMatch(g.html,/alert-summary/);
 assert.deepEqual(JSON.parse(JSON.stringify(g.run('deskApps().map(a=>[a.id,deskPages(a).map(p=>p[0])])'))),[['files',['files','trash']],['cam',['camera']],['storage',['storage','native']],['protect',['backups','snapshots']],['share',['shares','users']],['settings',['services']],['activity',['events']]]);
 // Chaque page de la console appartient à une application et une seule.
 const pages=f.run('DESK_APPS.flatMap(a=>a.pages.map(p=>p[0]))');assert.equal(new Set(pages).size,pages.length);
 for(const name of pages)assert.ok(f.run('titles')[name],name);
 for(const name of Object.keys(f.run('titles')))if(!['home','setup'].includes(name))assert.ok(pages.includes(name),name);
});
test('classic display stays one click away and the first-run assistant never uses the desktop',async()=>{
 const f=deskFixture();await f.run('go("users")');
 await f.click('shell-classic');
 assert.equal(f.store['nacre-shell'],'classic');assert.match(f.html,/class="sidebar"/);assert.match(f.html,/data-action="shell-desk"/);assert.equal(f.run('page'),'users');assert.equal(f.run('deskMode()'),false);
 await f.click('shell-desk');assert.equal(f.store['nacre-shell'],'desk');assert.match(f.html,/^<div class="dk">/);assert.equal(f.run('page'),'users');
 f.run('user.setup_required=true;shell();');assert.match(f.html,/class="sidebar"/);assert.doesNotMatch(f.html,/shell-desk/);assert.equal(f.run('deskMode()'),false);
 // Stockage du navigateur indisponible : le bureau reste l'affichage par défaut et le choix ne casse rien.
 const g=deskFixture();g.context.localStorage={getItem(){throw new Error('bloqué');},setItem(){throw new Error('bloqué');}};
 assert.equal(g.run('deskMode()'),true);await g.click('shell-classic');assert.match(g.html,/^<div class="dk">/);
});
test('navigation opens the application window with its tabs and the desktop hides it',async()=>{
 const f=deskFixture();const win=()=>f.elements.get('#dk-win');
 assert.equal(win().hidden,true);
 await f.run('go("snapshots")');
 assert.equal(win().hidden,false);assert.equal(f.elements.get('#dk-name').textContent,'Protection');assert.match(f.elements.get('#dk-tile').innerHTML,/dk-protect/);
 const tabs=f.elements.get('#dk-tabs');assert.equal(tabs.hidden,false);
 assert.deepEqual([...tabs.innerHTML.matchAll(/data-page="(\w+)" aria-selected="(\w+)">([^<]+)</g)].map(m=>m.slice(1)),[['backups','false','Sauvegardes'],['snapshots','true','Points de restauration'],['retention','false','Conservation']]);
 assert.equal(f.elements.get('#crumb').textContent,'Snapshots');
 await f.run('go("camera")');assert.equal(f.elements.get('#dk-name').textContent,'Surveillance');
 // Application à page unique : ses onglets sont des vues, la première sélectionnée.
 assert.equal(tabs.hidden,false);assert.deepEqual([...tabs.innerHTML.matchAll(/data-action="desk-view" data-app="cam" data-view="(\w+)" aria-selected="(\w+)">([^<]+)</g)].map(m=>m.slice(1)),[['wall','true','Mur'],['events','false','Événements'],['replay','false','Relecture'],['settings','false','Réglages']]);
 await f.click('desk-view',{app:'cam',view:'replay'});assert.equal(f.run('deskViewOf("cam")'),'replay');assert.match(tabs.innerHTML,/data-view="replay" aria-selected="true"/);assert.equal(f.run('page'),'camera');
 await f.click('desk-view',{app:'cam',view:'nowhere'});await f.click('desk-view',{app:'files',view:'replay'});assert.equal(f.run('deskViewOf("cam")'),'replay');assert.equal(f.run('deskViewOf("files")'),'');
 await f.run('go("users")');assert.match(tabs.innerHTML,/data-page="users" aria-selected="true"/);await f.run('go("camera")');
 await f.run('go("home")');assert.equal(win().hidden,true);assert.equal(f.run('deskOpen'),'cam');
 // Page hors application (fin de l'assistant) : fenêtre simple, titrée par la page.
 f.run('page="setup";deskSync();');assert.equal(win().hidden,false);assert.equal(f.elements.get('#dk-name').textContent,'Première configuration');assert.equal(tabs.hidden,true);
 // Fenêtre agrandie et position mémorisée survivent aux changements d'onglet.
 await f.click('desk-max');assert.equal(win().classList.max,true);f.run('deskPos={left:40,top:12};');await f.run('go("backups")');
 assert.deepEqual([win().classList.max,win().style.left,win().style.top],[true,'40px','12px']);
});
test('dock reopens an application on its last tab, closing forgets it, and unknown applications are ignored',async()=>{
 const f=deskFixture();
 await f.click('desk-open',{app:'protect'});assert.equal(f.run('page'),'backups');
 await f.run('go("retention")');await f.click('desk-min');assert.deepEqual([f.run('page'),f.run('deskOpen')],['home','protect']);
 await f.click('desk-open',{app:'protect'});assert.equal(f.run('page'),'retention');
 await f.click('desk-close');assert.deepEqual([f.run('page'),f.run('deskOpen')],['home',null]);
 const before=f.run('rendered.length');await f.click('desk-open',{app:'nowhere'});await f.click('desk-open',{});assert.equal(f.run('rendered.length'),before);
 // Un onglet mémorisé devenu inaccessible (compte passé en lecture seule) retombe sur le premier onglet permis.
 f.run('user.role="viewer"');await f.click('desk-open',{app:'protect'});assert.equal(f.run('page'),'backups');
});
test('desktop widgets replace the overview, escape what the NAS reports and ignore late answers',async()=>{
 const calls=[];let release;const f=deskFixture(url=>{calls.push(url);return new Promise(resolve=>{release=()=>resolve(response(200,overviewSample));});});
 f.run('render=async()=>renderHome();');const first=f.run('renderHome()');release();await first;
 assert.deepEqual(calls,['/api/overview']);
 const html=f.elements.get('#dk-widgets').innerHTML;
 assert.equal((html.match(/class="dk-wg"/g)||[]).length,5);assert.doesNotMatch(html,/<script>|<i>|<u>|style=/);assert.match(html,/&lt;script&gt;/);
 for(const target of ['storage','services','camera','events'])assert.match(html,new RegExp(`data-page="${target}"`));
 assert.match(html,/1 sur 2 en ligne/);assert.match(html,/<progress value="25" max="100">/);assert.match(html,/5 images\/s/);
 assert.equal(f.elements.get('#side-host').textContent,'<b>Atelier</b>');assert.equal(f.elements.get('#content').innerHTML,undefined);
 // Réponse arrivée après un changement de page ou une déconnexion : rien n'est écrit.
 f.elements.get('#dk-widgets').innerHTML='inchangé';const late=f.run('renderHome()');f.run('page="files";');release();await late;
 assert.equal(f.elements.get('#dk-widgets').innerHTML,'inchangé');
 f.run('page="home";');const gone=f.run('renderHome()');f.run('login();');release();await gone.catch(()=>{});assert.equal(f.run('user'),null);
 // Mesures absentes ou malformées : des tirets, pas d'erreur.
 const g=deskFixture();assert.match(g.run('deskWidgets({})'),/Aucune caméra/);assert.doesNotMatch(g.run('deskWidgets({disk:{total:0,used:0}})'),/<progress/);
 // Affichage classique : la vue d'ensemble d'origine est conservée.
 const h=deskFixture(async()=>response(200,{...overviewSample,uptime:10}));h.store['nacre-shell']='classic';h.run('shell();');h.elements.set('#side-host',{textContent:''});
 await h.run('renderHome()').catch(()=>{});assert.match(String(h.elements.get('#content').innerHTML),/Votre NAS, d’un regard/);
});

// Centre de notifications : cloche du bureau, alertes à traiter, tâches en cours, faits récents.
const bellNow=1794182400,bellAlerts={stale:false,attention:1,active:[{id:'a"1',version:3,title:'<b>Caméra</b> muette',page:'camera',first:bellNow-600,acknowledged:null},{id:'b',version:1,title:'Volume plein',page:'<script>',first:bellNow-9000,acknowledged:bellNow-100}],history:[{id:'c',title:'Service <i>vidéo</i>',resolved:bellNow-50},{id:'d',title:'Ancien',resolved:bellNow-200000}]};
const bellJobsSample=[{id:'j1',kind:'snapshot',status:'running',ts:bellNow-60,progress:'{"percent_done":0.62,"bytes_done":1024,"total_bytes":2048}',result:'{}'},{id:'j2',kind:'backup',status:'done',ts:bellNow-3600,progress:'{}',result:'{}'},{id:'j3',kind:'<img>',status:'failed',ts:bellNow-7200,progress:'{illisible',result:'{}'},{id:'j4',kind:'backup',status:'done',ts:bellNow-200000}];
function bellFixture(fetch,role='admin'){
 const f=deskFixture(fetch,role);vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/bell.js'),'utf8'),f.context);
 f.mount=()=>{for(const id of ['bell','bell-count','bell-tasks','bell-panel'])f.elements.set('#'+id,{hidden:false,textContent:'',innerHTML:'',attrs:{},setAttribute(k,v){this.attrs[k]=v;}});};
 f.click=(action,data={})=>f.listeners.get('click').at(-2)({target:{closest:()=>({dataset:{action,...data}})}});
 f.run('shell();');f.mount();f.context.now=bellNow;return f;
}
const bellReply=(alerts=bellAlerts,jobs=bellJobsSample)=>async url=>response(200,url.endsWith('/alerts')?alerts:url.endsWith('/jobs')?jobs:overviewSample);
test('desktop bar carries the bell instead of the alert button, and the classic display is untouched',async()=>{
 const f=bellFixture(bellReply());
 assert.match(f.html,/id="bell" data-action="bell-toggle" aria-expanded="false"/);assert.match(f.html,/id="bell-tasks"[^>]*hidden/);assert.match(f.html,/id="bell-panel"[^>]*hidden/);assert.doesNotMatch(f.html,/alert-summary|style=/);
 await f.click('shell-classic');assert.match(f.html,/id="alert-summary"/);assert.doesNotMatch(f.html,/id="bell"/);
});
test('bell counts what needs attention, announces running tasks and escapes everything it lists',async()=>{
 const calls=[],f=bellFixture(async url=>{calls.push(url);return bellReply()(url);});
 await f.run('refreshStatus()');
 assert.deepEqual(calls.sort(),['/api/alerts','/api/jobs']);
 const bell=f.elements.get('#bell'),count=f.elements.get('#bell-count'),tasks=f.elements.get('#bell-tasks'),panel=f.elements.get('#bell-panel');
 assert.deepEqual([count.hidden,count.textContent,bell.attrs['aria-label'],tasks.hidden,tasks.textContent,panel.hidden],[false,'1','Notifications : 1 alerte à traiter',false,'1 tâche en cours',true]);
 const html=f.run('bellPanel(now)');
 assert.doesNotMatch(html,/<b>|<i>|<img>|<script>|style=/);assert.match(html,/&lt;b&gt;Caméra/);
 assert.match(html,/data-page="camera">Ouvrir Surveillance/);assert.match(html,/data-action="alert-ack" data-id="a&quot;1" data-version="3"/);assert.equal((html.match(/alert-ack/g)||[]).length,1);
 // Page inconnue annoncée par le serveur : renvoi vers les alertes, jamais vers une valeur reçue.
 assert.match(html,/data-page="alerts">Ouvrir Alertes/);
 assert.match(html,/Snapshot de fichiers<\/strong><small>62 % · 1 Kio sur 2 Kio<\/small><progress max="1" value="0.62">/);
 assert.match(html,/Archive de fichiers : terminée/);assert.match(html,/À vérifier<\/span> &lt;img&gt; : échec/);assert.match(html,/Retour à la normale : Service &lt;i&gt;vidéo/);
 assert.doesNotMatch(html,/Ancien/);assert.equal((html.match(/Archive de fichiers/g)||[]).length,1);
 // Contrôle en retard sans incident : un repère sur la cloche, et l'explication dans le panneau.
 f.run('bellData={alerts:{stale:true,attention:0,active:[],history:[]},jobs:[]};drawBell();');
 assert.deepEqual([count.hidden,count.textContent,bell.attrs['aria-label'],tasks.hidden],[false,'!','Notifications : contrôle des alertes à vérifier',true]);
 assert.match(f.run('bellPanel(now)'),/n’est pas à jour/);assert.match(f.run('bellPanel(now)'),/Aucune tâche en cours/);assert.match(f.run('bellPanel(now)'),/Rien à signaler/);
});
test('a read-only account gets tasks without asking for alerts',async()=>{
 const calls=[],f=bellFixture(async url=>{calls.push(url);return bellReply()(url);},'viewer');
 await f.run('refreshStatus()');assert.deepEqual(calls,['/api/jobs']);
 const html=f.run('bellPanel(now)');assert.doesNotMatch(html,/À traiter|Toutes les alertes|alert-ack/);assert.match(html,/Snapshot de fichiers/);assert.match(html,/data-page="events">Journal/);
 assert.equal(f.elements.get('#bell-count').hidden,true);assert.equal(f.elements.get('#bell-tasks').textContent,'1 tâche en cours');
});
test('a task seen running is announced when it ends, and a failed read keeps the last known state',async()=>{
 let jobs=bellJobsSample,fail=false;const f=bellFixture(async url=>fail?response(500,{error:'Base occupée.'}):bellReply(bellAlerts,jobs)(url));
 const toast=f.elements.get('#toast');
 await f.run('refreshBell()');assert.equal(toast.textContent,'');
 fail=true;await f.run('refreshBell()');assert.equal(f.elements.get('#bell-tasks').textContent,'1 tâche en cours');assert.equal(f.run('bellData.alerts.attention'),1);
 fail=false;jobs=[{...bellJobsSample[0],status:'failed'},...bellJobsSample.slice(1)];await f.run('refreshBell()');
 assert.equal(toast.textContent,'Snapshot de fichiers : échec');assert.match(toast.className,/error/);assert.equal(f.elements.get('#bell-tasks').hidden,true);
 toast.textContent='';await f.run('refreshBell()');assert.equal(toast.textContent,'');
 // Session expirée ou remplacée pendant la lecture : rien n'est écrit.
 let release;const g=bellFixture(()=>new Promise(resolve=>{release=()=>resolve(response(200,bellJobsSample));}));
 const pending=g.run('refreshBell()');g.run('login();');release();await pending.catch(()=>{});assert.equal(g.run('user'),null);assert.equal(g.run('bellData.jobs.length'),0);
 const h=bellFixture(async()=>response(401,{error:'Session expirée.'}));await h.run('refreshBell()').catch(()=>{});assert.equal(h.elements.get('#login-error').textContent,'Session expirée.');
});
test('the panel opens on the bell, stays open while acknowledging and closes on navigation, outside clicks and Escape',async()=>{
 const f=bellFixture(bellReply());await f.run('refreshBell()');const panel=f.elements.get('#bell-panel'),bell=f.elements.get('#bell');
 const click=hit=>f.listeners.get('click').at(-1)({target:{closest:selector=>hit.some(part=>selector.includes(part))?{dataset:{}}:null}});
 click(['bell-toggle']);assert.deepEqual([panel.hidden,bell.attrs['aria-expanded']],[false,'true']);assert.match(panel.innerHTML,/À traiter/);
 click(['#bell-panel']);assert.equal(panel.hidden,false);
 click(['#bell-panel','data-page']);assert.equal(panel.hidden,true);
 click(['bell-toggle']);click([]);assert.equal(panel.hidden,true);
 click(['bell-toggle']);f.listeners.get('keydown').at(-1)({key:'a'});assert.equal(panel.hidden,false);f.listeners.get('keydown').at(-1)({key:'Escape'});assert.deepEqual([panel.hidden,bell.attrs['aria-expanded']],[true,'false']);
 click(['bell-toggle']);click(['bell-toggle']);assert.equal(panel.hidden,true);
 // Sans la coquille du bureau (affichage classique), le dessin ne touche à rien.
 for(const id of ['bell','bell-count','bell-tasks','bell-panel'])f.elements.delete('#'+id);f.run('drawBell()');
});

// Recherche globale : palette Ctrl+K du bureau.
const paletteReply=async url=>response(200,url.endsWith('/cameras')?[{id:'garage',name:'Garage <b>nord</b>'},{id:'',name:'sans identifiant'},null]:url.endsWith('/areas')?[{id:'fichiers',name:'Fichiers partagés'}]:overviewSample);
function paletteFixture(fetch=paletteReply,role='admin'){
 const f=deskFixture(fetch,role);vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/palette.js'),'utf8'),f.context);
 f.focused=[];f.mount=()=>{for(const id of ['palette','palette-results','palette-open','palette-q'])f.elements.set('#'+id,{hidden:true,value:'',innerHTML:'',attrs:{},setAttribute(k,v){this.attrs[k]=v;},focus(){f.focused.push(id);}});};
 f.run('shell();');f.mount();f.key=(key,extra={})=>f.listeners.get('keydown').at(-1)({key,preventDefault(){},...extra});
 f.type=text=>{f.elements.get('#palette-q').value=text;f.listeners.get('input').at(-1)({target:{id:'palette-q',value:text}});};
 f.labels=()=>JSON.parse(JSON.stringify(f.run('paletteFound.map(e=>e.label)')));return f;
}
test('search sits in the desktop bar and only indexes what the account can open',()=>{
 const f=paletteFixture();
 assert.match(f.html,/id="palette-open" data-action="palette-open"/);assert.match(f.html,/<section class="dk-palette" id="palette"[^>]*hidden>/);assert.match(f.html,/id="palette-q" type="search"/);assert.doesNotMatch(f.html,/style=/);
 const pages=f.run('DESK_APPS.flatMap(a=>a.pages.map(p=>p[0]))');
 for(const [label,target] of f.run('PALETTE_TOPICS'))assert.ok(pages.includes(target),label);
 const admin=f.run('paletteIndex()'),hints=new Set(admin.map(e=>e.hint));
 assert.ok(hints.has('Réglages · Général'));assert.ok(hints.has('Application'));assert.equal(admin.filter(e=>e.hint==='Application').length,7);
 const viewer=paletteFixture(paletteReply,'viewer').run('paletteIndex()');
 for(const entry of viewer)assert.ok(!['settings','updates','notifications','alerts','retention'].includes(entry.page),entry.label);
 assert.ok(viewer.some(e=>e.label==='Nouveau partage'));assert.ok(!viewer.some(e=>e.label==='Fuseau horaire'));
 f.store['nacre-shell']='classic';f.run('shell();');assert.doesNotMatch(f.html,/palette/);
});
test('typed words match the start of words, ignore accents and put the closest label first',async()=>{
 const f=paletteFixture();const q=text=>JSON.parse(JSON.stringify(f.run('paletteSearch')(text).map(e=>e.label)));
 assert.deepEqual(q(''),['Fichiers','Surveillance','Stockage','Protection','Partages et comptes','Réglages','Activité']);
 assert.deepEqual(q('fuseau'),['Fuseau horaire']);assert.deepEqual(q('HEURE'),['Fuseau horaire']);assert.deepEqual(q('mot de passe'),['Changer un mot de passe']);
 assert.deepEqual(q('reglages').slice(0,5),['Réglages','Réglages','Général','Services','Mises à jour']);assert.equal(q('reglages').length,8);
 assert.deepEqual(JSON.parse(JSON.stringify(f.run('paletteSearch')('mur').map(e=>[e.label,e.hint,e.view])))[0],['Mur','Surveillance',['cam','wall']]);assert.deepEqual(JSON.parse(JSON.stringify(f.run('paletteSearch')('relecture').map(e=>e.view))),[['cam','replay'],['cam','replay']]);assert.equal(q('sauv')[0],'Sauvegardes');
 assert.ok(!q('gar').includes('Sauvegardes'));assert.deepEqual(q('zzz'),[]);assert.ok(q('a').length<=8);
 assert.deepEqual(q('classique'),['Affichage classique']);
 // Caméras et espaces lus à l'ouverture : noms échappés à l'affichage, entrées sans identifiant écartées.
 f.key('k',{ctrlKey:true});await new Promise(resolve=>setImmediate(resolve));
 assert.deepEqual(JSON.parse(JSON.stringify(f.run('paletteExtra.map(e=>[e.label,e.hint])'))),[['Garage <b>nord</b>','Caméra'],['Fichiers partagés','Espace de fichiers']]);
 f.type('garage');assert.deepEqual(f.labels(),['Garage <b>nord</b>']);
 const html=f.elements.get('#palette-results').innerHTML;assert.match(html,/Garage &lt;b&gt;nord&lt;\/b&gt;<small>Caméra<\/small>/);assert.doesNotMatch(html,/<b>nord/);assert.match(html,/role="option" class="dk-note on" aria-selected="true" data-action="palette-run" data-index="0"/);
 f.type('zzz');assert.match(f.elements.get('#palette-results').innerHTML,/Aucun résultat/);
});
test('keyboard opens, moves, runs and closes the search without acting behind a dialog',async()=>{
 const f=paletteFixture();const panel=f.elements.get('#palette');
 f.elements.get('#modal').open=true;f.key('k',{ctrlKey:true});assert.equal(panel.hidden,true);f.elements.get('#modal').open=false;
 f.key('k',{ctrlKey:true,altKey:true});assert.equal(panel.hidden,true);
 f.key('K',{metaKey:true});assert.deepEqual([panel.hidden,f.focused.at(-1),f.elements.get('#palette-open').attrs['aria-expanded']],[false,'palette-q','true']);
 assert.equal(f.labels().length,7);f.key('ArrowUp');assert.equal(f.run('palettePick'),6);f.key('ArrowDown');assert.equal(f.run('palettePick'),0);f.key('ArrowDown');assert.equal(f.run('palettePick'),1);
 f.key('Enter');await new Promise(resolve=>setImmediate(resolve));assert.deepEqual([f.run('page'),panel.hidden],['camera',true]);
 f.key('k',{ctrlKey:true});f.type('fuseau');f.key('Enter');await new Promise(resolve=>setImmediate(resolve));assert.equal(f.run('page'),'settings');
 f.key('k',{ctrlKey:true});f.key('Escape');assert.deepEqual([panel.hidden,f.focused.at(-1)],[true,'palette-open']);
 f.key('k',{ctrlKey:true});f.key('k',{ctrlKey:true});assert.equal(panel.hidden,true);
 // Fermée, la recherche ignore les touches ; un clic ailleurs la referme.
 const before=f.run('rendered.length');f.key('Enter');f.key('ArrowDown');assert.equal(f.run('rendered.length'),before);
 const click=hit=>f.listeners.get('click').at(-1)({target:{closest:selector=>hit.some(part=>selector.includes(part))?{dataset:{index:'0'}}:null}});
 click(['palette-open']);assert.equal(panel.hidden,false);click(['#palette']);assert.equal(panel.hidden,false);click([]);assert.equal(panel.hidden,true);
 click(['palette-open']);f.type('journal');click(['palette-run']);await new Promise(resolve=>setImmediate(resolve));assert.deepEqual([f.run('page'),panel.hidden],['events',true]);
});
test('a result opens its camera, file area or display, and nothing the account cannot reach',async()=>{
 const f=paletteFixture();vm.runInContext('var cameraCatalog=[],selectedCamera="",cameraDetail=false;',f.context);
 await f.run('runPalette({camera:"garage"})');assert.deepEqual([f.run('page'),f.run('selectedCamera'),f.run('cameraDetail')],['camera','garage',true]);
 f.run('currentPath="ancien/dossier";');await f.run('runPalette({area:"fichiers"})');assert.deepEqual([f.run('page'),f.run('area'),f.run('currentPath')],['files','fichiers','']);
 const before=f.run('rendered.length');await f.run('runPalette({page:"nowhere"})');await f.run('runPalette(undefined)');assert.equal(f.run('rendered.length'),before);
 f.run('user.role="viewer"');await f.run('runPalette({page:"settings"})');assert.equal(f.run('page'),'files');f.run('user.role="admin"');
 await f.run('runPalette({shell:"classic"})');assert.equal(f.store['nacre-shell'],'classic');assert.match(f.html,/class="sidebar"/);
 // Lectures en échec ou tardives : les entrées dynamiques restent absentes, sans erreur ni écriture après déconnexion.
 const g=paletteFixture(async()=>response(500,{error:'Indisponible.'}));await g.run('loadPaletteExtra()');assert.equal(g.run('paletteExtra.length'),0);
 let release;const h=paletteFixture(()=>new Promise(resolve=>{release=()=>resolve(response(200,[{id:'x',name:'Tardive'}]));}));
 const pending=h.run('loadPaletteExtra()');h.run('login();');release();await pending.catch(()=>{});assert.equal(h.run('paletteExtra.length'),0);
});

function updateFixture(fetch){
 const f=fixture(fetch);vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/updates.js'),'utf8'),f.context);
 f.run('user={name:"admin",role:"admin",csrf:"synthetic"};page="updates";shell();');return f;
}
const updateStatus={phase:'prepared',id:'fixture',version:'1.0.0-alpha.2',previous_version:'1.0.0-alpha.1',current_version:'1.0.0-alpha.1',available:true,package_limit:33554432};
test('update preview escapes remote state and restricts viewer access',async()=>{
 const f=updateFixture(async()=>response(200,{...updateStatus,version:'<img src=x>',error:'<script>'}));
 await f.run('renderUpdates()');assert.match(f.elements.get('#content').innerHTML,/&lt;img src=x&gt;/);assert.doesNotMatch(f.elements.get('#content').innerHTML,/<script>/);
 f.run('user.role="viewer"');await f.run('renderUpdates()');assert.match(f.elements.get('#content').innerHTML,/réservées aux administrateurs/);
});
test('late update page response does not overwrite navigation',async()=>{
 let complete;const f=updateFixture(()=>new Promise(resolve=>complete=resolve));
 const pending=f.run('renderUpdates()');f.run('page="files";$("#content").innerHTML="preserved"');complete(response(200,updateStatus));await pending;
 assert.equal(f.elements.get('#content').innerHTML,'preserved');
});
test('lost installation response starts state reconciliation without repeating POST',async()=>{
 let calls=0;const f=updateFixture(async()=>{calls++;throw new TypeError('network closed');});
 f.context.initial=updateStatus;f.run('updateState=initial');
 await f.run('queueUpdate("fixture")');assert.equal(f.run('updateState.phase'),'queued');
 await f.run('renderUpdates()');assert.match(f.elements.get('#content').innerHTML,/Installation demandée/);assert.equal(calls,2);
});
test('installation refusal remains an error and does not fake a queued update',async()=>{
 const f=updateFixture(async()=>response(409,{error:'Tâche en cours.'}));f.context.initial=updateStatus;f.run('updateState=initial');
 await assert.rejects(f.run('queueUpdate("fixture")'),/Tâche en cours/);assert.equal(f.run('updateState.phase'),'prepared');
});
test('update polling reconnects, presents rollback and stops at terminal state',async()=>{
 let calls=0,timers=0;const f=updateFixture(async()=>{if(++calls===1)throw new TypeError('offline');return response(200,{...updateStatus,phase:'rolled_back'});});
 f.elements.set('#update-connection',{textContent:''});f.elements.set('#update-report',{innerHTML:''});f.context.setTimeout=()=>++timers;
 const check=f.run('watchUpdate(updateView,sessionGeneration)');await check();assert.match(f.elements.get('#update-connection').textContent,/Reconnexion/);
 const before=timers;await check();assert.match(f.elements.get('#update-report').innerHTML,/Version précédente restaurée/);assert.equal(timers,before);
 f.run('page="files"');await check();assert.equal(calls,2);
});
test('update polling stops cleanly on session expiry',async()=>{
 let timers=0;const f=updateFixture(async()=>response(401,{error:'Session expirée.'}));f.context.setTimeout=()=>++timers;
 const check=f.run('watchUpdate(updateView,sessionGeneration)');const before=timers;await check();assert.equal(timers,before);assert.equal(f.elements.has('#content'),false);
});
test('late upload errors cannot modify another page or new session',async()=>{
 let complete;const f=updateFixture(()=>new Promise(resolve=>complete=resolve));
 f.context.initial=updateStatus;f.run('updateState=initial');f.elements.set('#update-package',{files:[{size:100}]});f.elements.set('#update-upload-error',{textContent:''});
 const submit={disabled:false};f.context.uploadForm={querySelector:()=>submit};const pending=f.run('uploadUpdate(uploadForm)');
 f.run('page="files"');complete(response(409,{error:'Old error'}));await pending;
 assert.equal(f.elements.get('#update-upload-error').textContent,'');assert.equal(submit.disabled,false);
});
const copyId=n=>String(n).padStart(24,'0'),updateCopiesSample={keep:3,bytes:4096,items:[
 {id:copyId(3),kind:'copy',previous:'1.0.0-alpha.2',version:'1.0.0-alpha.3',created:1794182400,bytes:2048,current:true},
 {id:copyId(2),kind:'copy',previous:'<b>ancienne</b>',version:null,created:1794096000,bytes:1024,current:false},
 {id:copyId(1),kind:'prepared',previous:null,version:'1.0.0-alpha.9',created:1794009600,bytes:1024,current:false},null]};
test('update copies list the retained ones, escape their fields and protect the latest',async()=>{
 const f=updateFixture(async()=>response(200,{...updateStatus,phase:'succeeded',copies:updateCopiesSample}));
 await f.run('renderUpdates()');const html=f.elements.get('#content').innerHTML;
 assert.match(html,/Copies de retour arrière/);assert.match(html,/Nacre 1\.0\.0-alpha\.2/);assert.match(html,/Dernière mise à jour/);assert.match(html,/4 Kio sur le NAS/);
 assert.match(html,/Les 3 copies les plus récentes/);assert.match(html,/&lt;b&gt;ancienne&lt;\/b&gt;/);assert.match(html,/avant l’installation de version inconnue/);
 assert.equal(html.match(/data-action="update-copy-delete"/g).length,1);assert.match(html,new RegExp('data-id="'+copyId(2)+'"'));
 assert.doesNotMatch(html,/<b>ancienne/);assert.doesNotMatch(html,new RegExp(copyId(1)));assert.doesNotMatch(html,/1\.0\.0-alpha\.9/);
 // Sans copie, ou face à une ancienne console qui n'en parle pas, la carte n'apparaît pas.
 for(const copies of [undefined,null,{keep:3,bytes:0,items:[]},{items:'x'},{keep:3,bytes:9,items:[updateCopiesSample.items[2]]}]){
  f.context.sample={...updateStatus,copies};assert.equal(f.run('updateCopies(sample)'),'');
 }
});
test('deleting a copy asks for confirmation, sends its identifier and stays out of reach otherwise',async()=>{
 const calls=[];const f=updateFixture(async(url,options)=>{calls.push([url,options?.body]);return response(200,url.endsWith('/delete')?{keep:3,bytes:2048,items:[updateCopiesSample.items[0]]}:{...updateStatus,phase:'succeeded',copies:updateCopiesSample});});
 const modal=f.elements.get('#modal');let shown=0;modal.showModal=()=>shown++;modal.innerHTML='';
 await f.run('renderUpdates()');const click=id=>f.listeners.get('click').at(-1)({target:{closest:()=>({dataset:{action:'update-copy-delete',id}})}});
 await click(copyId(9));await click(copyId(1).replace('0','x'));assert.equal(shown,0);
 f.run('user.role="viewer"');await click(copyId(2));f.run('user.role="admin";page="files"');await click(copyId(2));assert.equal(shown,0);
 f.run('page="updates"');await click(copyId(2));assert.equal(shown,1);
 assert.match(modal.innerHTML,/Supprimer cette copie/);assert.match(modal.innerHTML,/définitive/);assert.match(modal.innerHTML,/&lt;b&gt;ancienne/);assert.doesNotMatch(modal.innerHTML,/<b>ancienne/);
 const before=calls.length;const result=await f.run('modalSubmit(new Map())');
 assert.deepEqual(calls.slice(before),[['/api/updates/copies/delete',JSON.stringify({id:copyId(2),confirm:true})]]);assert.equal(result.message,'Copie supprimée.');
});

// Relecture : journée synthétique de 24 h en UTC, deux plages et un moment détecté.
const dayStart=1794182400,playbackSample={camera:'entry',timezone:'UTC',day:'2026-11-08',today:'2026-11-09',start:dayStart,end:dayStart+86400,now:dayStart+2*86400,clip_max:300,
 days:[{day:'2026-11-09',recorded:600},{day:'2026-11-08',recorded:9000},{day:'2026-11-06',recorded:60}],
 hours:Array.from({length:24},(_,i)=>({start:dayStart+i*3600,end:dayStart+(i+1)*3600,label:String(i).padStart(2,'0')+':00',recorded:0,detected:0})),
 intervals:[[dayStart+3600,dayStart+3600+7200],[dayStart+18000,dayStart+19800]],detections:[[dayStart+4000,dayStart+4090]],recorded:9000,detected:90,segments:900};
function playbackFixture(fetch){const f=cameraFixture(fetch);f.context.sample=JSON.parse(JSON.stringify(playbackSample));return f;}
test('playback seeks inside ranges, skips gaps forward and stops after the last range',()=>{
 const f=playbackFixture(async()=>response(200,{}));
 assert.deepEqual(JSON.parse(f.run('JSON.stringify(playbackLocate(sample,sample.start+4000))')),{start:dayStart+4000,end:dayStart+4300,moved:false});
 assert.deepEqual(JSON.parse(f.run('JSON.stringify(playbackLocate(sample,sample.start))')),{start:dayStart+3600,end:dayStart+3900,moved:true});
 // Un extrait ne déborde pas de sa plage ; sa fin mène à la plage suivante.
 assert.deepEqual(JSON.parse(f.run('JSON.stringify(playbackLocate(sample,sample.start+10700))')),{start:dayStart+10700,end:dayStart+10800,moved:false});
 assert.deepEqual(JSON.parse(f.run('JSON.stringify(playbackLocate(sample,sample.start+10800))')),{start:dayStart+18000,end:dayStart+18300,moved:true});
 assert.equal(f.run('playbackLocate(sample,sample.start+19800)'),null);
 assert.deepEqual(JSON.parse(f.run('JSON.stringify(playbackBefore(sample,sample.start+18000))')),{start:dayStart+10500,end:dayStart+10800,moved:false});
 assert.deepEqual(JSON.parse(f.run('JSON.stringify(playbackBefore(sample,sample.start+3700))')),{start:dayStart+3600,end:dayStart+3700,moved:false});
 assert.equal(f.run('playbackBefore(sample,sample.start+3600)'),null);
});
test('typed time follows the civil hours sent by the NAS, including clock changes',()=>{
 const f=playbackFixture(async()=>response(200,{}));
 assert.equal(f.run('playbackInstant(sample,"01:06:40")'),dayStart+4000);
 assert.equal(f.run('playbackInstant(sample,"23:59")'),dayStart+86340);
 for(const bad of ['','24:00','1:00','aa:bb'])assert.equal(f.run(`playbackInstant(sample,${JSON.stringify(bad)})`),null);
 // Passage à l’heure d’été : 02:00 n’existe pas ; retour à l’heure d’hiver : la première occurrence est retenue.
 f.run('sample.hours=[["00:00",0],["01:00",3600],["03:00",7200]].map(([label,offset])=>({label,start:sample.start+offset,end:sample.start+offset+3600}))');
 assert.equal(f.run('playbackInstant(sample,"02:30")'),null);assert.equal(f.run('playbackInstant(sample,"03:30")'),dayStart+9000);
 f.run('sample.hours=[["01:00",3600],["02:00",7200],["02:00",10800]].map(([label,offset])=>({label,start:sample.start+offset,end:sample.start+offset+3600}))');
 assert.equal(f.run('playbackInstant(sample,"02:15")'),dayStart+8100);
});
test('playback card draws the day without inline styles and escapes received values',()=>{
 const f=playbackFixture(async()=>response(200,{}));
 let html=f.run('playbackData=sample;playbackCard(sample)');
 assert.doesNotMatch(html,/style=/);
 assert.equal((html.match(/<rect class="pb-rec"/g)||[]).length,2);assert.equal((html.match(/<rect class="pb-det"/g)||[]).length,1);
 assert.match(html,/<rect class="pb-rec" x="60\.0" y="0" width="120\.0"/);assert.doesNotMatch(html,/pb-future/);
 assert.match(html,/2 h 30 min<\/strong> enregistrées en 2 plages/);assert.match(html,/présence détectée pendant <strong>1 min 30 s/);
 assert.match(html,/Sans enregistrement : 03:00:00 → 05:00:00\./);assert.match(html,/Moments avec présence détectée/);
 assert.match(html,new RegExp(`data-start="${dayStart+3995}"`));assert.match(html,/id="playback-time" type="time" step="1" value="01:00:00"/);
 // Jour voisin enregistré : le 7 novembre, sans enregistrement, est ignoré par les flèches.
 assert.match(html,/data-day="2026-11-06" aria-label="Jour enregistré précédent" >/);assert.match(html,/data-day="2026-11-09" aria-label="Jour enregistré suivant" >/);
 assert.match(html,/dimanche 9 novembre|lundi 9 novembre/);assert.match(html,/\(aujourd’hui\)/);
 html=f.run('sample.detections=[];sample.detected=0;playbackCard(sample)');
 assert.match(html,/Plages enregistrées/);assert.doesNotMatch(html,/présence détectée pendant/);
 html=f.run('sample.intervals=[];sample.recorded=0;sample.day="2026-11-07";playbackCard(sample)');
 assert.match(html,/Aucun enregistrement conservé pour le/);assert.match(html,/value="2026-11-07" selected>[^<]*aucun enregistrement/);assert.doesNotMatch(html,/pb-track|playback-go/);
 html=f.run('sample.timezone="<img src=x>";sample.days=[{day:"2026-11-07\\" data-x=\\"1",recorded:5}];sample.day="2026-11-07";sample.hours[0].label="<b>";playbackCard(sample)');
 assert.doesNotMatch(html,/<img src=x>|data-x="1"|<b>/);
 assert.match(f.run('playbackCard(null)'),/temporairement indisponibles/);
});
test('today leaves the hours to come distinct from missing recordings',()=>{
 const f=playbackFixture(async()=>response(200,{}));
 const html=f.run('sample.now=sample.start+43200;sample.today=sample.day;playbackData=sample;playbackCard(sample)');
 assert.match(html,/<rect class="pb-future" x="720\.0" y="0" width="720\.0"/);assert.match(html,/À venir/);
});
test('camera detail loads the timeline once and keeps the chosen day across refreshes',async()=>{
 const calls=[],f=playbackFixture(async url=>{calls.push(url);return response(200,url==='/api/cameras'?cameraSamples:url.includes('/info')?{features:[]}:url.includes('/settings')?{days:3,enabled:true}:playbackSample);});
 f.run('selectedCamera="entry";cameraDetail=true;');await f.run('renderSurveillance()');
 assert.ok(calls.includes('/api/camera/timeline?camera=entry'));assert.ok(!calls.some(u=>u.includes('camera/recordings')||u.includes('camera/clip')));
 const html=f.elements.get('#content').innerHTML;assert.match(html,/id="playback"/);assert.match(html,/pb-track/);assert.doesNotMatch(html,/<video/);
 calls.length=0;await f.run('playbackLoad("2026-11-06")');
 assert.deepEqual(calls,['/api/camera/timeline?camera=entry&day=2026-11-06']);assert.equal(f.run('playbackDay'),'2026-11-06');
 calls.length=0;await f.run('renderSurveillance()');
 assert.ok(calls.includes('/api/camera/timeline?camera=entry&day=2026-11-06'));
});
test('unavailable or malformed timelines never invent recordings and a refused day is forgotten',async()=>{
 for(const [status,body] of [[200,[]],[200,{intervals:'x'}],[503,{error:'La vidéo est temporairement indisponible.'}]]){
  const f=playbackFixture(async url=>url==='/api/cameras'?response(200,cameraSamples):url.includes('/timeline')?response(status,body):response(200,url.includes('/info')?{features:[]}:{days:3,enabled:true}));
  f.run('selectedCamera="entry";cameraDetail=true;playbackDay="2026-11-06";');await f.run('renderSurveillance()');
  const html=f.elements.get('#content').innerHTML;assert.match(html,/Enregistrements temporairement indisponibles/);assert.doesNotMatch(html,/pb-track/);
  assert.equal(f.run('playbackData'),null);assert.equal(f.run('playbackDay'),'2026-11-06');
 }
 const f=playbackFixture(async url=>url==='/api/cameras'?response(200,cameraSamples):url.includes('/timeline')?response(400,{error:'Date hors de la période consultable.'}):response(200,url.includes('/info')?{features:[]}:{days:3,enabled:true}));
 f.run('selectedCamera="entry";cameraDetail=true;playbackDay="2001-01-01";');await f.run('renderSurveillance()');
 assert.equal(f.run('playbackDay'),'');
});
test('late timelines cannot replace the day after another choice, camera or page',async()=>{
 const complete=[],f=playbackFixture(()=>new Promise(resolve=>complete.push(resolve)));
 f.run('selectedCamera="entry";cameraDetail=true;playbackData=sample;');
 const old=f.run('playbackLoad("2026-11-06")'),fresh=f.run('playbackLoad("2026-11-09")');
 complete[1](response(200,{...playbackSample,day:'2026-11-09'}));await fresh;
 complete[0](response(200,{...playbackSample,day:'2026-11-06'}));await old;
 assert.equal(f.run('playbackDay'),'2026-11-09');assert.equal(f.run('playbackData.day'),'2026-11-09');
 for(const leave of ['selectedCamera="garage"','cameraDetail=false','page="files"']){
  f.run('selectedCamera="entry";cameraDetail=true;page="camera";');
  const pending=f.run('playbackLoad("2026-11-08")');f.run(leave);
  complete[complete.length-1](response(200,{...playbackSample,day:'2026-11-08'}));await pending;
  assert.equal(f.run('playbackData.day'),'2026-11-09',leave);
 }
});

// Événements : deux personnes, une voiture, un type inconnu hostile et un événement hors des plages conservées.
const eventSamples=[{id:'1794186400.5-aaaa11',label:'person',sub_label:null,start:dayStart+4000,end:dayStart+4013,ongoing:false,score:77},
 {id:'1794187000.5-bbbb22',label:'car',sub_label:'Voisin <b>',start:dayStart+4600,end:dayStart+4660,ongoing:false,score:null},
 {id:'1794190000.5-cccc33',label:'person',sub_label:null,start:dayStart+15000,end:dayStart+15020,ongoing:false,score:81},
 {id:'1794200500.5-dddd44',label:'"><img src=x>',sub_label:null,start:dayStart+18100,end:dayStart+86500,ongoing:true,score:60}];
function eventFixture(){const f=playbackFixture(async()=>response(200,{}));f.context.eventSamples=eventSamples;f.context.sample.events=JSON.parse(JSON.stringify(eventSamples));f.context.sample.events_more=false;return f;}
test('events become thumbnails with a type filter, without inline styles or unescaped values',()=>{
 const f=eventFixture();
 let html=f.run('playbackData=sample;playbackCard(sample)');
 assert.doesNotMatch(html,/style=|<img src=x>|<b> ·|Moments avec présence|Événements indisponibles/);
 assert.equal((html.match(/class="pb-event"/g)||[]).length,4);assert.equal((html.match(/class="pb-chip"/g)||[]).length,4);
 assert.match(html,/data-label="" aria-pressed="true">Tous<b>4<\/b>/);assert.match(html,/data-label="person" aria-pressed="false">Personne<b>2<\/b>.*data-label="car" aria-pressed="false">Voiture<b>1<\/b>/s);
 assert.match(html,/id="playback-count" role="status">4 événements</);
 assert.match(html,new RegExp(`data-label="person" data-start="${dayStart+3995}"><img class="pb-thumb" src="/api/camera/event-thumbnail\\?camera=entry&id=1794186400\\.5-aaaa11" alt="" loading="lazy"`));
 assert.match(html,/<strong>Personne<\/strong><span>01:06:40 · 13 s · 77 %<\/span><\/button>/);
 assert.match(html,/<strong>Voiture · Voisin &lt;b&gt;<\/strong><span>01:16:40 · 1 min<\/span>/);
 assert.match(html,/<strong>&quot;&gt;&lt;img src=x&gt;<\/strong><span>05:01:40 · en cours · 60 %<\/span>/);
 // L’événement de 04:10 tombe dans un trou : la vignette reste, la lecture est désactivée.
 assert.match(html,new RegExp(`data-start="${dayStart+14995}" disabled><img[^>]*><strong>Personne</strong><span>04:10:00 · 20 s · 81 %</span><em>Vidéo non conservée</em>`));
 assert.equal((html.match(/ disabled>/g)||[]).length,1);
 assert.equal((html.match(/<rect class="pb-evt" data-kind="mark"[^>]*visibility="hidden"/g)||[]).length,4);assert.match(html,/id="playback-mark-legend" hidden>/);
 html=f.run('playbackLabel="car";playbackCard(sample)');
 assert.equal((html.match(/class="pb-event"[^>]* hidden>/g)||[]).length,3);assert.match(html,/data-label="car" aria-pressed="true"/);assert.match(html,/data-label="" aria-pressed="false"/);
 assert.match(html,/<rect class="pb-evt" data-kind="mark" data-label="car" x="76\.7" y="0" width="5\.0" height="11" visibility="visible"/);
 assert.equal((html.match(/visibility="visible"/g)||[]).length,1);assert.match(html,/id="playback-count" role="status">1 sur 4 · Voiture</);assert.match(html,/id="playback-mark-legend"><i class="pb-evt"><\/i><span>Voiture</);
 // Un événement au tout début d’une plage part du début de la plage, pas du trou qui la précède.
 html=f.run('playbackLabel="";sample.events[3].start=sample.start+18002;playbackCard(sample)');
 assert.match(html,new RegExp(`data-start="${dayStart+18000}"><img[^>]*id=1794200500`));
 html=f.run('sample.detections=[[sample.start+3601,sample.start+3620]];sample.events=[];playbackCard(sample)');assert.match(html,new RegExp(`data-action="playback-moment" data-start="${dayStart+3600}"`));
 f.run('sample.events=JSON.parse(JSON.stringify(eventSamples));');
 // Un type absent ce jour-là ne masque rien ; le choix est gardé pour les autres jours.
 html=f.run('playbackLabel="dog";playbackCard(sample)');
 assert.doesNotMatch(html,/class="pb-event"[^>]* hidden>/);assert.match(html,/data-label="" aria-pressed="true"/);assert.equal(f.run('playbackLabel'),'dog');
 for(const hostile of ['constructor','__proto__','toString']){html=f.run(`sample.events[0].label=${JSON.stringify(hostile)};playbackCard(sample)`);assert.match(html,new RegExp(`<strong>${hostile}</strong>`));}
});
test('a single type needs no filter, and days without events keep the detected moments',()=>{
 const f=eventFixture();
 let html=f.run('sample.events=sample.events.filter(e=>e.label==="person");sample.events_more=true;playbackData=sample;playbackCard(sample)');
 assert.doesNotMatch(html,/pb-chip|pb-filter/);assert.match(html,/2 événements · Personne/);assert.match(html,/Seuls les 2 premiers événements de la journée sont affichés/);
 html=f.run('sample.events=[];playbackCard(sample)');
 assert.match(html,/Moments avec présence détectée/);assert.doesNotMatch(html,/pb-events|Événements indisponibles|pb-evt" data-kind/);
 for(const missing of ['null','undefined','"x"','{}']){html=f.run(`sample.events=${missing};playbackCard(sample)`);assert.match(html,/Événements indisponibles/);assert.match(html,/Moments avec présence détectée/);assert.doesNotMatch(html,/pb-events/);}
});
test('filter updates the open card in place and an event thumbnail starts playback',async()=>{
 const f=eventFixture(),player={innerHTML:'',scrolled:0,scrollIntoView(){this.scrolled++;}},count={textContent:''},legend={hidden:true,lastChild:{textContent:''}};
 f.elements.set('#playback-player',player);f.elements.set('#playback-count',count);f.elements.set('#playback-mark-legend',legend);
 const node=(kind,label)=>({dataset:{kind,label},hidden:false,attrs:{},setAttribute(k,v){this.attrs[k]=v;}});
 const nodes=[node('chip',''),node('chip','car'),node('event','person'),node('event','car'),node('mark','person'),node('mark','car')];
 f.context.document.querySelectorAll=selector=>{assert.equal(selector,'#playback [data-kind]');return nodes;};
 f.run('playbackData=sample;');
 const click=async dataset=>{const el={dataset,disabled:false};for(const fn of f.listeners.get('click'))await fn({target:{closest:s=>s.includes('playback-')?el:null},preventDefault(){}});};
 await click({action:'playback-filter',label:'car'});
 assert.deepEqual(nodes.map(n=>n.dataset.kind==='event'?n.hidden:n.attrs['aria-pressed']||n.attrs.visibility),['false','true',true,false,'hidden','visible']);
 assert.equal(count.textContent,'1 sur 4 · Voiture');assert.equal(legend.hidden,false);assert.equal(legend.lastChild.textContent,'Voiture');assert.equal(player.innerHTML,'');
 await click({action:'playback-filter',label:''});
 assert.deepEqual(nodes.map(n=>n.dataset.kind==='event'?n.hidden:n.attrs['aria-pressed']||n.attrs.visibility),['true','false',false,false,'hidden','hidden']);
 assert.equal(count.textContent,'4 événements');assert.equal(legend.hidden,true);
 await click({action:'playback-event',start:String(dayStart+3995)});
 assert.match(player.innerHTML,new RegExp(`/api/camera/clip\\?camera=entry&start=${dayStart+3995}&end=${dayStart+4295}"`));assert.equal(player.scrolled,1);
 // Une vignette que le service ne fournit plus laisse la carte lisible.
 const classes=[],img={id:'',hidden:false,classList:{contains:c=>c==='pb-thumb'},parentElement:{classList:{add:c=>classes.push(c)}}};
 for(const fn of f.listeners.get('error'))fn({target:img});
 assert.equal(img.hidden,true);assert.deepEqual(classes,['pb-nothumb']);assert.match(player.innerHTML,/<video/);
});

const detectionSample={enabled:true,tracked:['person','car'],groups:[{id:'people',name:'Personnes',labels:['person']},{id:'vehicles',name:'Véhicules',labels:['car','bicycle']},{id:'others',name:'Autres types déjà suivis',labels:['<b>x</b>']}]};
test('detection card shows the applied state without inline styles or unescaped values',()=>{
 const f=cameraFixture(async()=>response(200,{}));f.context.d=JSON.parse(JSON.stringify(detectionSample));f.context.d.tracked.push('<b>x</b>');
 let html=f.run('detectionCard(detectionValid(d))');
 assert.match(html,/id="detection"/);assert.match(html,/<span class="badge ">Active<\/span>/);
 assert.match(html,/<span class="dt-type">Personne<\/span><span class="dt-type">Voiture<\/span><span class="dt-type">&lt;b&gt;x&lt;\/b&gt;<\/span>/);
 assert.match(html,/data-action="detection-edit"/);assert.doesNotMatch(html,/style=|<b>x/);assert.doesNotMatch(html,/en pause/i);
 f.run('d.enabled=false;user.role="viewer";');html=f.run('detectionCard(detectionValid(d))');
 assert.match(html,/<span class="badge dim">En pause<\/span>/);assert.match(html,/aucun événement n’est créé/);assert.doesNotMatch(html,/detection-edit/);
 for(const bad of ['null','[]','{enabled:"yes",tracked:[],groups:[]}','{enabled:true,tracked:"person",groups:[]}','{enabled:true,tracked:[7],groups:[]}','{enabled:true,tracked:[],groups:[{name:"x",labels:"y"}]}']){
  assert.equal(f.run(`detectionValid(${bad})`),null,bad);
 }
 html=f.run('detectionCard(null)');assert.match(html,/Indisponible/);assert.doesNotMatch(html,/detection-edit|dt-type/);
});
test('camera detail asks for detection once and survives its absence',async()=>{
 const calls=[],answer=detection=>async url=>{calls.push(url);if(url.includes('/detection'))return detection;
  return response(200,url==='/api/cameras'?cameraSamples:url.includes('/info')?{features:[]}:url.includes('/settings')?{days:3,enabled:true}:playbackSample);};
 let f=playbackFixture(answer(response(200,detectionSample)));
 f.run('selectedCamera="entry";cameraDetail=true;');await f.run('renderSurveillance()');
 assert.equal(calls.filter(u=>u==='/api/camera/detection?camera=entry').length,1);
 let html=f.elements.get('#content').innerHTML;assert.match(html,/<span class="dt-type">Voiture<\/span>/);assert.ok(html.indexOf('id="detection"')<html.indexOf('id="playback"'));
 for(const detection of [response(503,{error:'Détection indisponible.'}),response(200,{enabled:true})]){
  f=playbackFixture(answer(detection));f.run('selectedCamera="entry";cameraDetail=true;detectionData={enabled:true,tracked:["person"],groups:[]};');await f.run('renderSurveillance()');
  html=f.elements.get('#content').innerHTML;assert.match(html,/id="detection"[^]*Indisponible/);assert.match(html,/pb-track/);assert.equal(f.run('detectionData'),null);
 }
});
test('detection form proposes the offered types and posts the choice for the open camera',async()=>{
 const posts=[],f=cameraFixture(async(url,options)=>{posts.push([url,options?.body]);return response(200,{message:'Détection mise à jour.'});});
 f.context.captured=null;f.context.cameraSamples=cameraSamples;f.context.d=JSON.parse(JSON.stringify(detectionSample));
 f.run('modal=(title,content,label,submit)=>{captured={title,content,label,submit};};selectedCamera="entry";cameraDetail=true;cameraCatalog=cameraSamples;detectionData=detectionValid(d);');
 const click=async()=>{const el={dataset:{action:'detection-edit'}};for(const fn of f.listeners.get('click'))await fn({target:{closest:s=>s.includes('detection-edit')?el:null},preventDefault(){}});};
 await click();const shown=f.run('captured');
 assert.equal(shown.title,'Détection · Entrée');assert.equal(shown.label,'Appliquer');
 assert.match(shown.content,/name="enabled" checked/);assert.match(shown.content,/<legend>Véhicules<\/legend>/);
 assert.match(shown.content,/value="car" checked>Voiture/);assert.match(shown.content,/value="bicycle" >Vélo/);assert.match(shown.content,/value="&lt;b&gt;x&lt;\/b&gt;"/);
 assert.match(shown.content,/sans redémarrer le service vidéo/);assert.doesNotMatch(shown.content,/style=|<b>x/);
 const form={has:name=>name==='enabled',getAll:name=>name==='track'?['person','bicycle']:[]};
 const result=await shown.submit(form);assert.equal(result.message,'Détection mise à jour.');
 const [url,body]=posts.at(-1);assert.equal(url,'/api/camera/detection');assert.deepEqual(JSON.parse(body),{camera:'entry',enabled:true,track:['person','bicycle']});
 // Un lecteur, une autre page ou un état indisponible n’ouvrent rien.
 for(const setup of ['user.role="viewer"','user.role="admin";page="home"','page="camera";detectionData=null']){f.run('captured=null;'+setup);await click();assert.equal(f.run('captured'),null,setup);}
});

// Recherche sur plusieurs jours : trois résultats sur deux jours, un type hostile, une vidéo non conservée.
const searchSample={camera:'entry',timezone:'UTC',from:'2026-11-03',to:'2026-11-09',today:'2026-11-09',label:'',next:dayStart+100,
 events:[{id:'1794200500.5-dddd44',label:'car',sub_label:'Voisin <b>',start:dayStart+18100,end:dayStart+18130,ongoing:false,score:60,day:'2026-11-08',recorded:true},
  {id:'1794186400.5-aaaa11',label:'person',sub_label:null,start:dayStart+4000,end:dayStart+4013,ongoing:false,score:77,day:'2026-11-08',recorded:true},
  {id:'1794000000.5-cccc33',label:'"><img src=x>',sub_label:null,start:dayStart-180000,end:dayStart-179990,ongoing:false,score:null,day:'2026-11-05',recorded:false}],
 facets:{total:9,matched:9,more:false,types:[{label:'person',count:6},{label:'car',count:2},{label:'"><img src=x>',count:1}],days:[{day:'2026-11-08',count:7},{day:'2026-11-05',count:2}]}};
function searchFixture(fetch){const f=playbackFixture(fetch);f.context.found=JSON.parse(JSON.stringify(searchSample));f.run('selectedCamera="entry";cameraDetail=true;');return f;}
test('search card proposes the last seven days and draws results by day without inline styles',()=>{
 const f=searchFixture(async()=>response(200,{}));
 f.run('playbackData=sample;');let html=f.run('searchCard()');
 assert.match(html,/id="search-from" type="date" value="2026-11-03" max="2026-11-09"/);assert.match(html,/id="search-to" type="date" value="2026-11-09" max="2026-11-09"/);
 assert.match(html,/Choisissez une période/);assert.doesNotMatch(html,/pb-event/);
 html=f.run('searchData=found;searchCard()');
 assert.doesNotMatch(html,/style=/);assert.doesNotMatch(html,/<img src=x>|Voisin <b>/);
 assert.match(html,/9 événements, du mardi 3 novembre au lundi 9 novembre/);
 assert.equal(html.match(/class="sr-day"/g).length,2);assert.match(html,/dimanche 8 novembre · 7 événements/);assert.match(html,/jeudi 5 novembre · 2 événements/);
 assert.equal(html.match(/data-action="search-filter"/g).length,4);assert.match(html,/data-label="" aria-pressed="true">Tous<b>9<\/b>/);assert.match(html,/Personne<b>6<\/b>/);
 assert.match(html,new RegExp(`data-action="search-open" data-day="2026-11-08" data-start="${dayStart+18100}" data-end="${dayStart+18130}"><img class="pb-thumb" src="/api/camera/event-thumbnail\\?camera=entry&id=1794200500.5-dddd44"`));
 assert.match(html,/data-day="2026-11-05"[^>]* disabled>.*Vidéo non conservée/);assert.match(html,/data-action="search-more"/);
 // Un type choisi, une seule journée, plus rien à suivre.
 html=f.run('found.label="car";found.from=found.to="2026-11-08";found.facets.matched=2;found.next=null;found.events.length=1;searchCard()');
 assert.match(html,/2 sur 9 événements · Voiture, le dimanche 8 novembre/);assert.match(html,/data-label="car" aria-pressed="true"/);assert.doesNotMatch(html,/data-action="search-more"/);
 // Les résultats d’une autre caméra ne sont jamais réaffichés ; une réponse malformée est refusée.
 html=f.run('selectedCamera="garage";searchCard()');assert.doesNotMatch(html,/pb-event/);assert.equal(f.run('searchData'),null);
 for(const bad of ['null','{...found,events:"x"}','{...found,from:"hier"}','{...found,next:"x"}','{...found,events:[{id:"a",label:"car",day:"x",start:1,end:2}]}','{...found,facets:{total:1}}'])assert.equal(f.run(`searchValid(${bad})`),null,bad);
});
test('search requests the period, type and following page, and ignores late or malformed replies',async()=>{
 const calls=[],complete=[],f=searchFixture(url=>{calls.push(url);return new Promise(resolve=>complete.push(resolve));});
 const box={innerHTML:''},list={added:[],insertAdjacentHTML(where,html){this.added.push([where,html]);}},more={innerHTML:'x'},card={attrs:{},setAttribute(k,v){this.attrs[k]=v;},removeAttribute(k){delete this.attrs[k];}};
 for(const [key,value] of [['#search-results',box],['#search-events',list],['#search-more',more],['#search',card]])f.elements.set(key,value);
 let pending=f.run('searchLoad("2026-11-03","2026-11-09","")');
 assert.deepEqual(calls,['/api/camera/search?camera=entry&from=2026-11-03&to=2026-11-09']);assert.equal(card.attrs['aria-busy'],'true');
 complete[0](response(200,searchSample));await pending;
 assert.match(box.innerHTML,/9 événements/);assert.equal(f.run('searchData.events.length'),3);assert.equal(card.attrs['aria-busy'],undefined);
 // Page suivante : ajoutée en fin de liste, sans titre répété pour le jour déjà entamé.
 const next={...searchSample,facets:null,next:null,events:[{...searchSample.events[2],id:'1794000001.5-eeee55',start:dayStart-180100,end:dayStart-180090,recorded:true}]};
 pending=f.run('searchLoad(searchData.from,searchData.to,searchData.label,searchData.next)');
 assert.equal(calls[1],`/api/camera/search?camera=entry&from=2026-11-03&to=2026-11-09&before=${dayStart+100}`);
 complete[1](response(200,next));await pending;
 assert.equal(f.run('searchData.events.length'),4);assert.equal(f.run('searchData.next'),null);assert.equal(more.innerHTML,'');
 assert.equal(list.added.length,1);assert.equal(list.added[0][0],'beforeend');assert.doesNotMatch(list.added[0][1],/sr-day|<img src=x>/);assert.match(list.added[0][1],/eeee55/);
 // Type choisi puis réponses croisées : seule la dernière demande s’affiche.
 const old=f.run('searchLoad("2026-11-03","2026-11-09","car")'),fresh=f.run('searchLoad("2026-11-03","2026-11-09","person")');
 assert.match(calls[2],/&label=car$/);assert.match(calls[3],/&label=person$/);
 complete[3](response(200,{...searchSample,label:'person'}));await fresh;complete[2](response(200,{...searchSample,label:'car'}));await old;
 assert.equal(f.run('searchData.label'),'person');
 for(const leave of ['selectedCamera="garage"','cameraDetail=false','page="files"','sessionGeneration++']){
  f.run('selectedCamera="entry";cameraDetail=true;page="camera";');box.innerHTML='intact';
  const late=f.run('searchLoad("2026-11-01","2026-11-02","")');f.run(leave);
  complete[complete.length-1](response(200,{...searchSample,from:'2026-11-01'}));await late.catch(error=>assert.equal(error.name,'AbortError'));
  assert.equal(box.innerHTML,'intact',leave);assert.equal(f.run('searchData.from'),'2026-11-03',leave);
 }
 f.run('selectedCamera="entry";cameraDetail=true;page="camera";');
 for(const body of [{...searchSample,facets:null},{events:'x'}]){
  const bad=f.run('searchLoad("2026-11-03","2026-11-09","")');complete[complete.length-1](response(200,body));
  await assert.rejects(bad,/Réponse de recherche illisible/);assert.equal(box.innerHTML,'intact');assert.equal(card.attrs['aria-busy'],undefined);
 }
});
test('a search result opens its day in the playback card, and says when the video is gone',async()=>{
 const calls=[],f=searchFixture(async url=>{calls.push(url);return response(200,{...playbackSample,day:'2026-11-08'});});
 const player={innerHTML:'',scrolled:0,scrollIntoView(){this.scrolled++;}},toasts=[];
 f.elements.set('#playback-player',player);f.elements.set('#playback',{setAttribute(){},removeAttribute(){},set outerHTML(v){}});
 f.elements.set('#search-from',{value:'2026-11-09'});f.elements.set('#search-to',{value:'2026-11-03'});
 f.run('playbackData={...sample,day:"2026-11-09"};searchData=found;');f.context.toast=(text,bad)=>toasts.push([text,!!bad]);
 const click=async dataset=>{const el={dataset,disabled:false};for(const fn of f.listeners.get('click'))await fn({target:{closest:s=>s.includes('search-')?el:null},preventDefault(){}});};
 await click({action:'search-open',day:'2026-11-08',start:String(dayStart+4000),end:String(dayStart+4013)});
 assert.deepEqual(calls,['/api/camera/timeline?camera=entry&day=2026-11-08']);assert.equal(f.run('playbackDay'),'2026-11-08');
 assert.match(player.innerHTML,new RegExp(`/api/camera/clip\\?camera=entry&start=${dayStart+3995}&end=${dayStart+4295}"`));assert.equal(player.scrolled,1);
 // Même jour déjà ouvert : aucune nouvelle requête ; hors des plages conservées : message, pas de lecture.
 await click({action:'search-open',day:'2026-11-08',start:String(dayStart+50000),end:String(dayStart+50010)});
 assert.equal(calls.length,1);assert.doesNotMatch(player.innerHTML,/<video/);assert.match(player.innerHTML,/n’est plus conservée/);assert.equal(player.scrolled,2);
 // Période à l’envers : refus local, sans requête.
 await click({action:'search-run'});
 assert.equal(calls.length,1);assert.deepEqual(toasts,[['Le début de la période suit sa fin.',true]]);
 f.elements.get('#search-from').value='2026-11-03';f.elements.get('#search-to').value='2026-11-09';f.run('found.label="car"');
 await click({action:'search-run'});await click({action:'search-filter',label:''});
 assert.deepEqual(calls.slice(1),['/api/camera/search?camera=entry&from=2026-11-03&to=2026-11-09&label=car','/api/camera/search?camera=entry&from=2026-11-03&to=2026-11-09']);
});
test('camera detail shows the search card without searching, and keeps results across refreshes',async()=>{
 const calls=[],f=searchFixture(async url=>{calls.push(url);return response(200,url==='/api/cameras'?cameraSamples:url.includes('/info')?{features:[]}:url.includes('/settings')?{days:3,enabled:true}:url.includes('/detection')?detectionSample:playbackSample);});
 await f.run('renderSurveillance()');
 let html=f.elements.get('#content').innerHTML;assert.match(html,/id="search"/);assert.match(html,/Recherche d’événements/);assert.ok(!calls.some(u=>u.includes('camera/search')));
 assert.ok(html.indexOf('id="playback"')<html.indexOf('id="search"'));
 f.run('searchData=found;');await f.run('renderSurveillance()');
 html=f.elements.get('#content').innerHTML;assert.match(html,/dimanche 8 novembre · 7 événements/);assert.ok(!calls.some(u=>u.includes('camera/search')));
});

// Application Surveillance du bureau : mur, événements de toutes les caméras, relecture à frise commune, réglages.
const survCameras=[...cameraSamples.slice(0,3),{id:'yard',name:'Cour <b>nord</b>',enabled:true,status:'receiving',online:true,fps:5,observed_at:1700000000,days:2}];
function survFixture(fetch,role='admin'){
 const f=deskFixture(fetch,role);
 for(const name of ['components.js','playback.js','detection.js','search.js','palette.js','surveillance.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static',name),'utf8'),f.context);
 f.run('shell();page="camera";deskSync();played=[];playbackPlay=t=>{played.push(["play",t]);};playbackOpen=async(day,start,end)=>{played.push(["open",day,start,end]);};');
 f.content=()=>String(f.elements.get('#content').innerHTML);f.act=(action,data={},extra={})=>f.listeners.get('click').at(-1)({target:{closest:()=>({dataset:{action,...data},...extra})},clientX:extra.x??0});return f;
}
const survReply=calls=>async url=>{calls.push(url);
 if(url==='/api/cameras')return response(200,survCameras);
 if(url.startsWith('/api/camera/search'))return url.includes('camera=garage')?response(500,{error:'Indisponible.'}):response(200,url.includes('camera=entry')?searchSample:{...searchSample,camera:'x',events:[],facets:undefined});
 if(url.startsWith('/api/camera/timeline'))return response(200,{...playbackSample,camera:new URL('http://x'+url).searchParams.get('camera')});
 if(url.startsWith('/api/camera/detection'))return response(200,detectionSample);
 if(url.startsWith('/api/camera/settings'))return response(200,{days:3});
 if(url.startsWith('/api/camera/info'))return response(200,{features:['pt'],presets:[]});
 return response(200,overviewSample);};
test('surveillance opens on a wall of still images in the desktop and keeps its page in the classic display',async()=>{
 const calls=[],f=survFixture(survReply(calls));
 await f.run('renderCamera()');let html=f.content();
 assert.deepEqual(calls,['/api/cameras']);assert.equal((html.match(/class="card sv-tile"/g)||[]).length,4);
 assert.deepEqual([...html.matchAll(/<img class="sv-still" src="\/api\/camera\/snapshot\?camera=(\w+)&t=\d+" data-camera="(\w+)"/g)].map(m=>m[1]),['entry','yard']);
 assert.doesNotMatch(html,/camera\/live|<b>nord|style=/);assert.match(html,/Cour &lt;b&gt;nord/);assert.match(html,/2 sur 4 reçues/);assert.match(html,/data-action="camera-add"/);
 assert.deepEqual([f.run('cameraDetail'),f.run('survFocus'),f.run('survView()')],[false,false,'wall']);
 f.store['nacre-shell']='classic';await f.run('renderCamera()');assert.match(f.content(),/Votre surveillance, d’un regard/);assert.doesNotMatch(f.content(),/sv-tile/);
 // Aucune caméra : même accueil que l'affichage classique ; lecture seule : pas d'ajout.
 const g=survFixture(async()=>response(200,[]),'viewer');await g.run('renderCamera()');assert.match(g.content(),/Votre surveillance commence ici/);assert.doesNotMatch(g.content(),/camera-add/);
});
test('enlarging a camera opens its live view alone, and unknown cameras or late answers change nothing',async()=>{
 const calls=[],f=survFixture(survReply(calls));await f.run('renderCamera()');
 await f.act('surv-focus',{camera:'nowhere'});assert.equal(f.run('survFocus'),false);
 await f.act('surv-focus',{camera:'entry'});const html=f.content();
 assert.deepEqual(calls.slice(-3).sort(),['/api/camera/info?camera=entry','/api/camera/settings?camera=entry','/api/cameras']);
 assert.equal((html.match(/src="\/api\/camera\/live\?camera=entry"/g)||[]).length,1);assert.match(html,/class="ptz-pad"/);assert.match(html,/data-action="surv-wall"/);
 assert.deepEqual([...html.matchAll(/class="sv-still"[^>]*data-camera="(\w+)"/g)].map(m=>m[1]),['yard']);assert.equal((html.match(/class="card sv-tile"/g)||[]).length,3);
 assert.deepEqual([f.run('cameraDetail'),f.run('selectedCamera')],[true,'entry']);
 await f.act('surv-wall');assert.doesNotMatch(f.content(),/camera\/live/);assert.equal(f.run('cameraDetail'),false);
 // Réponse arrivée après un changement d'onglet : le mur agrandi n'est pas dessiné.
 const waiting=[],release=()=>waiting.splice(0).forEach(done=>done(response(200,{features:[]})));const g=survFixture(url=>url==='/api/cameras'?Promise.resolve(response(200,survCameras)):new Promise(resolve=>{waiting.push(resolve);}));
 g.run('selectedCamera="entry";survFocus=true;');const pending=g.run('renderCamera()');await new Promise(resolve=>setImmediate(resolve));g.run('deskSetView("cam","events");$("#content").innerHTML="autre vue";');release();await pending;
 assert.equal(g.content(),'autre vue');
});
test('events of every camera merge newest first, filter in place and open the replay at the event',async()=>{
 const calls=[],f=survFixture(survReply(calls));f.run('deskSetView("cam","events");');await f.run('renderCamera()');
 assert.deepEqual(calls.filter(u=>u.startsWith('/api/camera/search')).sort(),['entry','garage','pause','yard'].map(id=>'/api/camera/search?camera='+id));
 assert.deepEqual(JSON.parse(JSON.stringify(f.run('survEvents.items.map(e=>[e.camera,e.start])'))),searchSample.events.map(e=>['entry',e.start]).sort((a,b)=>b[1]-a[1]));
 assert.deepEqual(JSON.parse(JSON.stringify(f.run('survEvents.failed'))),['Garage']);
 let html=f.run('survEventsHtml()');
 assert.match(html,/Événements indisponibles pour Garage/);assert.doesNotMatch(html,/<img src=x>|Voisin <b>|style=/);assert.match(html,/Voisin &lt;b&gt;/);
 const total=searchSample.events.length;assert.equal((html.match(/data-action="surv-open"/g)||[]).length,total);assert.equal((html.match(/ disabled>/g)||[]).length,searchSample.events.filter(e=>e.recorded===false).length);assert.match(html,new RegExp(`data-kind="camera" data-value="entry" aria-pressed="false">Entrée<b>${total}</b>`));
 assert.match(html,/event-thumbnail\?camera=entry&id=1794186400\.5-aaaa11/);
 const before=calls.length;f.elements.set('#surv-events',{innerHTML:''});
 await f.act('surv-filter',{kind:'label',value:'person'});html=f.elements.get('#surv-events').innerHTML;
 assert.equal(calls.length,before);assert.equal((html.match(/data-action="surv-open"/g)||[]).length,searchSample.events.filter(e=>e.label==='person').length);assert.match(html,/data-value="person" aria-pressed="true"/);
 await f.act('surv-filter',{kind:'camera',value:'yard'});assert.match(f.elements.get('#surv-events').innerHTML,/Aucun événement pour ces filtres/);
 await f.act('surv-open',{camera:'nowhere',day:'2026-11-08',start:'1',end:'2'});assert.equal(f.run('survView()'),'events');
 await f.act('surv-open',{camera:'entry',day:'2026-11-08',start:String(dayStart+4000),end:String(dayStart+4013)});
 assert.deepEqual([f.run('survView()'),f.run('selectedCamera'),f.run('cameraDetail')],['replay','entry',true]);
 assert.ok(calls.includes('/api/camera/timeline?camera=entry&day=2026-11-08'));assert.deepEqual(JSON.parse(JSON.stringify(f.run('played'))),[['open','2026-11-08',dayStart+4000,dayStart+4013]]);
 assert.match(f.content(),/id="playback"/);assert.match(f.content(),/id="surv-rows"/);assert.match(f.content(),/id="camera-select"/);
});
test('replay draws one row per camera for the day and a click on a row plays that camera at that time',async()=>{
 const calls=[],f=survFixture(survReply(calls));f.run('deskSetView("cam","replay");selectedCamera="entry";');await f.run('renderCamera()');
 const rows={innerHTML:'',attrs:{},setAttribute(k,v){this.attrs[k]=v;},removeAttribute(k){delete this.attrs[k];}};f.elements.set('#surv-rows',rows);
 const before=calls.length;await f.run('survRows(cameraCatalog,"2026-11-08",()=>true)');
 assert.deepEqual(calls.slice(before).sort(),['entry','garage','pause','yard'].map(id=>`/api/camera/timeline?camera=${id}&day=2026-11-08`));
 assert.equal((rows.innerHTML.match(/class="sv-row /g)||[]).length,4);assert.equal((rows.innerHTML.match(/class="sv-row sel"/g)||[]).length,1);
 assert.match(rows.innerHTML,/data-action="surv-seek" data-camera="yard" data-day="2026-11-08" data-start="\d+" data-end="\d+"/);assert.doesNotMatch(rows.innerHTML,/<b>nord|style=/);
 assert.equal((rows.innerHTML.match(/<rect class="pb-rec"/g)||[]).length,4*playbackSample.intervals.length);assert.equal(rows.attrs['aria-busy'],undefined);
 assert.match(f.run('survRow({id:"x",name:"Sans <i>"},null)'),/Sans &lt;i&gt;<\/span><p class="muted">Enregistrements indisponibles/);
 const box={getBoundingClientRect:()=>({left:100,width:400})},data={day:'2026-11-08',start:String(dayStart),end:String(dayStart+86400)};
 await f.act('surv-seek',{camera:'entry',...data},{...box,x:200});assert.deepEqual(JSON.parse(JSON.stringify(f.run('played'))),[['play',dayStart+21600]]);
 await f.act('surv-seek',{camera:'yard',...data},{...box,x:9999});
 assert.deepEqual([f.run('selectedCamera'),JSON.parse(JSON.stringify(f.run('played.at(-1)')))],['yard',['play',dayStart+86400]]);
 const count=f.run('played.length');await f.act('surv-seek',{camera:'nowhere',...data},{...box,x:200});await f.act('surv-seek',{camera:'entry',...data},{getBoundingClientRect:()=>({left:0,width:0}),x:5});assert.equal(f.run('played.length'),count);
 // Un rendu remplacé entre-temps ne reçoit pas les lignes.
 rows.innerHTML='ancien';const late=f.run('survRows(cameraCatalog,"2026-11-08",()=>false)');await late;assert.equal(rows.innerHTML,'ancien');
});
test('settings gather detection, retention and connection for the chosen camera, without buttons for a reader',async()=>{
 const calls=[],f=survFixture(survReply(calls));f.run('deskSetView("cam","settings");selectedCamera="yard";');await f.run('renderCamera()');
 let html=f.content();
 assert.deepEqual(calls.slice(-2).sort(),['/api/camera/detection?camera=yard','/api/camera/settings?camera=yard']);
 assert.match(html,/id="camera-select"/);assert.match(html,/<option value="yard" selected>/);assert.match(html,/Conservation continue : <strong>3 jour\(s\)<\/strong>/);
 assert.match(html,/data-action="camera-settings"/);assert.match(html,/data-action="camera-edit"/);assert.doesNotMatch(html,/camera\/live|style=/);assert.equal(f.run('cameraDetail'),true);
 const g=survFixture(survReply([]),'viewer');g.run('deskSetView("cam","settings");');await g.run('renderCamera()');
 assert.doesNotMatch(g.content(),/camera-settings|camera-edit|camera-add/);assert.match(g.content(),/réservés aux administrateurs/);
 // La recherche globale ouvre une caméra agrandie sur le mur, et une vue par son nom.
 f.run('user.role="admin";');await f.run('runPalette({camera:"entry"})');assert.deepEqual([f.run('survView()'),f.run('survFocus'),f.run('selectedCamera')],['wall',true,'entry']);
 await f.run('runPalette({page:"camera",view:["cam","events"]})');assert.equal(f.run('survView()'),'events');
});
