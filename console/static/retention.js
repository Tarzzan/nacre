'use strict';
let retentionProposal=null, retentionGeneration=0, retentionPolicyList=[], retentionOpeningGeneration=0;

function retentionSummary(p){
 const points=(list,reason)=>list.length?table(['Date','Identifiant',...(reason?['Motif']:[])],list.map(x=>`<tr><td>${date(Date.parse(x.time)/1000)}</td><td><code title="${esc(x.id)}">${esc(x.id.slice(0,12))}</code></td>${reason?`<td>${esc(x.reason||(x.reasons||[]).join(' · '))}</td>`:''}</tr>`)):empty('Aucun point dans cette catégorie.','backup');
 return `<section class="card cardpad"><div class="row"><div><p class="eyebrow">SIMULATION · ${esc(p.name)}</p><h2>Voici ce qui changerait.</h2></div><span class="spacer"></span>${button('retention-confirm','Examiner la confirmation','trash','',p.remove.length?'':'disabled')}${button('retention-enable','Activer après les prochaines sauvegardes',null,'primary')}</div><p>${p.groups} groupe(s) · ${retentionRuleText(p)}. Proposition valable jusqu’à ${date(p.expires)}.</p><p>${retentionWindowText(p)}</p><div class="retention-counts"><div><strong>${p.keep.length}</strong><span>Conservés par la règle</span></div><div><strong>${p.protected.length}</strong><span>Protégés hors règle</span></div><div><strong>${p.remove.length}</strong><span>À supprimer</span></div></div><p class="capacity-note">Aucun changement n’a encore été appliqué. Le nettoyage récupère les blocs non référencés de l’ensemble du dépôt ; la taille logique des points ne permet pas de prévoir l’espace libéré.</p></section><br><section class="card"><div class="cardhead"><h2>Points qui seraient supprimés</h2></div>${points(p.remove,false)}</section><br><details class="card cardpad"><summary>Voir les points conservés et protégés</summary><h3>Conservés par la règle</h3>${points(p.keep,true)}<h3>Protégés hors règle</h3>${points(p.protected,true)}</details>`;
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
 `<section class="card cardpad"><h2>Règle de conservation</h2><p>Chaque plan, hôte et combinaison de sources et d’options est traité séparément. Les captures partielles, importées ou sans preuve locale de réussite restent protégées.</p>${usable.length?`<form id="retention-form" method="post"><div class="formgrid"><div class="field"><label for="retention-repo">Dépôt chiffré</label><select id="retention-repo" name="repo">${usable.map(r=>`<option value="${esc(r.id)}" ${r.id===snapshotRepo?'selected':''}>${esc(r.name)}</option>`).join('')}</select></div><div class="field"><label for="retention-count">Derniers points réussis à conserver par groupe</label><input id="retention-count" name="keep_last" type="number" min="1" max="1000000" step="1" value="${initialCount}" required></div></div>${retentionCalendarFields(initialPolicy)}${retentionWindowFields(initialPolicy)}<p class="capacity-note">La simulation permet une application unique ou l’activation après les prochaines captures réussies. Les règles automatiques sont désactivées par défaut.</p><button type="submit" class="primary">Simuler sans supprimer</button><p id="retention-error" class="error" role="alert"></p></form>`:empty('Ajoutez un dépôt depuis Snapshots pour préparer une règle.','backup')}</section><br><div id="retention-result" aria-live="polite"></div><br><div id="retention-policies">${retentionPolicies(policies)}</div><br>${cleanupCard(usable)}<br><section class="card"><div class="cardhead"><h2>Historique des nettoyages</h2>${button('retention-refresh','Actualiser',null,'small')}</div><div id="retention-history">${retentionHistory(jobs)}</div></section><p class="capacity-note">La suppression est définitive dans Nacre. Le traitement continue sans navigateur et vérifie la structure du dépôt après nettoyage. Une interruption peut laisser une opération partielle ; la règle automatique est suspendue et la tâche n’est pas rejouée.</p>`;
}

