'use strict';
let nativeState = {volumes:[],points:[],actions:[],jobs:[],provisioning:{enabled:false,devices:[],deployments:[]}}, storageProfiles = [];
let pendingNativePlan=null;
// Conservation des points natifs : règle par volume et simulation. Rien n’est supprimé par cette version.
let nativeKeep={policies:[],defaults:null},nativeKeepOpen='',nativeKeepResult=null,nativeKeepRequest=0;
// Programmation des captures : une heure et des jours par volume, arrêt au plafond, jamais de suppression.
let nativePlans={schedules:[],defaults:null,confirmation:'PROGRAMMER '};
const NATIVE_DAYS=['Lun','Mar','Mer','Jeu','Ven','Sam','Dim'];
const NATIVE_OUTCOMES={done:'Capture créée',running:'Capture en cours',skipped:'Occurrence sautée',refused:'Capture refusée',missed:'Occurrence manquée',capped:'Plafond atteint'};
$('#modal').addEventListener('close',()=>{if(pendingNativePlan){const plan=pendingNativePlan;pendingNativePlan=null;nativeConfirmation(plan);}});

async function renderNative(){
  if(user.role!=='admin'){$('#content').innerHTML=empty('La gestion native du stockage est réservée aux administrateurs.','lock');return;}
  [nativeState,storageProfiles,nativeKeep,nativePlans]=await Promise.all([api('storage/native'),api('storage/profiles'),api('storage/native-retention'),api('storage/native-schedule')]);
  if(!nativeState.volumes.some(v=>v.id===nativeKeepOpen)){nativeKeepOpen='';nativeKeepResult=null;}
  const provision=nativeState.provisioning||{enabled:false,devices:[],deployments:[]};
  const familyNames={btrfs:'Btrfs',zfs:'ZFS',lvm:'LVM'};
  const nativeStatus={ready:'Disponible',uncertain:'À vérifier',creating:'Création en cours',invalid:'Invalide',missing:'Absent'};
  $('#content').innerHTML=heading('Préparez le stockage de vos NAS.','Profils matériels et snapshots natifs pour les volumes inscrits sur chaque serveur.',button('native-refresh','Actualiser',null,'small')+button('storage-profile-create','Préparer un profil','plus','primary'))+
  `<div class="notice ${nativeState.connected?'':'neutral'}"><strong>${nativeState.connected?'Service système connecté.':'Opérations natives à activer sur le matériel cible.'}</strong> ${esc(nativeState.message||'Seuls les volumes inscrits dans la politique système peuvent être utilisés. Chaque opération présente un plan avant exécution.')}</div>
  <div class="native-summary"><section class="card cardpad"><span class="appicon">${icon('disk')}</span><h2>Choisir son matériel</h2><p class="muted">Préparez un disque unique ou un miroir de deux disques. Le profil reste indépendant du serveur actuel.</p><span class="badge dim">${storageProfiles.length} profil(s) préparé(s)</span></section><section class="card cardpad"><span class="appicon">${icon('backup')}</span><h2>Capturer un volume</h2><p class="muted">Btrfs, ZFS et LVM disposent de parcours adaptés. Les snapshots de fichiers restent accessibles sur tous les volumes usuels.</p><button class="small" data-page="snapshots">Snapshots de fichiers →</button></section><section class="card cardpad"><span class="appicon">${icon('lock')}</span><h2>Autoriser les ressources</h2><p class="muted">Un service système distinct contrôle les identités et les destinations. La console conserve ses droits utilisateur.</p><span class="badge ${nativeState.connected?'':'dim'}">${nativeState.volumes.length} volume(s) inscrit(s)</span></section></div>
  <section class="card"><div class="cardhead"><h2>Profils de déploiement</h2><span class="muted">Disques à choisir avant application</span></div>${storageProfiles.length?table(['Profil','Organisation','Capacité estimée','Système',''],storageProfiles.map(p=>`<tr><td><strong>${esc(p.name)}</strong><br><small class="muted">Aucun disque affecté</small></td><td>${p.config.layout==='mirror'?'Miroir · RAID1 logiciel':'Disque unique'}<br><small class="muted">${p.config.disk_bytes.map(sizes).join(' + ')}</small></td><td>Jusqu’à ${sizes(p.config.usable_upper_bytes)}<br><small class="muted">Avant métadonnées et réserves</small></td><td>${esc(p.config.filesystem)}<br><small class="muted">${p.config.native_snapshot_family?'Snapshots natifs Btrfs':'Snapshots de fichiers restic'}</small></td><td>${button('storage-profile-apply','Appliquer…',null,'small',`data-id="${esc(p.id)}" ${provision.enabled&&provision.devices.filter(d=>d.ready).length>=p.config.disk_bytes.length?'':'disabled'}`)} ${button('storage-profile-delete','Supprimer',null,'small',`data-id="${esc(p.id)}"`)}</td></tr>`)):empty('Préparez une architecture sans choisir ni modifier les disques de ce serveur.','disk')}</section>
  <p class="capacity-note">L’application crée un système de fichiers sur des disques entiers explicitement autorisés. Un disque monté, partitionné ou portant une signature connue est refusé. Le miroir doit terminer sa synchronisation avant de fournir toute sa redondance. Un miroir ne remplace pas une sauvegarde.</p>
  <section class="card"><div class="cardhead"><h2>Disques autorisés à l’initialisation</h2><span class="badge ${provision.enabled?'':'dim'}">${provision.enabled?'Autorisation système active':'Non activée'}</span></div>${provision.devices.length?table(['Disque / série','Capacité','Disponibilité'],provision.devices.map(d=>`<tr><td>${esc(d.id)}<br><small class="muted">${esc(d.serial)}</small></td><td>${sizes(d.bytes)}</td><td><span class="badge ${d.ready?'':'dim'}">${d.ready?'Sélection possible':'Indisponible'}</span>${d.reason?`<br><small>${esc(d.reason)}</small>`:''}</td></tr>`)):empty('Le matériel cible doit autoriser chaque disque par son identité stable avant qu’il puisse être sélectionné.','lock')}</section><br>
  <section class="card"><div class="cardhead"><h2>Volumes créés par Nacre</h2><span class="muted">État réel du montage et du miroir</span></div>${provision.deployments.length?table(['Volume','Organisation','État','Destination'],provision.deployments.map(d=>`<tr><td>${esc(d.name)}<br><small class="muted">${esc(d.filesystem)}</small></td><td>${d.layout==='mirror'?'Miroir RAID1':'Disque unique'}${d.raid?`<br><small class="muted">${d.raid.degraded?'Miroir dégradé':d.raid.sync_action==='idle'?'Miroir synchronisé':'Synchronisation en cours'}${d.raid.sync_action!=='idle'?' · '+esc(d.raid.sync_completed):''}</small>`:''}</td><td><span class="badge ${d.mounted&&!d.raid?.degraded?'':'warn'}">${d.mounted?'Monté':d.phase==='uncertain'?'À vérifier':'Non monté'}</span>${d.error?`<br><small>${esc(d.error)}</small>`:''}</td><td class="native-location">${esc(d.mountpoint)}/data${d.layout==='mirror'&&d.phase==='ready'&&d.mounted&&d.raid?.degraded===1?button('mirror-repair','Reconstruire…',null,'small',`data-volume="${esc(d.id)}"`):''}${d.phase==='uncertain'&&d.repair?button('mirror-review','Vérifier la reconstruction',null,'small',`data-volume="${esc(d.id)}"`):''}${d.phase==='repairing'?'<p class="muted">Reconstruction à vérifier · réconciliation automatique après synchronisation complète</p>':''}</td></tr>`)):empty('Les volumes apparaîtront ici après application d’un profil sur le matériel cible.','disk')}</section><br>
  <section class="card"><div class="cardhead"><h2>Volumes natifs autorisés</h2><span class="muted">Identités vérifiées à chaque opération</span></div>${nativeState.volumes.length?table(['Volume','Famille','État',''],nativeState.volumes.map(v=>`<tr><td>${esc(v.name)}<br><small class="muted">${esc(v.id)}</small></td><td>${familyNames[v.family]||esc(v.family)}</td><td><span class="badge ${v.ready?'':'warn'}">${v.ready?'Prêt':'Indisponible'}</span>${v.reason?`<br><small>${esc(v.reason)}</small>`:''}</td><td>${button('native-snapshot','Préparer une capture',null,'small',`data-volume="${esc(v.id)}" ${v.ready?'':'disabled'}`)}</td></tr>`)):empty('Aucun volume inscrit. La politique système du matériel cible permettra de les autoriser.','lock')}</section><br>
  <section class="card"><div class="cardhead"><h2>Points de restauration natifs</h2><span class="muted">Conservés sur le même stockage</span></div>${nativeState.points.length?table(['Création','Volume','État',''],nativeState.points.map(p=>{const v=nativeState.volumes.find(v=>v.id===p.volume);return `<tr><td>${date(p.created)}<br><small class="muted">${esc(p.id.slice(0,8))}</small></td><td>${esc(v?.name||p.volume)} · ${familyNames[p.family]||esc(p.family)}</td><td><span class="badge ${p.status==='ready'?'':'warn'}">${nativeStatus[p.status]||esc(p.status)}</span>${p.detail?`<br><small>${esc(p.detail)}</small>`:''}</td><td>${v?.clone?button('native-clone','Préparer une restauration',null,'small',`data-volume="${esc(p.volume)}" data-point="${esc(p.id)}" ${p.status==='ready'&&v.ready?'':'disabled'}`):'<small class="muted">Restauration par copie à venir</small>'}</td></tr>`;})):empty('Les captures Btrfs, ZFS ou LVM apparaîtront ici après autorisation et exécution.','backup')}</section><br>
  ${nativeScheduleCard()}${nativeKeepCard()}<section class="card"><div class="cardhead"><h2>Copies de restauration LVM</h2><span class="muted">Tâches système indépendantes</span></div>${nativeState.jobs?.length?table(['Date','État','Progression','Destination / résultat',''],nativeState.jobs.map(j=>`<tr><td>${date(j.ts)}</td><td><span class="badge ${j.status==='done'?'':j.status==='failed'||j.status==='uncertain'?'warn':'dim'}">${({queued:'En attente',running:'En cours',done:'Terminée',cancelled:'Annulée',failed:'Échec',uncertain:'À vérifier'})[j.status]||esc(j.status)}</span></td><td>${sizes(j.bytes)}<br><small class="muted">${j.files} fichier(s)</small></td><td class="native-location">${esc(j.location||j.error||'Nouvelle destination privée en préparation')}</td><td>${['queued','running'].includes(j.status)?button('native-job-cancel','Annuler',null,'small',`data-job="${esc(j.id)}" ${j.cancel?'disabled':''}`):''}</td></tr>`)):empty('Les copies LVM sont suivies ici, même après fermeture du navigateur.','backup')}</section><br>
  <section class="card"><div class="cardhead"><h2>Opérations et restaurations</h2><span class="muted">Dernières opérations natives</span></div>${nativeState.actions.length?table(['Date','Opération','État','Destination'],nativeState.actions.map(a=>`<tr><td>${date(a.ts)}</td><td>${({clone:'Nouvelle restauration',snapshot:'Capture',provision:'Création de volume',repair:'Reconstruction RAID1'})[a.action]||esc(a.action)} · ${esc(a.volume)}</td><td><span class="badge ${a.status==='done'?'':'warn'}">${({done:'Terminée',running:'En cours',queued:'En attente',cancelled:'Annulée',failed:'Échec',uncertain:'À vérifier'})[a.status]||esc(a.status)}</span></td><td class="native-location">${esc(a.location||a.object)}</td></tr>`)):empty('Les destinations créées et les résultats seront conservés ici.','activity')}</section><br>
  <section class="card"><div class="cardhead"><h2>Parcourir les volumes et restaurations</h2><span class="muted">Gestion des volumes · restaurations en lecture seule</span></div>${nativeState.resources?.length?table(['Espace','Destination',''],nativeState.resources.map(r=>`<tr><td>${esc(r.name)}</td><td class="native-location">${esc(r.path)}</td><td>${r.kind==='volume'?button('native-files','Gérer les fichiers','folder','small',`data-resource="${esc(r.id)}"`):button('native-browse','Parcourir','folder','small',`data-resource="${esc(r.id)}"`)}</td></tr>`)):empty('Les volumes montés et les restaurations terminées seront accessibles ici.','folder')}</section><br>
  <section class="card"><div class="cardhead"><h2>Compatibilité des opérations</h2><span class="muted">Fonctions distinctes selon le stockage</span></div>${table(['Famille','Capture','Restauration','À savoir'],[
    '<tr><td>Btrfs</td><td>Sous-volume en lecture seule</td><td>Nouveau sous-volume inscriptible</td><td>Enfants exclus ; mêmes supports</td></tr>',
    '<tr><td>ZFS</td><td>Snapshot du dataset</td><td>Nouveau dataset non monté</td><td>Parent dédié dans le même pool</td></tr>',
    '<tr><td>LVM thin / classique</td><td>Snapshot en lecture seule</td><td>Copie dans un nouveau dossier privé</td><td>Suivi du pool ou de la réserve COW</td></tr>',
    '<tr><td>ext4 / XFS sans LVM</td><td>Snapshots de fichiers restic</td><td>Nouveau dossier privé</td><td>Dépôt chiffré à configurer</td></tr>'
  ])}</section><p class="capacity-note">Les applications restent actives pendant une capture native. Les bases de données nécessitent une préparation applicative pour garantir leur cohérence. Les sous-volumes et datasets enfants ne sont pas capturés récursivement.</p>`;
}

