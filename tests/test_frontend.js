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

test('native point retention shows one rule per volume and simulates it without ever deleting a point',async()=>{
 const calls=[];let refuse=0,hold=null;
 const state={connected:true,volumes:[{id:'documents',name:'Docs <b>',family:'btrfs',ready:true},{id:'photos',name:'Photos',family:'zfs',ready:true}],points:[],actions:[],jobs:[],resources:[],provisioning:{enabled:false,devices:[],deployments:[]}};
 const keep={connected:true,deletion:false,defaults:{keep_last:7,manual:false,calendar:{daily:0,weekly:0,monthly:0,timezone:'America/Cayenne'}},
  policies:[{volume:'documents',saved:false,keep_last:7,manual:false,calendar:{daily:0,weekly:0,monthly:0,timezone:'America/Cayenne'}},{volume:'photos',saved:true,keep_last:12,manual:true,calendar:{daily:7,weekly:4,monthly:1,timezone:'UTC'}}]};
 const preview={volume:'photos',name:'Photos <i>',rule:{},at:1794182400,deletion:false,busy:false,keep:[{id:'aaaaaaaa11111111',created:1794182400,manual:false,reasons:['Derniers points','Jour · 2026-11-10']}],
  remove:[{id:'bbbbbbbb22222222',created:1794096000,manual:true},null,{created:3}],protected:[{id:'cccccccc33333333',created:1794009600,manual:true,reason:'État <à vérifier>.'}]};
 const f=fixture(async(url,options)=>{
  const body=options?.body?JSON.parse(options.body):null;calls.push([url,body]);
  if(url.endsWith('/storage/native'))return response(200,state);
  if(url.endsWith('/storage/profiles'))return response(200,[]);
  if(url.endsWith('/storage/native-retention')&&!body)return response(200,keep);
  if(url.endsWith('/storage/native-schedule')&&!body)return response(200,{connected:true,schedules:[],defaults:null,confirmation:'PROGRAMMER '});
  if(hold)await hold;
  if(refuse)return response(refuse,{error:'Volume natif inconnu.'});
  return response(200,url.endsWith('-preview')?preview:{...body,saved:true});
 });
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/native.js'),'utf8'),f.context);
 f.run('user={name:"admin",role:"admin"};page="native";shell();');await f.run('renderNative()');
 const content=()=>String(f.elements.get('#content').innerHTML),posts=()=>calls.filter(c=>c[1]);
 const click=dataset=>f.listeners.get('click').at(-1)({target:{closest:s=>s==='[data-action]'?{dataset}:null}});
 // Une ligne par volume, avec sa règle en clair ; rien d'ouvert, et l'annonce qu'aucun point n'est supprimé.
 assert.match(content(),/<h2>Conservation des points natifs<\/h2><span class="muted">Simulation seulement · aucun point n’est supprimé<\/span>/);
 assert.match(content(),/Docs &lt;b&gt;<br><small class="muted">documents<\/small><\/td><td>7 derniers points · captures programmées seulement<br><small class="muted">Règle proposée, non enregistrée/);
 assert.match(content(),/12 derniers points \+ le dernier de 7 jours, 4 semaines, 1 mois · captures manuelles comprises<br><small class="muted">Règle enregistrée/);
 assert.doesNotMatch(content(),/native-keep-form|style=/);assert.equal(posts().length,0);
 // Ouvrir un volume montre sa règle dans un formulaire ; rouvrir le même le referme.
 await click({action:'native-keep-open',volume:'photos'});
 assert.match(content(),/data-volume="photos" aria-expanded="true"/);assert.match(content(),/<h3>Règle de « Photos »<\/h3>/);assert.match(content(),/id="native-keep-keep_last" name="keep_last" type="number" min="1" max="1000" step="1" value="12"/);
 assert.match(content(),/id="native-keep-manual" name="manual" checked>/);assert.match(content(),/name="timezone" value="UTC"/);assert.match(content(),/comptés dans le fuseau UTC/);
 await click({action:'native-keep-open',volume:'photos'});assert.doesNotMatch(content(),/native-keep-form/);
 await click({action:'native-keep-open',volume:'documents'});assert.match(content(),/Règle de « Docs &lt;b&gt; »/);assert.match(content(),/id="native-keep-manual" name="manual" >/);assert.match(content(),/fuseau America\/Cayenne/);
 // Simuler envoie la règle saisie, sans l'enregistrer, et montre les trois listes.
 const form={getAttribute:()=> 'native-keep-form',values:{keep_last:'3',daily:'2',weekly:'0',monthly:'1',manual:'on',timezone:'America/Cayenne'}},error={textContent:'ancien'},result={innerHTML:''};
 f.elements.set('#native-keep-form',form);f.elements.set('#native-keep-error',error);f.elements.set('#native-keep-result',result);
 const submit=()=>f.listeners.get('submit').at(-1)({target:form,preventDefault(){}});
 await submit();
 assert.deepEqual(posts().at(-1),['/api/storage/native-retention-preview',{volume:'documents',keep_last:3,manual:true,calendar:{daily:2,weekly:0,monthly:1,timezone:'America/Cayenne'}}]);assert.equal(error.textContent,'');
 assert.match(result.innerHTML,/SIMULATION · Photos &lt;i&gt;/);assert.match(result.innerHTML,/<strong>1<\/strong><span>Gardés par la règle<\/span>.*<strong>1<\/strong><span>Protégés hors règle<\/span>.*<strong>1<\/strong><span>Sortiraient<\/span>/);
 assert.match(result.innerHTML,/<h3>Points qui sortiraient<\/h3>.*<code>bbbbbbbb<\/code><\/td><td>Manuelle<\/td><\/tr>/);assert.match(result.innerHTML,/<code>aaaaaaaa<\/code><\/td><td>Programmée<\/td><td>Derniers points · Jour · 2026-11-10<\/td>/);
 assert.match(result.innerHTML,/État &lt;à vérifier&gt;\./);assert.match(result.innerHTML,/Rien n’est supprimé par la simulation\./);assert.match(result.innerHTML,/La suppression n’est pas accordée sur ce matériel\./);assert.doesNotMatch(result.innerHTML,/data-action="native-prune"/);assert.doesNotMatch(result.innerHTML,/restauration est en cours|style=/);
 preview.busy=true;await submit();assert.match(result.innerHTML,/Une restauration est en cours ou à vérifier sur ce volume : tous ses points sont protégés\./);preview.busy=false;
 // Retoucher la règle retire la simulation ; une saisie non entière ne part pas ; un refus du serveur s'affiche sous le formulaire.
 f.listeners.get('input').at(-1)({target:{id:'native-keep-daily'}});assert.equal(result.innerHTML,'');
 const sent=posts().length;form.values.daily='1.5';await submit();assert.equal(posts().length,sent);assert.equal(error.textContent,'Saisir des nombres entiers.');form.values.daily='2';
 refuse=404;await submit();assert.equal(error.textContent,'Volume natif inconnu.');assert.equal(result.innerHTML,'');refuse=0;
 // Une réponse arrivée après la fermeture du panneau n'est pas affichée.
 const panel={innerHTML:'ouvert'};f.elements.set('#native-keep-panel',panel);
 let release;hold=new Promise(resolve=>{release=resolve;});const late=submit();await click({action:'native-keep-close'});assert.equal(panel.innerHTML,'');release();await late;hold=null;assert.equal(result.innerHTML,'');assert.equal(f.run('nativeKeepResult'),null);
 // Enregistrer envoie la même règle à l'autre adresse, l'annonce, et recharge la page ; aucune demande de suppression n'existe.
 await click({action:'native-keep-open',volume:'documents'});f.elements.set('#native-keep-form',form);
 await click({action:'native-keep-save'});
 assert.deepEqual(posts().at(-1),['/api/storage/native-retention',{volume:'documents',keep_last:3,manual:true,calendar:{daily:2,weekly:0,monthly:1,timezone:'America/Cayenne'}}]);
 assert.match(f.elements.get('#toast').textContent,/Règle enregistrée\. Aucun point n’est supprimé\./);
 assert.deepEqual([...new Set(posts().map(c=>c[0]))].sort(),['/api/storage/native-retention','/api/storage/native-retention-preview']);
 // Tant que la règle est ouverte, l'actualisation périodique ne redessine pas la page.
 assert.equal(f.run('nativeEditing()'),true);f.elements.delete('#native-keep-form');assert.equal(f.run('nativeEditing()'),false);
 // Sans volume inscrit, la carte n'apparaît pas ; un compte en lecture seule ne demande rien.
 state.volumes=[];await f.run('renderNative()');assert.doesNotMatch(content(),/Conservation des points natifs/);assert.equal(f.run('nativeKeepOpen'),'');
 const before=calls.length;f.run('user={name:"lecteur",role:"viewer"};');await f.run('renderNative()');assert.equal(calls.length,before);assert.match(content(),/réservée aux administrateurs/);
});

test('points leaving a native simulation are deleted through a service plan and a typed phrase',async()=>{
 const calls=[];let refuse='',outcome=null,busy=false;
 const state={connected:true,deletion:true,volumes:[{id:'documents',name:'Docs <b>',family:'btrfs',ready:true}],points:[],jobs:[],resources:[],provisioning:{enabled:false,devices:[],deployments:[]},
  actions:[{id:'x',ts:1794096000,actor:'admin',action:'delete',volume:'documents',object:'nacre_bbbb',status:'done',location:''}]};
 const keep={connected:true,deletion:true,defaults:{keep_last:7,manual:false,calendar:{daily:0,weekly:0,monthly:0,timezone:'UTC'}},policies:[{volume:'documents',saved:true,keep_last:7,manual:false,calendar:{daily:0,weekly:0,monthly:0,timezone:'UTC'}}]};
 const points=count=>Array.from({length:count},(_,i)=>({id:String(i).padStart(8,'0')+'f'.repeat(24),created:1794009600+i,manual:i%2===1}));
 let leaving=points(2);
 const f=fixture(async(url,options)=>{
  const body=options?.body?JSON.parse(options.body):null;calls.push([url,body]);
  if(url.endsWith('/storage/native'))return response(200,state);
  if(url.endsWith('/storage/profiles'))return response(200,[]);
  if(url.endsWith('/storage/native-retention')&&!body)return response(200,keep);
  if(url.endsWith('/storage/native-schedule')&&!body)return response(200,{connected:true,schedules:[],defaults:null,confirmation:'PROGRAMMER '});
  if(url.endsWith('-preview'))return response(200,{volume:'documents',name:'Docs <b>',rule:{},at:1794182400,deletion:keep.deletion,busy,keep:[],remove:busy?[]:leaving,protected:[]});
  if(refuse)return response(409,{error:refuse});
  if(url.endsWith('/native-prune-prepare')){const batch=leaving.slice(0,50);return response(200,{id:'c'.repeat(32),volume:'documents',name:'Docs <b>',confirmation:`SUPPRIMER ${batch.length} POINT${batch.length>1?'S':''} DE documents`,points:batch,remaining:leaving.length-batch.length,notes:['Un point <supprimé> ne peut pas être récupéré.'],effect:'x'});}
  const done=outcome||{ok:true,deleted:leaving.slice(0,50).map(x=>x.id),uncertain:[],kept:[],reason:''};leaving=leaving.slice(done.deleted.length);
  return response(200,{volume:'documents',name:'Docs <b>',...done});
 });
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/native.js'),'utf8'),f.context);
 f.run('user={name:"admin",role:"admin"};page="native";shell();');await f.run('renderNative()');
 const content=()=>String(f.elements.get('#content').innerHTML),posts=()=>calls.filter(c=>c[1]);
 const click=dataset=>f.listeners.get('click').at(-1)({target:{closest:s=>s==='[data-action]'?{dataset}:null}});
 const rule={volume:'documents',keep_last:3,manual:false,calendar:{daily:0,weekly:0,monthly:0,timezone:'UTC'}};
 // Le matériel accorde la suppression : la carte l'annonce, et le journal des opérations nomme les suppressions.
 assert.match(content(),/<h2>Conservation des points natifs<\/h2><span class="muted">La suppression demande toujours une confirmation<\/span>/);assert.match(content(),/Suppression de point · documents/);
 await click({action:'native-keep-open',volume:'documents'});
 const form={getAttribute:()=> 'native-keep-form',values:{keep_last:'3',daily:'0',weekly:'0',monthly:'0',timezone:'UTC'}},error={textContent:''},result={innerHTML:''},refusal={textContent:'ancien'},send={disabled:false,className:'primary'};
 for(const [key,value] of [['#native-keep-form',form],['#native-keep-error',error],['#native-keep-result',result],['#native-prune-error',refusal],['#modal-form button[type=submit]',send]])f.elements.set(key,value);
 const simulate=()=>f.listeners.get('submit').at(-1)({target:form,preventDefault(){}});
 const typed=value=>f.listeners.get('input').forEach(listener=>listener({target:{id:'field-prune_confirmation',value}}));
 const confirm=value=>{f.context.sent=new Map([['prune_confirmation',value]]);return f.run('modalSubmit(sent)');};
 await simulate();
 // Sous les points sortants : un bouton discret qui annonce la fenêtre ; rien n'est demandé avant le clic.
 assert.match(result.innerHTML,/<h3>Points qui sortiraient<\/h3>.*<button type="button" class="danger" data-action="native-prune" ><span>Supprimer ces 2 points…<\/span><\/button><span class="muted">Une fenêtre demandera confirmation\.<\/span>/);
 assert.doesNotMatch(result.innerHTML,/pas accordée|style=/);assert.ok(!posts().some(c=>c[0].includes('prune')));
 // Le clic demande un plan pour la liste exacte affichée, puis montre les points un par un et la phrase à recopier.
 const modal=f.elements.get('#modal');let shown=0;modal.showModal=()=>shown++;modal.innerHTML='';
 await click({action:'native-prune'});
 assert.deepEqual(posts().at(-1),['/api/storage/native-prune-prepare',{...rule,expected:leaving.map(x=>x.id)}]);assert.equal(shown,1);assert.equal(refusal.textContent,'');
 assert.match(modal.innerHTML,/<h2>Supprimer 2 points de « Docs &lt;b&gt; »<\/h2>/);assert.match(modal.innerHTML,/Ces points, et eux seuls, seront supprimés du stockage/);
 assert.match(modal.innerHTML,/<code>00000000<\/code><\/td><td>Programmée<\/td><\/tr><tr><td>[^<]*<\/td><td><code>00000001<\/code><\/td><td>Manuelle<\/td>/);
 assert.match(modal.innerHTML,/Un point &lt;supprimé&gt; ne peut pas être récupéré\./);assert.match(modal.innerHTML,/Recopiez « SUPPRIMER 2 POINTS DE documents »<\/label><input id="field-prune_confirmation" name="prune_confirmation"/);
 assert.match(modal.innerHTML,/<button class="primary" type="submit">Supprimer définitivement<\/button>/);assert.doesNotMatch(modal.innerHTML,/style=/);
 // Le bouton rouge reste inactif tant que la phrase n'est pas recopiée à l'identique.
 assert.deepEqual([send.disabled,send.className],[true,'primary danger']);
 typed('SUPPRIMER 2 POINTS DE document');assert.equal(send.disabled,true);typed(' SUPPRIMER 2 POINTS DE documents ');assert.equal(send.disabled,false);
 // Validation : la phrase part telle quelle, la simulation est recalculée, le bilan s'affiche et la règle saisie reste dans le formulaire.
 let answer=await confirm(' SUPPRIMER 2 POINTS DE documents ');
 assert.deepEqual(posts().slice(-2),[['/api/storage/native-prune',{volume:'documents',plan:'c'.repeat(32),confirmation:'SUPPRIMER 2 POINTS DE documents'}],['/api/storage/native-retention-preview',rule]]);
 assert.equal(answer.message,'2 points supprimés de « Docs <b> ».');await f.run('renderNative()');
 assert.match(content(),/<div class="native-prune-note " role="status"><strong>2 points supprimés de « Docs &lt;b&gt; »\.<\/strong> Le volume, ses fichiers et les autres points n’ont pas été modifiés\.<\/div>/);
 assert.match(content(),/<h3>Aucun point ne sortirait<\/h3><details>/);assert.match(content(),/id="native-keep-keep_last" name="keep_last" type="number" min="1" max="1000" step="1" value="3"/);
 typed('SUPPRIMER 2 POINTS DE documents');assert.equal(send.disabled,false);
 // Arrêt en cours de liste : le bilan dit ce qui est fait, pourquoi, et que rien n'est retenté ; le reste peut être repris.
 leaving=points(3);await simulate();assert.doesNotMatch(result.innerHTML,/native-prune-note/);await click({action:'native-prune'});
 outcome={ok:false,deleted:[leaving[0].id],uncertain:[],kept:[leaving[2].id],reason:'Le système a refusé la suppression d’un point, qui reste intact.'};
 answer=await confirm('SUPPRIMER 3 POINTS DE documents');outcome=null;assert.equal(answer.message,'1 point supprimé sur 3. L’opération s’est arrêtée.');await f.run('renderNative()');
 assert.match(content(),/<div class="native-prune-note warn" role="status"><strong>1 point supprimé sur 3\. L’opération s’est arrêtée\.<\/strong> Le système a refusé la suppression d’un point, qui reste intact\. Rien n’est retenté automatiquement\.<\/div>/);
 assert.match(content(),/<span>Supprimer ces 2 points…<\/span>/);
 // Refus à la préparation : affiché sous le bouton, aucune fenêtre ; refus à la validation : il remonte à la fenêtre.
 refuse='Une restauration est en cours ou à vérifier sur ce volume : aucun point ne peut être supprimé.';await simulate();await click({action:'native-prune'});
 assert.equal(refusal.textContent,refuse+' Rien n’a été supprimé.');assert.equal(shown,2);
 refuse='';await click({action:'native-prune'});assert.equal(shown,3);refuse='Plan expiré, déjà exécuté ou appartenant à un autre compte.';
 await assert.rejects(confirm('SUPPRIMER 2 POINTS DE documents'),/Plan expiré/);refuse='';
 // Plus de cinquante points : les cinquante plus anciens, et ce qui reste est annoncé ; un seul point : libellés au singulier.
 leaving=points(120);await simulate();
 assert.match(result.innerHTML,/<span>Supprimer les 50 plus anciens…<\/span><\/button><span class="muted">120 points sortiraient ; une opération en supprime 50 au plus\.<\/span>/);
 await click({action:'native-prune'});assert.match(modal.innerHTML,/<h2>Supprimer 50 points de/);assert.equal(posts().at(-1)[1].expected.length,120);
 answer=await confirm('SUPPRIMER 50 POINTS DE documents');await f.run('renderNative()');
 assert.match(content(),/50 points supprimés de « Docs &lt;b&gt; »\.<\/strong> Le volume, ses fichiers et les autres points n’ont pas été modifiés\. 70 points sortiraient encore : relancer l’opération pour continuer\./);
 leaving=points(1);await simulate();assert.match(result.innerHTML,/<span>Supprimer ce point…<\/span>/);await click({action:'native-prune'});
 assert.match(modal.innerHTML,/<h2>Supprimer un point de « Docs &lt;b&gt; »<\/h2>/);assert.match(modal.innerHTML,/Ce point, et lui seul, sera supprimé du stockage\./);assert.match(modal.innerHTML,/SUPPRIMER 1 POINT DE documents/);
 // Restauration en cours : aucun point sortant, donc aucun bouton. Suppression non accordée : la raison à la place du bouton.
 busy=true;await simulate();assert.match(result.innerHTML,/tous ses points sont protégés/);assert.match(result.innerHTML,/<h3>Aucun point ne sortirait<\/h3>/);assert.doesNotMatch(result.innerHTML,/native-prune/);busy=false;
 keep.deletion=false;leaving=points(2);await f.run('renderNative()');assert.match(content(),/Simulation seulement · aucun point n’est supprimé/);
 f.elements.set('#native-keep-form',form);await simulate();
 assert.match(result.innerHTML,/<div class="native-prune-note info"><strong>La suppression n’est pas accordée sur ce matériel\.<\/strong>/);assert.doesNotMatch(result.innerHTML,/data-action="native-prune"/);
 // Fermer le panneau oublie le bilan et la règle en cours.
 await click({action:'native-keep-close'});assert.equal(f.run('JSON.stringify([nativeKeepDraft,nativePruneNote,nativeKeepResult])'),'[null,null,null]');
});