document.addEventListener('submit',async event=>{
 if(event.target.getAttribute('id')!=='retention-form')return;
 event.preventDefault();
 const form=event.target, submit=form.querySelector('button[type=submit]'), fields=new FormData(form);
 const generation=++retentionGeneration, session=sessionGeneration;
 retentionProposal=null;$('#retention-result').innerHTML='';$('#retention-error').textContent='';submit.disabled=true;
 try{
  const result=await api('protection/retention-preview',{repo:fields.get('repo'),keep_last:Number(fields.get('keep_last')),calendar:{daily:Number(fields.get('daily')||0),weekly:Number(fields.get('weekly')||0),monthly:Number(fields.get('monthly')||0),timezone:fields.get('timezone')||'UTC'},window:retentionWindowValue(fields)});
  if(page!=='retention'||generation!==retentionGeneration||session!==sessionGeneration||!$('#retention-result'))return;
  retentionProposal=result;$('#retention-result').innerHTML=retentionSummary(result);
 }catch(error){if(page==='retention'&&generation===retentionGeneration&&$('#retention-error'))$('#retention-error').textContent=error.message;}
 finally{submit.disabled=false;}
});

document.addEventListener('input',event=>{
 if(['retention-count','retention-repo','retention-daily','retention-weekly','retention-monthly','retention-timezone','retention-window-enabled'].includes(event.target.id)||event.target.id?.startsWith('retention-window-')){
  if(event.target.id==='retention-repo')retentionLoadPolicy(event.target.value);
  if(event.target.id==='retention-window-mode'||/^retention-window-day-[0-6]$/.test(event.target.id)||event.target.id?.endsWith('-kind'))retentionWindowVisibility();
  retentionInvalidate();
 }
});
document.addEventListener('click',async event=>{
 const el=event.target.closest('[data-action]');if(!el)return;
 try{
  if(retentionEditSchedule(el))return;
  if(el.dataset.action==='retention-openings')return await retentionShowOpenings(el);
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
   return modal('Activer après les prochaines sauvegardes',`<p>Dépôt : <strong>${esc(p.name)}</strong>. <strong>${retentionRuleText(p)}</strong>.</p><p>${retentionWindowText(p)}</p><p>Après chaque nouvelle capture réussie demandée après cette activation, Nacre recalculera les points à supprimer, puis nettoiera le dépôt sans nouvelle confirmation. La simulation montre l’effet actuel ; la sélection évoluera avec les prochaines captures.</p><p>Aucune suppression n’est lancée par ce bouton. Les captures déjà demandées et les sauvegardes partielles ou échouées ne déclenchent rien. Le nettoyage concerne tous les groupes de ce dépôt et les blocs non référencés de l’ensemble du dépôt.</p><div class="checks"><label><input type="checkbox" name="confirm" required>J’autorise ces prochaines suppressions automatiques et le nettoyage du dépôt.</label></div><p class="capacity-note">En cas d’échec ou d’interruption, la règle est suspendue et une alerte locale est créée. Vous pouvez la désactiver à tout moment.</p>`,'Activer la règle',async f=>{
    const result=await api('protection/retention-policy',{repo:p.repo,version:p.policy_version,token:p.token,enabled:true,confirm:f.has('confirm')});retentionProposal=null;return result;
   });
  }
  if(el.dataset.action==='retention-confirm'&&retentionProposal){
   const p=retentionProposal;
   modal('Confirmer la rétention',`<p>Dépôt : <strong>${esc(p.name)}</strong>.</p><p>${retentionRuleText(p)}.</p><p>Application ponctuelle : démarrage dès disponibilité, même hors du créneau automatique.</p><p><strong>${p.remove.length} point(s) seront supprimés définitivement.</strong> ${p.keep.length+p.protected.length} point(s) resteront disponibles selon cette simulation.</p><p>Les blocs non référencés de l’ensemble du dépôt seront ensuite nettoyés, y compris ceux d’anciennes suppressions. Les sauvegardes Nacre attendront la fin de cette tâche. L’espace récupérable n’est pas estimé.</p><div class="checks"><label><input type="checkbox" name="confirm" required>Je confirme cette suppression et le nettoyage du dépôt.</label></div><p class="capacity-note">Si les points ou le dépôt ont changé, le traitement sera refusé. Une annulation après démarrage ne recrée pas les points déjà supprimés.</p>`,'Supprimer et nettoyer',async f=>{
    const result=await api('protection/retention-apply',{token:p.token,confirm:f.has('confirm')});retentionProposal=null;return result;
   });
  }
 }catch(error){if(error.name!=='AbortError')toast(error.message,true);}
});

