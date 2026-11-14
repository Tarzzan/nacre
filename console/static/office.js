'use strict';
// Suite bureautique : Nacre garde les fichiers, une suite en conteneur les édite. Réglage pour les administrateurs,
// ouverture d’un document dans un nouvel onglet pour tous ceux qui lisent le fichier.
let officeData=null,officeTabs=0;
function officeCan(item){const name=String(item?.name||'').toLowerCase(),ext=name.includes('.')?name.split('.').pop():'';return !!item&&!item.directory&&!item.link&&Array.isArray(user?.office)&&user.office.includes(ext);}
// L’onglet est ouvert dès le clic, puis reçoit le document : un onglet ouvert après une attente serait bloqué par le navigateur.
// Si le navigateur le bloque malgré tout, le document est préparé et un second clic, direct celui-là, l’ouvre.
function officeFields(made){return `<input type="hidden" name="access_token" value="${esc(made.token)}"><input type="hidden" name="access_token_ttl" value="${esc(String(made.ttl))}">`;}
async function officeSend(space,path,prepare){
 const name='nacre-bureautique-'+(++officeTabs)+'-'+Date.now();let tab=null;
 try{tab=window.open('about:blank',name);}catch{}
 let made;
 try{if(prepare)path=await prepare();made=await api('office/open',{area:space,path});}catch(error){try{tab?.close();}catch{}throw error;}
 if(!tab)return {...made,blocked:true};
 // L’onglet de la suite ne garde aucune prise sur la fenêtre de Nacre.
 try{tab.opener=null;}catch{}
 const form=document.createElement('form');form.method='post';form.action=made.action;form.target=name;form.hidden=true;form.innerHTML=officeFields(made);
 document.body.append(form);form.submit();form.remove();
 return made;
}
function officeReady(made){
 const m=$('#modal');
 m.innerHTML=`<form id="office-go" method="post" action="${esc(made.action)}" target="_blank" rel="noopener"><div class="modalhead"><h2>Document prêt</h2><button type="button" class="iconbtn" data-action="close-modal" aria-label="Fermer">${icon('close')}</button></div><div class="modalbody"><p class="muted">Le navigateur n’a pas ouvert l’onglet de lui-même. « ${esc(made.name)} » est prêt : ouvrez-le ici.</p>${officeFields(made)}<div class="modalfoot"><button type="button" data-action="close-modal">Annuler</button><button class="primary" type="submit">Ouvrir le document</button></div></div></form>`;
 m.showModal();
}
async function officeOpen(space,path){
 const made=await officeSend(space,path);
 if(made.blocked)return officeReady(made);
 toast(made.write?'Document ouvert dans la suite bureautique. Chaque enregistrement garde l’ancien contenu comme version.':'Document ouvert en lecture dans la suite bureautique.');
}
// Création depuis « Nouveau document » : le fichier vide est créé, puis ouvert. S’il est créé sans pouvoir s’ouvrir, on le dit.
async function officeCreate(space,folder,name){
 let created=null,made;
 try{made=await officeSend(space,null,async()=>created=(await api('office/new',{area:space,path:folder,name})).path);}
 catch(error){if(!created)throw error;return {message:`Document créé, mais non ouvert : ${error.message}`};}
 // La fenêtre « Nouveau document » se referme d’abord ; « Document prêt » ne s’ouvre qu’une fois sa fermeture finie.
 if(made.blocked){$('#modal').addEventListener('close',()=>setTimeout(()=>officeReady(made),0),{once:true});return {message:'Document créé.'};}
 return {message:'Document créé et ouvert dans la suite bureautique.'};
}
function officeValid(d){return d&&typeof d.enabled==='boolean'&&typeof d.url==='string'&&typeof d.wopi==='string'&&Array.isArray(d.formats)?d:null;}
function officeHtml(d){
 const state=!d.enabled?['dim','Non raccordée']:d.reachable?['','Raccordée']:['warn','Raccordée, mais injoignable'];
 return heading('Éditer textes, classeurs et présentations.','Nacre garde les fichiers, les droits et les versions ; une suite bureautique en conteneur les édite.',button('office-refresh','Actualiser','activity','small'))+
  `<div class="stack"><section class="card cardpad" id="office-state"><h2>État</h2><p><span class="badge ${state[0]}">${state[1]}</span> ${d.enabled?(d.reachable?`La suite répond et ouvre ${d.formats.length} format${d.formats.length>1?'s':''} : ${d.formats.map(esc).join(', ')}.`:esc(d.error||'La suite ne répond pas.')):'Aucune suite n’est raccordée : les documents bureautiques se téléchargent.'}</p></section>`+
  `<section class="card cardpad" id="office-settings"><h2>Raccorder une suite</h2><form id="office-form" method="post"><div class="field"><label for="office-url">Adresse de la suite, pour le navigateur</label><input id="office-url" name="url" type="text" value="${esc(d.url)}" placeholder="http://localhost:9980" autocomplete="off"><small>Celle que le navigateur de chaque personne peut joindre.</small></div>`+
  `<div class="field"><label for="office-wopi">Adresse de Nacre, pour la suite</label><input id="office-wopi" name="wopi" type="text" value="${esc(d.wopi||d.default_wopi||'')}" placeholder="${esc(d.default_wopi||'http://127.0.0.1:8766')}" autocomplete="off"><small>Celle par laquelle la suite lit et enregistre les fichiers.</small></div>`+
  `<details><summary>Réglage avancé</summary><div class="field"><label for="office-internal">Adresse de la suite, pour Nacre (si elle diffère)</label><input id="office-internal" name="internal" type="text" value="${esc(d.internal||'')}" autocomplete="off"></div></details>`+
  `<p id="office-error" class="error" role="alert"></p><div class="row"><button class="primary" type="submit">${d.enabled?'Enregistrer':'Raccorder la suite'}</button>${d.enabled?button('office-off','Débrancher la suite',null,''):''}</div></form></section></div>`+
  '<p class="capacity-note">Nacre n’installe pas la suite : un administrateur lance Collabora Online en conteneur, puis indique ici où la joindre. Le guide donne la commande. Chaque document s’ouvre dans un nouvel onglet, avec un jeton limité à ce fichier, à cette personne et à huit heures.</p>';
}
async function renderOffice(){
 const generation=sessionGeneration,current=()=>generation===sessionGeneration&&page==='office';
 if(user?.role!=='admin'){$('#content').innerHTML=heading('Suite bureautique.','')+'<div class="notice neutral">Cette page est réservée aux administrateurs.</div>';return;}
 const data=officeValid(await api('office'));if(!current())return;
 if(!data){$('#content').innerHTML=heading('Suite bureautique.','')+'<div class="notice neutral">Réponse illisible du serveur. Utilisez Actualiser.</div>';return;}
 officeData=data;$('#content').innerHTML=officeHtml(data);
}
document.addEventListener('submit',async e=>{
 // Document prêt : le formulaire part tel quel vers la suite, la fenêtre se referme derrière lui.
 if(e.target.getAttribute?.('id')==='office-go'){setTimeout(()=>{try{$('#modal').close();}catch{}},0);return;}
 if(e.target.getAttribute?.('id')!=='office-form')return;
 e.preventDefault();
 const error=$('#office-error'),send=e.target.querySelector?.('button[type=submit]');if(error)error.textContent='';if(send)send.disabled=true;
 try{
  await api('office/configure',{enabled:true,url:String($('#office-url')?.value||''),wopi:String($('#office-wopi')?.value||''),internal:String($('#office-internal')?.value||'')});
  user.office=(await api('me')).office||[];toast('Suite bureautique raccordée.');await renderOffice();
 }catch(failure){if(failure.name!=='AbortError'&&error)error.textContent=failure.message;}
 finally{if(send)send.disabled=false;}
});
document.addEventListener('click',async e=>{
 const el=e.target.closest?.('[data-action^="office-"]');if(!el||el.disabled||!user)return;
 try{
  switch(el.dataset.action){
   case 'office-refresh':if(page==='office')await renderOffice();return;
   case 'office-off':if(page!=='office'||!officeData)return;return confirmAction('Débrancher la suite bureautique ?','Les documents bureautiques ne s’ouvriront plus depuis Nacre ; ceux qui sont ouverts ne pourront plus s’enregistrer. Aucun fichier n’est touché.','Débrancher',async()=>{await api('office/configure',{enabled:false,url:officeData.url,wopi:officeData.wopi,internal:officeData.internal||''});user.office=[];return {message:'Suite bureautique débranchée.'};});
   case 'office-open':{if(page!=='files'||typeof fmSelected!=='function')return;const chosen=fmSelected();if(chosen.length!==1||!officeCan(chosen[0]))return;return await officeOpen(area,fmJoin(chosen[0].name));}
  }
 }catch(error){if(error.name!=='AbortError')toast(error.message,true);}
});