function nativeSchedule(volume){return (Array.isArray(nativePlans?.schedules)?nativePlans.schedules:[]).find(s=>s&&s.volume===volume)||{volume,enabled:false,time:'02:00',weekdays:[0,1,2,3,4,5,6],timezone:'UTC',cap:30,points:0,next_run:null,last:null,...(nativePlans?.defaults||{})};}
function nativeScheduleText(s){
  if(!s.enabled)return 'Désactivée';
  const days=Array.isArray(s.weekdays)?s.weekdays.filter(d=>NATIVE_DAYS[d]):[];
  return `${esc(s.time)}, ${days.length===7?'tous les jours':days.map(d=>NATIVE_DAYS[d].toLowerCase()+'.').join(' ')} · fuseau ${esc(s.timezone)}`;
}
function nativeScheduleCard(){
  if(!nativeState.volumes.length)return '';
  return `<section class="card" id="native-schedule"><div class="cardhead"><h2>Programmation des captures</h2><span class="muted">Arrêt au plafond · aucun point n’est supprimé</span></div>${table(['Volume','Programmation','Dernière occurrence',''],nativeState.volumes.map(v=>{
    const s=nativeSchedule(v.id),last=s.last&&NATIVE_OUTCOMES[s.last.outcome]?s.last:null,points=Number(s.points)||0;
    return `<tr><td>${esc(v.name)}<br><small class="muted">${esc(v.id)}</small></td><td>${nativeScheduleText(s)}<br><small class="muted">${s.enabled?`${points} point${points>1?'s':''} programmé${points>1?'s':''} sur ${esc(s.cap)} au plus${Number.isFinite(s.next_run)?' · prochaine le '+date(s.next_run):''}`:'Aucune capture automatique'}</small></td><td>${last?`<span class="badge ${last.outcome==='done'||last.outcome==='running'?'':'warn'}">${NATIVE_OUTCOMES[last.outcome]}</span><br><small>${date(last.ts)}${last.outcome==='done'?'':' · '+esc(last.detail||'')}</small>`:'<small class="muted">Aucune</small>'}</td><td>${button('native-schedule-edit','Programmer…',null,'small',`data-volume="${esc(v.id)}"`)}</td></tr>`;}))}</section><br>`;
}
function nativeScheduleModal(identifier){
  const volume=nativeState.volumes.find(v=>v.id===identifier);if(!volume)return;
  const s=nativeSchedule(identifier),phrase=(nativePlans?.confirmation||'PROGRAMMER ')+identifier,days=Array.isArray(s.weekdays)?s.weekdays:[];
  modal('Programmer les captures de « '+volume.name+' »',
    field('Heure','time',s.time,'time')+
    `<div class="field"><label>Jours</label><div class="checks">${NATIVE_DAYS.map((d,i)=>`<label><input type="checkbox" name="weekdays" value="${i}" ${days.includes(i)?'checked':''}>${d}</label>`).join('')}</div></div>`+
    `<div class="field"><label for="native-schedule-cap">Plafond de points programmés</label><input id="native-schedule-cap" name="cap" type="number" min="1" max="500" step="1" value="${esc(s.cap)}" required><small>Atteint, la programmation s’arrête et le signale : elle ne supprime jamais pour faire de la place.</small></div>`+
    `<div class="checks"><label><input type="checkbox" name="enabled" ${s.enabled?'checked':''}>Activer la programmation</label></div>`+
    `<div class="field"><label for="native-schedule-confirmation">Pour activer, recopiez « ${esc(phrase)} »</label><input id="native-schedule-confirmation" name="confirmation" autocomplete="off"><small>Vaut accord durable pour les captures de ce volume. Inutile pour désactiver.</small></div>`+
    `<p class="capacity-note">L’heure s’entend dans le fuseau ${esc(nativePlans?.defaults?.timezone||s.timezone)} de la console. Une occurrence tombant pendant une autre opération sur le volume est sautée ; une occurrence manquée pendant un arrêt n’est pas rattrapée. Le service natif revérifie identité, politique et capacité à chaque capture.</p>`,
    'Enregistrer',async form=>{
      const cap=Number(form.get('cap'));if(!Number.isInteger(cap))throw new Error('Saisir un plafond entier.');
      const saved=await api('storage/native-schedule',{volume:identifier,enabled:form.has('enabled'),time:form.get('time'),weekdays:form.getAll('weekdays').map(Number),cap,confirmation:String(form.get('confirmation')||'').trim()});
      return {message:saved?.enabled?'Programmation activée. Aucun point ne sera supprimé.':'Programmation désactivée.'};
    });
}
// Tant qu’une règle est ouverte, l’actualisation périodique de la page attend : elle effacerait la saisie en cours.
function nativeEditing(){return !!nativeKeepOpen&&!!$('#native-keep-form');}
function nativeKeepPolicy(volume){return (Array.isArray(nativeKeep?.policies)?nativeKeep.policies:[]).find(p=>p&&p.volume===volume)||{volume,saved:false,keep_last:7,manual:false,calendar:{daily:0,weekly:0,monthly:0,timezone:'UTC'},...(nativeKeep?.defaults||{})};}
function nativeKeepText(p){
  const c=p.calendar||{},keep=Number(p.keep_last)||0;
  const periods=[['daily','jour'],['weekly','semaine'],['monthly','mois']].filter(([key])=>c[key]>0).map(([key,label])=>`${Number(c[key])} ${label}${c[key]>1&&key!=='monthly'?'s':''}`);
  return `${keep} dernier${keep>1?'s':''} point${keep>1?'s':''}${periods.length?' + le dernier de '+periods.join(', '):''} · ${p.manual?'captures manuelles comprises':'captures programmées seulement'}`;
}
function nativeKeepCard(){
  if(!nativeState.volumes.length)return '';
  return `<section class="card" id="native-keep"><div class="cardhead"><h2>Conservation des points natifs</h2><span class="muted">Simulation seulement · aucun point n’est supprimé</span></div>${table(['Volume','Règle',''],nativeState.volumes.map(v=>{const p=nativeKeepPolicy(v.id);return `<tr><td>${esc(v.name)}<br><small class="muted">${esc(v.id)}</small></td><td>${esc(nativeKeepText(p))}<br><small class="muted">${p.saved?'Règle enregistrée':'Règle proposée, non enregistrée'}</small></td><td>${button('native-keep-open','Régler et simuler',null,'small',`data-volume="${esc(v.id)}" aria-expanded="${v.id===nativeKeepOpen}"`)}</td></tr>`;}))}<div id="native-keep-panel">${nativeKeepPanel()}</div></section><br>`;
}
function nativeKeepPanel(){
  const volume=nativeState.volumes.find(v=>v.id===nativeKeepOpen);if(!volume)return '';
  const p=nativeKeepPolicy(volume.id),c=p.calendar||{};
  const number=(name,label,value,min,max)=>`<div class="field"><label for="native-keep-${name}">${label}</label><input id="native-keep-${name}" name="${name}" type="number" min="${min}" max="${max}" step="1" value="${esc(value)}" required></div>`;
  return `<form id="native-keep-form" class="cardpad" method="post"><h3>Règle de « ${esc(volume.name)} »</h3><p>Garder les derniers points, plus le dernier point de chaque jour, semaine ou mois ayant une capture ; 0 désactive une période. Un point peut être gardé pour plusieurs motifs.</p><div class="formgrid">${number('keep_last','Derniers points à garder',p.keep_last,1,1000)}${number('daily','Jours avec capture',c.daily||0,0,1000000)}${number('weekly','Semaines avec capture',c.weekly||0,0,1000000)}${number('monthly','Mois avec capture',c.monthly||0,0,1000000)}</div><label class="native-keep-check" for="native-keep-manual"><input type="checkbox" id="native-keep-manual" name="manual" ${p.manual?'checked':''}> Appliquer aussi la règle aux captures manuelles</label><input type="hidden" name="timezone" value="${esc(c.timezone||'UTC')}"><p class="capacity-note">Jours, semaines (du lundi au dimanche) et mois sont comptés dans le fuseau ${esc(c.timezone||'UTC')}. Sans la case, une capture faite à la main n’est jamais proposée à la suppression.</p><div class="row"><button type="submit" class="primary">Simuler</button>${button('native-keep-save','Enregistrer la règle')}${button('native-keep-close','Fermer',null,'small')}</div><p class="error" id="native-keep-error" role="alert"></p></form><div id="native-keep-result">${nativeKeepResult?nativeKeepSummary(nativeKeepResult):''}</div>`;
}
function nativeKeepSummary(r){
  const list=value=>(Array.isArray(value)?value:[]).filter(x=>x&&typeof x.id==='string');
  const keep=list(r.keep),remove=list(r.remove),guarded=list(r.protected);
  const points=(values,reason)=>values.length?table(['Création','Point','Origine',...(reason?['Motif']:[])],values.map(x=>`<tr><td>${Number.isFinite(x.created)?date(x.created):'—'}</td><td><code>${esc(x.id.slice(0,8))}</code></td><td>${x.manual?'Manuelle':'Programmée'}</td>${reason?`<td>${esc(x.reason||(Array.isArray(x.reasons)?x.reasons:[]).join(' · '))}</td>`:''}</tr>`)):empty('Aucun point dans cette catégorie.','backup');
  return `<div class="cardpad"><p class="eyebrow">SIMULATION · ${esc(r.name||r.volume)}</p><h3>Voici ce que la règle ferait des points actuels.</h3><div class="retention-counts"><div><strong>${keep.length}</strong><span>Gardés par la règle</span></div><div><strong>${guarded.length}</strong><span>Protégés hors règle</span></div><div><strong>${remove.length}</strong><span>Sortiraient</span></div></div><p class="capacity-note">${r.busy?'Une restauration est en cours ou à vérifier sur ce volume : tous ses points sont protégés. ':''}Rien n’a été supprimé et rien ne le sera : cette version ne sait pas supprimer un point natif. La simulation porte sur les points présents à ${date(r.at)}.</p><h3>Points qui sortiraient</h3>${points(remove,false)}<details><summary>Voir les points gardés et protégés</summary><h3>Gardés par la règle</h3>${points(keep,true)}<h3>Protégés hors règle</h3>${points(guarded,true)}</details></div>`;
}
function nativeKeepRedraw(){const panel=$('#native-keep-panel');if(panel)panel.innerHTML=nativeKeepPanel();}
function nativeKeepBody(form){
  const fields=new FormData(form),whole=name=>{const value=Number(fields.get(name));if(!Number.isInteger(value))throw new Error('Saisir des nombres entiers.');return value;};
  return {volume:nativeKeepOpen,keep_last:whole('keep_last'),manual:!!fields.get('manual'),calendar:{daily:whole('daily'),weekly:whole('weekly'),monthly:whole('monthly'),timezone:String(fields.get('timezone')||'UTC')}};
}
// Simuler ou enregistrer la règle affichée ; une réponse tardive pour un autre volume ou une autre session est ignorée.
async function nativeKeepSend(save){
  const form=$('#native-keep-form');if(!form||!nativeKeepOpen)return;
  const session=sessionGeneration,request=++nativeKeepRequest,volume=nativeKeepOpen,error=$('#native-keep-error');
  const current=()=>session===sessionGeneration&&request===nativeKeepRequest&&volume===nativeKeepOpen&&page==='native';
  if(error)error.textContent='';
  try{
    const body=nativeKeepBody(form),result=await api(save?'storage/native-retention':'storage/native-retention-preview',body);
    if(!current())return;
    if(save){nativeKeep={...nativeKeep,policies:[...(nativeKeep.policies||[]).filter(p=>p.volume!==volume),result]};toast('Règle enregistrée. Aucun point n’est supprimé.');return renderNative();}
    nativeKeepResult=result;const box=$('#native-keep-result');if(box)box.innerHTML=nativeKeepSummary(result);
  }catch(problem){if(!current())return;const box=$('#native-keep-error');if(box)box.textContent=problem.message;else toast(problem.message,true);}
}
document.addEventListener('submit',event=>{if(event.target.getAttribute?.('id')!=='native-keep-form')return;event.preventDefault();return nativeKeepSend(false);});
// Toucher à la règle retire une simulation devenue fausse.
document.addEventListener('input',event=>{if(event.target?.id?.startsWith('native-keep-')&&nativeKeepResult){nativeKeepResult=null;nativeKeepRequest++;const box=$('#native-keep-result');if(box)box.innerHTML='';}});