function retentionPolicies(policies){
 return `<section class="card"><div class="cardhead"><h2>Rétention automatique</h2><span class="muted">Après une nouvelle capture réussie</span></div>${policies.length?table(['Dépôt','Conservation par groupe','État',''],policies.map(p=>`<tr><td>${esc(p.name)}</td><td>${retentionRuleText(p)}<p class="muted">${retentionWindowText(p)}</p></td><td><span class="badge ${p.reason?'warn':p.enabled?'':'dim'}">${p.reason?'Suspendue':p.enabled?'Active':'Désactivée'}</span>${p.reason?`<p class="muted">${esc(p.reason)}</p>`:''}${p.enabled?`<p class="muted">${p.window_open===false?'Hors créneau · ':''}${Number(p.pending||0)} capture(s) en attente de traitement.</p>`:''}</td><td>${p.enabled||p.reason?button('retention-disable','Désactiver',null,'small',`data-repo="${esc(p.repo)}" data-version="${p.version}"`):'Simulez une règle pour l’activer.'}</td></tr>`)):empty('Aucun dépôt configuré.','backup')}</section>`;
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
 const policyTarget=$('#retention-policies');
 const [jobs,policies]=await Promise.all([api('jobs'),policyTarget?api('protection/retention-policies'):Promise.resolve([])]);
 if(page!=='retention'||session!==sessionGeneration||target!==$('#retention-history'))return;
 target.innerHTML=retentionHistory(jobs);
 if(policyTarget&&policyTarget===$('#retention-policies'))policyTarget.innerHTML=retentionPolicies(policies);
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
 const w=p.window||{};
 if($('#retention-window-enabled')){
  $('#retention-window-enabled').checked=Boolean(w.enabled);$('#retention-window-start').value=w.start||'02:00';$('#retention-window-end').value=w.end||'05:00';
  $('#retention-window').open=Boolean(w.enabled);
  if($('#retention-window-mode')){
   $('#retention-window-mode').value=w.mode||'daily';
   for(let day=0;day<7;day++){
    const entry=(w.week||[]).find(e=>e.day===day);
    $('#retention-window-day-'+day).checked=Boolean(entry);
    $('#retention-window-start-'+day).value=entry?.start||'02:00';
    $('#retention-window-end-'+day).value=entry?.end||'05:00';
   }
   retentionLoadExtras(w);
   retentionWindowVisibility();
  }
 }
 const section=$('#retention-calendar');if(section)section.open=Boolean(c.daily||c.weekly||c.monthly);
}


