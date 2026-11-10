'use strict';
let setupState=null, setupStep=0;

function setupSteps(step){
 return `<ol class="setup-steps" aria-label="Étapes de configuration">${['Votre compte','Votre système','Vos usages'].map((label,i)=>`<li class="${i===step?'current':i<step?'done':''}" ${i===step?'aria-current="step"':''}><span>${i<step?'✓':i+1}</span>${label}</li>`).join('')}</ol>`;
}

async function renderSetup(){
 if(user.role!=='admin'){$('#content').innerHTML=empty('La configuration est réservée aux administrateurs.','lock');return;}
 const generation=sessionGeneration;
 const data=await api('setup');
 if(generation!==sessionGeneration||page!=='setup')return;
 setupState=data;setupStep=data.phase==='account'?0:1;
 drawSetup();
}

function drawSetup(){
 const d=setupState;
 const content=$('#content');if(!content||!user||page!=='setup')return;
 let body='';
 if(setupStep===0){
  body=`<form method="post" id="setup-account" class="setup-form"><p class="eyebrow">UN ACCÈS QUI VOUS APPARTIENT</p><h2>Sécurisez votre compte.</h2><p>Le compte <strong>admin</strong> est votre premier administrateur. Remplacez son mot de passe provisoire avant de configurer votre NAS.</p>${field('Votre nouveau mot de passe','password','','password','12 à 128 caractères. Conservez-le dans votre gestionnaire de mots de passe.')}${field('Confirmer le mot de passe','confirmation','','password')}<p id="setup-error" class="error" role="alert"></p><button type="submit" class="primary">Enregistrer et continuer ${icon('arrow')}</button><p class="capacity-note">Les autres sessions et liens de connexion en attente seront révoqués. Les comptes Samba et caméra restent distincts.</p></form>`;
 }else if(setupStep===1){
  const s=d.system;
  body=`<div class="setup-system"><div class="setup-summary"><div><p class="eyebrow">VOTRE MACHINE, SES CAPACITÉS</p><h2>Faisons connaissance.</h2><p>Les composants peuvent être ajoutés progressivement. La détection consulte le système sans modifier vos disques.</p></div><div class="setup-machine">${icon('server')}<strong>${esc(s.os)} · ${esc(s.architecture)}</strong><span>${esc(s.cpus)} processeur(s) · Python ${esc(s.python)}</span><span>${sizes(s.free)} disponibles pour cette installation</span></div></div>${!s.supported||!s.non_root?'<p class="notice">Configuration à corriger : utiliser Linux x86-64 ou ARM64, Python 3.11+, avec un compte non root.</p>':''}<div class="setup-capabilities">${d.capabilities.map(c=>`<article class="setup-capability"><div class="row"><h3>${esc(c.title)}</h3><span class="badge ${c.ready?'':'warn'}">${c.ready?'Disponible':c.detected?'À vérifier':'À préparer'}</span></div><p>${esc(c.detail)}</p></article>`).join('')}</div><div class="setup-actions">${button('setup-refresh','Relancer la détection','activity')}<button type="button" data-action="setup-components">Installer les composants</button>${button('setup-next','Continuer','arrow','primary')}</div><p class="capacity-note">« Disponible » indique un composant accessible, pas une sauvegarde active ni une caméra connectée. Les fonctions natives demandent une politique explicite.</p></div>`;
 }else{
  body=`<form method="post" id="setup-finish" class="setup-form"><p class="eyebrow">UN NAS À VOTRE MESURE</p><h2>Donnez-lui ses repères.</h2><p>Vous pourrez ensuite choisir vos volumes, vos partages et votre protection.</p>${field('Nom affiché du NAS','name',d.name,'text','Ce nom est utilisé dans Nacre ; le nom réseau Linux reste inchangé.')}${field('Fuseau horaire','timezone',d.existing||d.phase==='complete'?d.timezone:Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC','text','Exemples : Europe/Paris, America/Cayenne, UTC. Les plans existants conservent leur propre fuseau.')}<div class="setup-next"><strong>Après cet assistant</strong><p>1. Choisissez votre stockage et vos partages.</p><p>2. Ajoutez une destination de sauvegarde.</p><p>3. Configurez la surveillance si vous en avez besoin.</p></div><p id="setup-error" class="error" role="alert"></p><div class="setup-actions">${button('setup-back','Retour', 'left')}<button type="submit" class="primary">Enregistrer et ouvrir mon NAS ${icon('arrow')}</button></div><p class="capacity-note">Chaque fonction reste à configurer selon votre matériel. Aucun disque ni plan de sauvegarde n’est créé par cet assistant.</p></form>`;
 }
 content.innerHTML=heading('Bienvenue chez vous.','Quelques étapes pour prendre les commandes de votre NAS.')+`<div class="setup-layout"><aside class="setup-intro"><span class="brandmark">${icon('server')}</span><h2>Vos données.<br>Vos choix.</h2><p>Un point de départ commun, du petit serveur au NAS dédié.</p>${setupSteps(setupStep)}<p class="setup-private">${icon('lock')} Configuration conservée sur ce serveur.</p></aside><section class="card setup-panel">${body}</section></div>`;
}

document.addEventListener('click',async e=>{
 const action=e.target.closest('[data-action]')?.dataset.action;
 if(!action?.startsWith('setup-'))return;
 try{
  if(action==='setup-components'){user.setup_required=false;return await go('services');}
  if(action==='setup-refresh')return await renderSetup();
  if(action==='setup-next')setupStep=2;
  if(action==='setup-back')setupStep=1;
  drawSetup();
 }catch(error){if(error.name!=='AbortError')toast(error.message,true);}
});

document.addEventListener('submit',async e=>{
 if(!['setup-account','setup-finish'].includes(e.target.getAttribute('id')))return;
 e.preventDefault();const form=e.target,submit=form.querySelector('[type=submit]');submit.disabled=true;
 const generation=sessionGeneration;
 try{
  const values=Object.fromEntries(new FormData(form));
  if(form.getAttribute('id')==='setup-account'){
   const result=await api('setup/account',values);user.csrf=result.csrf;
   form.reset();await renderSetup();
  }else{
   await api('setup/finish',values);user=await api('me');shell();
   $('#content').innerHTML=heading('Votre console est prête.','Choisissez la première fonction à configurer.')+`<div class="notice">Configuration enregistrée pour <strong>${esc(user.nas_name)}</strong>. Les fonctions ci-dessous s’adaptent aux composants disponibles sur votre serveur.</div><div class="native-summary">${[['storage','disk','Votre stockage','Consulter les disques, puis préparer les volumes et partages.'],['backups','backup','Votre protection','Choisir une destination et créer un plan de sauvegarde.'],['camera','camera','Votre surveillance','Retrouver le direct et les réglages de votre caméra.']].map(([p,ic,title,detail])=>`<section class="card cardpad">${icon(ic)}<h2>${title}</h2><p>${detail}</p><button data-page="${p}" class="primary">Ouvrir ${icon('arrow')}</button></section>`).join('')}</div><button data-page="home">Aller à la vue d’ensemble</button>`;
  }
 }catch(error){if(generation===sessionGeneration&&$('#setup-error'))$('#setup-error').textContent=error.message;else if(error.name!=='AbortError')toast(error.message,true);}
 finally{submit.disabled=false;}
});
