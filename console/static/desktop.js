'use strict';
// Bureau : une fenêtre par application, plusieurs ouvertes à la fois. Chaque fenêtre héberge la console elle-même dans un cadre
// de même origine, en mode « enfant » : les pages existantes y tournent sans modification, chacune avec son propre état.
// L’affichage classique reste disponible, au choix de chaque navigateur.
const DESK_APPS=[
 {id:'files',name:'Fichiers',pages:[['files','Parcourir'],['trash','Corbeille']]},
 {id:'cam',name:'Surveillance',pages:[['camera','Caméras']],views:[['wall','Mur'],['events','Événements'],['replay','Relecture'],['settings','Réglages']]},
 {id:'storage',name:'Stockage',pages:[['storage','Disques'],['native','Volumes et snapshots']]},
 {id:'protect',name:'Protection',pages:[['backups','Sauvegardes'],['snapshots','Points de restauration'],['retention','Conservation',true]]},
 {id:'share',name:'Personnes et partages',pages:[['people','Personnes et espaces',true],['shares','Partages SMB'],['users','Comptes']]},
 {id:'settings',name:'Réglages',pages:[['settings','Général',true],['services','Services'],['updates','Mises à jour',true],['notifications','Notifications',true]]},
 {id:'activity',name:'Activité',pages:[['alerts','Alertes',true],['events','Journal']]},
 {id:'me',name:'Mon compte',pages:[['account','Mon compte']]}];
// Un membre n’ouvre que ses fichiers et son compte ; la surveillance s’ajoute si elle lui est ouverte.
const DESK_MEMBER=['files','me'];
const DESK_ICONS={
 files:'<path d="M3 7h6l2 2h10v10H3z"/>',cam:'<path d="M3 8h12v8H3zM15 11l6-3v8l-6-3"/>',
 storage:'<path d="M4 5h16v14H4zM4 14h16M8 17h.01"/>',protect:'<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
 share:'<circle cx="8" cy="8" r="3"/><path d="M2 20c0-3.5 2.5-6 6-6s6 2.500 6 6M16 5a3 3 0 010 6M17 14c3 0 5 2.5 5 6"/>',
 settings:'<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
 activity:'<path d="M3 12h4l3-8 4 16 3-8h4"/>',
 me:'<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.4 3.6-7 8-7s8 2.600 8 7"/>'};
const DESK_KEY='nacre-shell',DESK_MIN=[420,300];
let deskWins=[],deskZ=10,deskDrag=null,deskTouched=false;
const deskViews={};
// Vues d’une application à page unique : ses onglets changent la vue, pas la page.
function deskViewOf(id){const app=DESK_APPS.find(a=>a.id===id),views=app?.views||[];return views.some(v=>v[0]===deskViews[id])?deskViews[id]:views[0]?.[0]||'';}
function deskSetView(id,view){
 const app=DESK_APPS.find(a=>a.id===id);if(!app?.views?.some(v=>v[0]===view))return;
 deskViews[id]=view;
 if(deskEmbedded())deskParent('deskChildView',id,view);else{const win=deskWindow(id);if(win)win.view=view;deskSync();}
}