function storageProfileModal(){
  modal('Préparer un profil de stockage',field('Nom du profil','name','Mon futur NAS')+
    `<div class="field"><label for="profile-layout">Organisation</label><select id="profile-layout" name="layout"><option value="single">Un disque</option><option value="mirror">Deux disques en miroir RAID1</option></select></div>`+
    `<div class="field"><label for="profile-filesystem">Système de fichiers</label><select id="profile-filesystem" name="filesystem"><option value="btrfs">Btrfs · snapshots natifs</option><option value="ext4">ext4 · snapshots de fichiers</option></select></div>`+
    `<div class="field"><label for="profile-size">Capacité de chaque disque (Gio)</label><input type="number" id="profile-size" name="size" min="1" step="1" value="4000" required></div>`+
    `<p class="capacity-note">Il s’agit d’un profil pour le matériel cible. Aucun périphérique n’est sélectionné. Après enregistrement, l’application demandera des disques autorisés et une confirmation distincte.</p>`,
    'Enregistrer le profil',async form=>{const bytes=Number(form.get('size'))*1024**3;if(!Number.isSafeInteger(bytes)||bytes<=0)throw new Error('Capacité invalide.');await api('storage/profile',{name:form.get('name'),layout:form.get('layout'),filesystem:form.get('filesystem'),disk_bytes:Array(form.get('layout')==='mirror'?2:1).fill(bytes)});});
}

