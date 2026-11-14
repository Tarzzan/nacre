'use strict';
// Centre de notifications du bureau : alertes à traiter, tâches en cours et faits récents, visibles depuis toute application.
// Lecture des API existantes ; la prise en compte d’une alerte réutilise l’action de la page Alertes.
const BELL_ACTIVE=['running','queued','deferred'],BELL_DAY=86400,BELL_PAGES={component_install:'services',camera_add:'camera'};
let bellData={alerts:null,jobs:[]},bellOpen=false,bellRequest=0;
const bellSeen=new Map();

function bellParse(text){try{const value=JSON.parse(text||'{}');return value&&typeof value==='object'?value:{};}catch{return {};}}
function bellJobs(){return Array.isArray(bellData.jobs)?bellData.jobs.filter(j=>j&&typeof j==='object'):[];}
function bellRunning(){return bellJobs().filter(j=>BELL_ACTIVE.includes(j.status));}
function bellLabel(job){return jobLabels[job.kind]||String(job.kind||'Tâche');}
function bellTarget(job){return BELL_PAGES[job.kind]||'backups';}
function bellButtons(){
 return `<button type="button" class="dk-bell" id="bell-tasks" data-action="bell-toggle" hidden></button><button type="button" class="dk-bell" id="bell" data-action="bell-toggle" aria-expanded="false" aria-controls="bell-panel" aria-label="Notifications"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 16V11a6 6 0 1112 0v5l2 2H4zM10 21h4"/></svg><span class="dk-count" id="bell-count" hidden></span></button>`;
}
function bellAlert(item){
 const page=titles[item.page]?item.page:'alerts';
 return `<div class="dk-note"><div><span class="badge ${item.acknowledged?'dim':'warn'}">${item.acknowledged?'Pris en compte':'À traiter'}</span> <strong>${esc(item.title)}</strong><small>Depuis le ${date(item.first)}</small></div><div class="dk-noteacts"><button type="button" class="small" data-page="${page}">Ouvrir ${esc(titles[page])}</button>${item.acknowledged?'':button('alert-ack','Prendre en compte',null,'small',`data-id="${esc(item.id)}" data-version="${Number(item.version)||0}"`)}</div></div>`;
}
function bellTask(job){
 const p=bellParse(job.progress),done=Number(p.percent_done);
 const detail=p.bytes_done!==undefined?sizes(p.bytes_done)+(p.total_bytes?' sur '+sizes(p.total_bytes):''):esc(p.message||(job.status==='running'?'En cours':jobStates[job.status]||''));
 return `<button type="button" class="dk-note" data-page="${bellTarget(job)}"><strong>${esc(bellLabel(job))}</strong><small>${Number.isFinite(done)?Math.round(done*100)+' % · ':''}${detail}</small>${Number.isFinite(done)?`<progress max="1" value="${Math.min(Math.max(done,0),1)}"></progress>`:''}</button>`;
}
// Faits des dernières vingt-quatre heures : tâches terminées et incidents revenus à la normale.
function bellRecent(now){
 const jobs=bellJobs().filter(j=>!BELL_ACTIVE.includes(j.status)&&now-j.ts<BELL_DAY).map(j=>({ts:j.ts,page:bellTarget(j),bad:['failed','partial'].includes(j.status),text:`${bellLabel(j)} : ${(jobStates[j.status]||String(j.status)).toLowerCase()}`}));
 const solved=(bellData.alerts?.history||[]).filter(i=>i&&i.resolved&&now-i.resolved<BELL_DAY).map(i=>({ts:i.resolved,page:'alerts',bad:false,text:`Retour à la normale : ${i.title}`}));
 return [...jobs,...solved].sort((a,b)=>b.ts-a.ts).slice(0,5);
}
function bellPanel(now=Date.now()/1000){
 const alerts=bellData.alerts,active=Array.isArray(alerts?.active)?alerts.active:[],running=bellRunning(),recent=bellRecent(now),admin=user?.role==='admin';
 return (admin?`<h3>À traiter</h3>${alerts?.stale?'<p class="dk-notehint">Le contrôle des alertes n’est pas à jour : le dernier état connu est affiché.</p>':''}${active.length?active.map(bellAlert).join(''):`<p class="dk-notehint">${alerts?'Aucun incident en cours.':'Alertes indisponibles pour le moment.'}</p>`}`:'')+
  `<h3>En cours</h3>${running.length?running.map(bellTask).join(''):'<p class="dk-notehint">Aucune tâche en cours.</p>'}`+
  `<h3>Dernières 24 heures</h3>${recent.length?recent.map(r=>`<button type="button" class="dk-note" data-page="${r.page}">${r.bad?'<span class="badge warn">À vérifier</span> ':''}${esc(r.text)}<small>${date(r.ts)}</small></button>`).join(''):'<p class="dk-notehint">Rien à signaler.</p>'}`+
  `<div class="dk-notefoot">${admin?'<button type="button" class="small" data-page="alerts">Toutes les alertes</button>':''}${user.role==='member'?'':'<button type="button" class="small" data-page="events">Journal</button>'}</div>`;
}
function drawBell(){
 const bell=$('#bell'),count=$('#bell-count'),tasks=$('#bell-tasks'),panel=$('#bell-panel');if(!bell||!count||!tasks||!panel)return;
 const attention=Number(bellData.alerts?.attention)||0,running=bellRunning().length,stale=!!bellData.alerts?.stale;
 count.hidden=!attention&&!stale;count.textContent=attention?String(attention):'!';
 bell.setAttribute('aria-label',attention?`Notifications : ${attention} alerte${attention>1?'s':''} à traiter`:stale?'Notifications : contrôle des alertes à vérifier':'Notifications');
 bell.setAttribute('aria-expanded',String(bellOpen));
 tasks.hidden=!running;tasks.textContent=running?`${running} tâche${running>1?'s':''} en cours`:'';
 panel.hidden=!bellOpen;if(bellOpen)panel.innerHTML=bellPanel();
}
async function refreshBell(){
 if(!user)return;
 const generation=sessionGeneration,request=++bellRequest;
 // Une panne passagère d’une des deux lectures garde le dernier état connu ; une session expirée remonte.
 const soft=promise=>promise.catch(error=>{if(error.name==='AbortError'||error.status===401)throw error;return undefined;});
 // Un membre n’a ni alertes ni tâches à suivre : rien n’est demandé pour lui.
 const [alerts,jobs]=await Promise.all([user.role==='admin'?soft(api('alerts')):null,user.role==='member'?null:soft(api('jobs'))]);
 if(generation!==sessionGeneration||!user||request!==bellRequest)return;
 if(alerts&&typeof alerts==='object')bellData.alerts=alerts;else if(alerts===null)bellData.alerts=null;
 if(Array.isArray(jobs)){
  bellData.jobs=jobs;
  for(const job of bellJobs()){
   const before=bellSeen.get(job.id);
   // Une tâche vue en cours puis terminée est annoncée, où que l’on soit dans la console.
   if(BELL_ACTIVE.includes(before)&&!BELL_ACTIVE.includes(job.status))toast(`${bellLabel(job)} : ${(jobStates[job.status]||String(job.status)).toLowerCase()}`,['failed','partial'].includes(job.status));
  }
  bellSeen.clear();for(const job of bellJobs())bellSeen.set(job.id,job.status);
 }
 drawBell();
}
function closeBell(){if(!bellOpen)return;bellOpen=false;drawBell();}

document.addEventListener('click',e=>{
 const target=e.target,toggle=target.closest?.('[data-action="bell-toggle"]');
 if(toggle){bellOpen=!bellOpen;drawBell();if(bellOpen)refreshBell().catch(()=>{});return;}
 // Un clic ailleurs, ou l’ouverture d’une page depuis le panneau, le referme ; « Prendre en compte » le laisse ouvert.
 if(bellOpen&&(!target.closest?.('#bell-panel')||target.closest?.('[data-page]')))closeBell();
});
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeBell();});