const retentionWeekdays=['Lundi','Mardi','Mercredi','Jeudi','Vendredi','Samedi','Dimanche'];
function retentionReadSlots(fields,scope){
 const prefix='window_slot_'+scope+'_';
 return [...fields].filter(([name])=>name.startsWith(prefix)&&name.endsWith('_start')).map(([name,start])=>({start,end:fields.get(name.slice(0,-6)+'_end')||''}));
}
function retentionWindowValue(fields){
 const mode=fields.get('window_mode')||'daily';
 const exceptions=[...fields].filter(([name])=>/^window_exception_[0-9]+_date$/.test(name)).map(([name,date])=>{
  const id=name.split('_')[2], custom=fields.get('window_exception_'+id+'_kind')==='custom';
  const slots=custom?retentionReadSlots(fields,'exception_'+id):[];
  if(custom&&!slots.length)throw new Error('Ajoutez au moins une plage à l’exception ou choisissez « Aucun démarrage ».');
  return {date,slots};
 });
 return {enabled:fields.has('window_enabled'),mode,start:fields.get('window_start')||'02:00',end:fields.get('window_end')||'05:00',
  extra:mode==='daily'?retentionReadSlots(fields,'daily'):[],exceptions,
  week:mode==='weekly'?retentionWeekdays.flatMap((_,day)=>fields.has('window_day_'+day)?[{start:fields.get('window_start_'+day)||'',end:fields.get('window_end_'+day)||''},...retentionReadSlots(fields,'day_'+day)].map(slot=>({day,...slot})):[]):[]};
}
function retentionSlotText(e){return `${esc(e.start)} à ${esc(e.end)}${e.start>e.end?' le lendemain':''}`;}
function retentionWindowText(p){
 const w=p.window||{};
 if(!w.enabled)return 'Démarrage automatique sans restriction horaire.';
 const timing=w.mode==='weekly'?((w.week||[]).map(e=>`${esc(retentionWeekdays[e.day]||'Jour inconnu')} de ${retentionSlotText(e)}`).join(' ; ')||'aucune plage hebdomadaire'):`chaque jour de ${[w,...(w.extra||[])].map(retentionSlotText).join(' ; de ')}`;
 const exceptions=(w.exceptions||[]).map(e=>`${esc(e.date)} : ${e.slots.length?e.slots.map(retentionSlotText).join(' ; '):'aucun démarrage'}`).join(' — ');
 return `Démarrage automatique autorisé ${timing} · ${esc(p.calendar?.timezone||'UTC')}. ${exceptions?`Exceptions prioritaires : ${exceptions}. Elles remplacent toute la date, y compris la continuation de la veille. `:''}Une opération commencée pourra se terminer après la fin du créneau.`;
}
function retentionWindowFields(p){
 const w=p.window||{}, weekly=w.mode==='weekly';
 return `<details id="retention-window" ${w.enabled?'open':''}><summary>Créneaux du nettoyage automatique</summary><div class="checks"><label><input type="checkbox" id="retention-window-enabled" name="window_enabled" ${w.enabled?'checked':''}>Limiter les démarrages automatiques aux créneaux choisis</label></div><div class="field"><label for="retention-window-mode">Rythme du nettoyage</label><select id="retention-window-mode" name="window_mode"><option value="daily" ${weekly?'':'selected'}>Tous les jours, mêmes horaires</option><option value="weekly" ${weekly?'selected':''}>Par jour de la semaine</option></select></div><div id="retention-window-daily" ${weekly?'hidden':''}><div class="formgrid"><div class="field"><label for="retention-window-start">Début du créneau</label><input type="time" id="retention-window-start" name="window_start" value="${esc(w.start||'02:00')}" ${weekly?'disabled':''} required></div><div class="field"><label for="retention-window-end">Fin du créneau</label><input type="time" id="retention-window-end" name="window_end" value="${esc(w.end||'05:00')}" ${weekly?'disabled':''} required></div></div>${retentionExtraFields('daily',w.extra||[],'chaque jour',weekly)}</div><div id="retention-window-weekly" ${weekly?'':'hidden'}><p>Cocher les jours de départ et choisir leurs plages.</p>${retentionWeekdays.map((name,day)=>{
  const entry=(w.week||[]).find(e=>e.day===day), disabled=!weekly||!entry;
  return `<div class="retention-weekday"><div class="checks"><label><input type="checkbox" id="retention-window-day-${day}" name="window_day_${day}" ${entry?'checked':''} ${weekly?'':'disabled'}>${name}</label></div>${[['start','Début'],['end','Fin']].map(([key,label])=>`<div class="field"><label for="retention-window-${key}-${day}">${label} · ${name.toLowerCase()}</label><input type="time" id="retention-window-${key}-${day}" name="window_${key}_${day}" value="${esc(entry?.[key]||(key==='start'?'02:00':'05:00'))}" ${disabled?'disabled':''} required></div>`).join('')}${retentionExtraFields('day_'+day,(w.week||[]).filter(e=>e.day===day).slice(1),name.toLowerCase(),disabled)}</div>`;
 }).join('')}<p class="capacity-note">Si la fin précède le début, la plage se termine le lendemain. Par exemple, lundi 22 h–2 h inclut mardi jusqu’à 2 h, même si mardi n’est pas coché. Les plages qui se recouvrent sont réunies.</p></div><section class="retention-exceptions"><h3>Exceptions pour certaines dates</h3><p>Une exception remplace toute la date dans le fuseau de la règle, y compris la continuation d’une plage de la veille. « Aucun démarrage » ferme la journée. Une tâche déjà commencée peut se terminer.</p><div id="retention-window-exceptions">${(w.exceptions||[]).map(retentionExceptionFields).join('')}</div>${button('retention-exception-add','Ajouter une exception',null,'small')}</section><p class="capacity-note">Dans le fuseau choisi dans « Conservation par jour, semaine et mois ». Une tâche déjà commencée se termine ; les demandes suivantes attendent. L’application ponctuelle et le nettoyage seul restent immédiats.</p>${button('retention-openings','Voir les ouvertures sur 7 jours',null,'small')}<div id="retention-window-openings" aria-live="polite"></div></details>`;
}
function retentionWindowVisibility(){
 const mode=$('#retention-window-mode');if(!mode)return;
 const weekly=mode.value==='weekly';
 $('#retention-window-daily').hidden=weekly;$('#retention-window-weekly').hidden=!weekly;
 for(const key of ['start','end'])$('#retention-window-'+key).disabled=weekly;
 retentionDisableExtras('daily',weekly);
 for(let day=0;day<7;day++){
  const checkbox=$('#retention-window-day-'+day);checkbox.disabled=!weekly;
  for(const key of ['start','end'])$('#retention-window-'+key+'-'+day).disabled=!weekly||!checkbox.checked;
  retentionDisableExtras('day_'+day,!weekly||!checkbox.checked);
 }
 for(const row of document.querySelectorAll('.retention-exception')){
  const id=row.dataset.id, custom=$('#retention-window-exception-'+id+'-kind').value==='custom';
  $('#retention-window-exception-'+id+'-slots').hidden=!custom;
  retentionDisableExtras('exception_'+id,!custom);
 }
}

