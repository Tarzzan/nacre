'use strict';
async function refreshAlertBadge(){
 if(typeof refreshBell==='function'&&typeof deskMode==='function'&&deskMode())return refreshBell();
 const generation=sessionGeneration;
 const d=await api('alerts');
 if(generation!==sessionGeneration||!user)return;
 const badge=$('#alert-summary');if(!badge)return;
 badge.textContent=d.stale?'Alertes · contrôle à vérifier':d.attention?`Alertes · ${d.attention} à traiter`:'Alertes';
 badge.className='small '+(d.attention||d.stale?'alert-attention':'');
}
function alertCard(item){
 const state=item.resolved?'Résolu':item.acknowledged?'Pris en compte':'À traiter';
 return `<article class="card cardpad incident ${item.resolved?'resolved':item.severity}"><div class="cardhead"><h2>${esc(item.title)}</h2><span class="badge ${item.resolved?'':item.acknowledged?'dim':'warn'}">${state}</span></div><p>${item.resolved?'Lors de l’incident : ':''}${esc(item.message)}</p><p class="muted">Détecté le ${date(item.first)}${item.resolved?' · Résolu le '+date(item.resolved):''}${item.acknowledged?' · Pris en compte par '+esc(item.ackby):''}</p><div class="quickactions"><button data-page="${esc(item.page)}">Ouvrir ${esc(titles[item.page])}</button>${!item.resolved&&!item.acknowledged?button('alert-ack','Prendre en compte','check','small',`data-id="${esc(item.id)}" data-version="${item.version}"`):''}</div></article>`;
}
async function renderAlerts(){
 const generation=sessionGeneration;
 const d=await api('alerts');
 if(generation!==sessionGeneration||page!=='alerts'||!user)return;
 const labels={services:'services',cameras:'caméras',backups:'sauvegardes',storage:'volume de Nacre',docker:'accès Docker',video_api:'état vidéo',video_storage:'stockage vidéo'};
 $('#content').innerHTML=heading('Gardez le contrôle.','Incidents locaux, prise en compte et retours à la normale.',button('notification-settings','Notifications','activity','small')+' '+button('alerts-refresh','Actualiser','activity','small'))+
 (d.stale?'<div class="notice neutral"><strong>Le contrôle n’est pas à jour.</strong> Le dernier état connu est conservé. Vérifiez que la console fonctionne en continu ; cette page ne peut pas signaler une panne totale de son propre hôte.</div>':'')+
 (d.unavailable.length?`<div class="notice neutral">Contrôle partiel : ${d.unavailable.map(x=>esc(labels[x]||x)).join(', ')} non vérifiés pendant le dernier passage. Les incidents correspondants ne sont pas clôturés automatiquement.</div>`:'')+
 `<div class="cards"><section class="card cardpad"><div class="metrichead">À traiter</div><div class="metric">${d.attention}</div></section><section class="card cardpad"><div class="metrichead">Incidents actifs</div><div class="metric">${d.active.length}</div></section><section class="card cardpad"><div class="metrichead">Dernier contrôle</div><p>${d.checked?date(d.checked):'Pas encore effectué'}</p><small>Environ toutes les ${d.interval} secondes</small></section></div>`+
 `<section class="incident-list" aria-label="Incidents actifs">${d.active.length?d.active.map(alertCard).join(''):empty(d.stale||d.unavailable.length?'Aucun incident actif enregistré ; certains contrôles restent à vérifier.':'Aucun incident actif détecté.','check')}</section>`+
 `<section class="card"><div class="cardhead"><h2>Retours à la normale</h2><span class="muted">100 derniers incidents résolus</span></div>${d.history.length?d.history.map(alertCard).join(''):empty('Les incidents résolus apparaîtront ici.','activity')}</section>`+
 '<p class="capacity-note">Prendre en compte un incident ne le répare pas et ne masque pas son état actif. Les notifications externes sont facultatives et se configurent avec le bouton Notifications. Les services déjà démarrés restent surveillés, même après un arrêt volontaire.</p>';
}
document.addEventListener('click',async e=>{
 const el=e.target.closest('[data-action]');if(!el)return;
 try{
  if(el.dataset.action==='alerts-refresh'){await renderAlerts();return;}
  if(el.dataset.action==='alert-ack'){
   el.disabled=true;
   await api('alerts/acknowledge',{id:el.dataset.id,version:Number(el.dataset.version)});
   if(page==='alerts')await renderAlerts();
   await refreshAlertBadge();
  }
 }catch(error){if(error.name!=='AbortError')toast(error.message,true);}
 finally{if(el.dataset.action==='alert-ack')el.disabled=false;}
});
