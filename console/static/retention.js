'use strict';
let retentionProposal=null, retentionGeneration=0, retentionPolicyList=[];

function retentionSummary(p){
 const points=(list,reason)=>list.length?table(['Date','Identifiant',...(reason?['Motif']:[])],list.map(x=>`<tr><td>${date(Date.parse(x.time)/1000)}</td><td><code title="${esc(x.id)}">${esc(x.id.slice(0,12))}</code></td>${reason?`<td>${esc(x.reason||(x.reasons||[]).join(' · '))}</td>`:''}</tr>`)):empty('Aucun point dans cette catégorie.','backup');
 return `<section class="card cardpad"><div class="row"><div><p class="eyebrow">SIMULATION · ${esc(p.name)}</p><h2>Voici ce qui changerait.</h2></div><span class="spacer"></span>${button('retention-confirm','Examiner la confirmation','trash','',p.remove.length?'':'disabled')}${button('retention-enable','Activer après les prochaines sauvegardes',null,'primary')}</div><p>${p.groups} groupe(s) · ${retentionRuleText(p)}. Proposition valable jusqu’à ${date(p.expires)}.</p><div class="retention-counts"><div><strong>${p.keep.length}</strong><span>Conservés par la règle</span></div><div><strong>${p.protected.length}</strong><span>Protégés hors règle</span></div><div><strong>${p.remove.length}</strong><span>À supprimer</span></div></div><p class="capacity-note">Aucun changement n’a encore été appliqué. Le nettoyage récupère les blocs non référencés de l’ensemble du dépôt ; la taille logique des points ne permet pas de prévoir l’espace libéré.</p></section><br><section class="card"><div class="cardhead"><h2>Points qui seraient supprimés</h2></div>${points(p.remove,false)}</section><br><details class="card cardpad"><summary>Voir les points conservés et protégés</summary><h3>Conservés par la règle</h3>${points(p.keep,true)}<h3>Protégés hors règle</h3>${points(p.protected,true)}</details>`;
}

async function renderRetention(){
 if(user?.role!=='admin'){$('#content').innerHTML=empty('La rétention est réservée aux administrateurs.','lock');return;}
 const generation=++retentionGeneration, session=sessionGeneration;
 retentionProposal=null;
 const [repos,jobs,policies]=await Promise.all([api('protection/repositories'),api('jobs'),api('protection/retention-policies')]);
 if(page!=='retention'||session!==sessionGeneration||generation!==retentionGeneration||!$('#content'))return;
 const usable=repos.filter(r=>r.target!=='recovery-detached');
 retentionPolicyList=policies;
 const initialPolicy=policies.find(p=>p.repo===(usable.find(r=>r.id===snapshotRepo)||usable[0])?.id)||{};
 const initialCount=initialPolicy.keep_last??7;
 $('#content').innerHTML=heading('Gardez les versions qui comptent.','Simulez la conservation des points de restauration avant de supprimer les plus anciens.',button('retention-back','Retour aux snapshots','backup'))+
 `<section class="card cardpad"><h2>Règle de conservation</h2><p>Chaque plan, hôte et combinaison de sources et d’options est traité séparément. Les captures partielles, importées ou sans preuve locale de réussite restent protégées.</p>${usable.length?`<form id="retention-form" method="post"><div class="formgrid"><div class="field"><label for="retention-repo">Dépôt chiffré</label><select id="retention-repo" name="repo">${usable.map(r=>`<option value="${esc(r.id)}" ${r.id===snapshotRepo?'selected':''}>${esc(r.name)}</option>`).join('')}</select></div><div class="field"><label for="retention-count">Derniers points réussis à conserver par groupe</label><input id="retention-count" name="keep_last" type="number" min="1" max="1000000" step="1" value="${initialCount}" required></div></div>${retentionCalendarFields(initialPolicy)}<p class="capacity-note">La simulation permet une application unique ou l’activation après les prochaines captures réussies. Les règles automatiques sont désactivées par défaut.</p><button type="submit" class="primary">Simuler sans supprimer</button><p id="retention-error" class="error" role="alert"></p></form>`:empty('Ajoutez un dépôt depuis Snapshots pour préparer une règle.','backup')}</section><br><div id="retention-result" aria-live="polite"></div><br>${retentionPolicies(policies)}<br>${cleanupCard(usable)}<br><section class="card"><div class="cardhead"><h2>Historique des nettoyages</h2>${button('retention-refresh','Actualiser',null,'small')}</div><div id="retention-history">${retentionHistory(jobs)}</div></section><p class="capacity-note">La suppression est définitive dans Nacre. Le traitement continue sans navigateur et vérifie la structure du dépôt après nettoyage. Une interruption peut laisser une opération partielle ; la règle automatique est suspendue et la tâche n’est pas rejouée.</p>`;
}