function deskMode(){
 if(!user||user.setup_required)return false;
 try{return localStorage.getItem(DESK_KEY)!=='classic';}catch{return true;}
}
function deskChoose(mode){try{localStorage.setItem(DESK_KEY,mode);}catch{}}
// Console chargée dans la fenêtre d’un bureau de même origine : elle n’affiche que son contenu et rend compte à son parent.
function deskEmbedded(){try{return typeof window!=='undefined'&&!!window.parent&&window.parent!==window&&typeof window.parent.deskChildAt==='function';}catch{return false;}}
function deskParent(name,...values){try{return window.parent[name](window,...values);}catch{return undefined;}}
// Les onglets réservés aux administrateurs disparaissent pour un compte en lecture seule, et l’application avec eux si elle est vide.
function deskPages(app){
 if(user?.role==='member'&&!DESK_MEMBER.includes(app.id)&&!(app.id==='cam'&&user.camera))return [];
 return app.pages.filter(p=>!p[2]||user?.role==='admin');
}
function deskApps(){return DESK_APPS.filter(a=>deskPages(a).length);}
function deskApp(name){return deskApps().find(a=>deskPages(a).some(p=>p[0]===name))||null;}
function deskTile(app){return `<span class="dk-tile dk-${app.id}"><svg viewBox="0 0 24 24" aria-hidden="true">${DESK_ICONS[app.id]}</svg></span>`;}
function deskLaunch(cls){return deskApps().map(a=>`<button type="button" class="${cls}" data-action="desk-open" data-app="${a.id}" title="${a.name}">${deskTile(a)}<span>${a.name}</span></button>`).join('');}
function deskWindow(id){return deskWins.find(w=>w.app===id)||null;}
function deskFront(){return deskWins.filter(w=>!w.min).sort((a,b)=>b.z-a.z)[0]||null;}
function deskChild(win){try{const child=$('#dk-frame-'+win.app)?.contentWindow;return child&&typeof child.go==='function'&&child.deskReady?child:null;}catch{return null;}}