async function nativePlan(action,volume,point){
  const plan=await api('storage/native-prepare',{action,volume,point});
  return nativeConfirmation(plan);
}

function nativeConfirmation(plan){
  modal(plan.action==='repair-review'?'Valider la reconstruction':plan.action==='repair'?'Confirmer la reconstruction du miroir':plan.action==='provision'?'Confirmer l’initialisation des disques':plan.action==='snapshot'?'Confirmer la capture native':'Confirmer une nouvelle restauration',
    `<p>${esc(plan.effect)}</p>${plan.devices?table(['Disque','Série','Capacité'],plan.devices.map(d=>`<tr><td>${esc(d.id)}</td><td>${esc(d.serial)}</td><td>${sizes(d.bytes)}</td></tr>`)):''}<div class="native-plan"><div class="legendrow"><span>Volume</span><b>${esc(plan.volume)}</b></div><div class="legendrow"><span>Validité</span><b>2 minutes</b></div>${plan.notes.map(n=>`<p class="muted">${esc(n)}</p>`).join('')}</div>`+
    field('Recopiez « '+plan.confirmation+' »','confirmation')+
    `<p class="capacity-note">Le service vérifiera à nouveau l’identité et la politique avant exécution.</p>`,'Exécuter le plan',async form=>{await api('storage/native-commit',{plan:plan.id,confirmation:form.get('confirmation')});});
}