document.addEventListener('submit',async event=>{
 if(event.target.getAttribute('id')!=='retention-form')return;
 event.preventDefault();
 const form=event.target, submit=form.querySelector('button[type=submit]'), fields=new FormData(form);
 const generation=++retentionGeneration, session=sessionGeneration;
 retentionProposal=null;$('#retention-result').innerHTML='';$('#retention-error').textContent='';submit.disabled=true;
 try{
  const result=await api('protection/retention-preview',{repo:fields.get('repo'),keep_last:Number(fields.get('keep_last')),calendar:{daily:Number(fields.get('daily')||0),weekly:Number(fields.get('weekly')||0),monthly:Number(fields.get('monthly')||0),timezone:fields.get('timezone')||'UTC'}});
  if(page!=='retention'||generation!==retentionGeneration||session!==sessionGeneration||!$('#retention-result'))return;
  retentionProposal=result;$('#retention-result').innerHTML=retentionSummary(result);
 }catch(error){if(page==='retention'&&generation===retentionGeneration&&$('#retention-error'))$('#retention-error').textContent=error.message;}
 finally{submit.disabled=false;}
});

document.addEventListener('input',event=>{
 if(['retention-count','retention-repo','retention-daily','retention-weekly','retention-monthly','retention-timezone'].includes(event.target.id)){
  if(event.target.id==='retention-repo')retentionLoadPolicy(event.target.value);
  retentionGeneration++;retentionProposal=null;
  if($('#retention-result'))$('#retention-result').innerHTML='';
 }
});
document.addEventListener('click',async event=>{
 const el=event.target.closest('[data-action]');if(!el)return;
 try{
  if(el.dataset.action==='retention-open')return await go('retention');
  if(el.dataset.action==='retention-back')return await go('snapshots');
  if(el.dataset.action==='retention-refresh')return await refreshRetentionHistory();
  if(el.dataset.action==='cleanup-simulate'){
   el.disabled=true;
   try{await api('protection/cleanup-preview',{repo:$('#cleanup-repo').value});toast('Simulation lancée. Retrouvez son résultat dans l’historique.');await refreshRetentionHistory();}finally{el.disabled=false;}
   return;
  }
  if(el.dataset.action==='cleanup-review'){
   const job=el.dataset.job, session=sessionGeneration, origin=page;
   const plan=await api('protection/cleanup-preview?job='+encodeURIComponent(job));
   if(page!==origin||session!==sessionGeneration||!user)return;
   return modal('Reprendre le nettoyage',cleanupConfirmation(plan),'Nettoyer le dépôt',f=>api('protection/cleanup-apply',{job,token:plan.token,confirm:f.has('confirm')}));
  }
  if(el.dataset.action==='retention-disable'){
   const repo=el.dataset.repo, version=Number(el.dataset.version);
   return modal('Désactiver la rétention automatique',`<p>Les prochaines captures ne déclencheront plus de nettoyage. Une commande déjà lancée peut se terminer ; les étapes suivantes et les tâches en attente seront bloquées.</p>`,'Désactiver',()=>api('protection/retention-policy',{repo,version,enabled:false}));
  }
  if(el.dataset.action==='retention-enable'&&retentionProposal){
   const p=retentionProposal;
   return modal('Activer après les prochaines sauvegardes',`<p>Dépôt : <strong>${esc(p.name)}</strong>. <strong>${retentionRuleText(p)}</strong>.</p><p>Après chaque nouvelle capture réussie demandée après cette activation, Nacre recalculera les points à supprimer, puis nettoiera le dépôt sans nouvelle confirmation. La simulation montre l’effet actuel ; la sélection évoluera avec les prochaines captures.</p><p>Aucune suppression n’est lancée par ce bouton. Les captures déjà demandées et les sauvegardes partielles ou échouées ne déclenchent rien. Le nettoyage concerne tous les groupes de ce dépôt et les blocs non référencés de l’ensemble du dépôt.</p><div class="checks"><label><input type="checkbox" name="confirm" required>J’autorise ces prochaines suppressions automatiques et le nettoyage du dépôt.</label></div><p class="capacity-note">En cas d’échec ou d’interruption, la règle est suspendue et une alerte locale est créée. Vous pouvez la désactiver à tout moment.</p>`,'Activer la règle',async f=>{
    const result=await api('protection/retention-policy',{repo:p.repo,version:p.policy_version,token:p.token,enabled:true,confirm:f.has('confirm')});retentionProposal=null;return result;
   });
  }
  if(el.dataset.action==='retention-confirm'&&retentionProposal){
   const p=retentionProposal;
   modal('Confirmer la rétention',`<p>Dépôt : <strong>${esc(p.name)}</strong>.</p><p>${retentionRuleText(p)}.</p><p><strong>${p.remove.length} point(s) seront supprimés définitivement.</strong> ${p.keep.length+p.protected.length} point(s) resteront disponibles selon cette simulation.</p><p>Les blocs non référencés de l’ensemble du dépôt seront ensuite nettoyés, y compris ceux d’anciennes suppressions. Les sauvegardes Nacre attendront la fin de cette tâche. L’espace récupérable n’est pas estimé.</p><div class="checks"><label><input type="checkbox" name="confirm" required>Je confirme cette suppression et le nettoyage du dépôt.</label></div><p class="capacity-note">Si les points ou le dépôt ont changé, le traitement sera refusé. Une annulation après démarrage ne recrée pas les points déjà supprimés.</p>`,'Supprimer et nettoyer',async f=>{
    const result=await api('protection/retention-apply',{token:p.token,confirm:f.has('confirm')});retentionProposal=null;return result;
   });
  }
 }catch(error){if(error.name!=='AbortError')toast(error.message,true);}
});