let retentionSlotSequence=0, retentionExceptionSequence=0;
function retentionInvalidate(){
 retentionGeneration++;retentionProposal=null;
 if($('#retention-result'))$('#retention-result').innerHTML='';
 if($('#retention-window-openings'))$('#retention-window-openings').innerHTML='';
}
function retentionSlotFields(scope,slot,label,disabled=false){
 const id=++retentionSlotSequence, prefix='retention-window-slot-'+scope+'-'+id;
 return `<div class="retention-slot" id="${prefix}">${[['start','Début'],['end','Fin']].map(([key,title])=>`<div class="field"><label for="${prefix}-${key}">${title} · ${esc(label)} · plage supplémentaire</label><input type="time" id="${prefix}-${key}" name="window_slot_${scope}_${id}_${key}" value="${esc(slot[key])}" ${disabled?'disabled':''} required></div>`).join('')}${button('retention-slot-remove','Retirer la plage',null,'small',`data-target="${prefix}" ${disabled?'disabled':''}`)}</div>`;
}
function retentionExtraFields(scope,slots,label,disabled=false){
 return `<div class="retention-extra" id="retention-window-extra-${scope}"><div id="retention-window-slots-${scope}">${slots.map(slot=>retentionSlotFields(scope,slot,label,disabled)).join('')}</div>${button('retention-slot-add','Ajouter une plage · '+esc(label),null,'small',`data-scope="${scope}" data-label="${esc(label)}" ${disabled?'disabled':''}`)}</div>`;
}
function retentionExceptionFields(entry={date:'',slots:[]}){
 const id=++retentionExceptionSequence, custom=entry.slots.length>0;
 return `<section class="retention-exception" data-id="${id}" id="retention-window-exception-${id}"><div class="formgrid"><div class="field"><label for="retention-window-exception-${id}-date">Date de l’exception</label><input type="date" id="retention-window-exception-${id}-date" name="window_exception_${id}_date" value="${esc(entry.date)}" required></div><div class="field"><label for="retention-window-exception-${id}-kind">Pour cette date</label><select id="retention-window-exception-${id}-kind" name="window_exception_${id}_kind"><option value="closed" ${custom?'':'selected'}>Aucun démarrage</option><option value="custom" ${custom?'selected':''}>Horaires de remplacement</option></select></div></div><div id="retention-window-exception-${id}-slots" ${custom?'':'hidden'}>${retentionExtraFields('exception_'+id,custom?entry.slots:[{start:'02:00',end:'05:00'}],'exception '+id,!custom)}</div>${button('retention-exception-remove','Retirer l’exception',null,'small',`data-target="retention-window-exception-${id}"`)}</section>`;
}
function retentionDisableExtras(scope,disabled){
 for(const control of $('#retention-window-extra-'+scope)?.querySelectorAll('input,button')||[])control.disabled=disabled;
}
function retentionLoadExtras(w){
 if($('#retention-window-slots-daily'))$('#retention-window-slots-daily').innerHTML=(w.extra||[]).map(e=>retentionSlotFields('daily',e,'chaque jour')).join('');
 for(let day=0;day<7;day++){
  const target=$('#retention-window-slots-day_'+day);
  if(target)target.innerHTML=(w.week||[]).filter(e=>e.day===day).slice(1).map(e=>retentionSlotFields('day_'+day,e,retentionWeekdays[day].toLowerCase())).join('');
 }
 if($('#retention-window-exceptions'))$('#retention-window-exceptions').innerHTML=(w.exceptions||[]).map(retentionExceptionFields).join('');
}
function retentionEditSchedule(el){
 if(el.dataset.action==='retention-slot-add'){
  $('#retention-window-slots-'+el.dataset.scope).insertAdjacentHTML('beforeend',retentionSlotFields(el.dataset.scope,{start:'02:00',end:'05:00'},el.dataset.label));
 }else if(el.dataset.action==='retention-exception-add'){
  $('#retention-window-exceptions').insertAdjacentHTML('beforeend',retentionExceptionFields());
 }else if(['retention-slot-remove','retention-exception-remove'].includes(el.dataset.action)){
  $('#'+el.dataset.target)?.remove();
 }else return false;
 retentionInvalidate();retentionWindowVisibility();return true;
}


