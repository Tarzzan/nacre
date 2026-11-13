'use strict';
let controlState=null,controlRequest=0,controlSessionsRequest=0;
const controlGroups=[
 ['Stocker et partager','Dossiers, volumes et accès aux fichiers.',[['storage','disk','Stockage'],['native','disk','Volumes et snapshots'],['shares','share','Partages SMB'],['users','users','Comptes et permissions']]],
 ['Protéger vos données','Destinations, plans et points de restauration.',[['backups','backup','Sauvegardes'],['snapshots','backup','Points de restauration'],['retention','activity','Conservation des sauvegardes']]],
 ['Exploiter votre NAS','Composants, surveillance et suivi des incidents.',[['updates','download','Mises à jour Nacre'],['services','server','Services'],['camera','camera','Caméras'],['alerts','activity','Alertes'],['notifications','activity','Notifications'],['events','activity','Journal d’activité']]]
];
function controlSessions(accounts){
 return table(['Compte','Rôle','Sessions valides',''],accounts.map(a=>{
  const available=Math.max(0,a.valid_sessions-(a.current?1:0));
  return `<tr><td><strong>${esc(a.name)}</strong>${a.current?'<small class="control-current">Votre compte</small>':''}${a.active?'':'<small class="control-current">Compte désactivé</small>'}</td><td>${a.role==='admin'?'Administrateur':'Lecture seule'}</td><td>${esc(a.valid_sessions)}</td><td>${button('control-revoke',a.current?'Déconnecter les autres':'Déconnecter',null,'small',`data-name="${esc(a.name)}" ${available?'':'disabled'}`)}</td></tr>`;
 }));
}
async function renderControlPanel(){
 if(user?.role!=='admin'){$('#content').innerHTML=empty('Le panneau de configuration est réservé aux administrateurs.','lock');return;}
 const generation=sessionGeneration,request=++controlRequest;
 let state;
 try{state=await api('control-panel');}catch(error){if(generation!==sessionGeneration||page!=='settings'||request!==controlRequest)return;throw error;}
 if(generation!==sessionGeneration||page!=='settings'||request!==controlRequest)return;
 controlState=state;
 $('#content').innerHTML=heading('Votre NAS, à votre mesure.','Retrouvez les réglages et les accès pour administrer Nacre au quotidien.')+
 `<div class="control-summary"><span class="badge">Nacre ${esc(state.version)}</span><span>${esc(state.system)} · ${esc(state.architecture)}</span><span>${state.accounts.filter(a=>a.active).length} compte(s) actif(s)</span></div>`+
 `<div class="control-layout"><section class="card cardpad"><h2>Identité et horaires</h2><form id="control-preferences" method="post"><fieldset ${state.setup_complete?'':'disabled'}>${field('Nom affiché du NAS','name',state.name,'text','Le nom utilisé dans Nacre ; le nom réseau Linux reste inchangé.')}${typeof zoneField==='function'?zoneField('Fuseau horaire de la console',state.timezone,state.timezones,'Saisissez une ville pour filtrer la liste, par exemple Cayenne ou Paris. Les calendriers existants gardent leur propre fuseau.'):field('Fuseau horaire de la console','timezone',state.timezone,'text','Exemples : America/Cayenne, Europe/Paris, UTC. Les calendriers existants gardent leur propre fuseau.')}<p class="capacity-note">Ce fuseau règle l’affichage des dates dans la console. Il ne modifie pas l’horloge du serveur ou des caméras.</p><p id="control-error" class="error" role="alert"></p><button type="submit" class="primary">Enregistrer les préférences</button></fieldset></form>${state.setup_complete?'':'<p>Terminez la première configuration pour modifier ces préférences.</p><button data-page="setup">Ouvrir l’assistant</button>'}</section><section class="control-groups">${controlGroups.map(([title,description,links])=>`<section class="card cardpad"><h2>${title}</h2><p>${description}</p><div class="control-links">${links.map(([p,ic,label])=>`<button data-page="${p}">${icon(ic)}<span>${label}</span>${icon('arrow')}</button>`).join('')}</div></section>`).join('')}</section></div>`+
 `<section class="card control-sessions"><div class="cardhead"><div><h2>Sessions de la console</h2><p class="muted">Une session valide peut correspondre à un navigateur fermé.</p></div>${button('control-refresh-sessions','Actualiser', 'activity','small')}</div><div id="control-sessions">${controlSessions(state.accounts)}</div><p class="capacity-note">La déconnexion prend effet aux prochaines requêtes. Votre session actuelle est conservée. Les transferts déjà commencés et les accès SMB ne sont pas interrompus.</p></section>`;
}
async function saveControlPreferences(form){
 const generation=sessionGeneration,revision=controlState?.revision;
 const fieldset=form.querySelector('fieldset');fieldset.disabled=true;
 const errorBox=$('#control-error');if(errorBox)errorBox.textContent='';
 try{
  // FormData excludes disabled controls: read the explicit named fields instead.
  const values={name:form.elements.namedItem('name').value,timezone:form.elements.namedItem('timezone').value.trim(),revision};
  if(!zoneKnown(values.timezone))throw new Error('Ce navigateur ne connaît pas ce fuseau. Choisissez-en un dans la liste, par exemple America/Cayenne.');
  const saved=await api('control-panel/configure',values);
  if(generation!==sessionGeneration)return;
  user.nas_name=saved.name;user.timezone=saved.timezone;user.timezone_unset=false;if(typeof drawZonePrompt==='function')drawZonePrompt();
  if(typeof deskEmbedded==='function'&&deskEmbedded())deskParent('deskChildPrefs',saved);
  const host=$('#side-host'),clock=$('#topclock');if(host)host.textContent=saved.name;if(clock)clock.textContent=date(Date.now()/1000);
  if(page==='settings'&&$('#control-preferences')===form){
   controlState={...controlState,...saved};toast('Préférences enregistrées.');
  }
 }catch(error){if(generation===sessionGeneration&&page==='settings'&&$('#control-preferences')===form&&error.name!=='AbortError')$('#control-error').textContent=error.message;}
 finally{fieldset.disabled=false;}
}
async function refreshControlSessions(){
 const generation=sessionGeneration,request=controlRequest,refresh=++controlSessionsRequest;
 const state=await api('control-panel');
 if(generation!==sessionGeneration||page!=='settings'||request!==controlRequest||refresh!==controlSessionsRequest)return;
 controlState.accounts=state.accounts;
 const target=$('#control-sessions');if(target)target.innerHTML=controlSessions(state.accounts);
}
document.addEventListener('submit',async e=>{
 if(e.target.getAttribute('id')!=='control-preferences')return;
 e.preventDefault();if(e.target.querySelector('fieldset').disabled)return;
 await saveControlPreferences(e.target);
});
document.addEventListener('click',async e=>{
 const el=e.target.closest('[data-action]');if(!el)return;
 try{
  if(el.dataset.action==='control-refresh-sessions')return await refreshControlSessions();
  if(el.dataset.action==='control-revoke'){
   const target=controlState?.accounts.find(a=>a.name===el.dataset.name);if(!target)return;
   return confirmAction('Déconnecter les sessions ?',`${target.current?'Les autres sessions':'Les sessions'} du compte ${target.name} devront se reconnecter. Les opérations déjà commencées peuvent se poursuivre. Les accès SMB sont conservés.`,'Déconnecter',async()=>api('control-panel/revoke',{name:target.name,confirm:true}));
  }
 }catch(error){if(error.name!=='AbortError')toast(error.message,true);}
});