document.addEventListener('click',async event=>{
  const element=event.target.closest('[data-action]');if(!element)return;
  try{switch(element.dataset.action){
    case 'mirror-review':return nativePlan('repair-review',element.dataset.volume);
    case 'mirror-repair':return repairMirror(element.dataset.volume);
    case 'native-refresh':return renderNative();
    case 'native-schedule-edit':return nativeScheduleModal(element.dataset.volume);
    case 'native-keep-open':nativeKeepOpen=nativeKeepOpen===element.dataset.volume?'':element.dataset.volume;nativeKeepResult=null;nativeKeepRequest++;return renderNative();
    case 'native-keep-close':nativeKeepOpen='';nativeKeepResult=null;nativeKeepRequest++;return nativeKeepRedraw();
    case 'native-keep-save':return nativeKeepSend(true);
    case 'storage-profile-create':return storageProfileModal();
    case 'storage-profile-delete':return confirmAction('Supprimer ce profil ?','Seul le profil de préparation sera supprimé.','Supprimer',async()=>api('storage/profile-delete',{id:element.dataset.id}));
    case 'storage-profile-apply':return applyProfile(element.dataset.id);
    case 'native-job-cancel':await api('storage/native-cancel',{job:element.dataset.job});return renderNative();
    case 'native-files':area='native_'+element.dataset.resource;currentPath='';return go('files');
    case 'native-browse':return nativeBrowse(element.dataset.resource,element.dataset.path||'');
    case 'native-snapshot':return nativePlan('snapshot',element.dataset.volume);
    case 'native-clone':return nativePlan('clone',element.dataset.volume,element.dataset.point);
  }}catch(error){toast(error.message,true);}
});