function deskShell(){
 deskWins=[];deskTouched=false;
 $('#app').innerHTML=`<div class="dk dk-bg-${typeof deskPrefs==='undefined'?'nacre':deskPrefs.background}" id="dk-root"><header class="dk-bar"><button type="button" class="dk-brand" data-action="desk-home" title="Afficher le bureau">nacre</button><strong id="side-host">${esc(user.nas_name||'NAS')}</strong><small id="side-version">Nacre ${esc(user.app_version||'version non identifiée')}</small><span class="dk-grow"></span>${typeof paletteButton==='function'?paletteButton()+'<span class="dk-grow"></span>':''}${typeof bellButtons==='function'?bellButtons():user.role==='admin'?'<button data-page="alerts" class="small" id="alert-summary">Alertes</button>':''}${typeof deskPrefsButton==='function'?deskPrefsButton():''}<time id="topclock">${date(Date.now()/1000)}</time><div class="account"><div class="avatar">${esc(user.name.slice(0,1).toUpperCase())}</div><span>${esc(user.name)}</span><button type="button" class="dk-switch" data-action="shell-classic" title="Revenir à l’affichage classique, avec le menu à gauche">Classique</button><button data-action="logout" aria-label="Se déconnecter">${icon('logout')}</button></div></header>`+
 `<div class="dk-desk"><div id="zone-prompt">${typeof zonePrompt==='function'?zonePrompt():''}</div><div class="dk-stage" id="dk-stage"><nav class="dk-icons" aria-label="Applications">${deskLaunch('dk-app')}</nav><aside class="dk-widgets" id="dk-widgets" aria-label="État du NAS"></aside><div id="dk-wins"></div><span class="dk-sr" id="crumb"></span><main class="content dk-solo" id="content" hidden></main></div></div>`+
 `<nav class="dk-dock" id="dk-dock" aria-label="Applications ouvertes et raccourcis">${deskLaunch('dk-dockapp')}</nav>${typeof bellButtons==='function'?'<section class="dk-panel" id="bell-panel" aria-label="Centre de notifications" hidden></section>':''}${typeof palettePanel==='function'?palettePanel():''}${typeof deskPrefsPanel==='function'?'<section class="dk-panel" id="desk-prefs" aria-label="Personnaliser le bureau" hidden></section>':''}</div>`;
 if(typeof drawBell==='function')drawBell();
 if(typeof drawPalette==='function'){paletteOpen=false;drawPalette();}
 // Fenêtres retrouvées : tant que l’utilisateur n’a rien fait, ni l’adresse demandée ni la mémoire ne sont réécrites.
 if(typeof deskRestore==='function'){deskPrefsOpen=false;deskRestore();deskTouched=false;loadDeskPrefs().catch(()=>{});}
 deskSync();
}
// Fenêtre enfant : le contenu seul. Les repères que les pages mettent à jour existent, masqués.
function deskChildShell(){
 $('#app').innerHTML='<div class="dk-child"><div id="zone-prompt" hidden></div><span id="crumb" hidden></span><time id="topclock" hidden></time><main class="content" id="content"></main></div>';
 deskApply(deskParent('deskIntent')||{});
 window.deskReady=true;
}
// Intention transmise par le bureau à une fenêtre : vue, caméra à agrandir, espace de fichiers, recherche à lancer.
function deskApply(intent){
 if(!intent||typeof intent!=='object')return;
 if(intent.view)for(const app of DESK_APPS)if(app.views?.some(v=>v[0]===intent.view)&&(!intent.app||intent.app===app.id))deskViews[app.id]=intent.view;
 if(intent.camera&&typeof survOpenCamera==='function'){selectedCamera=String(intent.camera);survFocus=true;deskViews.cam='wall';}
 if(intent.area){area=String(intent.area);currentPath='';}
 if(intent.find&&typeof fmQueue==='function')fmQueue(intent.find);
 else if((intent.big||intent.weigh||intent.spaces)&&typeof fmQueue==='function')fmQueue('',!!intent.big,!!intent.weigh,!!intent.spaces);
}
function deskTabs(win){
 const app=DESK_APPS.find(a=>a.id===win.app),pages=deskPages(app),views=app.views&&pages.length===1?app.views:null;
 return views?views.map(([v,label])=>`<button type="button" role="tab" data-action="desk-view" data-app="${app.id}" data-view="${v}" aria-selected="${v===(win.view||views[0][0])}">${label}</button>`).join(''):pages.length<2?'':pages.map(([p,label])=>`<button type="button" role="tab" data-action="desk-tab" data-app="${app.id}" data-target="${p}" aria-selected="${p===win.page}">${label}</button>`).join('');
}
function deskFrameHtml(win){
 const app=DESK_APPS.find(a=>a.id===win.app);
 const control=(action,label,d)=>`<button type="button" class="dk-wbtn" data-action="${action}" data-app="${app.id}" aria-label="${label}" title="${label}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="${d}"/></svg></button>`;
 return `<section class="dk-win" id="dk-win-${app.id}" data-app="${app.id}" aria-label="${app.name}"><div class="dk-title" data-app="${app.id}">${deskTile(app)}<strong>${app.name}</strong><span class="dk-grow"></span>${control('desk-min','Réduire','M6 18h12')}${control('desk-max','Agrandir ou rétablir','M6 6h12v12H6z')}${control('desk-close','Fermer','M6 6l12 12M18 6L6 18')}</div><div class="dk-tabs" id="dk-tabs-${app.id}" role="tablist"></div><iframe class="dk-frame" id="dk-frame-${app.id}" title="${app.name}" src="/#${win.page}"></iframe><span class="dk-resize" data-app="${app.id}" aria-hidden="true"></span></section>`;
}
// Ouvre la page dans la fenêtre de son application, créée au besoin, et la met devant.
function deskOpenPage(target,intent={}){
 const app=deskApp(target),box=$('#dk-wins');if(!app||!box)return false;
 deskTouched=true;
 let win=deskWindow(app.id);
 if(!win){
  const index=deskWins.length;
  win={app:app.id,page:target,view:intent.view||deskViewOf(app.id),min:false,max:false,z:++deskZ,left:236+(index%4)*30,top:18+(index%4)*30,width:0,height:0,intent:{...intent,app:app.id}};
  deskWins.push(win);box.insertAdjacentHTML('beforeend',deskFrameHtml(win));
 }else{
  win.page=target;win.min=false;win.z=++deskZ;if(intent.view)win.view=intent.view;
  const child=deskChild(win);
  if(child){child.deskApply({...intent,app:app.id});Promise.resolve(child.go(target)).catch(()=>{});}
  else{win.intent={...intent,app:app.id};const frame=$('#dk-frame-'+app.id);if(frame)frame.src='/#'+target;}
 }
 deskSync();return true;
}
// Aiguillage de go() : dans le bureau, une page s’ouvre dans sa fenêtre ; dans une fenêtre, une page d’une autre application remonte au bureau.
function deskRoute(next){
 if(deskEmbedded()){
  const mine=deskParent('deskAppOf'),app=deskApp(next);
  if(next==='home'||(app&&mine&&app.id!==mine)){deskParent('deskChildGo',next);return true;}
  deskParent('deskChildAt',next);return false;
 }
 if(!deskMode()||next==='home'||!$('#dk-wins'))return false;
 if(!deskOpenPage(next))return false;
 // Arrivée directe sur une application : le bureau derrière elle reçoit quand même ses mesures.
 if(!$('#dk-widgets')?.innerHTML)renderDesk().catch(()=>{});
 return true;
}
// Aligne les fenêtres, leurs onglets, le dock et l’adresse sur l’état courant.
function deskSync(){
 if(!user||!$('#dk-stage'))return;
 const front=deskFront(),solo=$('#content');
 for(const win of deskWins){
  const el=$('#dk-win-'+win.app),tabs=$('#dk-tabs-'+win.app);if(!el)continue;
  el.hidden=win.min;el.classList.toggle('max',win.max);el.classList.toggle('front',win===front);
  if(el.style){el.style.zIndex=String(win.z);el.style.left=win.left+'px';el.style.top=win.top+'px';if(win.width){el.style.width=win.width+'px';el.style.height=win.height+'px';}}
  if(tabs){const html=deskTabs(win);tabs.hidden=!html;if(tabs.innerHTML!==html)tabs.innerHTML=html;}
 }
 if(solo)solo.hidden=page==='home';
 document.querySelectorAll('[data-app].dk-dockapp,[data-app].dk-app').forEach(e=>{e.classList.toggle('open',!!deskWindow(e.dataset.app));e.classList.toggle('front',front?.app===e.dataset.app);});
 // L’adresse suit la fenêtre de devant, une fois qu’une fenêtre a été ouverte : au chargement, elle garde la page demandée.
 if(page==='home'&&deskTouched&&!(typeof deskRestoring!=='undefined'&&deskRestoring)&&typeof location!=='undefined')location.hash=front?front.page:'home';
 if(typeof deskRemember==='function')deskRemember();
}
// Change d’affichage en gardant la page regardée : celle de la fenêtre de devant, ou la page classique courante.
function deskSwitch(mode){
 const target=$('#dk-wins')?deskFront()?.page||page:page;
 deskWins=[];deskChoose(mode);shell();refreshStatus().catch(()=>{});
 return go(target);
}
function deskClose(win){const el=$('#dk-win-'+win.app);el?.remove?.();deskWins=deskWins.filter(w=>w!==win);deskSync();}
function deskByChild(child){return deskWins.find(w=>{try{return $('#dk-frame-'+w.app)?.contentWindow===child;}catch{return false;}})||null;}
// Appels reçus des fenêtres enfants (même origine).
function deskIntent(child){const win=deskByChild(child);if(!win)return {};const intent=win.intent||{};win.intent=null;return {...intent,view:intent.view||win.view};}
function deskAppOf(child){return deskByChild(child)?.app||'';}
function deskChildAt(child,next){const win=deskByChild(child);if(!win||!deskApp(next)||deskApp(next).id!==win.app)return;win.page=next;deskSync();}
function deskChildView(child,id,view){const win=deskByChild(child);if(!win||win.app!==id)return;win.view=view;deskSync();}
function deskChildFocus(child){const win=deskByChild(child);if(!win)return;if(typeof closeBell==='function')closeBell();if(typeof closePalette==='function')closePalette();if(typeof closeDeskPrefs==='function')closeDeskPrefs();if(win===deskFront())return;win.z=++deskZ;deskSync();}
function deskChildGo(child,next){if(!deskByChild(child))return;go(next).catch(()=>{});}
// Préférences changées dans une fenêtre : la barre du bureau suit, et les autres fenêtres se rechargent pour prendre le fuseau.
function deskChildPrefs(child,saved){
 if(!deskByChild(child)||!saved||!user)return;
 user.nas_name=saved.name;user.timezone=saved.timezone;user.timezone_unset=false;
 const host=$('#side-host'),clock=$('#topclock');if(host)host.textContent=saved.name;if(clock)clock.textContent=date(Date.now()/1000);
 if(typeof drawZonePrompt==='function')drawZonePrompt();
 deskReload(child);
}
function deskReload(except=null){for(const win of deskWins){try{const child=$('#dk-frame-'+win.app)?.contentWindow;if(child&&child!==except)child.location.reload();}catch{}}}