test('automatic native retention shows its state per volume and is enabled in a dialog with a maximum and a typed phrase',async()=>{
 const calls=[];let refuse='',stopped=false;
 const volume=(id,name)=>({id,name,family:'btrfs',ready:true}),rule=(volume,saved,auto)=>({volume,saved,keep_last:3,manual:true,calendar:{daily:2,weekly:0,monthly:0,timezone:'UTC'},auto});
 const state={connected:true,deletion:true,volumes:[volume('documents','Docs <b>'),volume('photos','Photos'),volume('films','Films'),volume('archives','Archives')],points:[],actions:[],jobs:[],resources:[],provisioning:{enabled:false,devices:[],deployments:[]}};
 const keep={connected:true,deletion:true,auto_phrase:'AUTOMATISER ',auto_floor:5,batch:50,defaults:{keep_last:7,manual:false,calendar:{daily:0,weekly:0,monthly:0,timezone:'UTC'}},policies:[
  rule('documents',true,{enabled:false,cap:5,reason:'',last:null,since:null,pending:3}),rule('photos',false,{enabled:false,cap:5,reason:'',last:null,since:null,pending:null}),
  rule('films',true,{enabled:true,cap:7,reason:'',last:{ts:1794096000,outcome:'done',detail:'1 point <supprimé>.',deleted:1},since:1,pending:0}),
  rule('archives',true,{enabled:false,cap:1,reason:'4 points sortiraient, plus que le maximum de 1 <par> passage.',last:{ts:1794096000,outcome:'suspended',detail:'x',deleted:0},since:1,pending:4})]};
 const f=fixture(async(url,options)=>{
  const body=options?.body?JSON.parse(options.body):null;calls.push([url,body]);
  if(url.endsWith('/storage/native'))return response(200,state);
  if(url.endsWith('/storage/profiles'))return response(200,[]);
  if(url.endsWith('/storage/native-retention')&&!body)return response(200,keep);
  if(url.endsWith('/storage/native-schedule')&&!body)return response(200,{connected:true,schedules:[],defaults:null,confirmation:'PROGRAMMER '});
  if(refuse)return response(400,{error:refuse});
  if(url.endsWith('/storage/native-retention'))return response(200,{...body,saved:true,auto:{enabled:false,cap:5,reason:'',last:null,pending:0},auto_stopped:stopped});
  return response(200,{volume:body.volume,enabled:body.enabled,cap:body.cap,reason:'',last:null,pending:0});
 });
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/native.js'),'utf8'),f.context);
 f.run('user={name:"admin",role:"admin"};page="native";shell();');await f.run('renderNative()');
 const content=()=>String(f.elements.get('#content').innerHTML),posts=()=>calls.filter(c=>c[1]),toast=()=>f.elements.get('#toast').textContent;
 const click=dataset=>f.listeners.get('click').at(-1)({target:{closest:s=>s==='[data-action]'?{dataset}:null}});
 const form=values=>{const map=new Map(Object.entries(values));map.getAll=name=>values[name]||[];return map;};
 // Sous chaque règle : rien si jamais activée, l'état et le dernier passage si activée, la raison si suspendue.
 assert.match(content(),/Règle enregistrée<\/small><\/td><td><button type="button" class="small" data-action="native-keep-open" data-volume="documents" aria-expanded="false"><span>Régler et simuler<\/span><\/button><button type="button" class="small" data-action="native-auto-edit" data-volume="documents"><span>Automatique…<\/span><\/button>/);
 assert.match(content(),/<br><small><span class="badge">Conservation automatique<\/span> au plus 7 points par passage · dernier passage le [^:<]*:\d\d : 1 point &lt;supprimé&gt;\.<\/small>/);
 assert.match(content(),/<br><small><span class="badge warn">Conservation automatique suspendue<\/span> 4 points sortiraient, plus que le maximum de 1 &lt;par&gt; passage\.<\/small>/);
 assert.equal(content().match(/data-action="native-auto-edit"/g).length,4);assert.doesNotMatch(content(),/style=/);
 // La fenêtre dit ce qui sera fait, ce que le prochain passage sortirait, et propose un maximum ; la phrase nomme le volume.
 const modal=f.elements.get('#modal');let shown=0;modal.showModal=()=>shown++;modal.innerHTML='';
 await click({action:'native-auto-edit',volume:'documents'});
 assert.equal(shown,1);assert.match(modal.innerHTML,/<h2>Conservation automatique de « Docs &lt;b&gt; »<\/h2>/);
 assert.match(modal.innerHTML,/<span>Règle enregistrée<\/span><b>3 derniers points \+ le dernier de 2 jours · captures programmées seulement<\/b>/);
 assert.match(modal.innerHTML,/<span>Au prochain passage<\/span><b>3 points programmés sortiraient<\/b>/);assert.match(modal.innerHTML,/Une capture manuelle n’est jamais supprimée automatiquement\./);
 assert.match(modal.innerHTML,/id="native-auto-cap" name="cap" type="number" min="1" max="50" step="1" value="8" required>/);assert.match(modal.innerHTML,/name="enabled" >Activer la conservation automatique/);
 assert.match(modal.innerHTML,/Pour activer, recopiez « AUTOMATISER documents »<\/label><input id="native-auto-confirmation" name="confirmation" autocomplete="off">/);assert.doesNotMatch(modal.innerHTML,/style=/);
 // Enregistrer envoie l'état, le maximum et la phrase saisie.
 f.context.sent=form({cap:'8',enabled:'on',confirmation:' AUTOMATISER documents '});let result=await f.run('modalSubmit(sent)');
 assert.deepEqual(posts().at(-1),['/api/storage/native-auto',{volume:'documents',enabled:true,cap:8,confirmation:'AUTOMATISER documents'}]);assert.match(result.message,/^Conservation automatique activée : elle s’appliquera après la prochaine capture programmée\.$/);
 f.context.sent=form({cap:'8'});result=await f.run('modalSubmit(sent)');assert.deepEqual(posts().at(-1)[1],{volume:'documents',enabled:false,cap:8,confirmation:''});assert.equal(result.message,'Conservation automatique désactivée. Aucun point n’est supprimé.');
 const count=posts().length;f.context.sent=form({cap:'2.5',enabled:'on'});await assert.rejects(f.run('modalSubmit(sent)'),/maximum entier/);assert.equal(posts().length,count);
 refuse='Recopier exactement « AUTOMATISER documents » pour activer.';f.context.sent=form({cap:'8',enabled:'on',confirmation:'non'});await assert.rejects(f.run('modalSubmit(sent)'),/Recopier exactement/);refuse='';
 // Le maximum proposé dépasse de cinq ce que la règle sortirait aujourd'hui, dans la limite d'une opération ; une conservation active garde le sien.
 keep.policies[0].auto.pending=12;await f.run('renderNative()');await click({action:'native-auto-edit',volume:'documents'});assert.match(modal.innerHTML,/name="cap" type="number" min="1" max="50" step="1" value="17"/);
 keep.policies[0].auto.pending=80;await f.run('renderNative()');await click({action:'native-auto-edit',volume:'documents'});assert.match(modal.innerHTML,/value="50" required/);
 await click({action:'native-auto-edit',volume:'films'});assert.match(modal.innerHTML,/value="7" required/);assert.match(modal.innerHTML,/name="enabled" checked>Activer/);assert.match(modal.innerHTML,/<b>aucun point ne sortirait<\/b>/);
 // Sans règle enregistrée, ou sans accord de suppression, rien ne s'ouvre et la raison est dite ; une conservation active reste désactivable.
 shown=0;await click({action:'native-auto-edit',volume:'photos'});assert.equal(shown,0);assert.equal(toast(),'Enregistrer d’abord la règle de conservation de ce volume.');
 await click({action:'native-auto-edit',volume:'inconnu'});assert.equal(shown,0);
 keep.deletion=false;await f.run('renderNative()');assert.equal(content().match(/data-action="native-auto-edit"/g).length,2);
 await click({action:'native-auto-edit',volume:'archives'});assert.equal(shown,0);assert.equal(toast(),'La suppression de points n’est pas accordée sur ce matériel.');
 await click({action:'native-auto-edit',volume:'films'});assert.equal(shown,1);keep.deletion=true;
 // Enregistrer une autre règle désactive la conservation automatique, et le message le dit.
 await f.run('renderNative()');await click({action:'native-keep-open',volume:'films'});
 f.elements.set('#native-keep-form',{getAttribute:()=> 'native-keep-form',values:{keep_last:'9',daily:'0',weekly:'0',monthly:'0',timezone:'UTC'}});f.elements.set('#native-keep-error',{textContent:''});
 stopped=true;await click({action:'native-keep-save'});assert.equal(toast(),'Règle enregistrée. La conservation automatique est désactivée : la réactiver pour cette règle.');
});