function applyProfile(identifier){
  const profile=storageProfiles.find(p=>p.id===identifier);
  if(!profile)throw new Error('Profil inconnu.');
  const disks=nativeState.provisioning.devices.filter(d=>d.ready);
  const count=profile.config.disk_bytes.length;
  modal('Choisir les disques pour « '+profile.name+' »',
    `<p>${profile.config.layout==='mirror'?'Deux disques entiers seront utilisés pour un miroir RAID1.':'Un disque entier sera utilisé pour ce volume.'} Système : ${esc(profile.config.filesystem)}.</p>`+
    Array.from({length:count},(_,index)=>`<div class="field"><label for="apply-disk-${index}">Disque ${index+1}</label><select name="disk${index}" id="apply-disk-${index}" required><option value="">Choisir un disque autorisé</option>${disks.map(d=>`<option value="${esc(d.id)}">${esc(d.id)} · ${esc(d.serial)} · ${sizes(d.bytes)}</option>`).join('')}</select></div>`).join('')+
    `<p class="capacity-note">L’étape suivante présentera le plan d’initialisation. Aucune écriture n’a lieu à cette étape.</p>`,
    'Préparer le plan',async form=>{
      const selected=Array.from({length:count},(_,i)=>form.get('disk'+i));
      if(new Set(selected).size!==selected.length)throw new Error('Choisir des disques distincts.');
      const plan=await api('storage/profile-prepare',{id:identifier,devices:selected});
      // Ouvrir la confirmation après la fermeture automatique de ce formulaire.
      pendingNativePlan=plan;
    });
}