// Le bureau remplace la vue d’ensemble : mêmes mesures, présentées en widgets qui ouvrent l’application concernée.
function deskWidgets(d){
 const widget=(target,label,value,note,meter='')=>`<button type="button" class="dk-wg" data-page="${target}"><small>${label}</small><b>${value}</b><small>${note}</small>${meter}</button>`;
 if(user?.role==='member')return widget('files','Mes fichiers','Ouvrir','Mon espace et ceux qui me sont ouverts')+(user.camera?widget('camera','Surveillance','Ouvrir','Caméras, en lecture'):'')+widget('account','Mon compte',esc(user.name),'Changer mon mot de passe');
 const meter=(value,total)=>Number.isFinite(value/total)?`<progress value="${Math.round(value/total*100)}" max="100"></progress>`:'';
 const services=Array.isArray(d.services)?d.services:[],running_services=services.filter(s=>s.state==='running').length;
 const fps=Number(d.camera?.camera_fps),events=Array.isArray(d.events)?d.events.slice(0,3):[];
 const attention=typeof bellData==='undefined'?null:bellData.alerts,running=typeof bellRunning==='function'?bellRunning().length:0;
 const parts={
  storage:widget('storage','Stockage libre',sizes(d.disk?.free),`sur ${sizes(d.disk?.total)}`,meter(d.disk?.used,d.disk?.total)),
  services:widget('services','Services',d.services_available?`${running_services} sur ${services.length} en ligne`:'À démarrer',d.services_available?'Partage de fichiers et vidéo':'Services à installer ou à démarrer'),
  camera:widget('camera','Surveillance',d.camera?(Number.isFinite(fps)?`${fps.toLocaleString('fr-FR',{maximumFractionDigits:1})} images/s`:'Sans mesure'):'Aucune caméra',d.camera?(d.camera.id?`Caméra ${esc(d.camera.id)}`:'Caméra principale'):'Ajouter une caméra'),
  activity:widget('events','Activité récente',events.length?esc(events[0].action):'Aucune action',events.length?events.map(e=>`${date(e.ts)} · ${esc(e.username)}`).slice(0,1).join(''):'Le journal est vide'),
  memory:`<div class="dk-wg"><small>Mémoire</small><b>${sizes(d.memory?.used)}</b><small>sur ${sizes(d.memory?.total)} · charge ${Number(d.load?.[0]||0).toLocaleString('fr-FR',{maximumFractionDigits:2})} sur ${esc(d.cpus)} cœurs</small>${meter(d.memory?.used,d.memory?.total)}</div>`,
  alerts:user?.role==='admin'?widget('alerts','Alertes',attention?(attention.attention?`${Number(attention.attention)||0} à traiter`:'Rien à traiter'):'—',attention?.stale?'Contrôle à vérifier':`${(attention?.active||[]).length} incident(s) actif(s)`):'',
  tasks:widget('backups','Tâches en cours',running?`${running} en cours`:'Aucune',running?'Ouvrir le suivi':'Sauvegardes et installations'),
 };
 const order=typeof deskPrefs==='undefined'?['storage','services','camera','activity','memory']:deskPrefs.widgets;
 return order.map(id=>parts[id]||'').join('')||'<p class="dk-notehint">Aucun widget affiché. Le bouton Personnaliser, en haut à droite, permet d’en choisir.</p>';
}
async function renderDesk(){
 clearInterval(imageTimer);
 const generation=sessionGeneration,d=await api('overview');
 if(generation!==sessionGeneration||page!=='home'||!user)return;
 currentOverview=d;
 const host=$('#side-host'),box=$('#dk-widgets');
 if(host)host.textContent=d.host;
 if(box)box.innerHTML=deskWidgets(d);
}

