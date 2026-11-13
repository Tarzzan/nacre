'use strict';
// Bureau : coquille à une fenêtre. Les pages existantes deviennent les onglets de sept applications ;
// leur rendu ne change pas. L’affichage classique reste disponible, au choix de chaque navigateur.
const DESK_APPS=[
 {id:'files',name:'Fichiers',pages:[['files','Parcourir'],['trash','Corbeille']]},
 {id:'cam',name:'Surveillance',pages:[['camera','Caméras']]},
 {id:'storage',name:'Stockage',pages:[['storage','Disques'],['native','Volumes et snapshots']]},
 {id:'protect',name:'Protection',pages:[['backups','Sauvegardes'],['snapshots','Points de restauration'],['retention','Conservation',true]]},
 {id:'share',name:'Partages et comptes',pages:[['shares','Partages'],['users','Utilisateurs']]},
 {id:'settings',name:'Réglages',pages:[['settings','Général',true],['services','Services'],['updates','Mises à jour',true],['notifications','Notifications',true]]},
 {id:'activity',name:'Activité',pages:[['alerts','Alertes',true],['events','Journal']]}];
const DESK_ICONS={
 files:'<path d="M3 7h6l2 2h10v10H3z"/>',cam:'<path d="M3 8h12v8H3zM15 11l6-3v8l-6-3"/>',
 storage:'<path d="M4 5h16v14H4zM4 14h16M8 17h.01"/>',protect:'<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
 share:'<circle cx="8" cy="8" r="3"/><path d="M2 20c0-3.5 2.5-6 6-6s6 2.500 6 6M16 5a3 3 0 010 6M17 14c3 0 5 2.5 5 6"/>',
 settings:'<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
 activity:'<path d="M3 12h4l3-8 4 16 3-8h4"/>'};
const DESK_KEY='nacre-shell';
let deskOpen=null,deskMax=false,deskPos=null,deskDrag=null;
const deskLast={};

function deskMode(){
 if(!user||user.setup_required)return false;
 try{return localStorage.getItem(DESK_KEY)!=='classic';}catch{return true;}
}
function deskChoose(mode){try{localStorage.setItem(DESK_KEY,mode);}catch{}}
// Les onglets réservés aux administrateurs disparaissent pour un compte en lecture seule, et l’application avec eux si elle est vide.
function deskPages(app){return app.pages.filter(p=>!p[2]||user?.role==='admin');}
function deskApps(){return DESK_APPS.filter(a=>deskPages(a).length);}
function deskApp(name){return deskApps().find(a=>deskPages(a).some(p=>p[0]===name))||null;}
function deskTile(app){return `<span class="dk-tile dk-${app.id}"><svg viewBox="0 0 24 24" aria-hidden="true">${DESK_ICONS[app.id]}</svg></span>`;}
function deskLaunch(cls){return deskApps().map(a=>`<button type="button" class="${cls}" data-action="desk-open" data-app="${a.id}" title="${a.name}">${deskTile(a)}<span>${a.name}</span></button>`).join('');}

function deskShell(){
 const control=(action,label,d)=>`<button type="button" class="dk-wbtn" data-action="${action}" aria-label="${label}" title="${label}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="${d}"/></svg></button>`;
 $('#app').innerHTML=`<div class="dk"><header class="dk-bar"><button type="button" class="dk-brand" data-page="home" title="Afficher le bureau">nacre</button><strong id="side-host">${esc(user.nas_name||'NAS')}</strong><small id="side-version">Nacre ${esc(user.app_version||'version non identifiée')}</small><span class="dk-grow"></span>${typeof bellButtons==='function'?bellButtons():user.role==='admin'?'<button data-page="alerts" class="small" id="alert-summary">Alertes</button>':''}<time id="topclock">${date(Date.now()/1000)}</time><div class="account"><div class="avatar">${esc(user.name.slice(0,1).toUpperCase())}</div><span>${esc(user.name)}</span><button type="button" class="dk-switch" data-action="shell-classic" title="Revenir à l’affichage classique, avec le menu à gauche">Classique</button><button data-action="logout" aria-label="Se déconnecter">${icon('logout')}</button></div></header>`+
 `<div class="dk-desk"><div id="zone-prompt">${typeof zonePrompt==='function'?zonePrompt():''}</div><div class="dk-stage" id="dk-stage"><nav class="dk-icons" aria-label="Applications">${deskLaunch('dk-app')}</nav><aside class="dk-widgets" id="dk-widgets" aria-label="État du NAS"></aside>`+
 `<section class="dk-win" id="dk-win" hidden aria-labelledby="dk-name"><div class="dk-title" id="dk-title"><span id="dk-tile"></span><strong id="dk-name"></strong><span class="dk-sr" id="crumb"></span><span class="dk-grow"></span>${control('desk-min','Réduire','M6 18h12')}${control('desk-max','Agrandir ou rétablir','M6 6h12v12H6z')}${control('desk-close','Fermer','M6 6l12 12M18 6L6 18')}</div><div class="dk-tabs" id="dk-tabs" role="tablist" hidden></div><main class="content" id="content"></main></section></div></div>`+
 `<nav class="dk-dock" id="dk-dock" aria-label="Applications ouvertes et raccourcis">${deskLaunch('dk-dockapp')}</nav>${typeof bellButtons==='function'?'<section class="dk-panel" id="bell-panel" aria-label="Centre de notifications" hidden></section>':''}</div>`;
 if(typeof drawBell==='function')drawBell();
 deskSync();
}

