'use strict';
// Personnes, groupes et espaces : qui ouvre quoi. Page réservée aux administrateurs.
// Mon compte : changer son propre mot de passe, pour tous les rôles.
let peopleData=null;
const PEOPLE_LEVELS={read:'Lecture',write:'Écriture'};

function peopleValid(d){
 const text=v=>typeof v==='string'&&v.length>0&&v.length<=80,levels=o=>o&&typeof o==='object'&&Object.values(o).every(v=>v==='read'||v==='write');
 if(!d||!Array.isArray(d.people)||!Array.isArray(d.groups)||!Array.isArray(d.spaces)||!d.common||!Array.isArray(d.orphans))return null;
 if(!d.people.every(p=>p&&text(p.name)&&text(p.role)&&typeof p.active==='boolean'&&Array.isArray(p.groups)))return null;
 if(!d.groups.every(g=>g&&text(g.id)&&text(g.name)&&Array.isArray(g.members)))return null;
 if(!d.spaces.every(s=>s&&text(s.id)&&text(s.name)&&levels(s.members)&&levels(s.groups)))return null;
 return levels(d.common.members)&&levels(d.common.groups)?d:null;
}
// Résumé des accès d’un espace : groupes d’abord, puis personnes.
function peopleAccess(d,space,everyone){
 const parts=[];
 if(everyone)parts.push(`Tous les membres · ${PEOPLE_LEVELS[everyone].toLowerCase()}`);
 for(const g of d.groups)if(space.groups[g.id])parts.push(`${g.name} (groupe) · ${PEOPLE_LEVELS[space.groups[g.id]].toLowerCase()}`);
 for(const p of d.people)if(space.members[p.name])parts.push(`${p.name} · ${PEOPLE_LEVELS[space.members[p.name]].toLowerCase()}`);
 return parts.length?parts.map(esc).join('<br>'):'<span class="muted">Administrateurs seulement</span>';
}
function peopleHtml(d){
 const chips=p=>p.groups.map(id=>d.groups.find(g=>g.id===id)).filter(Boolean).map(g=>`<span class="badge dim">${esc(g.name)}</span>`).join(' ')||'<span class="muted">—</span>';
 const persons=d.people.map(p=>`<tr><td><strong>${esc(p.name)}</strong>${p.active?'':' <span class="badge warn">Désactivé</span>'}</td><td><span class="badge ${p.role==='admin'?'':'dim'}">${roleName(p.role)}</span></td><td>${chips(p)}</td><td>${p.role==='member'?button('people-camera',p.camera?'Ouverte':'Fermée',null,'small',`data-name="${esc(p.name)}" data-on="${p.camera?'1':''}" aria-pressed="${!!p.camera}" title="Ouvrir ou fermer la surveillance pour cette personne"`):p.role==='viewer'?'Ouverte':'Complète'}</td><td>${button('webuser-edit','Gérer',null,'small',`data-name="${esc(p.name)}"`)}</td></tr>`);
 const groups=d.groups.map(g=>`<tr><td><strong>${esc(g.name)}</strong></td><td>${g.members.length?g.members.map(esc).join(', '):'<span class="muted">Aucun membre</span>'}</td><td><div class="row">${button('people-group','Modifier',null,'small',`data-id="${esc(g.id)}"`)}${button('people-group-delete','Supprimer',null,'small',`data-id="${esc(g.id)}"`)}</div></td></tr>`);
 const spaces=[`<tr><td><strong>Fichiers partagés</strong><br><small class="muted">Espace commun</small></td><td>${peopleAccess(d,d.common,d.common.everyone)}</td><td>${button('people-common','Modifier',null,'small')}</td></tr>`,
  ...d.spaces.map(s=>`<tr><td><strong>${esc(s.name)}</strong>${s.former?`<br><small class="muted">Ancien espace personnel de ${esc(s.former)}</small>`:''}</td><td>${peopleAccess(d,s)}</td><td><div class="row">${button('people-space','Modifier',null,'small',`data-id="${esc(s.id)}"`)}${button('people-space-delete','Supprimer',null,'small',`data-id="${esc(s.id)}"`)}</div></td></tr>`)];
 return heading('Les bons accès, aux bonnes personnes.','Chaque personne a son espace ; les espaces d’équipe s’ouvrent par personne ou par groupe.')+
  (d.orphans.length?`<div class="notice neutral">${d.orphans.map(name=>`L’espace personnel de <strong>${esc(name)}</strong>, compte désactivé, n’est plus ouvert à personne. ${button('people-adopt','Reprendre cet espace',null,'small',`data-name="${esc(name)}"`)}`).join('<br>')}</div>`:'')+
  `<div class="stack"><section class="card" id="people-persons"><div class="cardhead"><h2>Personnes</h2>${button('webuser-create','Ajouter une personne','plus','small')}</div>${table(['Personne','Rôle','Groupes','Surveillance',''],persons)}</section>`+
  `<section class="card" id="people-groups"><div class="cardhead"><h2>Groupes</h2>${button('people-group','Nouveau groupe','plus','small')}</div>${groups.length?table(['Groupe','Membres',''],groups):empty('Aucun groupe. Un groupe ouvre un espace à plusieurs personnes d’un coup.','users')}</section>`+
  `<section class="card" id="people-spaces"><div class="cardhead"><h2>Espaces</h2>${button('people-space','Nouvel espace d’équipe','plus','small')}</div>${table(['Espace','Accès',''],spaces)}</section></div>`+
  '<p class="capacity-note">Un <strong>membre</strong> ne voit que son espace personnel et les espaces qui lui sont ouverts ; un compte en <strong>lecture seule</strong> consulte tout le NAS sans rien modifier. L’espace personnel d’une personne n’est ouvert à personne d’autre depuis la console, administrateurs compris ; il peut être repris une fois le compte désactivé. Ces droits sont appliqués par la console : ils ne protègent pas d’une personne qui a la main sur la machine elle-même.</p>';
}
async function renderPeople(){
 const generation=sessionGeneration,current=()=>generation===sessionGeneration&&page==='people';
 if(user?.role!=='admin'){$('#content').innerHTML=heading('Personnes et espaces.','')+'<div class="notice neutral">Cette page est réservée aux administrateurs.</div>';return;}
 const data=peopleValid(await api('spaces'));if(!current())return;
 if(!data){$('#content').innerHTML=heading('Personnes et espaces.','')+'<div class="notice neutral">Réponse illisible du serveur. Utilisez Actualiser.</div>';return;}
 peopleData=data;webUsers=data.people;
 $('#content').innerHTML=peopleHtml(data);
}
// Lignes de choix d’accès : un niveau par groupe puis par personne.
function peopleRows(d,current){
 const select=(key,label,value)=>`<div class="pp-row"><label for="pp-${esc(key)}">${label}</label><select id="pp-${esc(key)}" name="${esc(key)}"><option value="">Aucun accès</option><option value="read" ${value==='read'?'selected':''}>Lecture</option><option value="write" ${value==='write'?'selected':''}>Écriture</option></select></div>`;
 const people=d.people.filter(p=>p.role!=='admin');
 return (d.groups.length?`<h3>Groupes</h3>${d.groups.map(g=>select('g:'+g.id,esc(g.name)+` <small class="muted">${g.members.length} membre${g.members.length>1?'s':''}</small>`,current.groups[g.id])).join('')}`:'')+
  (people.length?`<h3>Personnes</h3>${people.map(p=>select('m:'+p.name,esc(p.name)+` <small class="muted">${roleName(p.role).toLowerCase()}</small>`,current.members[p.name])).join('')}`:'')+
  (!d.groups.length&&!people.length?'<p class="muted">Aucun membre ni groupe pour l’instant : l’espace sera ouvert aux administrateurs seulement.</p>':'')+
  '<p class="capacity-note">Les administrateurs ouvrent tous les espaces d’équipe. Un compte en lecture seule reste en lecture, quel que soit le niveau choisi.</p>';
}
function peopleLevels(form){
 const members={},groups={};
 for(const [key,value] of form){if(value!=='read'&&value!=='write')continue;if(key.startsWith('m:'))members[key.slice(2)]=value;else if(key.startsWith('g:'))groups[key.slice(2)]=value;}
 return {members,groups};
}
function peopleSpaceModal(id){
 const d=peopleData,space=id?d.spaces.find(s=>s.id===id):null;if(id&&!space)return;
 modal(space?'Modifier l’espace':'Nouvel espace d’équipe',
  `<div class="field"><label for="pp-name">Nom de l’espace</label><input id="pp-name" name="name" type="text" maxlength="${d.name_max||60}" value="${esc(space?.name||'')}" autocomplete="off" required></div>`+peopleRows(d,space||{members:{},groups:{}}),
  space?'Enregistrer':'Créer l’espace',async form=>{await api('spaces/space',{...(space?{id:space.id}:{}),name:String(form.get('name')||''),...peopleLevels(form)});return {message:space?'Espace enregistré.':'Espace créé. Il apparaît dans Fichiers pour les personnes choisies.'};});
}
function peopleCommonModal(){
 const d=peopleData,c=d.common;
 modal('Accès à l’espace commun',
  `<p class="muted">« Fichiers partagés » est l’espace commun du NAS. Les administrateurs y écrivent toujours.</p><div class="pp-row"><label for="pp-everyone"><strong>Tous les membres</strong></label><select id="pp-everyone" name="everyone"><option value="">Aucun accès</option><option value="read" ${c.everyone==='read'?'selected':''}>Lecture</option><option value="write" ${c.everyone==='write'?'selected':''}>Écriture</option></select></div>`+peopleRows(d,c),
  'Enregistrer',async form=>{const everyone=form.get('everyone');await api('spaces/common',{everyone:everyone==='read'||everyone==='write'?everyone:null,...peopleLevels(form)});return {message:'Accès à l’espace commun enregistrés.'};});
}
function peopleGroupModal(id){
 const d=peopleData,group=id?d.groups.find(g=>g.id===id):null;if(id&&!group)return;
 modal(group?'Modifier le groupe':'Nouveau groupe',
  `<div class="field"><label for="pp-name">Nom du groupe</label><input id="pp-name" name="name" type="text" maxlength="${d.name_max||60}" value="${esc(group?.name||'')}" autocomplete="off" required></div><div class="field"><label>Membres</label><div class="checks">${d.people.map(p=>`<label><input type="checkbox" name="member" value="${esc(p.name)}" ${group?.members.includes(p.name)?'checked':''}>${esc(p.name)}</label>`).join('')}</div></div>`,
  group?'Enregistrer':'Créer le groupe',async form=>{await api('spaces/group',{...(group?{id:group.id}:{}),name:String(form.get('name')||''),members:form.getAll('member').map(String)});return {message:'Groupe enregistré.'};});
}
document.addEventListener('click',async e=>{
 const el=e.target.closest?.('[data-action^="people-"]');if(!el||el.disabled||page!=='people'||user?.role!=='admin'||!peopleData)return;
 const d=peopleData;
 try{
  switch(el.dataset.action){
   case 'people-space':return peopleSpaceModal(el.dataset.id||'');
   case 'people-common':return peopleCommonModal();
   case 'people-group':return peopleGroupModal(el.dataset.id||'');
   case 'people-camera':{await api('spaces/person',{name:el.dataset.name,camera:!el.dataset.on});toast(el.dataset.on?'Surveillance fermée pour cette personne.':'Surveillance ouverte en lecture pour cette personne.');return await renderPeople();}
   case 'people-group-delete':{const g=d.groups.find(x=>x.id===el.dataset.id);if(!g)return;
    return confirmAction('Supprimer ce groupe ?',`Le groupe « ${g.name} » disparaît aussi des accès de tous les espaces : ses membres perdent les accès qu’ils ne tenaient que de lui. Aucun fichier n’est touché.`,'Supprimer',async()=>{await api('spaces/group-delete',{id:g.id});return {message:'Groupe supprimé.'};});}
   case 'people-space-delete':{const s=d.spaces.find(x=>x.id===el.dataset.id);if(!s)return;
    return confirmAction('Supprimer cet espace ?',`« ${s.name} » ne peut être supprimé que vide, corbeille comprise : rien n’est effacé à votre place.`,'Supprimer',async()=>{await api('spaces/space-delete',{id:s.id});return {message:'Espace supprimé.'};});}
   case 'people-adopt':{const name=el.dataset.name;if(!d.orphans.includes(name))return;
    return confirmAction('Reprendre cet espace personnel ?',`L’espace personnel de ${name} devient un espace d’équipe, ouvert aux administrateurs. Aucun fichier n’est déplacé. Cette reprise est inscrite au journal.`,'Reprendre',async()=>{await api('spaces/adopt',{name});return {message:'Espace repris : il apparaît dans les espaces d’équipe.'};});}
  }
 }catch(error){if(error.name!=='AbortError')toast(error.message,true);}
});