async function retentionShowOpenings(button){
 const target=$('#retention-window-openings'), form=$('#retention-form');if(!target||!form)return;
 const generation=retentionGeneration, request=++retentionOpeningGeneration, session=sessionGeneration;
 const current=()=>page==='retention'&&session===sessionGeneration&&generation===retentionGeneration&&request===retentionOpeningGeneration&&target===$('#retention-window-openings');
 button.disabled=true;target.textContent='Calcul des ouvertures…';
 try{
  const fields=new FormData(form);
  const result=await api('protection/retention-openings',{window:retentionWindowValue(fields),timezone:fields.get('timezone')||'UTC'});
  if(current())target.innerHTML=retentionOpenings(result);
 }catch(error){if(current())target.textContent=error.message;}
 finally{button.disabled=false;}
}
function retentionOpenings(result){
 const format=new Intl.DateTimeFormat('fr-FR',{timeZone:result.timezone,year:'numeric',month:'short',day:'2-digit',hour:'2-digit',minute:'2-digit',timeZoneName:'shortOffset'});
 const at=value=>esc(format.format(new Date(value*1000)));
 const intro=`<h3>Ouvertures autorisées sur 7 jours</h3><p>Du ${at(result.generated_at)} au ${at(result.until)} · ${esc(result.timezone)}.</p><p class="capacity-note">Aperçu du formulaire, sans enregistrement ni activation. Ces plages autorisent un démarrage ; elles ne réservent pas une heure d’exécution. Une tâche commencée peut finir après fermeture.</p>`;
 if(!result.enabled)return intro+'<p>Limitation désactivée : les démarrages automatiques ne sont pas restreints par ce calendrier.</p>';
 if(!result.windows.length)return intro+'<p>Aucune ouverture dans les sept prochains jours. Des dates plus lointaines peuvent encore être configurées.</p>';
 return intro+table(['Début autorisé','Fin de l’ouverture'],result.windows.map(w=>`<tr><td>${w.ongoing?'Déjà ouvert · ':''}${at(w.start)}</td><td>${at(w.end)}${w.continues?' · ouverture prolongée au-delà de cet aperçu':''}</td></tr>`));
}