test('native capture schedules show per volume and are set in a dialog that asks for a typed confirmation',async()=>{
 const calls=[];let refuse=0;
 const state={connected:true,volumes:[{id:'documents',name:'Docs <b>',family:'btrfs',ready:true},{id:'photos',name:'Photos',family:'zfs',ready:true},{id:'films',name:'Films',family:'lvm',ready:true}],points:[],actions:[],jobs:[],resources:[],provisioning:{enabled:false,devices:[],deployments:[]}};
 const plans={connected:true,confirmation:'PROGRAMMER ',defaults:{enabled:false,time:'02:00',weekdays:[0,1,2,3,4,5,6],timezone:'America/Cayenne',cap:30,next_run:null,last:null},schedules:[
  {volume:'documents',enabled:true,time:'03:30',weekdays:[0,2,4],timezone:'America/Cayenne',cap:12,points:1,next_run:1794182400,last:{ts:1794096000,outcome:'skipped',detail:'Une opération <native> était en cours.'}},
  {volume:'photos',enabled:true,time:'23:00',weekdays:[0,1,2,3,4,5,6],timezone:'UTC',cap:30,points:7,next_run:1794182400,last:{ts:1794096000,outcome:'done',detail:'Capture créée.'}},
  {volume:'films',enabled:false,time:'02:00',weekdays:[0,1,2,3,4,5,6],timezone:'UTC',cap:30,points:0,next_run:null,last:{ts:1,outcome:'inconnu',detail:'x'}}]};
 const f=fixture(async(url,options)=>{
  const body=options?.body?JSON.parse(options.body):null;calls.push([url,body]);
  if(url.endsWith('/storage/native'))return response(200,state);
  if(url.endsWith('/storage/profiles'))return response(200,[]);
  if(url.endsWith('/storage/native-retention'))return response(200,{connected:true,policies:[],defaults:null});
  if(url.endsWith('/storage/native-schedule')&&!body)return response(200,plans);
  if(refuse)return response(refuse,{error:'Recopier exactement la confirmation pour activer la programmation.'});
  return response(200,{...body,next_run:1,last:null});
 });
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/native.js'),'utf8'),f.context);
 f.run('user={name:"admin",role:"admin"};page="native";shell();');await f.run('renderNative()');
 const content=()=>String(f.elements.get('#content').innerHTML),posts=()=>calls.filter(c=>c[1]);
 const click=dataset=>f.listeners.get('click').at(-1)({target:{closest:s=>s==='[data-action]'?{dataset}:null}});
 // Une ligne par volume : heure, jours, fuseau, points sur plafond, prochaine occurrence, et la dernière avec son résultat.
 assert.match(content(),/<h2>Programmation des captures<\/h2><span class="muted">Arrêt au plafond · aucun point n’est supprimé<\/span>/);
 assert.match(content(),/Docs &lt;b&gt;<br><small class="muted">documents<\/small><\/td><td>03:30, lun\. mer\. ven\. · fuseau America\/Cayenne<br><small class="muted">1 point programmé sur 12 au plus · prochaine le /);
 assert.match(content(),/<span class="badge warn">Occurrence sautée<\/span><br><small>[^<]* · Une opération &lt;native&gt; était en cours\.<\/small>/);
 assert.match(content(),/23:00, tous les jours · fuseau UTC<br><small class="muted">7 points programmés sur 30 au plus/);assert.match(content(),/<span class="badge ">Capture créée<\/span><br><small>[^<·]*<\/small>/);
 assert.match(content(),/<td>Désactivée<br><small class="muted">Aucune capture automatique<\/small><\/td><td><small class="muted">Aucune<\/small><\/td>/);assert.doesNotMatch(content(),/style=|inconnu/);
 assert.ok(content().indexOf('Programmation des captures')<content().indexOf('Conservation des points natifs'));
 // « Programmer… » ouvre le réglage du volume : heure, jours, plafond, activation, et la phrase à recopier.
 const modal=f.elements.get('#modal');let shown=0;modal.showModal=()=>shown++;modal.innerHTML='';
 await click({action:'native-schedule-edit',volume:'documents'});
 assert.equal(shown,1);assert.match(modal.innerHTML,/Programmer les captures de « Docs &lt;b&gt; »/);assert.match(modal.innerHTML,/name="time" type="time" value="03:30"/);
 assert.match(modal.innerHTML,/name="weekdays" value="0" checked>Lun<\/label><label><input type="checkbox" name="weekdays" value="1" >Mar/);assert.match(modal.innerHTML,/name="cap" type="number" min="1" max="500" step="1" value="12" required/);
 assert.match(modal.innerHTML,/name="enabled" checked>Activer la programmation/);assert.match(modal.innerHTML,/Pour activer, recopiez « PROGRAMMER documents »<\/label><input id="native-schedule-confirmation" name="confirmation" autocomplete="off">/);
 assert.match(modal.innerHTML,/fuseau America\/Cayenne de la console/);assert.match(modal.innerHTML,/elle ne supprime jamais pour faire de la place/);
 // Enregistrer envoie le réglage et la phrase saisie ; le message dit ce qui a été fait.
 const form=values=>{const map=new Map(Object.entries(values));map.getAll=name=>values[name]||[];return map;};
 f.context.sent=form({time:'04:15',weekdays:['1','3'],cap:'8',enabled:'on',confirmation:' PROGRAMMER documents '});
 let result=await f.run('modalSubmit(sent)');
 assert.deepEqual(posts().at(-1),['/api/storage/native-schedule',{volume:'documents',enabled:true,time:'04:15',weekdays:[1,3],cap:8,confirmation:'PROGRAMMER documents'}]);assert.equal(result.message,'Programmation activée. Aucun point ne sera supprimé.');
 f.context.sent=form({time:'04:15',weekdays:['1'],cap:'8'});result=await f.run('modalSubmit(sent)');
 assert.deepEqual(posts().at(-1)[1],{volume:'documents',enabled:false,time:'04:15',weekdays:[1],cap:8,confirmation:''});assert.equal(result.message,'Programmation désactivée.');
 // Un plafond non entier ne part pas ; un refus du serveur remonte à la fenêtre.
 const count=posts().length;f.context.sent=form({time:'04:15',weekdays:['1'],cap:'2.5',enabled:'on'});await assert.rejects(f.run('modalSubmit(sent)'),/plafond entier/);assert.equal(posts().length,count);
 refuse=400;f.context.sent=form({time:'04:15',weekdays:['1'],cap:'8',enabled:'on',confirmation:'non'});await assert.rejects(f.run('modalSubmit(sent)'),/Recopier exactement la confirmation/);refuse=0;
 // Un volume inconnu n'ouvre rien ; sans volume inscrit, la carte n'apparaît pas.
 await click({action:'native-schedule-edit',volume:'ailleurs'});assert.equal(shown,1);
 state.volumes=[];await f.run('renderNative()');assert.doesNotMatch(content(),/Programmation des captures/);
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
 for(const name of ['components.js','kept.js','playback.js','detection.js','search.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static',name),'utf8'),f.context);
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
 assert.equal(calls.filter(u=>u.startsWith('/api/camera/')).length,5);
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
 assert.match(f.html,/^<div class="dk dk-bg-nacre" id="dk-root">/);assert.doesNotMatch(f.html,/class="sidebar"|<b>Atelier|style=|<iframe/);assert.match(f.html,/&lt;b&gt;Atelier/);
 for(const id of ['content','crumb','topclock','side-host','side-version','alert-summary','zone-prompt','dk-stage','dk-wins','dk-widgets'])assert.match(f.html,new RegExp(`id="${id}"`),id);
 assert.match(f.html,/<main class="content dk-solo" id="content" hidden>/);assert.match(f.html,/class="dk-brand" data-action="desk-home"/);
 assert.equal((f.html.match(/class="dk-dockapp"/g)||[]).length,8);assert.equal((f.html.match(/class="dk-app"/g)||[]).length,8);
 assert.match(f.html,/data-action="shell-classic"/);assert.match(f.html,/data-action="logout"/);
 // Lecture seule : ni alertes ni onglets d'administration, et les applications gardent leurs pages ouvertes à tous.
 const g=deskFixture(undefined,'viewer');assert.doesNotMatch(g.html,/alert-summary/);
 assert.deepEqual(JSON.parse(JSON.stringify(g.run('deskApps().map(a=>[a.id,deskPages(a).map(p=>p[0])])'))),[['files',['files','trash']],['cam',['camera']],['storage',['storage','native']],['protect',['backups','snapshots']],['share',['shares','users']],['settings',['services']],['activity',['events']],['me',['account']]]);
 // Chaque page de la console appartient à une application et une seule.
 const pages=f.run('DESK_APPS.flatMap(a=>a.pages.map(p=>p[0]))');assert.equal(new Set(pages).size,pages.length);
 for(const name of pages)assert.ok(f.run('titles')[name],name);
 for(const name of Object.keys(f.run('titles')))if(!['home','setup'].includes(name))assert.ok(pages.includes(name),name);
});
test('classic display stays one click away and the first-run assistant never uses the desktop',async()=>{
 const f=deskFixture();await f.run('go("users")');
 await f.click('shell-classic');
 assert.equal(f.store['nacre-shell'],'classic');assert.match(f.html,/class="sidebar"/);assert.match(f.html,/data-action="shell-desk"/);assert.equal(f.run('page'),'users');assert.equal(f.run('deskMode()'),false);
 await f.click('shell-desk');assert.equal(f.store['nacre-shell'],'desk');assert.match(f.html,/^<div class="dk dk-bg-nacre" id="dk-root">/);assert.equal(f.run('page'),'users');
 f.run('user.setup_required=true;shell();');assert.match(f.html,/class="sidebar"/);assert.doesNotMatch(f.html,/shell-desk/);assert.equal(f.run('deskMode()'),false);
 // Stockage du navigateur indisponible : le bureau reste l'affichage par défaut et le choix ne casse rien.
 const g=deskFixture();g.context.localStorage={getItem(){throw new Error('bloqué');},setItem(){throw new Error('bloqué');}};
 assert.equal(g.run('deskMode()'),true);await g.click('shell-classic');assert.match(g.html,/^<div class="dk dk-bg-nacre" id="dk-root">/);
});
// Gestionnaire de fenêtres : une fenêtre par application, chacune dans un cadre de même origine.
function winFixture(fetch,role='admin'){
 const f=deskFixture(fetch,role);f.frames={};f.removed=[];
 const node=(id,extra={})=>{const el={hidden:false,innerHTML:'',src:'',style:{},dataset:{},classList:{toggle(name,on){this[name]=on;},add(name){this[name]=true;},remove(name){this[name]=false;}},remove(){f.removed.push(id);f.elements.delete('#'+id);},...extra};f.elements.set('#'+id,el);return el;};
 f.arm=()=>{node('dk-stage');node('dk-widgets',{innerHTML:'déjà là'});node('dk-wins',{insertAdjacentHTML(_,html){this.innerHTML+=html;const app=html.match(/id="dk-win-(\w+)"/)[1];node('dk-win-'+app);node('dk-tabs-'+app);f.frames[app]=node('dk-frame-'+app,{src:html.match(/<iframe[^>]* src="([^"]+)"/)[1],contentWindow:null});}});};
 for(const name of ['bell.js','palette.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static',name),'utf8'),f.context);
 f.run('shell();');f.arm();
 f.child=app=>{const calls=[],child={deskReady:true,calls,go(page){calls.push(['go',page]);},deskApply(intent){calls.push(['apply',JSON.parse(JSON.stringify(intent))]);},location:{reload(){calls.push(['reload']);}}};f.frames[app].contentWindow=child;return child;};
 f.desk=(action,data={},cls='')=>f.listeners.get('click').find(fn=>String(fn).includes("action==='desk-open'"))({target:{closest:()=>({dataset:{action,...data},classList:{contains:name=>name===cls}})}});
 f.wins=()=>JSON.parse(JSON.stringify(f.run('deskWins.map(w=>[w.app,w.page,w.min,w.max])')));return f;
}
test('pages open in one window per application, side by side, and the desktop keeps running behind them',async()=>{
 const f=winFixture();
 await f.run('go("snapshots")');
 assert.deepEqual(f.wins(),[['protect','snapshots',false,false]]);assert.deepEqual([f.run('page'),f.run('rendered.length'),f.run('location.hash')],['home',0,'snapshots']);
 const html=f.elements.get('#dk-wins').innerHTML;
 assert.match(html,/<section class="dk-win" id="dk-win-protect" data-app="protect" aria-label="Protection">/);assert.match(html,/<iframe class="dk-frame" id="dk-frame-protect" title="Protection" src="\/#snapshots"><\/iframe>/);assert.doesNotMatch(html,/style=/);
 assert.deepEqual([...f.elements.get('#dk-tabs-protect').innerHTML.matchAll(/data-action="desk-tab" data-app="protect" data-target="(\w+)" aria-selected="(\w+)">([^<]+)</g)].map(m=>m.slice(1)),[['backups','false','Sauvegardes'],['snapshots','true','Points de restauration'],['retention','false','Conservation']]);
 // Même application : la fenêtre existante change de page ; sans enfant prêt, par l'adresse du cadre.
 await f.run('go("backups")');assert.deepEqual(f.wins(),[['protect','backups',false,false]]);assert.equal(f.frames.protect.src,'/#backups');
 const child=f.child('protect');await f.desk('desk-tab',{app:'protect',target:'retention'});assert.deepEqual(child.calls,[['apply',{app:'protect'}],['go','retention']]);assert.equal(f.frames.protect.src,'/#backups');
 // Autre application : seconde fenêtre, devant ; ses onglets sont des vues.
 await f.run('go("camera")');assert.deepEqual(f.wins().map(w=>w[0]),['protect','cam']);assert.equal(f.run('deskFront().app'),'cam');
 assert.equal(f.elements.get('#dk-win-cam').classList.front,true);assert.equal(f.elements.get('#dk-win-protect').classList.front,false);
 assert.ok(Number(f.elements.get('#dk-win-cam').style.zIndex)>Number(f.elements.get('#dk-win-protect').style.zIndex));
 assert.match(f.elements.get('#dk-tabs-cam').innerHTML,/data-action="desk-view" data-app="cam" data-view="wall" aria-selected="true">Mur</);
 const cam=f.child('cam');await f.desk('desk-view',{app:'cam',view:'replay'});assert.deepEqual(cam.calls,[['apply',{app:'cam',view:'replay'}],['go','camera']]);assert.match(f.elements.get('#dk-tabs-cam').innerHTML,/data-view="replay" aria-selected="true"/);
 await f.desk('desk-view',{app:'cam',view:'nowhere'});await f.desk('desk-view',{app:'protect',view:'replay'});assert.equal(cam.calls.length,2);
 // Page inconnue ou interdite : aucune fenêtre.
 await f.run('go("nowhere")');assert.equal(f.wins().length,2);
 const g=winFixture(undefined,'viewer');await g.run('go("settings")');assert.deepEqual(g.wins(),[]);await g.run('go("services")');assert.deepEqual(g.wins(),[['settings','services',false,false]]);
});
test('dock, title bar and brand reduce, restore, enlarge and close windows without touching the others',async()=>{
 const f=winFixture();await f.run('go("files")');await f.run('go("camera")');
 await f.desk('desk-open',{app:'cam'},'dk-dockapp');assert.deepEqual(f.wins(),[['files','files',false,false],['cam','camera',true,false]]);assert.equal(f.elements.get('#dk-win-cam').hidden,true);assert.equal(f.run('deskFront().app'),'files');assert.equal(f.run('location.hash'),'files');
 await f.desk('desk-open',{app:'cam'},'dk-dockapp');assert.equal(f.run('deskFront().app'),'cam');assert.equal(f.elements.get('#dk-win-cam').hidden,false);
 // Une icône du bureau ramène devant, sans jamais réduire.
 await f.desk('desk-open',{app:'cam'},'dk-app');assert.equal(f.wins()[1][2],false);await f.desk('desk-open',{app:'files'},'dk-app');assert.equal(f.run('deskFront().app'),'files');
 await f.desk('desk-open',{app:'storage'},'dk-dockapp');assert.deepEqual(f.wins().at(-1),['storage','storage',false,false]);await f.desk('desk-open',{app:'nowhere'});assert.equal(f.wins().length,3);
 await f.desk('desk-max',{app:'files'});assert.equal(f.elements.get('#dk-win-files').classList.max,true);assert.equal(f.run('deskFront().app'),'files');await f.desk('desk-max',{app:'files'});assert.equal(f.elements.get('#dk-win-files').classList.max,false);
 await f.desk('desk-min',{app:'files'});assert.equal(f.wins()[0][2],true);
 await f.desk('desk-home');assert.ok(f.wins().every(w=>w[2]));assert.equal(f.run('location.hash'),'home');assert.equal(f.run('deskFront()'),null);
 await f.desk('desk-close',{app:'cam'});assert.deepEqual(f.wins().map(w=>w[0]),['files','storage']);assert.deepEqual(f.removed,['dk-win-cam']);
 await f.desk('desk-close',{app:'cam'});await f.desk('desk-min',{app:'cam'});await f.desk('desk-max',{app:'cam'});assert.equal(f.wins().length,2);
 // Rouvrir après fermeture repart de la première page de l'application.
 await f.run('go("camera")');assert.deepEqual(f.wins().at(-1),['cam','camera',false,false]);
 // Recherche globale : le résultat s'ouvre dans la fenêtre de son application, avec ce qu'il faut y montrer.
 const cam=f.child('cam');await f.run('runPalette({camera:"garage"})');assert.deepEqual(cam.calls,[['apply',{view:'wall',camera:'garage',app:'cam'}],['go','camera']]);
 await f.desk('desk-close',{app:'files'});await f.run('runPalette({area:"video"})');assert.deepEqual(JSON.parse(JSON.stringify(f.run('deskWindow("files").intent'))),{area:'video',app:'files'});
 await f.run('runPalette({page:"camera",view:["cam","events"]})');assert.deepEqual(cam.calls.slice(-2),[['apply',{view:'events',app:'cam'}],['go','camera']]);
 const before=f.wins().length;await f.run('runPalette({page:"nowhere"})');assert.equal(f.wins().length,before);
});
test('the desktop only listens to its own windows, and follows what they report',async()=>{
 const f=winFixture(async url=>response(200,url.endsWith('/alerts')?{stale:false,attention:0,active:[],history:[]}:url.endsWith('/jobs')?[]:overviewSample));
 await f.run('go("camera")');await f.run('go("settings")');const cam=f.child('cam'),settings=f.child('settings'),stranger={};
 f.context.cam=cam;f.context.settings=settings;f.context.stranger=stranger;
 assert.deepEqual([f.run('deskAppOf(cam)'),f.run('deskAppOf(stranger)')],['cam','']);
 f.run('deskWindow("cam").intent={app:"cam",camera:"garage"};');assert.deepEqual(JSON.parse(JSON.stringify(f.run('deskIntent(cam)'))),{app:'cam',camera:'garage',view:'wall'});
 assert.deepEqual(JSON.parse(JSON.stringify(f.run('deskIntent(cam)'))),{view:'wall'});assert.deepEqual(JSON.parse(JSON.stringify(f.run('deskIntent(stranger)'))),{});
 // Page suivie seulement si elle appartient à l'application de la fenêtre.
 f.run('deskChildAt(settings,"updates");deskChildAt(settings,"files");deskChildAt(stranger,"services");');assert.equal(f.run('deskWindow("settings").page'),'updates');
 assert.match(f.elements.get('#dk-tabs-settings').innerHTML,/data-target="updates" aria-selected="true"/);
 f.run('deskChildView(cam,"cam","replay");deskChildView(settings,"cam","events");deskChildView(stranger,"cam","events");');assert.equal(f.run('deskWindow("cam").view'),'replay');assert.match(f.elements.get('#dk-tabs-cam').innerHTML,/data-view="replay" aria-selected="true"/);
 // Un appui dans une fenêtre la met devant et referme les panneaux du bureau.
 assert.equal(f.run('deskFront().app'),'settings');f.run('bellOpen=true;deskChildFocus(cam);');assert.deepEqual([f.run('deskFront().app'),f.run('bellOpen')],['cam',false]);f.run('deskChildFocus(stranger)');assert.equal(f.run('deskFront().app'),'cam');
 // Une page d'une autre application demandée par une fenêtre s'ouvre dans la sienne.
 f.run('deskChildGo(cam,"storage");deskChildGo(stranger,"users");');assert.deepEqual(f.wins().map(w=>w[0]),['cam','settings','storage']);
 // Préférences enregistrées dans une fenêtre : la barre suit, les autres fenêtres se rechargent.
 f.elements.set('#side-host',{textContent:''});f.elements.set('#topclock',{textContent:''});f.run('user.timezone_unset=true;deskChildPrefs(settings,{name:"Maison",timezone:"Europe/Paris"});deskChildPrefs(stranger,{name:"Autre",timezone:"UTC"});');
 assert.deepEqual([f.run('user.nas_name'),f.run('user.timezone'),f.run('user.timezone_unset'),f.elements.get('#side-host').textContent],['Maison','Europe/Paris',false,'Maison']);
 assert.deepEqual([cam.calls.filter(c=>c[0]==='reload').length,settings.calls.filter(c=>c[0]==='reload').length],[1,0]);
 // Changer d'affichage détruit les fenêtres et garde la page de devant.
 f.run('render=async()=>{rendered.push(page);};');await f.desk('shell-classic');assert.match(f.html,/class="sidebar"/);assert.equal(f.run('page'),'storage');assert.deepEqual(f.wins(),[]);
});
test('a child window shows only its content, navigates inside its application and hands the rest to the desktop',async()=>{
 const f=deskFixture();for(const name of ['bell.js','palette.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static',name),'utf8'),f.context);
 const calls=[],parent={};for(const name of ['deskChildAt','deskChildGo','deskChildView','deskChildFocus','deskChildPrefs'])parent[name]=(child,...values)=>{calls.push([name,...values]);};
 Object.assign(parent,{deskIntent:()=>({app:'cam',view:'replay'}),deskAppOf:()=>'cam',login:message=>{calls.push(['login',message]);},openPalette:()=>{calls.push(['openPalette']);}});
 f.context.window.parent=parent;const fetched=[];f.context.fetch=async url=>{fetched.push(url);return response(200,[]);};
 assert.equal(f.run('deskEmbedded()'),true);f.run('shell();');
 assert.match(f.html,/^<div class="dk-child">/);assert.doesNotMatch(f.html,/dk-bar|dk-dock|sidebar|<iframe/);assert.match(f.html,/<main class="content" id="content"><\/main>/);
 assert.deepEqual([f.run('deskViewOf("cam")'),f.context.window.deskReady],['replay',true]);
 await f.run('go("camera")');assert.deepEqual([f.run('page'),f.run('rendered.at(-1)'),calls.at(-1)],['camera','camera',['deskChildAt','camera']]);
 const local=f.run('rendered.length');await f.run('go("files")');await f.run('go("home")');
 assert.deepEqual(calls.slice(-2),[['deskChildGo','files'],['deskChildGo','home']]);assert.deepEqual([f.run('page'),f.run('rendered.length')],['camera',local]);
 f.run('deskSetView("cam","events")');assert.deepEqual([calls.at(-1),f.run('deskViewOf("cam")')],[['deskChildView','cam','events'],'events']);
 f.run('deskApply({app:"files",area:"video"});deskApply(null);deskApply({view:"nowhere"});');assert.deepEqual([f.run('area'),f.run('currentPath'),f.run('deskViewOf("cam")')],['video','','events']);
 // Session expirée, état de la barre et recherche : c'est le bureau qui s'en charge.
 f.run('login("Session expirée.")');assert.deepEqual(calls.at(-1),['login','Session expirée.']);assert.notEqual(f.run('user'),null);
 await f.run('refreshStatus()');assert.deepEqual(fetched,[]);
 let prevented=0;f.listeners.get('keydown').at(-1)({key:'k',ctrlKey:true,preventDefault(){prevented++;}});assert.deepEqual([calls.at(-1),prevented],[['openPalette'],1]);
 f.listeners.get('pointerdown').at(-1)({target:{closest:()=>null}});assert.deepEqual(calls.at(-1),['deskChildFocus']);
 // Parent d'une autre nature (page tierce qui encadrerait la console) : jamais traité comme un bureau.
 f.context.window.parent={};assert.equal(f.run('deskEmbedded()'),false);f.context.window.parent=f.context.window;assert.equal(f.run('deskEmbedded()'),false);
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
 assert.ok(hints.has('Réglages · Général'));assert.ok(hints.has('Application'));assert.equal(admin.filter(e=>e.hint==='Application').length,8);
 const viewer=paletteFixture(paletteReply,'viewer').run('paletteIndex()');
 for(const entry of viewer)assert.ok(!['settings','updates','notifications','alerts','retention'].includes(entry.page),entry.label);
 assert.ok(viewer.some(e=>e.label==='Nouveau partage'));assert.ok(!viewer.some(e=>e.label==='Fuseau horaire'));
 f.store['nacre-shell']='classic';f.run('shell();');assert.doesNotMatch(f.html,/palette/);
});
test('typed words match the start of words, ignore accents and put the closest label first',async()=>{
 const f=paletteFixture();const q=text=>JSON.parse(JSON.stringify(f.run('paletteSearch')(text).map(e=>e.label)));
 assert.deepEqual(q(''),['Fichiers','Surveillance','Stockage','Protection','Personnes et partages','Réglages','Activité','Mon compte']);
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
 assert.equal(f.labels().length,8);f.key('ArrowUp');assert.equal(f.run('palettePick'),7);f.key('ArrowDown');assert.equal(f.run('palettePick'),0);f.key('ArrowDown');assert.equal(f.run('palettePick'),1);
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
test('search card takes an optional time slot, keeps it across type and following pages, and refuses a half or empty slot',async()=>{
 // Copie propre à chaque réponse : la carte complète sa liste en place, et l'exemple commun ne doit pas en hériter.
 const calls=[],toasts=[],f=searchFixture(async url=>{calls.push(url);return response(200,{...JSON.parse(JSON.stringify(searchSample)),next:dayStart+100,hours:url.includes('time_from')?{from:'22:00',to:'06:00'}:null,label:url.includes('label=car')?'car':''});});
 f.run('playbackData=sample;');let html=f.run('searchCard()');
 // Champs d'heure vides par défaut, expliqués par une note reliée aux deux champs.
 assert.match(html,/<label for="search-after">entre<\/label><input id="search-after" type="time" value="" aria-describedby="search-hours">/);assert.match(html,/<label for="search-before">et<\/label><input id="search-before" type="time" value="" aria-describedby="search-hours">/);
 assert.match(html,/id="search-hours">Heures facultatives/);assert.doesNotMatch(html,/style=/);
 // Résultats d'une tranche : champs repris, tranche dite dans le résumé et dans le message d'absence.
 html=f.run('found.hours={from:"22:00",to:"06:00"};searchData=found;searchCard()');
 assert.match(html,/id="search-after" type="time" value="22:00"/);assert.match(html,/id="search-before" type="time" value="06:00"/);assert.match(html,/9 événements, du mardi 3 novembre au lundi 9 novembre, entre 22:00 et 06:00/);
 html=f.run('found.events=[];found.next=null;searchCard()');assert.match(html,/Aucun événement dans cette tranche horaire sur cette période\./);
 for(const bad of ['{from:"22:00"}','{from:"22:00",to:"6h"}','{from:"24:00",to:"06:00"}','"nuit"','{from:"<b>",to:"06:00"}'])assert.equal(f.run(`searchValid({...found,hours:${bad}})`),null,bad);
 assert.notEqual(f.run('searchValid({...found,hours:null})'),null);assert.notEqual(f.run('searchValid({...found,hours:undefined})'),null);
 // Bouton Rechercher : la tranche part avec la période ; à moitié remplie, identique ou illisible, rien ne part.
 const fields={from:{value:'2026-11-03'},to:{value:'2026-11-09'},after:{value:''},before:{value:''}};
 for(const [key,el] of Object.entries(fields))f.elements.set('#search-'+key,el);f.elements.set('#search-results',{innerHTML:''});
 f.context.toast=(text,bad)=>toasts.push([text,!!bad]);f.run('searchData=null;');
 const click=async dataset=>{const el={dataset,disabled:false};for(const fn of f.listeners.get('click'))await fn({target:{closest:s=>s.includes('search-')?el:null},preventDefault(){}});};
 for(const [after,before,message] of [['22:00','',/début et la fin de la tranche/],['','06:00',/début et la fin de la tranche/],['22:00','22:00',/identiques/],['22h','06:00',/illisible/]]){
  fields.after.value=after;fields.before.value=before;await click({action:'search-run'});assert.equal(calls.length,0,after+'-'+before);assert.match(toasts.at(-1)[0],message);assert.equal(toasts.at(-1)[1],true);
 }
 fields.after.value='22:00';fields.before.value='06:00';await click({action:'search-run'});
 assert.deepEqual(calls,['/api/camera/search?camera=entry&from=2026-11-03&to=2026-11-09&time_from=22%3A00&time_to=06%3A00']);assert.deepEqual(JSON.parse(JSON.stringify(f.run('searchData.hours'))),{from:'22:00',to:'06:00'});
 // Type puis page suivante : la tranche suit, avant la position de la suite.
 await click({action:'search-filter',label:'car'});assert.equal(calls[1],'/api/camera/search?camera=entry&from=2026-11-03&to=2026-11-09&label=car&time_from=22%3A00&time_to=06%3A00');
 f.elements.set('#search-events',{insertAdjacentHTML(){}});f.elements.set('#search-more',{innerHTML:'x'});
 await click({action:'search-more'});assert.equal(calls[2],`/api/camera/search?camera=entry&from=2026-11-03&to=2026-11-09&label=car&time_from=22%3A00&time_to=06%3A00&before=${dayStart+100}`);
 // Même période et même tranche : le type choisi est gardé ; tranche changée ou retirée : il est remis à zéro.
 await click({action:'search-run'});assert.match(calls[3],/&label=car&time_from=22%3A00&time_to=06%3A00$/);
 fields.after.value='';fields.before.value='';await click({action:'search-run'});assert.equal(calls[4],'/api/camera/search?camera=entry&from=2026-11-03&to=2026-11-09');assert.equal(f.run('searchData.hours'),null);
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
 for(const name of ['components.js','kept.js','playback.js','detection.js','search.js','palette.js','surveillance.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static',name),'utf8'),f.context);
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
test('events tab loads further pages camera by camera and only ever grows at its end',async()=>{
 const calls=[],state={fail:false};
 const ev=(id,offset)=>({id,label:'person',sub_label:null,day:'2026-11-09',start:dayStart+offset,end:dayStart+offset+10,ongoing:false,score:80,recorded:true});
 const reply=(events,next,first)=>({camera:'x',timezone:'UTC',from:'2026-11-03',to:'2026-11-09',today:'2026-11-09',label:'',hours:null,events,next,facets:first?{total:events.length,matched:events.length,more:next!==null,types:[],days:[]}:null});
 const f=survFixture(async url=>{calls.push(url);
  if(url==='/api/cameras')return response(200,survCameras);
  if(!url.startsWith('/api/camera/search'))return response(200,overviewSample);
  if(url.includes('camera=yard'))return response(200,reply([ev('y1',950),ev('y2',700),ev('y3',300),ev('y4',100)],null,true));
  if(!url.includes('camera=entry'))return response(200,reply([],null,true));
  if(!url.includes('before='))return response(200,reply([ev('e1',1000),ev('e2',900)],dayStart+900,true));
  if(state.fail)return response(503,{error:'Le service vidéo est arrêté.'});
  return response(200,url.endsWith('before='+(dayStart+900))?reply([ev('e2',900),ev('e3',600),ev('e4',500)],dayStart+500,false):reply([ev('e5',200)],null,false));});
 const html=()=>String(f.elements.get('#surv-events')?.innerHTML??f.run('survEventsHtml()')),starts=()=>[...html().matchAll(/data-start="(\d+)"/g)].map(m=>Number(m[1])-dayStart);
 const further=()=>calls.filter(u=>u.includes('before='));
 f.run('deskSetView("cam","events");');await f.run('renderCamera()');
 // L'entrée a une suite : la liste s'arrête à son dernier événement chargé, sans montrer ce que la cour a de plus ancien.
 assert.deepEqual(starts(),[1000,950,900]);assert.match(html(),/data-action="surv-more"/);assert.match(html(),/<span>Afficher la suite<\/span>/);
 assert.match(html(),/« Afficher la suite » remonte plus loin dans la période\. Les pastilles comptent les événements déjà chargés\./);assert.doesNotMatch(html(),/style=|soixante/);
 // Filtrée sur une caméra sans suite, la liste est complète ; sur celle qui en a une, le bouton reste.
 await f.act('surv-filter',{kind:'camera',value:'yard'});assert.deepEqual(starts(),[950,700,300,100]);assert.doesNotMatch(html(),/surv-more/);assert.match(html(),/Tous les événements de la période sont listés\./);
 await f.act('surv-filter',{kind:'camera',value:'entry'});assert.deepEqual(starts(),[1000,900]);assert.match(html(),/surv-more/);
 await f.act('surv-filter',{kind:'camera',value:''});
 // Un refus du serveur est dit, et rien ne bouge.
 state.fail=true;await f.act('surv-more');
 assert.match(html(),/role="alert">La suite n’a pas pu être chargée : Le service vidéo est arrêté\.</);assert.deepEqual(starts(),[1000,950,900]);assert.match(html(),/surv-more/);
 // La suite demande la caméra qui borne la liste, sur la période exacte de la première réponse, jusqu'à épuisement ; aucun doublon.
 state.fail=false;calls.length=0;await f.act('surv-more');
 assert.deepEqual(further(),[`/api/camera/search?camera=entry&from=2026-11-03&to=2026-11-09&before=${dayStart+900}`,`/api/camera/search?camera=entry&from=2026-11-03&to=2026-11-09&before=${dayStart+500}`]);
 assert.deepEqual(starts(),[1000,950,900,700,600,500,300,200,100]);assert.doesNotMatch(html(),/surv-more|role="alert"/);assert.match(html(),/Tous les événements de la période sont listés\./);
 assert.equal(f.run('survEvents.items.length'),9);
 // Plus rien à demander : un nouveau clic n'envoie rien. Une nouvelle recherche repart de la première page.
 calls.length=0;await f.act('surv-more');assert.equal(further().length,0);
 await f.run('renderCamera()');assert.deepEqual(starts(),[1000,950,900]);assert.equal(f.run('survLimit'),120);
});

test('events tab takes a period and a time slot for every camera, sums what the server counted and explains a refusal',async()=>{
 const calls=[],toasts=[],state={refuse:false};
 const sample=(url,extra={})=>({...JSON.parse(JSON.stringify(searchSample)),hours:url.includes('time_from')?{from:'22:00',to:'06:00'}:null,...(url.includes('from=2026-11-01')?{from:'2026-11-01',to:'2026-11-05'}:{}),...extra});
 const f=survFixture(async url=>{calls.push(url);
  if(url==='/api/cameras')return response(200,survCameras);
  if(!url.startsWith('/api/camera/search'))return response(200,overviewSample);
  if(state.refuse)return response(400,{error:'Date hors de la période consultable.'});
  if(url.includes('camera=garage'))return response(500,{error:'Indisponible.'});
  return response(200,url.includes('camera=entry')?sample(url):sample(url,{camera:'x',events:[],facets:{total:4,matched:4,more:url.includes('camera=yard'),types:[],days:[]}}));});
 f.context.toast=(text,bad)=>toasts.push([text,!!bad]);
 const searches=()=>calls.filter(u=>u.startsWith('/api/camera/search')).sort(),html=()=>String(f.elements.get('#surv-events')?.innerHTML??f.run('survEventsHtml()'));
 f.run('deskSetView("cam","events");');await f.run('renderCamera()');
 // Par défaut : aucune période envoyée, formulaire prérempli par la réponse, total additionné sur les caméras lues.
 assert.deepEqual(searches(),['entry','garage','pause','yard'].map(id=>'/api/camera/search?camera='+id));
 let page=f.run('survEventsHtml()');
 assert.match(page,/id="surv-from" type="date" value="2026-11-03" max="2026-11-09"/);assert.match(page,/id="surv-to" type="date" value="2026-11-09" max="2026-11-09"/);assert.match(page,/id="surv-after" type="time" value="" aria-describedby="surv-hours"/);
 assert.match(page,/id="surv-summary" role="status">17 événements parmi les plus récents, du mardi 3 novembre au lundi 9 novembre</);assert.doesNotMatch(page,/surv-reset|style=/);assert.match(page,/Événements indisponibles pour Garage/);
 // Saisies refusées sur place : aucune requête.
 const fields={from:{value:'2026-11-05'},to:{value:'2026-11-01'},after:{value:''},before:{value:''}};for(const [key,el] of Object.entries(fields))f.elements.set('#surv-'+key,el);
 const before=calls.length;
 await f.act('surv-search');assert.match(toasts.at(-1)[0],/début de la période suit sa fin/);
 fields.from.value='2026-11-01';fields.to.value='2026-11-05';fields.after.value='22:00';await f.act('surv-search');assert.match(toasts.at(-1)[0],/début et la fin de la tranche/);
 fields.before.value='22:00';await f.act('surv-search');assert.match(toasts.at(-1)[0],/identiques/);
 fields.from.value='';await f.act('surv-search');assert.match(toasts.at(-1)[0],/début et la fin de la période/);
 assert.equal(calls.length,before);assert.equal(f.run('survAsk'),null);
 // Période et tranche valides : envoyées à chaque caméra, reprises dans le formulaire et le résumé.
 fields.from.value='2026-11-01';fields.before.value='06:00';calls.length=0;await f.act('surv-search');
 assert.deepEqual(searches(),['entry','garage','pause','yard'].map(id=>`/api/camera/search?camera=${id}&from=2026-11-01&to=2026-11-05&time_from=22%3A00&time_to=06%3A00`));
 page=f.run('survEventsHtml()');
 assert.match(page,/id="surv-from" type="date" value="2026-11-01"/);assert.match(page,/id="surv-after" type="time" value="22:00"/);assert.match(page,/id="surv-before" type="time" value="06:00"/);
 assert.match(page,/17 événements parmi les plus récents, du dimanche 1 novembre au jeudi 5 novembre, entre 22:00 et 06:00/);assert.match(page,/data-action="surv-reset" ><span>Sept derniers jours/);
 assert.equal((page.match(/data-action="surv-open"/g)||[]).length,searchSample.events.length);
 // Sans événement : le message dit la tranche. Les filtres en place ne relancent rien.
 f.run('survEvents.items=[];');assert.match(f.run('survEventsHtml()'),/Aucun événement dans cette tranche horaire sur cette période\./);
 f.run('survEvents.hours=null;');assert.match(f.run('survEventsHtml()'),/Aucun événement sur cette période\./);
 // Refus du serveur pour toutes les caméras : expliqué une fois, formulaire gardé pour corriger, caméras non accusées.
 state.refuse=true;await f.act('surv-search');page=f.run('survEventsHtml()');
 assert.match(page,/<div class="notice neutral">Date hors de la période consultable\.<\/div>/);assert.match(page,/id="surv-from" type="date" value="2026-11-01"/);assert.doesNotMatch(page,/indisponibles pour|pb-chip|surv-summary/);
 // Retour aux sept derniers jours : plus rien n'est envoyé.
 state.refuse=false;calls.length=0;await f.act('surv-reset');
 assert.deepEqual(searches(),['entry','garage','pause','yard'].map(id=>'/api/camera/search?camera='+id));assert.equal(f.run('survAsk'),null);assert.doesNotMatch(f.run('survEventsHtml()'),/surv-reset/);
 f.run('survEvents.items=[];');assert.match(f.run('survEventsHtml()'),/Aucun événement sur les sept derniers jours\./);
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
 assert.deepEqual(calls.slice(-3).sort(),['/api/camera/detection?camera=yard','/api/camera/settings?camera=yard','/api/cameras/storage']);
 assert.match(html,/id="camera-select"/);assert.match(html,/<option value="yard" selected>/);assert.match(html,/Conservation continue : <strong>3 jour\(s\)<\/strong>/);
 assert.match(html,/data-action="camera-settings"/);assert.match(html,/data-action="camera-edit"/);assert.doesNotMatch(html,/camera\/live|style=/);assert.equal(f.run('cameraDetail'),true);
 const g=survFixture(survReply([]),'viewer');g.run('deskSetView("cam","settings");');await g.run('renderCamera()');
 assert.doesNotMatch(g.content(),/camera-settings|camera-edit|camera-add/);assert.match(g.content(),/réservés aux administrateurs/);
 // La recherche globale ouvre une caméra agrandie sur le mur, et une vue par son nom.
 f.run('user.role="admin";');await f.run('runPalette({camera:"entry"})');assert.deepEqual([f.run('survView()'),f.run('survFocus'),f.run('selectedCamera')],['wall',true,'entry']);
 await f.run('runPalette({page:"camera",view:["cam","events"]})');assert.equal(f.run('survView()'),'events');
});

// Gestionnaire de fichiers du bureau : arborescence, sélection multiple, aperçu, déplacement, envoi.
const fmAreas=[{id:'fichiers',name:'Fichiers <b>partagés</b>',writable:true,kind:'local'},{id:'video',name:'Vidéos',writable:false,kind:'local'}];
const fmSample=[{name:'Docs & co',directory:true,link:false,size:4096,modified:1794182400},{name:'photo "été".jpg',directory:false,link:false,size:2048,modified:1794182500},
 {name:'notes.txt',directory:false,link:false,size:10,modified:1794182600},{name:'clip.mp4',directory:false,link:false,size:900000,modified:1794182700},
 {name:'<img src=x>.pdf',directory:false,link:false,size:5,modified:1794182800},{name:'raccourci',directory:true,link:true,size:9,modified:1794182900},null,{name:''}];
function fmFixture(fetch,role='admin'){
 const calls=[],mode={clean:false},reply=fetch||(async(url,options)=>{calls.push([url,options?.body]);return response(200,url.startsWith('/api/areas')?(role==='admin'?fmAreas:fmAreas.map(a=>({...a,writable:false}))):url.startsWith('/api/files')?{items:mode.clean?fmSample.filter(i=>i&&i.name):fmSample}:{ok:true});});
 const f=deskFixture(reply,role);vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/files.js'),'utf8'),f.context);
 f.calls=calls;f.mode=mode;f.run('shell();page="files";area="fichiers";currentPath="";');
 f.mount=()=>{for(const id of ['fm','fm-list','fm-side','fm-tools'])f.elements.set('#'+id,{innerHTML:'',classList:{toggle(name,on){this[name]=on;}}});};
 f.hit=(dataset,extra={})=>f.listeners.get('click').at(-1)({target:{closest:selector=>selector==='[data-action]'?(dataset.action?{dataset}:null):selector==='.fm-row'?(dataset.name?{dataset}:null):null},...extra});
 f.names=()=>JSON.parse(JSON.stringify(f.run('[...fmSel].sort()')));return f;
}
test('file manager draws tree, list and preview in the desktop, without write actions for a reader, and leaves the classic page alone',async()=>{
 const f=fmFixture();await f.run('renderFiles()');let html=String(f.elements.get('#content').innerHTML);
 assert.deepEqual(f.calls.map(c=>c[0]),['/api/areas','/api/files?area=fichiers&path=']);
 assert.match(html,/^<div class="fm " id="fm"><nav class="fm-tree"/);assert.doesNotMatch(html,/<b>partagés|<img src=x>|style=/);assert.match(html,/Fichiers &lt;b&gt;partagés/);assert.match(html,/&lt;img src=x&gt;\.pdf/);
 assert.equal((html.match(/<tr class="fm-row /g)||[]).length,6);assert.match(html,/data-name="Docs &amp; co" draggable="true" data-fm-drop="Docs &amp; co"/);
 assert.doesNotMatch(html,/data-name="raccourci"[^>]*data-fm-drop/);assert.match(html,/Vidéos<small>lecture seule<\/small>/);
 assert.match(html,/data-action="mkdir"/);assert.match(html,/data-action="fm-send"/);assert.match(html,/id="fm-upload" multiple hidden/);
 assert.deepEqual(JSON.parse(JSON.stringify(f.run('fmShown().map(i=>i.name)'))),['Docs & co','raccourci','<img src=x>.pdf','clip.mp4','notes.txt','photo "été".jpg']);
 f.run('fmSort=["size",-1];');assert.deepEqual(JSON.parse(JSON.stringify(f.run('fmShown().slice(2).map(i=>i.name)'))),['clip.mp4','photo "été".jpg','notes.txt','<img src=x>.pdf']);
 // Sous-dossier : l'arborescence déplie le chemin et garde les dossiers déjà vus.
 f.run('fmSort=["name",1];currentPath="Docs & co/Sous";');await f.run('renderFiles()');const tree=f.run('fmTree()');
 assert.match(tree,/data-path="Docs &amp; co" data-fm-drop="Docs &amp; co" data-depth="1">Docs &amp; co<\/button><button type="button" class="fm-node on"[^>]*data-path="Docs &amp; co\/Sous"[^>]*data-depth="2">Sous/);
 assert.match(f.run('fmTools()'),/data-path="Docs &amp; co">Docs &amp; co<\/button><span aria-hidden="true">›<\/span><button type="button" data-action="fm-go" data-area="fichiers" data-path="Docs &amp; co\/Sous">Sous/);
 // Espace en lecture seule ou compte lecteur : rien à écrire ni à glisser.
 f.run('area="video";currentPath="";');await f.run('renderFiles()');html=String(f.elements.get('#content').innerHTML);assert.doesNotMatch(html,/draggable|data-action="mkdir"|fm-send/);
 const g=fmFixture(null,'viewer');await g.run('renderFiles()');assert.doesNotMatch(String(g.elements.get('#content').innerHTML),/draggable|data-action="mkdir"|fm-send|fm-trash|fm-move/);
 f.store['nacre-shell']='classic';f.mode.clean=true;f.run('area="fichiers";');await f.run('renderFiles()');assert.match(String(f.elements.get('#content').innerHTML),/Vos fichiers\. Simplement\./);
});
test('a vanished folder returns to the root, a missing volume to shared files, and late listings are discarded',async()=>{
 let gone=true;const f=fmFixture(async url=>url.startsWith('/api/areas')?response(200,fmAreas):gone&&url.includes('path=perdu')?response(404,{error:'Fichier ou dossier introuvable.'}):response(200,{items:fmSample}));
 f.run('currentPath="perdu";');await f.run('renderFiles()');assert.equal(f.run('currentPath'),'');assert.match(f.elements.get('#toast').textContent,/n’existe plus/);assert.match(String(f.elements.get('#content').innerHTML),/id="fm"/);
 f.run('area="native_absent";');await f.run('renderFiles()');assert.equal(f.run('area'),'fichiers');
 let release;const g=fmFixture(url=>url.startsWith('/api/areas')?Promise.resolve(response(200,fmAreas)):new Promise(resolve=>{release=()=>resolve(response(200,{items:fmSample}));}));
 const pending=g.run('renderFiles()');await new Promise(resolve=>setImmediate(resolve));g.run('page="users";$("#content").innerHTML="autre page";');release();await pending;
 assert.equal(g.elements.get('#content').innerHTML,'autre page');
});
test('selection follows clicks, Ctrl, Shift and checkboxes, and its bar offers the right download',async()=>{
 const f=fmFixture();await f.run('renderFiles()');f.mount();
 await f.hit({name:'notes.txt'});assert.deepEqual(f.names(),['notes.txt']);
 await f.hit({name:'clip.mp4'},{ctrlKey:true});assert.deepEqual(f.names(),['clip.mp4','notes.txt']);
 await f.hit({name:'clip.mp4'},{ctrlKey:true});assert.deepEqual(f.names(),['notes.txt']);
 // La plage part du dernier élément cliqué, même s'il vient d'être retiré de la sélection.
 await f.hit({name:'<img src=x>.pdf'},{shiftKey:true});assert.deepEqual(f.names(),['<img src=x>.pdf','clip.mp4']);
 await f.hit({action:'fm-check',name:'Docs & co'});assert.equal(f.names().length,3);await f.hit({action:'fm-clear'});assert.deepEqual(f.names(),[]);
 await f.hit({action:'fm-all'});assert.equal(f.names().length,6);await f.hit({action:'fm-all'});assert.equal(f.names().length,0);
 assert.equal(f.run('fmBar()'),'');
 f.run('fmSel=new Set(["notes.txt"]);');let bar=f.run('fmBar()');
 assert.match(bar,/<a class="fm-link" href="\/api\/download\?area=fichiers&amp;path=notes\.txt">Télécharger<\/a>/);assert.match(bar,/data-action="rename" data-path="notes\.txt" data-name="notes\.txt"/);assert.match(bar,/fm-move/);assert.match(bar,/fm-trash/);
 f.run('fmSel=new Set(["Docs & co","photo \\"été\\".jpg"]);');bar=f.run('fmBar()');
 assert.match(bar,/href="\/api\/archive\?area=fichiers&amp;path=&amp;name=Docs%20%26%20co&amp;name=photo%20%22%C3%A9t%C3%A9%22\.jpg">Télécharger en archive/);assert.doesNotMatch(bar,/data-action="rename"/);
 f.run('fmSel=new Set(["raccourci"]);');assert.doesNotMatch(f.run('fmBar()'),/fm-link/);
 // Filtrer vide la sélection, pour ne jamais agir sur un élément masqué.
 f.run('fmSel=new Set(["notes.txt"]);');f.listeners.get('input').at(-1)({target:{id:'fm-filter',value:'CLIP'}});
 assert.deepEqual([f.names(),JSON.parse(JSON.stringify(f.run('fmShown().map(i=>i.name)')))],[[],['clip.mp4']]);
 // Clavier : tout sélectionner, vider, sans effet derrière une boîte de dialogue ou dans un champ.
 const key=(k,extra={})=>f.listeners.get('keydown').at(-1)({key:k,preventDefault(){},target:{tagName:'DIV'},...extra});
 f.run('fmFilter="";');key('a',{ctrlKey:true});assert.equal(f.names().length,6);key('Escape');assert.equal(f.names().length,0);
 key('a',{ctrlKey:true,target:{tagName:'INPUT'}});f.elements.get('#modal').open=true;key('a',{ctrlKey:true});assert.equal(f.names().length,0);
});
test('preview shows images and videos through the safe inline route and text as plain text',async()=>{
 const texts=[],f=fmFixture(async url=>{if(url.includes('inline=1')){texts.push(url);return {ok:true,status:200,text:async()=>'<script>alert(1)</script>'};}return response(200,url.startsWith('/api/areas')?fmAreas:{items:fmSample});});
 await f.run('renderFiles()');f.run('currentPath="Docs & co";');
 const side=name=>{f.context.pick=name;return f.run('fmSel=new Set([pick]);fmSide()');};
 assert.match(side('photo "été".jpg'),/<img class="fm-shot" src="\/api\/download\?area=fichiers&amp;path=Docs%20%26%20co%2Fphoto%20%22%C3%A9t%C3%A9%22\.jpg&amp;inline=1" alt="Aperçu de photo &quot;été&quot;\.jpg">/);
 assert.match(side('clip.mp4'),/<video class="fm-shot" controls preload="metadata" src="[^"]*clip\.mp4&amp;inline=1">/);
 const pdf=side('<img src=x>.pdf');assert.doesNotMatch(pdf,/<img src=x>|fm-shot/);assert.match(pdf,/se télécharge/);assert.match(pdf,/<dt>Type<\/dt><dd>PDF<\/dd>/);
 assert.match(side('Docs & co'),/data-action="fm-open" data-name="Docs &amp; co"/);assert.match(side('Docs & co'),/href="\/api\/archive\?[^"]*name=Docs%20%26%20co">Télécharger en archive/);
 assert.match(side('raccourci'),/Nacre ne le suit pas/);assert.doesNotMatch(side('raccourci'),/fm-link|fm-open/);
 f.run('fmSel=new Set();');assert.match(f.run('fmSide()'),/Sélectionnez un élément/);f.run('fmSel=new Set(["notes.txt","clip.mp4"]);');assert.match(f.run('fmSide()'),/2 éléments sélectionnés/);
 // Texte : lu par la route d'aperçu, posé comme du texte, et ignoré si la sélection a changé entre-temps.
 const box={dataset:{name:'notes.txt'},textContent:'',innerHTML:'vide'};f.elements.set('#fm-text',box);await f.run('fmLoadText()');
 assert.deepEqual([texts.length,box.textContent,box.innerHTML],[1,'<script>alert(1)</script>','vide']);assert.match(texts[0],/path=Docs%20%26%20co%2Fnotes\.txt&inline=1$/);
 const late=f.run('fmLoadText()');box.dataset.name='autre.txt';box.textContent='inchangé';await late;assert.equal(box.textContent,'inchangé');
});
test('moving, trashing and sending act on the selection only, refuse a folder into itself and stop when the folder changes',async()=>{
 const f=fmFixture();await f.run('renderFiles()');f.mount();const modal=f.elements.get('#modal');let shown=0;modal.showModal=()=>shown++;modal.innerHTML='';
 const posts=()=>f.calls.filter(c=>c[1]).map(c=>[c[0],JSON.parse(c[1])]);
 f.run('fmSel=new Set(["notes.txt","Docs & co"]);');await f.run('fmMove([...fmSel],"Docs & co/Sous")');
 assert.deepEqual(posts().at(-1),['/api/move',{area:'fichiers',path:'',names:['notes.txt','Docs & co'],target:'Docs & co/Sous'}]);assert.match(f.elements.get('#toast').textContent,/2 éléments déplacés vers Sous/);assert.equal(f.names().length,0);
 const before=posts().length;await f.run('fmMove(["notes.txt"],"")');await f.run('fmMove([],"x")');assert.equal(posts().length,before);
 // Cible de dépôt : jamais le dossier courant, ni un élément glissé, ni l'un de ses sous-dossiers.
 f.run('fmDrag=["Docs & co"];');const target=dest=>f.run('fmTarget')({target:{closest:()=>({dataset:{fmDrop:dest}})}});
 assert.equal(target(''),null);assert.equal(target('Docs & co'),null);assert.equal(target('Docs & co/Sous'),null);assert.ok(target('Autre'));f.run('fmDrag=null;');assert.equal(target('Autre'),null);
 // Corbeille : confirmation, puis un appel par élément.
 f.run('fmSel=new Set(["notes.txt","clip.mp4"]);fmAskTrash();');assert.equal(shown,1);assert.match(modal.innerHTML,/Mettre 2 éléments en corbeille/);
 const result=await f.run('modalSubmit(new Map())');assert.deepEqual(posts().slice(-2),[['/api/trash',{path:'notes.txt',area:'fichiers'}],['/api/trash',{path:'clip.mp4',area:'fichiers'}]]);assert.equal(result.message,'2 éléments en corbeille.');
 // Déplacer par la boîte de dialogue : les dossiers connus, sauf le courant et la sélection.
 f.run('fmDirs.set("fichiers|Docs & co",["Sous"]);fmSel=new Set(["Docs & co"]);fmAskMove();');assert.equal(shown,1);assert.match(f.elements.get('#toast').textContent,/Ouvrez d’abord le dossier de destination/);
 f.run('fmDirs.set("fichiers|",["Docs & co","Archives <i>"]);fmSel=new Set(["notes.txt"]);fmAskMove();');assert.equal(shown,2);
 assert.deepEqual([...modal.innerHTML.matchAll(/<option value="([^"]*)">/g)].map(m=>m[1]),['Archives &lt;i&gt;','Docs &amp; co','Docs &amp; co/Sous']);assert.doesNotMatch(modal.innerHTML,/<i>/);
 await f.run('modalSubmit(new Map([["target","Docs & co"]]))');assert.deepEqual(posts().at(-1),['/api/move',{area:'fichiers',path:'',names:['notes.txt'],target:'Docs & co'}]);
 // Envoi : un fichier après l'autre ; un changement de dossier arrête la suite ; un lecteur n'envoie rien.
 f.run('sent=[];uploadFile=async file=>{sent.push([file.name,currentPath]);if(file.name==="b.txt")currentPath="ailleurs";if(file.name==="x.txt")throw new Error("Ce nom existe déjà.");};');
 await f.run('fmSend([{name:"x.txt"},{name:"a.txt"},{name:"b.txt"},{name:"c.txt"}])');
 assert.deepEqual(JSON.parse(JSON.stringify(f.run('sent'))),[['x.txt',''],['a.txt',''],['b.txt','']]);assert.match(f.elements.get('#toast').textContent,/^2 fichiers déposés\. Non envoyé : x\.txt : Ce nom existe déjà\. ; envoi arrêté/);assert.equal(f.run('fmBusy'),false);
 const g=fmFixture(null,'viewer');await g.run('renderFiles()');g.run('sent=[];uploadFile=async file=>{sent.push(file.name);};');await g.run('fmSend([{name:"a.txt"}])');await g.run('fmMove(["notes.txt"],"x")');g.run('fmSel=new Set(["notes.txt"]);fmAskTrash();fmAskMove();');
 assert.deepEqual([g.run('sent.length'),g.calls.filter(c=>c[1]).length],[0,0]);
});

// Recherche de fichiers par nom : filtre local pendant la saisie, parcours du NAS à la demande.
const fmHits=[{area:'fichiers',path:'',name:'été.md',directory:false,link:false,size:6,modified:1794182400},{area:'fichiers',path:'Photos/Été <b>',name:'Été 2026',directory:true,link:false,size:4096,modified:1794182500},
 {area:'video',path:'extraits',name:'été.mp4',directory:false,link:false,size:9,modified:1794182600},{area:'fichiers',path:'Docs & co',name:'notes.txt',directory:false,link:false,size:10,modified:1794182600},
 {area:'restaurations',path:'',name:'été.md'},null,{area:'fichiers',path:3,name:'x'},{area:'fichiers',path:'',name:''}];
function findFixture(role='admin'){
 const state={urls:[],answer:{items:fmHits,partial:null,visited:42,skipped:[],limit:200},hold:null,usage:null};
 const f=fmFixture(async url=>{state.urls.push(url);if(url.startsWith('/api/files/search')){if(state.hold)await state.hold;return state.status?response(state.status,{error:'Deux recherches sont déjà en cours.'}):response(200,state.answer);}if(url.startsWith('/api/files/usage-spaces'))return response(200,state.spaces);if(url.startsWith('/api/files/usage')){if(state.fail&&url.includes(state.fail))return response(429,{error:'Deux recherches sont déjà en cours.'});if(state.hold)await state.hold;return state.status?response(state.status,{error:'Deux recherches sont déjà en cours.'}):response(200,state.usage);}return response(200,url.startsWith('/api/areas')?fmAreas:{items:fmSample});},role);
 f.state=state;f.list=()=>String(f.elements.get('#fm-list').innerHTML);f.side=()=>String(f.elements.get('#fm-side').innerHTML);
 f.type=text=>f.listeners.get('input').at(-1)({target:{id:'fm-filter',value:text}});
 f.at=(selector,dataset)=>f.listeners.get('click').at(-1)({target:{closest:s=>s===selector?{dataset}:null}});
 f.key=(key,target={})=>f.listeners.get('keydown').at(-1)({key,target,preventDefault(){}});
 f.settle=async()=>{for(let i=0;i<4;i++)await new Promise(resolve=>setImmediate(resolve));};
 f.searches=()=>state.urls.filter(url=>url.startsWith('/api/files/search'));return f;
}
test('the filter stays local while typing and a name search runs only on demand, here or in the whole NAS',async()=>{
 const f=findFixture();await f.run('renderFiles()');f.mount();
 assert.match(String(f.elements.get('#content').innerHTML),/id="fm-filter" type="search" placeholder="Filtrer ou rechercher"/);
 f.type('é');assert.doesNotMatch(f.list(),/fm-find/);
 f.type('été');assert.match(f.list(),/class="fm-find"><span>Filtre sur ce dossier\./);assert.match(f.list(),/data-action="fm-find" data-scope="here"><span>Dans cet espace/);assert.match(f.list(),/data-action="fm-find" data-scope="all"><span>Dans tout le NAS/);
 assert.equal(f.searches().length,0);
 // Entrée dans le champ : tout le NAS. Les résultats mal formés ou hors des espaces du compte sont écartés.
 f.key('Enter',{id:'fm-filter',tagName:'INPUT'});assert.match(f.list(),/Recherche en cours/);await f.settle();
 assert.deepEqual(f.searches(),['/api/files/search?q=%C3%A9t%C3%A9']);
 assert.match(f.list(),/<strong>4 résultats<\/strong> pour « été » dans tout le NAS/);assert.match(f.list(),/data-action="fm-find-close"/);
 assert.match(f.list(),/<tr class="fm-hit " data-hit="1"><td>.*Été 2026<\/td><td>Fichiers &lt;b&gt;partagés&lt;\/b&gt; › Photos › Été &lt;b&gt;<\/td><td>—<\/td>/);
 assert.doesNotMatch(f.list(),/<b>|fm-row|draggable|fm-trash|fm-check|fm-note/);assert.match(f.side(),/Sélectionnez un résultat/);
 // Un résultat sélectionné : aperçu et téléchargement depuis son propre emplacement, sans action d'écriture.
 await f.at('.fm-hit',{hit:'0'});assert.match(f.list(),/<tr class="fm-hit sel" data-hit="0">/);
 assert.match(f.side(),/id="fm-text" data-name="été\.md" data-src="\/api\/download\?area=fichiers&amp;path=%C3%A9t%C3%A9\.md&amp;inline=1"/);assert.match(f.side(),/<dt>Emplacement<\/dt><dd>Fichiers &lt;b&gt;partagés&lt;\/b&gt;<\/dd>/);
 assert.match(f.side(),/class="primary small" data-action="fm-reveal" ><span>Afficher dans son dossier/);assert.doesNotMatch(f.side(),/data-inside|rename|fm-trash|fm-open/);
 await f.at('.fm-hit',{hit:'2'});assert.match(f.side(),/<video class="fm-shot" controls preload="metadata" src="\/api\/download\?area=video&amp;path=extraits%2F%C3%A9t%C3%A9\.mp4&amp;inline=1">/);assert.match(f.side(),/href="\/api\/download\?area=video&amp;path=extraits%2F%C3%A9t%C3%A9\.mp4">Télécharger/);
 await f.at('.fm-hit',{hit:'1'});assert.match(f.side(),/data-action="fm-reveal" data-inside="1"><span>Ouvrir ce dossier/);assert.match(f.side(),/href="\/api\/archive\?area=fichiers&amp;path=Photos%2F%C3%89t%C3%A9%20%3Cb%3E&amp;name=%C3%89t%C3%A9%202026">Télécharger en archive/);
 // Le clavier du gestionnaire ne touche à rien pendant une recherche ; Échap la ferme.
 f.key('a',{});f.key('Delete',{});assert.deepEqual(f.names(),[]);
 // Afficher dans son dossier : le dossier parent s'ouvre, l'élément sélectionné, le champ vidé.
 await f.at('.fm-hit',{hit:'3'});await f.at('[data-action]',{action:'fm-reveal'});
 assert.deepEqual(JSON.parse(JSON.stringify(f.run('[area,currentPath,fmFound,fmFilter,[...fmSel]]'))),['fichiers','Docs & co',null,'',['notes.txt']]);
 assert.match(f.state.urls.at(-1),/^\/api\/files\?area=fichiers&path=Docs%20%26%20co$/);
 // Depuis un dossier : la portée « ici » envoie l'espace et le chemin ; ouvrir un dossier trouvé y entre.
 f.mount();f.type('été');assert.match(f.list(),/data-scope="here"><span>Dans ses sous-dossiers/);
 await f.at('[data-action]',{action:'fm-find',scope:'here'});
 assert.equal(f.searches().at(-1),'/api/files/search?q=%C3%A9t%C3%A9&area=fichiers&path=Docs%20%26%20co');assert.match(f.list(),/pour « été » dans « Docs &amp; co » et ses sous-dossiers/);
 await f.at('.fm-hit',{hit:'1'});await f.at('[data-action]',{action:'fm-reveal',inside:'1'});
 assert.deepEqual(JSON.parse(JSON.stringify(f.run('[area,currentPath,fmFound,[...fmSel]]'))),['fichiers','Photos/Été <b>/Été 2026',null,[]]);
 // Double-clic : un fichier s'affiche dans son dossier, un dossier s'ouvre.
 f.mount();f.type('été');await f.at('[data-action]',{action:'fm-find',scope:'all'});
 f.listeners.get('dblclick').at(-1)({target:{closest:s=>s==='.fm-hit'?{dataset:{hit:'2'}}:null}});await f.settle();
 assert.deepEqual(JSON.parse(JSON.stringify(f.run('[area,currentPath,fmFound]'))),['video','extraits',null]);
 // Un compte en lecture seule cherche de la même façon.
 const g=findFixture('viewer');await g.run('renderFiles()');g.mount();g.type('été');await g.at('[data-action]',{action:'fm-find',scope:'all'});assert.match(g.list(),/<strong>4 résultats<\/strong>/);
});
test('a name search says when it stopped early, drops a late or refused answer and can be queued from elsewhere',async()=>{
 const f=findFixture();await f.run('renderFiles()');f.mount();f.type('été');
 f.state.answer={items:[],partial:'time',visited:200000,skipped:['video','inconnu',7],limit:200};await f.at('[data-action]',{action:'fm-find',scope:'here'});
 assert.match(f.list(),/<strong>0 résultat<\/strong> pour « été » dans Fichiers &lt;b&gt;partagés&lt;\/b&gt;/);assert.match(f.list(),/class="fm-note">Recherche arrêtée après 200\s000 éléments parcourus/);
 assert.match(f.list(),/Espace indisponible, non parcouru : Vidéos, inconnu\./);assert.match(f.list(),/Aucun nom ne correspond ici/);
 f.state.answer={items:fmHits.slice(0,1),partial:'results',visited:9,skipped:[],limit:200};await f.at('[data-action]',{action:'fm-find',scope:'all'});
 assert.match(f.list(),/Seuls les 200 premiers résultats sont affichés/);assert.match(f.list(),/<strong>1 résultat<\/strong>/);
 f.state.answer={items:'abîmé'};await f.at('[data-action]',{action:'fm-find',scope:'all'});assert.match(f.list(),/Aucun fichier ni dossier ne porte ce nom/);assert.doesNotMatch(f.list(),/fm-note/);
 // Retoucher le champ ou appuyer sur Échap quitte les résultats ; la réponse d'une recherche quittée est ignorée.
 f.type('ét');assert.equal(f.run('fmFound'),null);assert.match(f.list(),/Filtre sur ce dossier/);
 let release;f.state.hold=new Promise(resolve=>{release=resolve;});f.state.answer={items:fmHits,partial:null,visited:1,skipped:[],limit:200};
 const late=f.at('[data-action]',{action:'fm-find',scope:'all'});assert.match(f.list(),/Recherche de « ét » dans tout le NAS…/);
 f.key('Escape',{});assert.equal(f.run('fmFound'),null);release();await late;assert.equal(f.run('fmFound'),null);assert.doesNotMatch(f.list(),/fm-hit/);
 // Un refus du serveur ramène au dossier et s'annonce ; moins de deux caractères ne partent pas.
 f.state.hold=null;f.state.status=429;await f.at('[data-action]',{action:'fm-find',scope:'all'});
 assert.equal(f.run('fmFound'),null);assert.match(f.elements.get('#toast').textContent,/Deux recherches sont déjà en cours/);
 f.state.status=0;const before=f.searches().length;f.run('fmFilter=" e ";');await f.run('fmFind("all")');assert.equal(f.searches().length,before);assert.match(f.elements.get('#toast').textContent,/au moins deux caractères/);
 // Demandée depuis la recherche globale : le nom arrive dans le champ et la recherche part sur tout le NAS, une seule fois.
 f.state.answer={items:fmHits,partial:null,visited:1,skipped:[],limit:200};f.run('deskApply({find:"  rapport annuel  "});');await f.run('renderFiles()');f.mount();await f.settle();
 assert.equal(f.searches().at(-1),'/api/files/search?q=rapport%20annuel');assert.equal(f.run('fmFilter'),'rapport annuel');
 const count=f.searches().length;await f.run('renderFiles()');await f.settle();assert.equal(f.searches().length,count);
 // Naviguer dans l'arborescence quitte la recherche.
 f.run('fmFilter="été";');await f.run('fmFind("all")');assert.notEqual(f.run('fmFound'),null);await f.run('fmGo("video","")');assert.deepEqual([f.run('fmFound'),f.run('fmFilter')],[null,'']);
});
test('search results can be narrowed by kind, date and size without changing the name or the scope',async()=>{
 const f=findFixture();await f.run('renderFiles()');f.mount();f.run('currentPath="Docs & co";');f.type('été');
 const pick=(key,value,id='fm-ref-'+key)=>f.listeners.get('change').at(-2)({target:{dataset:{refine:key},value,id}});
 const filters=()=>JSON.parse(JSON.stringify(f.run('fmFound&&fmFound.filters')));
 await f.at('[data-action]',{action:'fm-find',scope:'here'});
 // Trois listes sous le titre, aucune active, pas de bouton de retrait.
 assert.match(f.list(),/class="fm-find fm-refine" role="group" aria-label="Affiner les résultats"><label for="fm-ref-kind">Type<\/label><select id="fm-ref-kind" data-refine="kind">/);
 assert.match(f.list(),/<option value="" selected>Tous les types<\/option><option value="folder">Dossiers<\/option>/);assert.match(f.list(),/id="fm-ref-days" data-refine="days">.*Depuis 7 jours/);assert.match(f.list(),/id="fm-ref-min_size" data-refine="min_size">.*Plus de 1 Gio/);
 assert.doesNotMatch(f.list(),/fm-refine-clear|style=/);assert.deepEqual(filters(),{});
 // Un choix relance la même recherche avec le filtre ; le suivant s'ajoute ; nom et portée ne bougent pas.
 const focused=[];f.elements.set('#fm-ref-kind',{focus(){focused.push('kind');}});
 await pick('kind','image');
 assert.equal(f.searches().at(-1),'/api/files/search?q=%C3%A9t%C3%A9&area=fichiers&path=Docs%20%26%20co&kind=image');assert.deepEqual(filters(),{kind:'image'});assert.deepEqual(focused,['kind']);
 assert.match(f.list(),/<option value="image" selected>Images<\/option>/);assert.match(f.list(),/data-action="fm-refine-clear"/);assert.match(f.list(),/pour « été » dans « Docs &amp; co » et ses sous-dossiers/);
 await pick('days','7');await pick('min_size','1048576');
 assert.equal(f.searches().at(-1),'/api/files/search?q=%C3%A9t%C3%A9&area=fichiers&path=Docs%20%26%20co&kind=image&days=7&min_size=1048576');
 // Revenir au choix vide retire ce filtre seul ; une valeur qui n'est pas proposée ou une clé inconnue ne lance rien.
 await pick('days','');assert.match(f.searches().at(-1),/&kind=image&min_size=1048576$/);
 const count=f.searches().length;await pick('kind','exe');await pick('days','8');await pick('autre','1');f.listeners.get('change').at(-2)({target:{id:'fm-upload',files:[]}});assert.equal(f.searches().length,count);
 // Aucun résultat avec des filtres : le message le dit ; plafond atteint : les filtres sont suggérés.
 f.state.answer={items:[],partial:null,visited:9,skipped:[],limit:200};await pick('kind','archive');assert.match(f.list(),/Aucun résultat avec ces filtres\./);
 f.state.answer={items:fmHits.slice(0,1),partial:'results',visited:9,skipped:[],limit:200};await pick('kind','');assert.match(f.list(),/précisez le nom, ou affinez par type, date ou taille\./);
 // Pendant la recherche, les listes sont inactives et un autre choix est ignoré.
 let release;f.state.hold=new Promise(resolve=>{release=resolve;});const slow=pick('kind','video');
 assert.match(f.list(),/data-refine="kind" disabled>/);assert.doesNotMatch(f.list(),/fm-refine-clear/);const during=f.searches().length;await pick('days','30');assert.equal(f.searches().length,during);
 release();await slow;f.state.hold=null;assert.deepEqual(filters(),{kind:'video',min_size:'1048576'});
 // Un affinage refusé laisse les résultats précédents ; retirer les filtres relance sans aucun.
 f.state.status=429;await pick('kind','audio');assert.deepEqual(filters(),{kind:'video',min_size:'1048576'});assert.match(f.elements.get('#toast').textContent,/Deux recherches/);assert.match(f.list(),/fm-hit/);
 f.state.status=0;await f.at('[data-action]',{action:'fm-refine-clear'});assert.equal(f.searches().at(-1),'/api/files/search?q=%C3%A9t%C3%A9&area=fichiers&path=Docs%20%26%20co');assert.deepEqual(filters(),{});
 // Une nouvelle recherche repart sans filtre ; hors recherche, un choix ne fait rien.
 await pick('kind','image');f.type('ét');assert.equal(f.run('fmFound'),null);const idle=f.searches().length;await pick('kind','video');assert.equal(f.searches().length,idle);
 f.type('été');await f.at('[data-action]',{action:'fm-find',scope:'all'});assert.equal(f.searches().at(-1),'/api/files/search?q=%C3%A9t%C3%A9');assert.deepEqual(filters(),{});
});
test('a search by criteria alone needs no name: it ranks the biggest or the latest, here first, then in the whole NAS',async()=>{
 const f=findFixture();await f.run('renderFiles()');f.mount();const box={value:'été'};f.elements.set('#fm-filter',box);f.type('été');
 const pick=(key,value,id='fm-ref-'+key)=>f.listeners.get('change').at(-2)({target:{dataset:{refine:key},value,id}});
 const filters=()=>JSON.parse(JSON.stringify(f.run('fmFound&&fmFound.filters')));
 // Le bouton de la barre d'outils lance, sans nom, les plus gros fichiers du dossier ouvert ; le champ est vidé.
 assert.match(String(f.elements.get('#content').innerHTML),/data-action="fm-criteria" title="Chercher sans nom[^"]*"><span>Par critères</);
 await f.at('[data-action]',{action:'fm-criteria'});
 assert.equal(f.searches().at(-1),'/api/files/search?q=&area=fichiers&path=&sort=size');assert.deepEqual([f.run('fmFilter'),box.value,filters()],['','',{sort:'size'}]);
 assert.match(f.list(),/<strong>4 éléments<\/strong> dans Fichiers &lt;b&gt;partagés&lt;\/b&gt;, les plus gros d’abord/);assert.match(f.list(),/data-action="fm-find-wide"[^>]*><span>Étendre à tout le NAS</);
 // L'ordre se choisit ; sans nom, pas de « pertinence » ; un classement n'est pas un filtre à retirer.
 assert.match(f.list(),/id="fm-ref-sort" data-refine="sort"><option value="size" selected>Les plus gros<\/option><option value="recent">Les plus récents<\/option><\/select>/);assert.doesNotMatch(f.list(),/Par pertinence|fm-refine-clear|style=/);
 await pick('sort','recent');assert.match(f.searches().at(-1),/\?q=&area=fichiers&path=&sort=recent$/);assert.match(f.list(),/les plus récents d’abord/);
 const count=f.searches().length;await pick('sort','');await pick('sort','name');assert.equal(f.searches().length,count);
 // Des dossiers n'ont pas de taille propre : l'ordre par taille n'est plus proposé et le classement passe à la date.
 await pick('sort','size');await pick('kind','folder');assert.match(f.searches().at(-1),/&kind=folder&sort=recent$/);assert.doesNotMatch(f.list(),/Les plus gros/);
 const still=f.searches().length;await pick('sort','size');assert.equal(f.searches().length,still);
 await pick('kind','image');await pick('min_size','1048576');assert.match(f.searches().at(-1),/&kind=image&min_size=1048576&sort=recent$/);
 await f.at('[data-action]',{action:'fm-refine-clear'});assert.match(f.searches().at(-1),/\?q=&area=fichiers&path=&sort=recent$/);assert.deepEqual(filters(),{sort:'recent'});
 // Étendre garde critères et ordre, et quitte le dossier ; le bouton disparaît une fois partout.
 await pick('kind','video');await f.at('[data-action]',{action:'fm-find-wide'});
 assert.equal(f.searches().at(-1),'/api/files/search?q=&kind=video&sort=recent');assert.match(f.list(),/dans tout le NAS, les plus récents d’abord/);assert.doesNotMatch(f.list(),/fm-find-wide/);
 const wide=f.searches().length;await f.at('[data-action]',{action:'fm-find-wide'});assert.equal(f.searches().length,wide);
 // Plus de correspondances que de lignes, ou parcours écourté : c'est dit ; rien trouvé sans filtre : rien à classer.
 f.state.answer={items:fmHits,partial:null,visited:5000,matched:1234,skipped:[],limit:200};await pick('kind','');assert.match(f.list(),/Seuls les 4 plus récents sont affichés, sur 1.234 correspondances\./);
 f.state.answer={items:fmHits,partial:'time',visited:5000,matched:4,skipped:[],limit:200};await pick('sort','size');assert.match(f.list(),/Recherche arrêtée après 5.000 éléments parcourus : le classement ne porte que sur ce qui a été vu\./);assert.doesNotMatch(f.list(),/correspondances/);
 f.state.answer={items:[],partial:null,visited:3,matched:0,skipped:[],limit:200};await pick('sort','recent');assert.match(f.list(),/<strong>0 élément<\/strong>/);assert.match(f.list(),/Rien à classer ici\./);
 // Retoucher le champ quitte les résultats ; un refus ramène au dossier et s'annonce.
 f.type('é');assert.equal(f.run('fmFound'),null);
 f.state.status=429;await assert.rejects(f.run('fmCriteria("here")'));assert.equal(f.run('fmFound'),null);f.state.status=0;
 // Avec un nom, l'ordre s'ajoute à la recherche et « Par pertinence » le retire ; une recherche étendue garde le nom.
 f.state.answer={items:fmHits,partial:null,visited:9,matched:4,skipped:[],limit:200};f.type('été');await f.at('[data-action]',{action:'fm-find',scope:'here'});
 assert.match(f.list(),/<option value="" selected>Par pertinence<\/option><option value="size">Les plus gros<\/option>/);assert.match(f.list(),/<strong>4 résultats<\/strong> pour « été »/);
 await pick('sort','size');assert.equal(f.searches().at(-1),'/api/files/search?q=%C3%A9t%C3%A9&area=fichiers&path=&sort=size');
 await f.at('[data-action]',{action:'fm-find-wide'});assert.equal(f.searches().at(-1),'/api/files/search?q=%C3%A9t%C3%A9&sort=size');
 await pick('sort','');assert.equal(f.searches().at(-1),'/api/files/search?q=%C3%A9t%C3%A9');assert.deepEqual(filters(),{});
 // Depuis la recherche globale : les plus gros fichiers de tout le NAS, à l'ouverture de Fichiers ; un nom l'emporte.
 f.run('deskApply({big:true});');await f.run('renderFiles()');f.mount();await f.settle();
 assert.equal(f.searches().at(-1),'/api/files/search?q=&sort=size');assert.match(f.list(),/dans tout le NAS, les plus gros d’abord/);
 const once=f.searches().length;await f.run('renderFiles()');f.mount();await f.settle();assert.equal(f.searches().length,once);
 f.run('fmQueue(" bilan ",true);');assert.deepEqual([f.run('fmPending'),f.run('fmPendingBig')],['bilan',false]);
});
test('space weights put the kept weighing of every space side by side and weigh a space on demand',async()=>{
 const f=findFixture();await f.run('renderFiles()');f.mount();
 const usages=()=>f.state.urls.filter(url=>url.startsWith('/api/files/usage'));
 f.state.usage={area:'fichiers',path:'',items:[],total:{size:10,count:1,state:'whole'},hidden:{size:0,count:0,state:'whole'},others:{count:0,size:0},partial:null,visited:1,limit:200};
 f.state.spaces={spaces:[{id:'fichiers',name:'Fichiers <b>partagés</b>',kept:{at:1794182400,size:3221225472,count:1204,state:'whole'}},{id:'video',name:'Vidéos',kept:null},
  {id:'ailleurs',name:'Espace inconnu',kept:{at:1,size:9,count:1,state:'whole'}},null,{id:'video'}]};
 // Depuis une pesée : « Comparer les espaces ». Aucune pesée n'est lancée par l'affichage.
 await f.at('[data-action]',{action:'fm-weigh'});await f.settle();assert.match(f.list(),/data-action="fm-spaces" title="[^"]*"><span>Comparer les espaces/);
 const before=usages().length;
 await f.at('[data-action]',{action:'fm-spaces'});await f.settle();
 assert.deepEqual(usages().slice(before),['/api/files/usage-spaces']);
 assert.match(f.list(),/<strong>1 espace pesé sur 2<\/strong> · 3 Gio en tout/);assert.match(f.list(),/Chaque poids est celui de la dernière pesée de l’espace entier/);
 assert.match(f.list(),/Fichiers &lt;b&gt;partagés&lt;\/b&gt;<\/td><td>1[\s ]204 éléments<\/td><td>3 Gio<\/td><td>100 %<\/td><td>[^<—]+<\/td><td><button type="button" class="small" data-action="fm-space-weigh" data-area="fichiers"><span>Repeser<\/span><\/button><button type="button" class="small" data-action="fm-space-open" data-area="fichiers"/);
 assert.match(f.list(),/Vidéos<\/td><td>—<\/td><td>non pesé<\/td><td>—<\/td><td>—<\/td><td><button type="button" class="small" data-action="fm-space-weigh" data-area="video"><span>Peser<\/span><\/button><\/td>/);
 assert.doesNotMatch(f.list(),/Espace inconnu|style=|<b>|data-hit=/);assert.doesNotMatch(f.side(),/fm-weigh|fm-open|Espace/);
 // Peser un espace : sa racine est pesée, puis les pesées gardées sont relues ; une pesée arrêtée s'affiche comme un minimum.
 f.state.spaces.spaces[1].kept={at:1794182500,size:1073741824,count:40,state:'partial'};
 await f.at('[data-action]',{action:'fm-space-weigh',area:'video'});await f.settle();
 assert.deepEqual(usages().slice(-2),['/api/files/usage?area=video&path=','/api/files/usage-spaces']);
 assert.match(f.list(),/<strong>2 espaces pesés sur 2<\/strong> · au moins 4 Gio en tout/);assert.match(f.list(),/Vidéos<\/td><td>40 éléments<\/td><td>au moins 1 Gio<\/td><td>25 %<\/td>/);assert.match(f.list(),/<td>75 %<\/td>/);
 // Un espace inconnu n'est jamais pesé ; un refus est dit et la suite continue ; « tous » pèse chaque espace à la suite.
 let count=usages().length;await f.at('[data-action]',{action:'fm-space-weigh',area:'ailleurs'});await f.settle();assert.equal(usages().length,count);
 f.state.fail='area=fichiers';count=usages().length;
 await f.at('[data-action]',{action:'fm-spaces-all'});await f.settle();await f.settle();
 assert.deepEqual(usages().slice(count),['/api/files/usage?area=fichiers&path=','/api/files/usage-spaces','/api/files/usage?area=video&path=','/api/files/usage-spaces']);
 assert.match(String(f.elements.get('#toast').textContent+' '+JSON.stringify(f.context.toasts||[])),/partagés|déjà en cours/);f.state.fail='';
 // « Détail » ouvre l'espace et pèse ses dossiers ; fermer revient à la liste.
 await f.at('[data-action]',{action:'fm-space-open',area:'video'});f.mount();await f.settle();
 assert.deepEqual([f.run('area'),f.run('currentPath'),usages().at(-1)],['video','','/api/files/usage?area=video&path=']);assert.match(f.list(),/pèse/);
 await f.at('[data-action]',{action:'fm-spaces'});await f.settle();await f.at('[data-action]',{action:'fm-find-close'});assert.doesNotMatch(f.list(),/fm-spaces"|espaces pesés/);
 // Depuis la recherche globale, la vue s'ouvre directement.
 f.run('fmQueue("",false,false,true)');count=usages().length;await f.run('renderFiles()');f.mount();await f.settle();
 assert.deepEqual(usages().slice(count),['/api/files/usage-spaces']);assert.match(f.list(),/espaces pesés sur 2/);
 f.run('fmQueue("",false,true,true)');assert.deepEqual(JSON.parse(f.run('JSON.stringify([fmPendingWeigh,fmPendingSpaces])')),[true,false]);
});

test('folder weights rank what the open folder holds, drill down into a folder, and say what could not be weighed',async()=>{
 const f=findFixture();await f.run('renderFiles()');f.mount();
 const usages=()=>f.state.urls.filter(url=>url.startsWith('/api/files/usage'));
 const sample={area:'fichiers',path:'',items:[{name:'Docs & co',directory:true,link:false,size:3221225472,modified:1794182400,count:1204,state:'whole'},{name:'film <b>.mp4',directory:false,link:false,size:1073741824,modified:1794182500,count:0,state:'whole'},
  {name:'petit.txt',directory:false,link:false,size:5,modified:1794182500,count:0,state:'whole'},{name:'vide.txt',directory:false,link:false,size:0,modified:1,count:0,state:'whole'},{name:'a/b',directory:true,size:9},null,{name:''}],
  total:{size:4831838208,count:1300,state:'whole'},hidden:{size:536870912,count:40,state:'whole'},others:{count:0,size:0},partial:null,visited:1300,limit:200};
 f.state.usage=sample;
 // Depuis le panneau d'un dossier sélectionné : on s'y rend, puis il est pesé.
 f.run('fmSel=new Set(["Docs & co"]);fmRedraw();');assert.match(f.side(),/data-action="fm-weigh" data-name="Docs &amp; co"><span>Peser ce dossier/);
 f.run('fmSel=new Set(["photo \\"été\\".jpg"]);fmRedraw();');assert.doesNotMatch(f.side(),/fm-weigh/);
 await f.at('[data-action]',{action:'fm-weigh',name:'Docs & co'});f.mount();await f.settle();
 assert.equal(usages().at(-1),'/api/files/usage?area=fichiers&path=Docs%20%26%20co');assert.equal(f.run('currentPath'),'Docs & co');
 // Titre, lignes du plus lourd au plus léger, part de chacun ; cachés et corbeille comptés à part ; lignes mal formées écartées.
 assert.match(f.list(),/<strong>« Docs &amp; co » pèse 4,5 Gio<\/strong> pour 1.300 éléments/);assert.match(f.list(),/data-action="fm-weigh-up" ><span>Peser le dossier parent/);
 assert.match(f.list(),/<th>Nom<\/th><th>Contenu<\/th><th>Poids<\/th><th>Part<\/th>/);assert.equal(f.list().match(/class="fm-hit /g).length,4);
 assert.match(f.list(),/Docs &amp; co<\/td><td>1.204 éléments<\/td><td>3 Gio<\/td><td>67 %<\/td>/);assert.match(f.list(),/film &lt;b&gt;\.mp4<\/td><td>—<\/td><td>1 Gio<\/td><td>22 %<\/td>/);
 assert.match(f.list(),/petit\.txt<\/td><td>—<\/td><td>5 o<\/td><td>&lt; 1 %<\/td>|petit\.txt<\/td><td>—<\/td><td>5 o<\/td><td>< 1 %<\/td>/);assert.match(f.list(),/vide\.txt<\/td><td>—<\/td><td>0 o<\/td><td>0 %<\/td>/);
 assert.match(f.list(),/<tr class="fm-rest"><td>Éléments cachés et corbeille<\/td><td>40 éléments<\/td><td>512 Mio<\/td><td>11 %<\/td><\/tr>/);assert.doesNotMatch(f.list(),/Autres éléments|fm-note|fm-refine|fm-find-wide|style=|a\/b/);
 // Une ligne sélectionnée : un dossier se pèse ou s'ouvre, un fichier se montre dans son dossier ; un double-clic sur un dossier le pèse.
 await f.at('.fm-hit',{hit:'0'});assert.match(f.side(),/class="primary small" data-action="fm-weigh" data-name="Docs &amp; co"><span>Peser ce dossier/);assert.match(f.side(),/data-action="fm-reveal" data-inside="1"><span>Ouvrir ce dossier/);assert.doesNotMatch(f.side(),/Afficher dans son dossier/);
 await f.at('.fm-hit',{hit:'1'});assert.match(f.side(),/Afficher dans son dossier/);assert.doesNotMatch(f.side(),/fm-weigh/);
 f.listeners.get('dblclick').at(-1)({target:{closest:s=>s==='.fm-hit'?{dataset:{hit:'0'}}:null}});await f.settle();f.mount();await f.settle();
 assert.equal(usages().at(-1),'/api/files/usage?area=fichiers&path=Docs%20%26%20co%2FDocs%20%26%20co');
 await f.at('[data-action]',{action:'fm-weigh-up'});f.mount();await f.settle();assert.equal(usages().at(-1),'/api/files/usage?area=fichiers&path=Docs%20%26%20co');
 await f.at('[data-action]',{action:'fm-weigh-up'});f.mount();await f.settle();assert.equal(usages().at(-1),'/api/files/usage?area=fichiers&path=');
 assert.match(f.list(),/« Fichiers &lt;b&gt;partagés&lt;\/b&gt; » pèse/);assert.doesNotMatch(f.list(),/fm-weigh-up/);
 // Borne atteinte : minimums, dossiers non pesés, reste compté d'un bloc, et une note qui l'explique.
 f.state.usage={...sample,items:[{name:'A',directory:true,link:false,size:2048,modified:1,count:3,state:'partial'},{name:'B',directory:true,link:false,size:0,modified:1,count:0,state:'waiting'},{name:'C',directory:true,link:false,size:10,modified:1,count:1,state:'étrange'}],
  total:{size:4096,count:9,state:'partial'},hidden:{size:1024,count:2,state:'partial'},others:{count:310,size:1014},partial:'time',visited:200000};
 await f.at('[data-action]',{action:'fm-weigh'});
 assert.match(f.list(),/pèse au moins 4 Kio<\/strong> pour 9 éléments/);assert.match(f.list(),/class="fm-note">Pesée arrêtée après 200.000 éléments parcourus : un poids précédé de « au moins » est un minimum/);
 assert.match(f.list(),/A<\/td><td>3 éléments<\/td><td>au moins 2 Kio<\/td><td>50 %<\/td>/);assert.match(f.list(),/B<\/td><td>—<\/td><td>non pesé<\/td><td>—<\/td>/);assert.match(f.list(),/C<\/td><td>1 élément<\/td><td>au moins 10 o<\/td>/);
 assert.match(f.list(),/<td>Autres éléments, plus légers<\/td><td>310 éléments<\/td><td>1.014 o<\/td><td>25 %<\/td>/);assert.match(f.list(),/Éléments cachés et corbeille<\/td><td>2 éléments<\/td><td>au moins 1 Kio<\/td>/);
 f.state.usage={...sample,items:[],total:{size:7,count:1,state:'partial'},hidden:{size:0,count:0,state:'whole'},partial:null};await f.at('[data-action]',{action:'fm-weigh'});
 assert.match(f.list(),/n’a pas pu être lu en entier/);assert.match(f.list(),/Ce dossier est vide\./);
 // Pendant le calcul ; un refus ramène au dossier et s'annonce ; fermer, Échap et le champ quittent la pesée.
 let release;f.state.hold=new Promise(resolve=>{release=resolve;});f.state.usage=sample;const slow=f.run('fmUsage()');
 assert.match(f.list(),/Pesée de « Fichiers &lt;b&gt;partagés&lt;\/b&gt; »…/);assert.match(f.list(),/Calcul en cours…/);release();await slow;f.state.hold=null;assert.match(f.list(),/fm-usage/);
 f.state.status=429;await assert.rejects(f.run('fmUsage()'));assert.equal(f.run('fmFound'),null);f.state.status=0;
 await f.run('fmUsage()');await f.at('[data-action]',{action:'fm-find-close'});assert.equal(f.run('fmFound'),null);
 await f.run('fmUsage()');f.key('Escape');assert.equal(f.run('fmFound'),null);await f.run('fmUsage()');f.type('do');assert.equal(f.run('fmFound'),null);
 // La pesée n'est pas une recherche : ni filtre ni extension ne partent d'elle.
 await f.run('fmUsage()');const idle=f.state.urls.length;await f.listeners.get('change').at(-2)({target:{dataset:{refine:'kind'},value:'image',id:'fm-ref-kind'}});await f.at('[data-action]',{action:'fm-find-wide'});await f.at('[data-action]',{action:'fm-refine-clear'});assert.equal(f.state.urls.length,idle);
 // Depuis la recherche par critères, un bouton mène au poids des dossiers ; depuis la recherche globale, il s'ouvre avec Fichiers.
 await f.at('[data-action]',{action:'fm-criteria'});assert.match(f.list(),/data-action="fm-weigh" title="Ce que pèse chaque dossier[^"]*"><span>Poids des dossiers/);
 f.type('été');await f.at('[data-action]',{action:'fm-find',scope:'all'});assert.doesNotMatch(f.list(),/fm-weigh/);
 const before=usages().length;f.run('deskApply({weigh:true});');await f.run('renderFiles()');f.mount();await f.settle();assert.equal(usages().length,before+1);assert.match(f.list(),/fm-usage/);
 await f.run('renderFiles()');f.mount();await f.settle();assert.equal(usages().length,before+1);
 f.run('fmQueue("",true,true);');assert.deepEqual([f.run('fmPendingBig'),f.run('fmPendingWeigh')],[true,false]);f.run('fmQueue("x",true,true);');assert.deepEqual([f.run('fmPending'),f.run('fmPendingBig'),f.run('fmPendingWeigh')],['x',false,false]);
});
test('global search offers to look a name up in the files from two characters, and hands it to the Files application',async()=>{
 const f=paletteFixture();f.key('k',{ctrlKey:true});await new Promise(resolve=>setImmediate(resolve));
 // Sans le gestionnaire de fichiers chargé, rien n'est proposé.
 f.type('facture 2026');assert.deepEqual(f.labels(),[]);
 f.context.asked=[];f.context.fmQueue=text=>f.context.asked.push(text);
 f.type('f');assert.doesNotMatch(f.labels().join('|'),/Chercher/);
 f.type('  facture <b>2026</b> ');assert.deepEqual(f.labels(),['Chercher « facture <b>2026</b> » dans les fichiers']);
 assert.match(f.elements.get('#palette-results').innerHTML,/Chercher « facture &lt;b&gt;2026&lt;\/b&gt; » dans les fichiers<small>Fichiers · par nom, dans tout le NAS<\/small>/);
 f.type('place');assert.deepEqual(f.labels(),['Les plus gros fichiers','Poids des dossiers','Poids des espaces','Chercher « place » dans les fichiers']);
 // Elle vient après les résultats habituels et ne lance rien tant qu'elle n'est pas choisie.
 f.type('sauv');assert.deepEqual([f.labels()[0],f.labels().at(-1)],['Sauvegardes','Chercher « sauv » dans les fichiers']);assert.deepEqual(f.context.asked,[]);
 await f.run('runPalette(paletteFound.at(-1))');assert.deepEqual([f.context.asked,f.run('page'),f.elements.get('#palette').hidden],[['sauv'],'files',true]);
 // Dans le bureau, la demande part vers la fenêtre de Fichiers.
 const opened=[];f.context.deskOpenPage=(...args)=>opened.push(args);f.elements.set('#dk-wins',{});
 await f.run('runPalette({find:"rapport"})');assert.deepEqual(JSON.parse(JSON.stringify(opened)),[['files',{find:'rapport'}]]);
 // « Qu'est-ce qui prend de la place ? » : une entrée fixe, trouvée par ses mots, qui lance les plus gros fichiers.
 await f.run('runPalette({big:true})');assert.deepEqual(JSON.parse(JSON.stringify(opened.at(-1))),['files',{big:true}]);
 f.elements.delete('#dk-wins');f.context.asked=[];f.context.fmQueue=(...args)=>f.context.asked.push(args);
 await f.run('runPalette({big:true})');assert.deepEqual([JSON.parse(JSON.stringify(f.context.asked)),f.run('page')],[[['',true]],'files']);
 // « Poids des dossiers » : même chemin, vers la pesée du dossier ouvert.
 f.context.asked=[];await f.run('runPalette({weigh:true})');assert.deepEqual(JSON.parse(JSON.stringify(f.context.asked)),[['',false,true]]);
 f.elements.set('#dk-wins',{});await f.run('runPalette({weigh:true})');assert.deepEqual(JSON.parse(JSON.stringify(opened.at(-1))),['files',{weigh:true}]);
});

// Bureau personnalisable : widgets et fond par compte, fenêtres mémorisées par navigateur.
function prefFixture(fetch,role='admin'){
 const posts=[],f=winFixture(fetch||(async(url,options)=>{if(options?.body)posts.push([url,JSON.parse(options.body)]);return response(200,url.endsWith('/desk')?{widgets:['tasks','storage','<x>',7,'tasks'],background:'lagon'}:url.endsWith('/alerts')?{stale:false,attention:2,active:[{},{}],history:[]}:url.endsWith('/jobs')?[{id:'j',kind:'backup',status:'running',ts:1,progress:'{}'}]:overviewSample);}),role);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/desk-prefs.js'),'utf8'),f.context);
 f.posts=posts;f.run('shell();');f.arm();
 f.root={classes:{},classList:{toggle:(name,on)=>{f.root.classes[name]=on;}}};f.elements.set('#dk-root',f.root);
 f.panel={hidden:true,innerHTML:''};f.elements.set('#desk-prefs',f.panel);f.elements.set('#desk-prefs-open',{attrs:{},setAttribute(k,v){this.attrs[k]=v;}});
 f.pref=(action,data={},inside=true)=>f.listeners.get('click').at(-1)({target:{closest:selector=>selector==='[data-action]'?(action?{dataset:{action,...data}}:null):inside?{}:null}});return f;
}
test('desktop widgets follow the order chosen for the account, and the panel edits and saves it',async()=>{
 const f=prefFixture();f.run('currentOverview=JSON.parse(JSON.stringify(overview));',f.context.overview=overviewSample);
 assert.match(f.html,/class="dk dk-bg-nacre" id="dk-root"/);assert.match(f.html,/id="desk-prefs-open" data-action="desk-prefs-toggle"/);assert.match(f.html,/<section class="dk-panel" id="desk-prefs"[^>]*hidden>/);
 const labels=()=>[...f.run('deskWidgets(currentOverview)').matchAll(/class="dk-wg"[^>]*><small>([^<]+)</g)].map(m=>m[1]);
 assert.deepEqual(labels(),['Stockage libre','Services','Surveillance','Activité récente','Mémoire']);
 // Réponse du NAS assainie : identifiants inconnus et doublons écartés, fond appliqué.
 await f.run('loadDeskPrefs()');assert.deepEqual(JSON.parse(JSON.stringify(f.run('deskPrefs'))),{widgets:['tasks','storage'],background:'lagon'});
 assert.deepEqual([f.root.classes['dk-bg-lagon'],f.root.classes['dk-bg-nacre']],[true,false]);assert.deepEqual(labels(),['Tâches en cours','Stockage libre']);
 assert.equal(JSON.parse(JSON.stringify(f.run('deskPrefsValid({background:"<b>",widgets:"x"})'))).background,'nacre');
 await f.run('refreshBell()');f.run('deskPrefs.widgets=["alerts","tasks"];');
 assert.match(f.run('deskWidgets(currentOverview)'),/<small>Alertes<\/small><b>2 à traiter<\/b><small>2 incident\(s\) actif\(s\)<\/small>/);assert.match(f.run('deskWidgets(currentOverview)'),/<b>1 en cours<\/b>/);
 f.run('deskPrefs.widgets=[];');assert.match(f.run('deskWidgets(currentOverview)'),/Aucun widget affiché/);
 f.run('user.role="viewer";deskPrefs.widgets=["alerts","memory"];');assert.deepEqual(labels(),['Mémoire']);f.run('user.role="admin";deskPrefs.widgets=["tasks","storage"];');
 // Panneau : affichés d'abord et dans l'ordre, flèches bornées, fond choisi marqué.
 await f.pref('desk-prefs-toggle');assert.equal(f.panel.hidden,false);const html=f.panel.innerHTML;
 assert.deepEqual([...html.matchAll(/data-action="desk-widget" data-id="(\w+)" (checked)?/g)].map(m=>[m[1],!!m[2]]),[['tasks',true],['storage',true],['services',false],['camera',false],['activity',false],['memory',false],['alerts',false]]);
 assert.match(html,/data-id="tasks" data-step="-1" aria-label="Monter Tâches en cours" disabled/);assert.match(html,/data-id="storage" data-step="1" aria-label="Descendre Stockage libre" disabled/);
 assert.match(html,/data-action="desk-background" data-id="lagon" aria-pressed="true"/);assert.doesNotMatch(html,/style=/);
 const last=()=>f.posts.at(-1);
 await f.pref('desk-widget',{id:'memory'});assert.deepEqual(last(),['/api/desk',{widgets:['tasks','storage','memory'],background:'lagon'}]);
 await f.pref('desk-widget-move',{id:'memory',step:'-1'});assert.deepEqual(last()[1].widgets,['tasks','memory','storage']);
 await f.pref('desk-widget',{id:'tasks'});assert.deepEqual(last()[1].widgets,['memory','storage']);
 await f.pref('desk-background',{id:'sable'});assert.deepEqual([last()[1].background,f.root.classes['dk-bg-sable'],f.root.classes['dk-bg-lagon']],['sable',true,false]);
 const count=f.posts.length;
 await f.pref('desk-widget',{id:'nowhere'});await f.pref('desk-widget-move',{id:'memory',step:'-1'});await f.pref('desk-widget-move',{id:'storage',step:'1'});await f.pref('desk-widget-move',{id:'absent',step:'1'});await f.pref('desk-background',{id:'rose'});await f.pref('desk-background',{id:'sable'});
 assert.equal(f.posts.length,count);
 await f.pref('desk-prefs-reset');assert.deepEqual(last(),['/api/desk',{widgets:['storage','services','camera','activity','memory'],background:'nacre'}]);
 // Fermeture : clic ailleurs ou Échap ; panneau fermé, plus aucune modification.
 await f.pref('',{},false);assert.equal(f.panel.hidden,true);await f.pref('desk-widget',{id:'tasks'});assert.equal(f.posts.length,count+1);
 await f.pref('desk-prefs-toggle');f.listeners.get('keydown').at(-1)({key:'Escape'});assert.equal(f.panel.hidden,true);
});
test('a refused or late answer never changes the desktop of another session, and a failed save says so',async()=>{
 let mode='fail';const f=prefFixture(async(url,options)=>mode==='fail'&&options?.body?response(500,{error:'Base occupée.'}):response(200,url.endsWith('/desk')?{widgets:['memory'],background:'sable'}:overviewSample));
 await f.pref('desk-prefs-toggle');await f.pref('desk-background',{id:'ardoise'});assert.match(f.elements.get('#toast').textContent,/non enregistrées : Base occupée/);assert.equal(f.root.classes['dk-bg-ardoise'],true);
 let release;const g=prefFixture(url=>url.endsWith('/desk')?new Promise(resolve=>{release=()=>resolve(response(200,{widgets:['memory'],background:'sable'}));}):Promise.resolve(response(200,overviewSample)));
 const pending=g.run('loadDeskPrefs()');g.run('login();');release();await pending.catch(()=>{});assert.deepEqual(JSON.parse(JSON.stringify(g.run('deskPrefs.widgets'))),['storage','services','camera','activity','memory']);
 const h=prefFixture(async url=>url.endsWith('/desk')?response(500,{error:'Indisponible.'}):response(200,overviewSample));await h.run('loadDeskPrefs()');assert.equal(h.run('deskPrefs.background'),'nacre');
});
test('open windows, their place and size come back after a reload, without touching the requested address',async()=>{
 const f=prefFixture();
 // Tant qu'aucune fenêtre n'a été ouverte, rien n'est écrit.
 f.run('deskSync()');assert.equal(f.store['nacre-windows:admin'],undefined);
 await f.run('go("files")');await f.run('go("camera")');await f.desk('desk-view',{app:'cam',view:'replay'});await f.desk('desk-max',{app:'cam'});
 f.run('Object.assign(deskWindow("files"),{left:300,top:40,width:600,height:380,min:true});deskSync();');
 const saved=JSON.parse(f.store['nacre-windows:admin']);
 assert.deepEqual(saved.wins.map(w=>[w.app,w.page,w.view,w.left,w.top,w.width,w.height,w.max,w.min]),[['files','files','',300,40,600,380,false,true],['cam','camera','replay',266,48,0,0,true,false]]);
 await f.desk('desk-close',{app:'files'});assert.deepEqual(JSON.parse(f.store['nacre-windows:admin']).wins.map(w=>w.app),['cam']);
 // Rechargement : le bureau se reconstruit depuis la mémoire, sans réécrire l'adresse ni la mémoire pendant qu'il le fait.
 f.store['nacre-windows:admin']=JSON.stringify(saved);f.run('location.hash="events";shell();');f.arm();f.elements.get('#dk-stage').getBoundingClientRect=()=>({width:800,height:500});
 const before=f.store['nacre-windows:admin'];assert.equal(f.run('deskRestore()'),2);
 assert.deepEqual(f.wins(),[['files','files',true,false],['cam','camera',false,true]]);assert.equal(f.run('deskWindow("cam").view'),'replay');
 assert.deepEqual(JSON.parse(JSON.stringify(f.run('["left","top","width","height"].map(k=>deskWindow("files")[k])'))),[300,40,600,380]);
 assert.deepEqual([f.run('location.hash'),f.store['nacre-windows:admin']],['events',before]);assert.match(f.frames.cam.src,/#camera$/);
 // Valeurs hors de l'écran ou abîmées : ramenées dans la scène, ou oubliées.
 f.store['nacre-windows:admin']=JSON.stringify({wins:[{app:'files',page:'files',left:9000,top:-50,width:20,height:99999},{app:'files',page:'trash'},{app:'cam',page:'files'},{app:'x',page:'nowhere'},null,{app:'settings',page:'settings',left:'12',min:'oui'}]});
 f.run('shell();');f.arm();f.elements.get('#dk-stage').getBoundingClientRect=()=>({width:800,height:500});assert.equal(f.run('deskRestore()'),2);
 assert.deepEqual(JSON.parse(JSON.stringify(f.run('deskWins.map(w=>[w.app,w.left,w.top,w.width,w.height,w.min])'))),[['files',680,0,420,500,false],['settings',266,48,0,0,false]]);
 for(const bad of ['{illisible','null','{"wins":"x"}']){f.store['nacre-windows:admin']=bad;f.run('shell();');f.arm();assert.equal(f.run('deskRestore()'),0);}
 // Un compte en lecture seule ne retrouve pas une fenêtre qu'il ne peut plus ouvrir, et chaque compte a sa mémoire.
 const g=prefFixture(undefined,'viewer');g.run('user.name="reader";');g.store['nacre-windows:reader']=JSON.stringify({wins:[{app:'settings',page:'settings'},{app:'activity',page:'events'}]});g.store['nacre-windows:admin']=JSON.stringify({wins:[{app:'files',page:'files'}]});
 g.run('shell();');g.arm();assert.equal(g.run('deskRestore()'),1);assert.deepEqual(g.wins().map(w=>w[0]),['activity']);
});

// Passages conservés : copie à part d’un extrait, et autonomie du volume vidéo.
const keptSample={camera:'entry',timezone:'UTC',size:7500000,more:false,keep_max:300,name_max:60,items:[
 {id:'entry_b',start:dayStart+7200,end:dayStart+7320,name:'Livraison <b>colis</b>',pending:false,size:7500000,day:'2026-11-08'},
 {id:'entry_a',start:dayStart+3600,end:null,name:'',pending:true,size:null,day:'2026-11-08'}]};
function keptFixture(reply,role='admin'){
 const calls=[],f=cameraFixture(async(url,options)=>{const body=options?.body?JSON.parse(options.body):null;calls.push([url,body]);return reply(url,body);});
 const modal=f.elements.get('#modal');modal.showModal=()=>{modal.open=true;};modal.close=()=>{modal.open=false;};
 f.run(`user={name:"x",role:"${role}"};selectedCamera="entry";cameraDetail=true;playbackData=${JSON.stringify(playbackSample)};`);
 f.calls=calls;f.click=dataset=>f.listeners.get('click').find(fn=>fn.toString().includes('kept-keep'))({target:{closest:()=>({dataset})}});
 return f;
}
test('kept passages list what is kept, play a copy and remove it only after confirmation',async()=>{
 let listed=keptSample;const f=keptFixture(url=>url.startsWith('/api/camera/kept?')?response(200,listed):response(200,{ok:true}));
 const list={innerHTML:''},player={innerHTML:'',scrollIntoView(){}};f.elements.set('#kept-list',list);f.elements.set('#kept-player',player);
 let html=f.run('keptCard()');
 assert.match(html,/<h2>Passages conservés<\/h2>/);assert.match(html,/Recherche des passages conservés/);assert.match(html,/ni la durée de conservation ni un volume plein/);
 let timers=0;f.context.setTimeout=()=>{timers++;return 1;};
 await f.run('keptLoad()');html=list.innerHTML;
 assert.deepEqual(f.calls,[['/api/camera/kept?camera=entry',null]]);
 assert.match(html,/2 passages conservés · 7,2 Mio/);assert.match(html,/Livraison &lt;b&gt;colis&lt;\/b&gt;/);assert.doesNotMatch(html,/<b>colis/);
 assert.match(html,/dimanche 8 novembre, 02:00:00 → 02:02:00/);assert.match(html,/<td>2 min<\/td><td>7,2 Mio<\/td>/);
 assert.match(html,/href="\/api\/camera\/kept-video\?camera=entry&id=entry_b&download=1" download/);
 // Une copie en cours n’offre aucune action, et la liste est relue un peu plus tard.
 assert.match(html,/<strong>Extrait<\/strong>[^]*<td>—<\/td><td>—<\/td><td><span class="badge dim" role="status">Copie en cours<\/span><\/td>/);
 assert.equal((html.match(/data-action="kept-play"/g)||[]).length,1);assert.equal(timers,1);
 await f.click({action:'kept-play',id:'entry_a'});assert.equal(player.innerHTML,'');
 await f.click({action:'kept-play',id:'entry_b'});
 assert.match(player.innerHTML,/<video class="recordvideo" id="kept-video" controls autoplay playsinline src="\/api\/camera\/kept-video\?camera=entry&id=entry_b">/);
 // Retirer : fenêtre de confirmation, puis une seule demande.
 await f.click({action:'kept-remove',id:'entry_a'});assert.equal(f.elements.get('#modal').open,false);
 await f.click({action:'kept-remove',id:'entry_b'});
 assert.match(f.elements.get('#modal').innerHTML,/Retirer ce passage conservé \?/);assert.match(f.elements.get('#modal').innerHTML,/supprimée définitivement/);
 assert.equal(f.calls.length,1);
 const result=await f.run('modalSubmit(new Map())');
 assert.deepEqual(f.calls.at(-1),['/api/camera/unkeep',{camera:'entry',id:'entry_b',confirm:true}]);assert.equal(result.message,'Passage retiré.');
 // Liste vide, réponse illisible, autre caméra.
 listed={...keptSample,items:[],size:0};timers=0;await f.run('keptLoad()');assert.match(list.innerHTML,/Aucun passage conservé\. Lisez un extrait/);assert.equal(timers,0);
 // Après une demande de conservation, la liste est relue même si la copie n’y figure pas encore.
 f.run('keptAwait=1');await f.run('keptLoad()');assert.equal(timers,1);assert.equal(f.run('keptAwait'),0);await f.run('keptLoad()');assert.equal(timers,1);
 listed={camera:'entry',items:'x'};await f.run('keptLoad()');assert.match(list.innerHTML,/class="notice neutral">Réponse illisible/);
 f.run('selectedCamera="garage"');assert.match(f.run('keptCard()'),/Recherche des passages conservés/);assert.equal(f.run('keptData'),null);
});
test('a reader plays and downloads kept passages without keep or remove buttons',async()=>{
 const f=keptFixture(()=>response(200,keptSample),'viewer');
 const list={innerHTML:''};f.elements.set('#kept-list',list);
 await f.run('keptLoad()');
 assert.match(list.innerHTML,/data-action="kept-play"/);assert.doesNotMatch(list.innerHTML,/kept-remove/);
 assert.equal(f.run('keptAction()'),'');
 const player={innerHTML:''};f.elements.set('#playback-player',player);f.run(`playbackShow({start:${dayStart+3700},end:${dayStart+3760}})`);
 assert.match(player.innerHTML,/Télécharger cet extrait/);assert.doesNotMatch(player.innerHTML,/kept-keep/);
 f.run('keptData={camera:"entry",items:[],size:0}');assert.match(f.run('keptList(keptData)'),/Aucun passage conservé pour cette caméra\./);
});
test('the extract being played is kept after a window naming exactly what will be copied',async()=>{
 let refuse='';const f=keptFixture(url=>refuse&&url.endsWith('/keep')?response(409,{error:refuse}):response(200,{ok:true,id:'entry_c'}));
 const player={innerHTML:''};f.elements.set('#playback-player',player);
 // Sans extrait en lecture, rien n’est proposé à conserver.
 f.run('playbackClip=null');await f.click({action:'kept-keep'});assert.equal(f.elements.get('#modal').open,false);assert.match(f.elements.get('#toast').textContent,/Lisez d’abord un extrait/);
 f.run(`playbackShow({start:${dayStart+3700.4},end:${dayStart+3760}})`);
 assert.match(player.innerHTML,/data-action="kept-keep"[^>]*>.*Conserver cet extrait/);
 await f.click({action:'kept-keep'});
 const html=f.elements.get('#modal').innerHTML;
 assert.match(html,/<h2>Conserver cet extrait<\/h2>/);assert.match(html,/dimanche 8 novembre, 01:01:40 → 01:02:40<\/strong> · 1 min/);
 assert.match(html,/name="name" type="text" maxlength="60"/);assert.doesNotMatch(html,/name="name"[^>]*required/);assert.match(html,/occupe de la place tant que vous ne la retirez pas/);
 assert.equal(f.calls.length,0);
 const result=await f.run('modalSubmit(new Map([["name","Portail"]]))');
 assert.deepEqual(f.calls,[['/api/camera/keep',{camera:'entry',start:dayStart+3700.4,end:dayStart+3760,name:'Portail'}]]);
 assert.equal(result.message,'Extrait conservé. La copie se termine en arrière-plan.');assert.equal(f.run('keptAwait'),2);
 // Un refus du serveur reste dans la fenêtre : la relecture n’est pas déplacée.
 refuse='Cet extrait est déjà conservé.';await assert.rejects(f.run('modalSubmit(new Map())'),/déjà conservé/);
 assert.deepEqual(f.calls.at(-1)[1].name,'');
});
test('keeping from the desktop resumes the same extract once the page is redrawn',async()=>{
 const calls=[],f=survFixture(async(url,options)=>{calls.push(url);return url.endsWith('/keep')?response(200,{ok:true}):survReply([])(url);});
 const modal=f.elements.get('#modal');modal.showModal=()=>{};modal.close=()=>{};
 f.run(`selectedCamera="entry";cameraDetail=true;playbackData=${JSON.stringify(playbackSample)};playbackClip={start:${dayStart+3700},end:${dayStart+3760}};keptAsk();`);
 await f.run('modalSubmit(new Map())');
 assert.deepEqual(JSON.parse(f.run('JSON.stringify(survPending)')),{day:'2026-11-08',start:dayStart+3700});
 // La vue Relecture du bureau présente la carte et relit la liste.
 calls.length=0;f.run('deskSetView("cam","replay");');await f.run('renderCamera()');
 assert.match(f.content(),/id="kept"/);assert.ok(f.content().indexOf('id="search"')<f.content().indexOf('id="kept"'));
 assert.ok(calls.includes('/api/camera/kept?camera=entry'));
});
test('video storage states its autonomy, and says so when it cannot be measured',()=>{
 const f=keptFixture(()=>response(200,{}));
 const gib=1024**3,base={available:true,total:3755*gib,free:2791*gib,recorded:41*gib,rate:1.7*gib,hours:1638.1,needed:41*gib,reach_days:null,kept:{count:2,size:15*1024**2},state:'ample',cameras:[]};
 let html=f.run(`keptStorageCard(${JSON.stringify(base)})`);
 assert.match(html,/id="video-storage"><h2>Stockage vidéo<\/h2>/);assert.match(html,/<span class="badge ">Espace suffisant<\/span>/);
 assert.match(html,/<dt>Autonomie<\/dt><dd>environ 68 jours<\/dd>/);assert.match(html,/<dt>Espace libre<\/dt><dd>2,7 Tio sur 3,7 Tio<\/dd>/);
 assert.match(html,/<dt>Débit d’enregistrement<\/dt><dd>40,8 Gio par jour<\/dd>/);assert.match(html,/<dt>Passages conservés<\/dt><dd>2 · 15 Mio<\/dd>/);
 assert.match(html,/<progress class="vs-bar" max="100" value="26" aria-label="Volume vidéo occupé à 26 %">/);assert.match(html,/l’enregistrement continue en effaçant les plus anciens/);
 html=f.run(`keptStorageCard(${JSON.stringify({...base,state:'short',hours:30.2,reach_days:10.5})})`);
 assert.match(html,/<span class="badge warn">Conservation hors de portée<\/span>/);assert.match(html,/remontent à environ 10,5 jours/);assert.match(html,/<dd>environ 30 heures<\/dd>/);
 html=f.run(`keptStorageCard(${JSON.stringify({...base,state:'full',hours:0.4})})`);
 assert.match(html,/<span class="badge alert">Volume plein<\/span>/);assert.match(html,/les passages conservés ne sont pas touchés/);assert.match(html,/<dd>environ 1 heure<\/dd>/);
 html=f.run(`keptStorageCard(${JSON.stringify({...base,state:'unknown',rate:null,hours:null,needed:null})})`);
 html=f.run(`keptStorageCard(${JSON.stringify({...base,state:'unknown',rate:null,hours:null,needed:null,kept:{count:0,size:0}})})`);
 assert.match(html,/Débit non mesuré/);assert.match(html,/<dt>Passages conservés<\/dt><dd>aucun<\/dd>/);assert.match(html,/<dt>Autonomie<\/dt><dd>—<\/dd>/);assert.match(html,/<dt>Débit d’enregistrement<\/dt><dd>—<\/dd>/);
 for(const bad of ['null','{"available":false}',JSON.stringify({...base,state:'x'}),JSON.stringify({...base,free:'<b>'}),JSON.stringify({...base,kept:null})]){
  html=f.run(`keptStorageCard(${bad})`);assert.match(html,/Mesures indisponibles/);assert.doesNotMatch(html,/<b>|vs-bar/);
 }
});

// Personnes, groupes et espaces : un membre ne voit que ses fichiers et son compte ; l’administration décide qui ouvre quoi.
const peopleSample={people:[{name:'admin',role:'admin',active:true,camera:false,groups:[],personal:true},{name:'camille',role:'member',active:true,camera:false,groups:['a1a1a1a1a1a1'],personal:true},
  {name:'bruno',role:'member',active:true,camera:true,groups:[],personal:false},{name:'lecteur',role:'viewer',active:true,camera:false,groups:[],personal:false},{name:'ancien',role:'member',active:false,camera:false,groups:[],personal:true}],
 groups:[{id:'a1a1a1a1a1a1',name:'Compta <b>',members:['camille']}],
 spaces:[{id:'espace_c0c0c0c0c0c0',name:'Bilans <i>',members:{bruno:'read'},groups:{a1a1a1a1a1a1:'write'},former:null},{id:'espace_d0d0d0d0d0d0',name:'Espace de ancien',members:{},groups:{},former:'ancien'}],
 common:{everyone:'read',members:{},groups:{}},orphans:['ancien'],levels:['read','write'],name_max:60};
function peopleFixture(reply,role='admin'){
 const calls=[],f=deskFixture(async(url,options)=>{const body=options?.body?JSON.parse(options.body):null;calls.push([url,body]);return reply?reply(url,body):response(200,url==='/api/spaces'?peopleSample:{ok:true});},role);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/people.js'),'utf8'),f.context);
 const modal=f.elements.get('#modal');modal.showModal=()=>{modal.open=true;};modal.close=()=>{modal.open=false;};
 f.calls=calls;f.run('page="people";');f.content=()=>String(f.elements.get('#content').innerHTML);
 f.act=(action,data={})=>f.listeners.get('click').find(fn=>fn.toString().includes('people-adopt'))({target:{closest:()=>({dataset:{action,...data}})}});
 f.form=(values,all={})=>{const m=new Map(Object.entries(values));m.getAll=key=>all[key]||[];return m;};return f;
}
test('a member opens only files and account in the desktop, plus surveillance when it is opened to them',()=>{
 const f=deskFixture(undefined,'member');
 assert.deepEqual(JSON.parse(f.run('JSON.stringify(deskApps().map(a=>a.id))')),['files','me']);
 assert.equal((f.html.match(/class="dk-dockapp"/g)||[]).length,2);
 let html=f.run('deskWidgets({})');assert.match(html,/Mes fichiers/);assert.match(html,/data-page="account"/);assert.doesNotMatch(html,/Stockage libre|Services|Activité récente|data-page="camera"/);
 f.run('user.camera=true');assert.deepEqual(JSON.parse(f.run('JSON.stringify(deskApps().map(a=>a.id))')),['files','cam','me']);assert.match(f.run('deskWidgets({})'),/data-page="camera"/);
 // Un compte en lecture seule garde ses applications, sans la page d’administration des personnes.
 const g=deskFixture(undefined,'viewer');
 assert.deepEqual(JSON.parse(g.run('JSON.stringify(deskPages(DESK_APPS.find(a=>a.id==="share")).map(p=>p[0]))')),['shares','users']);
 const h=deskFixture();assert.deepEqual(JSON.parse(h.run('JSON.stringify(deskPages(DESK_APPS.find(a=>a.id==="share")).map(p=>p[0]))')),['people','shares','users']);
 assert.equal(h.run('roleName("member")'),'Membre');assert.equal(h.run('roleName("x")'),'Lecture seule');
});
test('files tree groups personal, team and NAS spaces, and a member starts in their own space with tools only where they may write',async()=>{
 const areas=[{id:'espace_e0e0e0e0e0e0',name:'Mon espace',writable:true,kind:'personal'},{id:'espace_c0c0c0c0c0c0',name:'Compta <b>',writable:true,kind:'team'},{id:'espace_d0d0d0d0d0d0',name:'Direction',writable:false,kind:'team'},{id:'fichiers',name:'Fichiers partagés',writable:false,kind:'local'}];
 const f=fmFixture(async url=>response(200,url.startsWith('/api/areas')?areas:{items:[]}),'member');
 await f.run('renderFiles()');
 assert.equal(f.run('area'),'espace_e0e0e0e0e0e0');assert.equal(f.run('fmWritable()'),true);
 const tree=f.run('fmTree()');
 assert.match(tree,/>Mon espace<\/button>[^]*<p class="fm-group">Équipes<\/p>[^]*Compta &lt;b&gt;<\/button>[^]*Direction<small>lecture seule<\/small>[^]*<p class="fm-group">NAS<\/p>[^]*Fichiers partagés<small>lecture seule<\/small>/);
 assert.equal((tree.match(/class="fm-group"/g)||[]).length,2);assert.doesNotMatch(tree,/<b>/);
 assert.match(String(f.elements.get('#content').innerHTML),/data-action="mkdir"/);
 f.run('area="espace_d0d0d0d0d0d0"');await f.run('renderFiles()');assert.equal(f.run('fmWritable()'),false);assert.doesNotMatch(String(f.elements.get('#content').innerHTML),/data-action="mkdir"|fm-send/);
 // Un espace retiré entre-temps : retour au premier espace ouvert, sans rester sur un identifiant mort.
 f.run('area="espace_000000000000"');await f.run('renderFiles()');assert.equal(f.run('area'),'fichiers');
 // Sans espace personnel ni d’équipe, l’arbre reste celui d’avant, sans titres de section.
 const g=fmFixture();await g.run('renderFiles()');assert.doesNotMatch(g.run('fmTree()'),/fm-group/);assert.equal(g.run('area'),'fichiers');
});
test('people page lists who opens what and sends exactly the chosen accesses',async()=>{
 const f=peopleFixture();await f.run('renderPeople()');
 let html=f.content();
 assert.deepEqual(f.calls,[['/api/spaces',null]]);
 assert.match(html,/id="people-persons"/);assert.match(html,/<strong>camille<\/strong><\/td><td><span class="badge dim">Membre<\/span><\/td><td><span class="badge dim">Compta &lt;b&gt;<\/span>/);
 assert.match(html,/<strong>ancien<\/strong> <span class="badge warn">Désactivé<\/span>/);assert.doesNotMatch(html,/<b>|<i>/);
 // Surveillance : bouton pour un membre, mention fixe pour les autres rôles.
 assert.equal((html.match(/data-action="people-camera"/g)||[]).length,3);assert.match(html,/data-name="bruno" data-on="1" aria-pressed="true"/);assert.match(html,/<td>Complète<\/td>/);
 assert.match(html,/Fichiers partagés<\/strong><br><small class="muted">Espace commun<\/small><\/td><td>Tous les membres · lecture/);
 assert.match(html,/Bilans &lt;i&gt;<\/strong><\/td><td>Compta &lt;b&gt; \(groupe\) · écriture<br>bruno · lecture/);
 assert.match(html,/Ancien espace personnel de ancien[^]*Administrateurs seulement/);
 assert.match(html,/L’espace personnel de <strong>ancien<\/strong>, compte désactivé[^]*data-action="people-adopt"[^]*data-name="ancien"/);
 assert.match(html,/ne protègent pas d’une personne qui a la main sur la machine/);
 // Nouvel espace : un niveau par groupe et par personne, les administrateurs n’y figurent pas.
 await f.act('people-space');let modal=f.elements.get('#modal').innerHTML;
 assert.match(modal,/Nouvel espace d’équipe/);assert.match(modal,/name="g:a1a1a1a1a1a1"/);assert.match(modal,/name="m:camille"/);assert.doesNotMatch(modal,/name="m:admin"/);
 let result=await f.run('modalSubmit(sent)',f.context.sent=f.form({name:'Direction','g:a1a1a1a1a1a1':'read','m:camille':'write','m:bruno':'','m:lecteur':'manage'}));
 assert.deepEqual(f.calls.at(-1),['/api/spaces/space',{name:'Direction',members:{camille:'write'},groups:{a1a1a1a1a1a1:'read'}}]);assert.match(result.message,/Espace créé/);
 // Modifier : l’identifiant accompagne, les niveaux actuels sont présélectionnés.
 await f.act('people-space',{id:'espace_c0c0c0c0c0c0'});modal=f.elements.get('#modal').innerHTML;
 assert.match(modal,/value="Bilans &lt;i&gt;"/);assert.match(modal,/name="m:bruno"><option value="">Aucun accès<\/option><option value="read" selected>/);assert.match(modal,/name="g:a1a1a1a1a1a1">[^]*?<option value="write" selected>/);
 f.context.sent=f.form({name:'Bilans'});await f.run('modalSubmit(sent)');assert.deepEqual(f.calls.at(-1),['/api/spaces/space',{id:'espace_c0c0c0c0c0c0',name:'Bilans',members:{},groups:{}}]);
 await f.act('people-space',{id:'espace_inconnu'});
 // Espace commun, groupe, surveillance, reprise.
 await f.act('people-common');f.context.sent=f.form({everyone:'','m:camille':'write'});await f.run('modalSubmit(sent)');assert.deepEqual(f.calls.at(-1),['/api/spaces/common',{everyone:null,members:{camille:'write'},groups:{}}]);
 await f.act('people-group',{id:'a1a1a1a1a1a1'});assert.match(f.elements.get('#modal').innerHTML,/value="camille" checked/);
 f.context.sent=f.form({name:'Compta'},{member:['camille','bruno']});await f.run('modalSubmit(sent)');assert.deepEqual(f.calls.at(-1),['/api/spaces/group',{id:'a1a1a1a1a1a1',name:'Compta',members:['camille','bruno']}]);
 await f.act('people-camera',{name:'bruno',on:'1'});assert.deepEqual(f.calls.at(-2),['/api/spaces/person',{name:'bruno',camera:false}]);
 await f.act('people-camera',{name:'camille',on:''});assert.deepEqual(f.calls.at(-2),['/api/spaces/person',{name:'camille',camera:true}]);
 await f.act('people-adopt',{name:'camille'});const count=f.calls.length;await f.act('people-adopt',{name:'ancien'});assert.match(f.elements.get('#modal').innerHTML,/Aucun fichier n’est déplacé/);assert.equal(f.calls.length,count);
 await f.run('modalSubmit(new Map())');assert.deepEqual(f.calls.at(-1),['/api/spaces/adopt',{name:'ancien'}]);
 await f.act('people-space-delete',{id:'espace_c0c0c0c0c0c0'});assert.match(f.elements.get('#modal').innerHTML,/que vide, corbeille comprise/);await f.run('modalSubmit(new Map())');assert.deepEqual(f.calls.at(-1),['/api/spaces/space-delete',{id:'espace_c0c0c0c0c0c0'}]);
 await f.act('people-group-delete',{id:'a1a1a1a1a1a1'});await f.run('modalSubmit(new Map())');assert.deepEqual(f.calls.at(-1),['/api/spaces/group-delete',{id:'a1a1a1a1a1a1'}]);
});
test('people page refuses a non administrator and an unreadable answer, and anyone changes their own password',async()=>{
 const f=peopleFixture(null,'viewer');await f.run('renderPeople()');assert.match(f.content(),/réservée aux administrateurs/);assert.deepEqual(f.calls,[]);
 const g=peopleFixture(url=>response(200,url==='/api/spaces'?{people:'x'}:{ok:true}));await g.run('renderPeople()');assert.match(g.content(),/Réponse illisible/);
 for(const bad of ['null','{}','{"people":[],"groups":[],"spaces":[{"id":"e","name":"n","members":{"a":"manage"},"groups":{}}],"common":{"members":{},"groups":{}},"orphans":[]}'])assert.equal(g.run(`peopleValid(${bad})`),null);
 // Mon compte : les deux saisies doivent concorder avant tout envoi.
 let refuse='';const h=peopleFixture((url,body)=>url==='/api/account'?response(200,{name:'cam <b>',role:'member'}):refuse?response(403,{error:refuse}):response(200,{ok:true}),'member');
 h.run('page="account"');await h.run('renderAccount()');
 assert.match(h.content(),/<h2>cam &lt;b&gt;<\/h2><p><span class="badge dim">Membre<\/span>/);assert.match(h.content(),/id="account-form"/);assert.match(h.content(),/autocomplete="new-password" minlength="12"/);
 const error={textContent:''},send={disabled:false};h.elements.set('#account-error',error);
 const submit=values=>h.listeners.get('submit').find(fn=>fn.toString().includes('account-form'))({target:{getAttribute:()=> 'account-form',values,querySelector:()=>send},preventDefault(){}});
 await submit({current:'ancien',password:'nouveau-mot-de-passe',again:'autre-mot-de-passe'});assert.match(error.textContent,/diffèrent/);assert.equal(h.calls.filter(c=>c[0].endsWith('/password')).length,0);
 refuse='Mot de passe actuel refusé.';await submit({current:'faux',password:'nouveau-mot-de-passe',again:'nouveau-mot-de-passe'});assert.equal(error.textContent,refuse);assert.equal(send.disabled,false);
 refuse='';await submit({current:'ancien',password:'nouveau-mot-de-passe',again:'nouveau-mot-de-passe'});
 assert.deepEqual(h.calls.filter(c=>c[0].endsWith('/password')).at(-1),['/api/account/password',{current:'ancien',password:'nouveau-mot-de-passe'}]);assert.match(h.elements.get('#toast').textContent,/Mot de passe modifié/);
});

// Liens de partage : création depuis Fichiers, liste et révocation, page publique sans compte.
const linksSample={days:[1,7,30,90],password_min:8,links:[
 {id:'a'.repeat(16),name:'Devis <b>.pdf',path:'Offres/Devis <b>.pdf',directory:false,space:'Chantier <i>',by:'camille',created:1794182400,expires:1794787200,expired:false,protected:true,uses:3,last:1794268800},
 {id:'b'.repeat(16),name:'Plans',path:'Plans',directory:true,space:'Chantier <i>',by:'bruno',created:1794182400,expires:1794182500,expired:true,protected:false,uses:0,last:null}]};
function linksFixture(role='member',reply){
 const calls=[],areas=[{id:'espace_c0c0c0c0c0c0',name:'Chantier',writable:true,kind:'team'},{id:'fichiers',name:'Fichiers partagés',writable:false,kind:'local'},{id:'video',name:'Vidéos',writable:true,kind:'local'}];
 const f=fmFixture(async(url,options)=>{const body=options?.body?JSON.parse(options.body):null;calls.push([url,body]);if(reply){const made=reply(url,body);if(made)return made;}
  return response(200,url.startsWith('/api/areas')?areas:url.startsWith('/api/files')?{items:fmSample.filter(i=>i&&i.name)}:url==='/api/links'?linksSample:url.endsWith('/create')?{ok:true,url:'/p/'+'t'.repeat(43),expires:1794787200,name:'notes.txt'}:{ok:true});},role);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/links.js'),'utf8'),f.context);
 const modal=f.elements.get('#modal');modal.showModal=()=>{modal.open=true;};modal.close=()=>{modal.open=false;};
 f.context.location.origin='http://nas.test';f.context.went=[];f.run('go=async target=>{went.push(target);page=target;};area="espace_c0c0c0c0c0c0";');
 f.calls=calls;f.content=()=>String(f.elements.get('#content').innerHTML);
 f.hit=dataset=>f.listeners.get('click').find(fn=>fn.toString().includes('fm-share'))({target:{closest:selector=>selector==='[data-action]'?{dataset}:null}});
 f.links=(action,data={})=>f.listeners.get('click').find(fn=>fn.toString().includes('links-revoke'))({target:{closest:()=>({dataset:{action,...data}})}});return f;
}
test('one selected element is shared by link only where the person writes, and the new link is shown once',async()=>{
 const f=linksFixture();await f.run('renderFiles()');
 f.run('fmSel=new Set(["notes.txt"])');assert.match(f.run('fmBar()'),/data-action="fm-share"[^>]*>.*Partager par lien/);
 // Espace en lecture, espace vidéo, plusieurs éléments, compte en lecture seule : pas de partage.
 f.run('area="fichiers"');assert.doesNotMatch(f.run('fmBar()'),/fm-share/);f.run('area="video"');assert.doesNotMatch(f.run('fmBar()'),/fm-share/);
 f.run('area="espace_c0c0c0c0c0c0";fmSel=new Set(["notes.txt","Docs & co"])');assert.doesNotMatch(f.run('fmBar()'),/fm-share/);
 f.run('fmSel=new Set(["notes.txt"])');
 let timers=[];f.context.setTimeout=fn=>{timers.push(fn);return 1;};
 f.mount();await f.hit({action:'fm-share'});
 const html=f.elements.get('#modal').innerHTML;
 assert.match(html,/<h2>Partager par lien<\/h2>/);assert.match(html,/<strong>notes\.txt<\/strong> · fichier/);assert.match(html,/<option value="7" selected>7 jours<\/option>/);assert.match(html,/minlength="8"/);assert.match(html,/n’est affiché qu’une fois/);
 const before=f.calls.length,result=await f.run('modalSubmit(new Map([["days","30"],["password","un-mot-de-passe"]]))');
 assert.deepEqual(f.calls.at(-1),['/api/links/create',{area:'espace_c0c0c0c0c0c0',path:'notes.txt',days:30,password:'un-mot-de-passe'}]);assert.equal(f.calls.length,before+1);
 assert.match(result.message,/Copiez-le maintenant/);assert.equal(f.run('linkFresh.url'),'http://nas.test/p/'+'t'.repeat(43));
 // La fenêtre passe à l’onglet Liens, où le lien reste affiché jusqu’à ce qu’on le referme.
 timers.forEach(fn=>fn());assert.deepEqual(JSON.parse(JSON.stringify(f.context.went)),['links']);
 await f.run('renderLinks()');assert.match(f.content(),/id="link-fresh"[^]*Lien créé pour « notes\.txt »[^]*value="http:\/\/nas\.test\/p\/t{43}"/);
 await f.links('links-seen');assert.doesNotMatch(f.content(),/link-fresh/);assert.equal(f.run('linkFresh'),null);
 const g=linksFixture('viewer');await g.run('renderFiles()');g.run('fmSel=new Set(["notes.txt"])');assert.doesNotMatch(g.run('fmBar()'),/fm-share/);
 g.run('page="links"');await g.run('renderLinks()');assert.match(g.content(),/demandent un compte qui écrit/);assert.ok(!g.calls.some(c=>c[0]==='/api/links'));
});
test('links page lists what is shared, shows who created it to an administrator only, and revokes after confirmation',async()=>{
 const f=linksFixture('admin');f.run('page="links"');await f.run('renderLinks()');
 let html=f.content();
 assert.match(html,/1 actif\(s\)/);assert.match(html,/<strong>Devis &lt;b&gt;\.pdf<\/strong><br><small class="muted">Chantier &lt;i&gt; · Offres\/Devis &lt;b&gt;\.pdf<\/small><\/td><td>camille<\/td>/);assert.doesNotMatch(html,/<b>|<i>/);
 assert.match(html,/<td>Mot de passe<\/td><td>3<br><small class="muted">dernier : /);assert.match(html,/<tr class="link-old">[^]*<span class="badge dim">Dossier<\/span>[^]*<span class="badge warn">Échu<\/span>[^]*Lien seul[^]*>.*Retirer/);
 assert.match(html,/<th>Créé par<\/th>/);
 await f.links('links-revoke',{id:'z'.repeat(16)});assert.equal(f.elements.get('#modal').open,false);
 await f.links('links-revoke',{id:'a'.repeat(16)});assert.match(f.elements.get('#modal').innerHTML,/Révoquer ce lien \?[^]*cesse aussitôt de fonctionner/);
 const result=await f.run('modalSubmit(new Map())');assert.deepEqual(f.calls.at(-1),['/api/links/revoke',{id:'a'.repeat(16)}]);assert.equal(result.message,'Lien révoqué.');
 await f.links('links-revoke',{id:'b'.repeat(16)});assert.match(f.elements.get('#modal').innerHTML,/déjà échu/);
 // Copie : presse-papiers s’il existe, sinon le lien est sélectionné.
 const input={value:'http://nas.test/p/x',selected:0,select(){this.selected++;}};f.elements.set('#link-url',input);
 f.context.navigator={clipboard:{writeText:async text=>{f.context.copied=text;}}};await f.links('links-copy');assert.equal(f.context.copied,'http://nas.test/p/x');
 f.context.navigator={};await f.links('links-copy');assert.equal(input.selected,1);assert.match(f.elements.get('#toast').textContent,/copiez-le au clavier/);
 // Un membre ne voit pas la colonne de l’auteur ; une réponse illisible est dite.
 const g=linksFixture('member');g.run('page="links"');await g.run('renderLinks()');assert.doesNotMatch(g.content(),/Créé par/);
 const h=linksFixture('member',url=>url==='/api/links'?response(200,{links:[{id:7}]}):null);h.run('page="links"');await h.run('renderLinks()');assert.match(h.content(),/Réponse illisible/);
});
test('public link page shows a file, a folder, a lock or a refusal, and escapes every name',()=>{
 const context=vm.createContext({location:{pathname:'/p/'+'t'.repeat(43)},console});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../console/static/public.js'),'utf8'),context);
 const run=code=>vm.runInContext(code,context);
 assert.equal(run('pubApi("download","a b/c&d")'),'/api/public/'+'t'.repeat(43)+'/download?path=a%20b%2Fc%26d');
 let html=run('pubView({name:"Devis <b>.pdf",directory:false,size:2048,expires:1794787200})');
 assert.match(html,/<h1>Devis &lt;b&gt;\.pdf<\/h1><p>2 Kio<\/p>/);assert.match(html,/href="\/api\/public\/t{43}\/download" download>Télécharger/);assert.match(html,/Disponible jusqu’au/);assert.doesNotMatch(html,/<b>/);
 html=run('pubView({name:"Plans",directory:true,expires:1794787200,items:[{name:"Étage <i>",directory:true},{name:"façade.png",directory:false,size:10},null,{name:7}]},"Sous dossier")');
 assert.match(html,/data-pub-path="">Plans<\/button><span aria-hidden="true">›<\/span><button type="button" data-pub-path="Sous dossier">/);
 assert.match(html,/class="pub-dir" data-pub-path="Sous dossier\/Étage &lt;i&gt;">Étage &lt;i&gt;/);assert.match(html,/download\?path=Sous%20dossier%2Ffa%C3%A7ade\.png" download>Télécharger/);
 assert.match(html,/\/archive" download>Tout télécharger en archive/);assert.equal((html.match(/<tr>/g)||[]).length,3);assert.doesNotMatch(html,/<i>/);
 assert.match(run('pubView({name:"Vide",directory:true,expires:1,items:[]})'),/Ce dossier est vide/);
 html=run('pubLocked({name:"Secret <b>"},"Mot de passe refusé.")');assert.match(html,/id="pub-unlock"/);assert.match(html,/Secret &lt;b&gt;/);assert.match(html,/role="alert">Mot de passe refusé\./);
 html=run('pubGone()');assert.match(html,/Lien indisponible/);assert.match(html,/n’existe pas ou n’est plus valable/);assert.match(run('pubGone("<x>")'),/&lt;x&gt;/);
});
test('a new backup plan protects the common space and the spaces of people, and an existing plan keeps its choices',()=>{
 const f=fixture(async()=>response(200,{}));
 f.run('protectionSources=[{id:"fichiers",name:"Fichiers partagés"},{id:"espaces",name:"Espaces <b>"},{id:"native_x",name:"Volume"}];');
 let html=f.run('dataChoices()');
 assert.match(html,/value="fichiers" checked/);assert.match(html,/value="espaces" checked>Espaces &lt;b&gt;/);assert.doesNotMatch(html,/value="native_x" checked/);
 html=f.run('dataChoices({sources:["fichiers"],configuration:true,video:false})');assert.match(html,/value="fichiers" checked/);assert.doesNotMatch(html,/value="espaces" checked/);
 f.run('protectionSources=[{id:"fichiers",name:"Fichiers partagés"}];');assert.doesNotMatch(f.run('dataChoices()'),/value="espaces"/);
});