// Mon compte.
async function renderAccount(){
 const generation=sessionGeneration,data=await api('account');
 if(generation!==sessionGeneration||page!=='account')return;
 $('#content').innerHTML=heading('Mon compte.','Votre identifiant et votre mot de passe sur ce NAS.')+
  `<div class="stack"><section class="card cardpad"><h2>${esc(data.name)}</h2><p><span class="badge ${data.role==='admin'?'':'dim'}">${roleName(data.role)}</span></p></section>`+
  `<section class="card cardpad"><h2>Changer mon mot de passe</h2><form id="account-form" method="post"><div class="formgrid"><div class="field"><label for="account-current">Mot de passe actuel</label><input id="account-current" name="current" type="password" autocomplete="current-password" required></div><div class="field"><label for="account-password">Nouveau mot de passe</label><input id="account-password" name="password" type="password" autocomplete="new-password" minlength="12" maxlength="128" required><small>12 caractères minimum.</small></div><div class="field"><label for="account-again">Nouveau mot de passe, encore</label><input id="account-again" name="again" type="password" autocomplete="new-password" minlength="12" maxlength="128" required></div></div><p id="account-error" class="error" role="alert"></p><button class="primary" type="submit">Changer le mot de passe</button></form><p class="capacity-note">Vos autres sessions ouvertes sur ce compte sont fermées. Celle-ci reste ouverte.</p></section></div>`;
}
document.addEventListener('submit',async e=>{
 if(e.target.getAttribute?.('id')!=='account-form')return;
 e.preventDefault();
 const form=new FormData(e.target),error=$('#account-error'),send=e.target.querySelector('button[type=submit]');
 if(form.get('password')!==form.get('again')){if(error)error.textContent='Les deux saisies du nouveau mot de passe diffèrent.';return;}
 if(send)send.disabled=true;
 try{await api('account/password',{current:String(form.get('current')||''),password:String(form.get('password')||'')});toast('Mot de passe modifié.');await renderAccount();}
 catch(failure){if(failure.name!=='AbortError'&&error)error.textContent=failure.message;}
 finally{if(send)send.disabled=false;}
});