async function nativeBrowse(identifier,path=''){
  const resource=nativeState.resources.find(r=>r.id===identifier);
  if(!resource)throw new Error('Espace indisponible.');
  const area='native_'+identifier;
  const data=await api('files?area='+encodeURIComponent(area)+'&path='+encodeURIComponent(path));
  const content=`<p class="muted">Consultation de /${esc(path)} · les fichiers actuels sont conservés.</p>`+
    (path?button('native-browse','Dossier parent','up','small',`data-resource="${esc(identifier)}" data-path="${esc(path.split('/').slice(0,-1).join('/'))}"`):'')+
    (data.items.length?table(['Nom','Taille',''],data.items.map(f=>{const child=path?path+'/'+f.name:f.name;return `<tr><td>${esc(f.name)}${f.link?' · lien non suivi':''}</td><td>${f.directory?'Dossier':sizes(f.size)}</td><td>${f.link?'':f.directory?button('native-browse','Ouvrir','folder','small',`data-resource="${esc(identifier)}" data-path="${esc(child)}"`):`<a href="/api/download?area=${encodeURIComponent(area)}&path=${encodeURIComponent(child)}">Télécharger ↓</a>`}</td></tr>`;})):empty('Ce dossier est vide.','folder'));
  modal(resource.name,content,'Fermer',async()=>{});
}