document.addEventListener('click',async e=>{
 const el=e.target.closest?.('[data-action]');if(!el||!user)return;
 const action=el.dataset.action,win=deskWindow(el.dataset.app);
 try{
  if(action==='desk-open'){
   const app=deskApps().find(a=>a.id===el.dataset.app);if(!app)return;
   if(!win)return deskOpenPage(deskPages(app)[0][0]);
   // Le dock bascule : devant, la fenêtre se réduit ; ailleurs ou réduite, elle revient devant.
   if(win===deskFront()&&el.classList?.contains?.('dk-dockapp'))win.min=true;else{win.min=false;win.z=++deskZ;}
   return deskSync();
  }
  if(action==='desk-home'){for(const w of deskWins)w.min=true;return deskSync();}
  if(action==='desk-tab'){if(win)deskOpenPage(el.dataset.target);return;}
  if(action==='desk-view'){
   const app=DESK_APPS.find(a=>a.id===el.dataset.app);if(!win||!app?.views?.some(v=>v[0]===el.dataset.view))return;
   win.view=el.dataset.view;win.z=++deskZ;const child=deskChild(win);
   if(child){child.deskApply({app:app.id,view:win.view});Promise.resolve(child.go(win.page)).catch(()=>{});}else win.intent={...(win.intent||{}),app:app.id,view:win.view};
   return deskSync();
  }
  if(action==='desk-min'){if(win){win.min=true;deskSync();}return;}
  if(action==='desk-max'){if(win){win.max=!win.max;win.z=++deskZ;deskSync();}return;}
  if(action==='desk-close'){if(win)deskClose(win);return;}
  if(action==='shell-classic'||action==='shell-desk')return await deskSwitch(action==='shell-desk'?'desk':'classic');
 }catch(error){if(error.name!=='AbortError')toast(error.message,true);}
});
// Dans une fenêtre enfant, tout appui la met devant.
document.addEventListener('pointerdown',e=>{
 if(deskEmbedded())return void deskParent('deskChildFocus');
 const bar=e.target.closest?.('.dk-title'),grip=e.target.closest?.('.dk-resize'),win=deskWindow((bar||grip)?.dataset.app),el=win&&$('#dk-win-'+win.app),stage=$('#dk-stage');
 if(!win||!el||!stage)return;
 if(win!==deskFront()){win.z=++deskZ;deskSync();}
 if(e.target.closest('button')||win.max||innerWidth<=720)return;
 const box=el.getBoundingClientRect(),area=stage.getBoundingClientRect();
 deskDrag={win,el,resize:!!grip,dx:e.clientX-box.left,dy:e.clientY-box.top,area,box};
 // Pendant le geste, les cadres ne captent plus la souris.
 stage.classList.add('dk-dragging');(bar||grip).setPointerCapture?.(e.pointerId);
});
document.addEventListener('pointermove',e=>{
 if(!deskDrag)return;
 const {win,el,area,box}=deskDrag;
 if(deskDrag.resize){
  win.width=Math.round(Math.max(DESK_MIN[0],Math.min(e.clientX-box.left,area.right-box.left)));win.height=Math.round(Math.max(DESK_MIN[1],Math.min(e.clientY-box.top,area.bottom-box.top)));
  el.style.width=win.width+'px';el.style.height=win.height+'px';return;
 }
 win.left=Math.round(Math.max(120-box.width,Math.min(e.clientX-deskDrag.dx-area.left,area.width-120)));win.top=Math.round(Math.max(0,Math.min(e.clientY-deskDrag.dy-area.top,area.height-60)));
 el.style.left=win.left+'px';el.style.top=win.top+'px';
});
for(const type of ['pointerup','pointercancel'])document.addEventListener(type,()=>{if(!deskDrag)return;deskDrag=null;$('#dk-stage')?.classList.remove('dk-dragging');deskSync();});
document.addEventListener('dblclick',e=>{const bar=e.target.closest?.('.dk-title');if(!bar||e.target.closest('button'))return;const win=deskWindow(bar.dataset.app);if(win){win.max=!win.max;deskSync();}});