function retentionPolicies(policies){
 return `<section class="card"><div class="cardhead"><h2>Rétention automatique</h2><span class="muted">Après une nouvelle capture réussie</span></div>${policies.length?table(['Dépôt','Conservation par groupe','État',''],policies.map(p=>`<tr><td>${esc(p.name)}</td><td>${retentionRuleText(p)}</td><td><span class="badge ${p.reason?'warn':p.enabled?'':'dim'}">${p.reason?'Suspendue':p.enabled?'Active':'Désactivée'}</span>${p.reason?`<p class="muted">${esc(p.reason)}</p>`:''}</td><td>${p.enabled||p.reason?button('retention-disable','Désactiver',null,'small',`data-repo="${esc(p.repo)}" data-version="${p.version}"`):'Simulez une règle pour l’activer.'}</td></tr>`)):empty('Aucun dépôt configuré.','backup')}</section>`;
}


function cleanupCard(repos){
 return `<section class="card cardpad"><h2>Reprendre le nettoyage</h2><p>Récupérez les blocs laissés par une suppression interrompue. Tous les points encore présents seront conservés. La simulation continue si vous fermez le navigateur.</p>${repos.length?`<div class="field"><label for="cleanup-repo">Dépôt à nettoyer</label><select id="cleanup-repo">${repos.map(r=>`<option value="${esc(r.id)}">${esc(r.name)}</option>`).join('')}</select></div>${button('cleanup-simulate','Simuler le nettoyage',null,'')}<p class="capacity-note">Puis examinez la simulation dans l’historique pour confirmer. Une règle automatique suspendue reste suspendue après le nettoyage.</p>`:empty('Ajoutez un dépôt pour préparer le nettoyage.','backup')}</section>`;
}
function cleanupConfirmation(p){
 return `<p>Dépôt : <strong>${esc(p.name)}</strong> · ${p.points.length} point(s) conservé(s). Simulation valable jusqu’à ${date(p.expires)}.</p><p>Seuls les blocs non référencés seront nettoyés, y compris ceux d’anciennes suppressions. Aucun point encore présent ne sera supprimé. Les points déjà oubliés ne seront pas recréés.</p><details><summary>Points conservés</summary>${table(['Date','Identifiant'],p.points.map(x=>`<tr><td>${date(Date.parse(x.time)/1000)}</td><td><code class="cleanup-point">${esc(x.id)}</code></td></tr>`))}</details><p>Le nettoyage peut durer et retarder les sauvegardes en attente. L’espace récupérable n’est pas estimé ; le contrôle de structure sera exécuté ensuite.</p><div class="checks"><label><input type="checkbox" name="confirm" required>Je confirme le nettoyage définitif des blocs non référencés.</label></div><p class="capacity-note">Si le dépôt ou ses points ont changé, refaites une simulation. Une règle automatique suspendue ne sera pas réactivée.</p>`;
}
function retentionHistory(jobs){
 const rows=jobs.filter(j=>['retention','retention_auto','cleanup_preview','cleanup'].includes(j.kind));
 return rows.length?table(['Date','Opération','État','Résultat',''],jobRows(rows)):empty('Aucune rétention ni simulation de nettoyage.','activity');
}
async function refreshRetentionHistory(){
 const session=sessionGeneration, target=$('#retention-history');
 if(page!=='retention'||!target)return;
 const jobs=await api('jobs');
 if(page==='retention'&&session===sessionGeneration&&target===$('#retention-history'))target.innerHTML=retentionHistory(jobs);
}