function repairMirror(identifier){
 const volume=nativeState.provisioning.deployments.find(v=>v.id===identifier);
 if(!volume)throw new Error('Miroir inconnu.');
 const disks=nativeState.provisioning.devices.filter(d=>d.ready&&!volume.members.includes(d.id));
 modal('Reconstruire le miroir '+volume.name,
  '<p>Ce parcours exige un seul membre sain, le membre défaillant déjà retiré du miroir, et un disque de remplacement vierge autorisé par le système.</p>'+
  `<div class="field"><label for="repair-old">Membre absent à remplacer</label><select name="replace" id="repair-old">${volume.members.map(id=>`<option value="${esc(id)}">${esc(id)}</option>`).join('')}</select></div>`+
  `<div class="field"><label for="repair-new">Nouveau disque</label><select name="device" id="repair-new" required><option value="">Choisir un disque</option>${disks.map(d=>`<option value="${esc(d.id)}">${esc(d.id)} · ${esc(d.serial)} · ${sizes(d.bytes)}</option>`).join('')}</select></div>`+
  '<p class="capacity-note">La préparation vérifie les identités sans ajouter de disque. Une confirmation distincte sera requise pour lancer la reconstruction.</p>',
  'Préparer le plan',async form=>{pendingNativePlan=await api('storage/native-prepare',{action:'repair',volume:identifier,replace:form.get('replace'),device:form.get('device')});});
}
