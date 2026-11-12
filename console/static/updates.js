'use strict';
let updateState=null,updateView=0,updateTimer=null,updateBusy=false;
const updateLabels={idle:'Prêt',prepared:'Paquet vérifié',queued:'Installation demandée',backing_up:'Copie préalable',installing:'Installation',verifying:'Vérification du démarrage',rolling_back:'Retour arrière',rolled_back:'Version précédente restaurée',succeeded:'Mise à jour réussie',failed:'Installation non effectuée'};
const updateActive=s=>['queued','backing_up','installing','verifying','rolling_back'].includes(s?.phase);
function updateReport(s){
 return `<section class="card cardpad" aria-live="polite"><div class="row"><h2>Suivi de l’installation</h2><span class="badge ${['failed','rolled_back'].includes(s.phase)?'warn':''}">${esc(updateLabels[s.phase]||'État inconnu')}</span></div>${s.version?`<p><strong>${esc(s.previous_version)}</strong> → <strong>${esc(s.version)}</strong></p>`:'<p>Importez un paquet pour vérifier sa version et sa compatibilité.</p>'}${s.error?`<p role="alert">${esc(s.error)}</p>`:''}${s.phase==='prepared'?'<p>Signature et contenu vérifiés. Une copie du code et de la base sera créée avant installation.</p>'+button('update-apply','Installer cette version','download','primary'):''}${updateActive(s)?'<p>La console peut être indisponible quelques instants. Le suivi reprend automatiquement ; vous pouvez aussi rouvrir cette page.</p>':''}${['succeeded','rolled_back'].includes(s.phase)?button('update-reload','Recharger Nacre','activity','primary'):''}<p id="update-connection" class="muted"></p></section>`;
}
async function renderUpdates(){
 clearTimeout(updateTimer);const generation=sessionGeneration,view=++updateView;
 if(user?.role!=='admin'){$('#content').innerHTML=empty('Les mises à jour sont réservées aux administrateurs.','lock');return;}
 let s;try{s=await api('updates');}catch(error){if(page!=='updates'||view!==updateView||generation!==sessionGeneration)return;if(error.name==='AbortError'||error.status===401||!updateActive(updateState))throw error;s=updateState;}
 if(page!=='updates'||view!==updateView||generation!==sessionGeneration)return;
 updateState=s;
 $('#content').innerHTML=heading('Gardez Nacre à jour.','Vérifiez une version, installez-la et retrouvez le résultat ici.',`<button data-page="settings">Panneau de configuration</button>`)+
 `<div class="control-summary"><span class="badge">Version installée : ${esc(s.current_version)}</span><span>Retour automatique si le démarrage échoue</span></div>`+
 `<section class="card cardpad"><h2>Importer une version Nacre</h2><p>Téléchargez le paquet <strong>.nacre-update</strong> de la version souhaitée sur GitHub, puis sélectionnez-le ici. Nacre vérifie sa signature avant de proposer l’installation.</p><p><a href="https://github.com/Tarzzan/nacre/releases" target="_blank" rel="noopener noreferrer">Consulter les versions Nacre ↗</a></p>${!s.available?`<div class="notice neutral">${esc(s.reason)}</div>`:''}<form id="update-upload" method="post"><div class="field"><label for="update-package">Paquet signé Nacre</label><input type="file" id="update-package" accept=".nacre-update" ${!s.available||updateActive(s)?'disabled':''} required></div><button type="submit" class="primary" ${!s.available||updateActive(s)?'disabled':''}>Vérifier le paquet</button><p id="update-upload-error" class="error" role="alert"></p></form><p class="capacity-note">Ce parcours met à jour le logiciel Nacre. Les changements de schéma, du service natif ou du superviseur nécessitent une installation accompagnée. Les composants Samba et Frigate se gèrent depuis Services.</p></section><div id="update-report">${updateReport(s)}</div>`;
 if(updateActive(s))watchUpdate(view,generation);
}
function watchUpdate(view,generation){
 const current=()=>page==='updates'&&view===updateView&&generation===sessionGeneration;
 const check=async()=>{
  if(!current())return;
  try{
   const s=await api('updates');if(!current())return;
   updateState=s;const target=$('#update-report');if(target)target.innerHTML=updateReport(s);
   if(!updateActive(s))return;
  }catch(error){if(!current()||error.name==='AbortError'||error.status===401)return;const status=$('#update-connection');if(status)status.textContent='Reconnexion à la console en cours…';}
  if(current())updateTimer=setTimeout(check,2000);
 };
 updateTimer=setTimeout(check,1000);return check;
}
async function uploadUpdate(form){
 if(updateBusy)return;
 const file=$('#update-package')?.files?.[0];if(!file)return;
 const generation=sessionGeneration,view=updateView,submit=form.querySelector('[type=submit]');
 if(file.size>updateState.package_limit){$('#update-upload-error').textContent='Le paquet de mise à jour dépasse 32 Mio.';return;}
 updateBusy=true;submit.disabled=true;
 try{
  const response=await fetch('/api/updates/upload',{method:'POST',headers:{'X-CSRF-Token':user.csrf,'Content-Type':'application/octet-stream'},body:file});
  const data=await response.json();if(generation!==sessionGeneration||view!==updateView||page!=='updates')return;
  if(response.status===401){login(data.error);return;}
  if(!response.ok)throw new Error(data.error||'Paquet refusé.');
  await renderUpdates();
 }catch(error){if(generation===sessionGeneration&&page==='updates'&&view===updateView&&$('#update-upload-error'))$('#update-upload-error').textContent=error.message;}
 finally{updateBusy=false;submit.disabled=false;}
}
document.addEventListener('submit',async e=>{if(e.target.getAttribute('id')==='update-upload'){e.preventDefault();await uploadUpdate(e.target);}});
document.addEventListener('click',async e=>{
 const el=e.target.closest('[data-action]');if(!el)return;
 if(el.dataset.action==='update-reload'){location.reload();return;}
 if(el.dataset.action==='update-apply'&&updateState?.phase==='prepared'){
  const id=updateState.id,version=updateState.version;
  confirmAction('Installer Nacre '+version+' ?','La console sera brièvement interrompue ; les transferts web en cours peuvent être coupés. Une copie préalable permettra de restaurer le code et la base si le démarrage échoue. Samba et Frigate continueront de fonctionner.','Installer',async()=>queueUpdate(id));
 }
});

async function queueUpdate(id){
 const previous=updateState;
 try{updateState=await api('updates/apply',{id,confirm:true});}
 catch(error){
  if(error.name==='AbortError'||error.status)throw error;
  // The restart may close HTTP after queuing but before returning its response.
  // Read the durable state again; never retry the installation automatically.
  updateState={...previous,phase:'queued'};
 }
 return {message:'Demande transmise. Vérification du résultat en cours…'};
}