function retentionRuleText(p){
 const c=p.calendar||{};
 const periods=[['daily','jours'],['weekly','semaines ISO'],['monthly','mois']].filter(([key])=>c[key]>0).map(([key,label])=>`${esc(c[key])} ${label}`);
 return `${esc(p.keep_last)} derniers points par groupe${periods.length?` + dernier point de chacune des dernières périodes avec capture : ${periods.join(', ')} · fuseau ${esc(c.timezone||'UTC')}`:''}`;
}
function retentionCalendarFields(p){
 const c=p.calendar||{};
 return `<details id="retention-calendar" class="retention-calendar" ${c.daily||c.weekly||c.monthly?'open':''}><summary>Conservation par jour, semaine et mois</summary><p>En complément des derniers points, garder le dernier point de chaque période. Seules les périodes contenant une capture réussie comptent ; 0 désactive une catégorie. Un même point peut satisfaire plusieurs règles.</p><div class="formgrid">${[['daily','Jours avec capture à conserver'],['weekly','Semaines avec capture à conserver'],['monthly','Mois avec capture à conserver']].map(([key,label])=>`<div class="field"><label for="retention-${key}">${label}</label><input id="retention-${key}" name="${key}" type="number" min="0" max="1000000" step="1" value="${esc(c[key]||0)}" required></div>`).join('')}<div class="field"><label for="retention-timezone">Fuseau de la règle</label><input id="retention-timezone" name="timezone" value="${esc(c.timezone||user.timezone||'UTC')}" maxlength="100" required placeholder="America/Cayenne"><small>Par exemple America/Cayenne, Europe/Paris ou UTC. Les semaines vont du lundi au dimanche. Ce choix reste attaché à la règle.</small></div></div></details>`;
}
function retentionLoadPolicy(repo){
 const p=retentionPolicyList.find(p=>p.repo===repo)||{}, c=p.calendar||{};
 $('#retention-count').value=p.keep_last??7;
 for(const key of ['daily','weekly','monthly'])$('#retention-'+key).value=c[key]||0;
 $('#retention-timezone').value=c.timezone||user.timezone||'UTC';
 const section=$('#retention-calendar');if(section)section.open=Boolean(c.daily||c.weekly||c.monthly);
}
