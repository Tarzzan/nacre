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
 for(const name of ['components.js','playback.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static',name),'utf8'),f.context);
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
 assert.equal(calls.filter(u=>u.startsWith('/api/camera/')).length,3);
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
 for(let n=0;n<8&&!complete.length;n++)await Promise.resolve();assert.equal(complete.length,3);
 f.run('cameraDetail=false;');await f.run('renderSurveillance()');
 complete[0](response(200,{features:['pt']}));complete[1](response(200,[]));complete[2](response(200,{days:3}));await detail;
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