// Aligne la fenêtre, ses onglets et le dock sur la page courante. Appelé à chaque navigation.
function deskSync(){
 const win=$('#dk-win');if(!win||!user)return;
 const app=deskApp(page),home=page==='home';
 win.hidden=home;
 if(!home){
  if(app){deskOpen=app.id;deskLast[app.id]=page;}
  const pages=app?deskPages(app):[],tabs=$('#dk-tabs');
  $('#dk-name').textContent=app?app.name:(titles[page]||'');
  $('#dk-tile').innerHTML=app?deskTile(app):'';
  tabs.hidden=pages.length<2;
  tabs.innerHTML=pages.length<2?'':pages.map(([p,label])=>`<button type="button" role="tab" data-page="${p}" aria-selected="${p===page}">${label}</button>`).join('');
  win.classList.toggle('max',deskMax);
  if(deskPos&&win.style){win.style.left=deskPos.left+'px';win.style.top=deskPos.top+'px';}
 }
 document.querySelectorAll('[data-app]').forEach(e=>e.classList.toggle('open',e.dataset.app===deskOpen));
}

// Le bureau remplace la vue d’ensemble : mêmes mesures, présentées en widgets qui ouvrent l’application concernée.
function deskWidgets(d){
 const widget=(target,label,value,note,meter='')=>`<button type="button" class="dk-wg" data-page="${target}"><small>${label}</small><b>${value}</b><small>${note}</small>${meter}</button>`;
 const meter=(value,total)=>Number.isFinite(value/total)?`<progress value="${Math.round(value/total*100)}" max="100"></progress>`:'';
 const services=Array.isArray(d.services)?d.services:[],running=services.filter(s=>s.state==='running').length;
 const fps=Number(d.camera?.camera_fps),events=Array.isArray(d.events)?d.events.slice(0,3):[];
 return widget('storage','Stockage libre',sizes(d.disk?.free),`sur ${sizes(d.disk?.total)}`,meter(d.disk?.used,d.disk?.total))+
  widget('services','Services',d.services_available?`${running} sur ${services.length} en ligne`:'À démarrer',d.services_available?'Partage de fichiers et vidéo':'Services à installer ou à démarrer')+
  widget('camera','Surveillance',d.camera?(Number.isFinite(fps)?`${fps.toLocaleString('fr-FR',{maximumFractionDigits:1})} images/s`:'Sans mesure'):'Aucune caméra',d.camera?(d.camera.id?`Caméra ${esc(d.camera.id)}`:'Caméra principale'):'Ajouter une caméra')+
  widget('events','Activité récente',events.length?esc(events[0].action):'Aucune action',events.length?events.map(e=>`${date(e.ts)} · ${esc(e.username)}`).slice(0,1).join(''):'Le journal est vide')+
  `<div class="dk-wg"><small>Mémoire</small><b>${sizes(d.memory?.used)}</b><small>sur ${sizes(d.memory?.total)} · charge ${Number(d.load?.[0]||0).toLocaleString('fr-FR',{maximumFractionDigits:2})} sur ${esc(d.cpus)} cœurs</small>${meter(d.memory?.used,d.memory?.total)}</div>`;
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
 const action=el.dataset.action;
 try{
  if(action==='desk-open'){const app=deskApps().find(a=>a.id===el.dataset.app);if(!app)return;const pages=deskPages(app).map(p=>p[0]);return await go(pages.includes(deskLast[app.id])?deskLast[app.id]:pages[0]);}
  if(action==='desk-min')return await go('home');
  if(action==='desk-close'){deskOpen=null;return await go('home');}
  if(action==='desk-max'){deskMax=!deskMax;return deskSync();}
  if(action==='shell-classic'||action==='shell-desk'){deskChoose(action==='shell-desk'?'desk':'classic');shell();refreshStatus().catch(()=>{});return await go(page);}
 }catch(error){if(error.name!=='AbortError')toast(error.message,true);}
});
// Déplacement par la barre de titre, borné à la scène ; sans effet en plein écran ou sur téléphone.
document.addEventListener('pointerdown',e=>{
 const bar=e.target.closest?.('#dk-title'),win=$('#dk-win'),stage=$('#dk-stage');
 if(!bar||!win||!stage||e.target.closest('button')||deskMax||innerWidth<=720)return;
 const box=win.getBoundingClientRect(),area=stage.getBoundingClientRect();
 deskDrag={dx:e.clientX-box.left,dy:e.clientY-box.top,area,width:box.width};bar.setPointerCapture?.(e.pointerId);
});
document.addEventListener('pointermove',e=>{
 const win=$('#dk-win');if(!deskDrag||!win)return;
 deskPos={left:Math.round(Math.max(120-deskDrag.width,Math.min(e.clientX-deskDrag.dx-deskDrag.area.left,deskDrag.area.width-120))),top:Math.round(Math.max(0,Math.min(e.clientY-deskDrag.dy-deskDrag.area.top,deskDrag.area.height-60)))};
 win.style.left=deskPos.left+'px';win.style.top=deskPos.top+'px';
});
for(const type of ['pointerup','pointercancel'])document.addEventListener(type,()=>{deskDrag=null;});
document.addEventListener('dblclick',e=>{if(e.target.closest?.('#dk-title')&&!e.target.closest('button')){deskMax=!deskMax;deskSync();}});
