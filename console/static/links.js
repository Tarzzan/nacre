'use strict';
// Liens de partage : un fichier ou un dossier ouvert en lecture, sans compte, jusqu’à une date.
let linksData=null,linkFresh=null;
const LINK_DAYS={1:'1 jour',7:'7 jours',30:'30 jours',90:'90 jours'};

function linksValid(d){
 const text=v=>typeof v==='string'&&v.length<=400;
 if(!d||!Array.isArray(d.links))return null;
 return d.links.every(l=>l&&text(l.id)&&l.id&&text(l.name)&&text(l.space)&&text(l.by)&&Number.isFinite(l.expires)&&typeof l.expired==='boolean'&&typeof l.protected==='boolean'&&Number.isFinite(l.uses))?d:null;
}
// Un espace se partage par lien s’il est commun, personnel ou d’équipe, et si la personne y écrit.
function linkAllowed(){return user?.role!=='viewer'&&(area==='fichiers'||area.startsWith('espace_'))&&!!fileAreas.find(a=>a.id===area)?.writable;}
function linkAsk(path,item){
 const where=area,days=linksData?.days||[1,7,30,90],min=linksData?.password_min||8;
 modal('Partager par lien',
  `<p><strong>${esc(item.name)}</strong> · ${item.directory?'dossier, avec tout son contenu':'fichier'}</p>`+
  `<div class="field"><label for="link-days">Le lien fonctionne pendant</label><select id="link-days" name="days">${days.map(d=>`<option value="${d}" ${d===7?'selected':''}>${LINK_DAYS[d]||d+' jours'}</option>`).join('')}</select></div>`+
  `<div class="field"><label for="link-password">Mot de passe (facultatif)</label><input id="link-password" name="password" type="text" minlength="${min}" maxlength="128" autocomplete="off"><small>${min} caractères minimum. À transmettre par un autre moyen que le lien.</small></div>`+
  '<p class="capacity-note">Toute personne qui a le lien lit et télécharge cet élément, sans compte, jusqu’à l’échéance. Le lien n’est affiché qu’une fois : copiez-le aussitôt. Vous pouvez le révoquer à tout moment dans l’onglet Liens.</p>',
  'Créer le lien',async form=>{
   const made=await api('links/create',{area:where,path,days:Number(form.get('days')),password:String(form.get('password')||'')});
   linkFresh={url:location.origin+made.url,name:made.name,expires:made.expires,at:Date.now()};
   // La fenêtre passe à l’onglet Liens une fois la confirmation refermée, pour montrer le lien à copier.
   setTimeout(()=>{Promise.resolve(go('links')).catch(()=>{});},0);
   return {message:'Lien créé. Copiez-le maintenant : il ne sera plus affiché.'};
  });
}
function linksFreshHtml(){
 // Le lien tout juste créé reste affiché dix minutes, ou jusqu’à ce qu’on le referme.
 if(!linkFresh||Date.now()-linkFresh.at>600000){linkFresh=null;return '';}
 return `<section class="card cardpad link-fresh" id="link-fresh"><h2>Lien créé pour « ${esc(linkFresh.name)} »</h2><p>Copiez-le maintenant : il ne sera plus affiché. Il fonctionne jusqu’au ${date(linkFresh.expires)}.</p><div class="row"><input id="link-url" type="text" readonly value="${esc(linkFresh.url)}" aria-label="Lien de partage">${button('links-copy','Copier','check','primary small')}${button('links-seen','J’ai copié le lien',null,'small')}</div></section>`;
}
function linksHtml(d){
 const admin=user?.role==='admin';
 const rows=d.links.map(l=>`<tr class="${l.expired?'link-old':''}"><td><strong>${esc(l.name)}</strong>${l.directory?' <span class="badge dim">Dossier</span>':''}<br><small class="muted">${esc(l.space)}${l.path&&l.path!==l.name?' · '+esc(l.path):''}</small></td>${admin?`<td>${esc(l.by)}</td>`:''}<td>${l.expired?'<span class="badge warn">Échu</span>':date(l.expires)}</td><td>${l.protected?'Mot de passe':'Lien seul'}</td><td>${l.uses.toLocaleString('fr-FR')}${l.last?`<br><small class="muted">dernier : ${date(l.last)}</small>`:''}</td><td>${button('links-revoke',l.expired?'Retirer':'Révoquer',null,'small',`data-id="${esc(l.id)}"`)}</td></tr>`);
 return heading('Ce que vous partagez par lien.','Chaque lien s’éteint à son échéance ; vous pouvez le révoquer avant.',button('links-refresh','Actualiser','activity','small'))+linksFreshHtml()+
  `<section class="card" id="links-list"><div class="cardhead"><h2>Liens de partage</h2><span class="muted">${d.links.filter(l=>!l.expired).length} actif(s)</span></div>${rows.length?table(['Élément',...(admin?['Créé par']:[]),'Échéance','Protection','Téléchargements',''],rows):empty('Aucun lien. Dans Fichiers, sélectionnez un élément puis « Partager par lien ».','share')}</section>`+
  '<p class="capacity-note">Un lien ne fonctionne que là où la console est joignable. Il s’éteint aussi si sa cible disparaît, ou dès que son auteur n’a plus accès à l’espace. Chaque téléchargement est inscrit au journal.</p>';
}
async function renderLinks(){
 const generation=sessionGeneration,current=()=>generation===sessionGeneration&&page==='links';
 if(user?.role==='viewer'){$('#content').innerHTML=heading('Liens de partage.','')+'<div class="notice neutral">Les liens de partage demandent un compte qui écrit dans un espace.</div>';return;}
 const data=linksValid(await api('links'));if(!current())return;
 if(!data){$('#content').innerHTML=heading('Liens de partage.','')+'<div class="notice neutral">Réponse illisible du serveur. Utilisez Actualiser.</div>';return;}
 linksData=data;$('#content').innerHTML=linksHtml(data);
}
document.addEventListener('click',async e=>{
 const el=e.target.closest?.('[data-action^="links-"]');if(!el||el.disabled||page!=='links'||!user)return;
 try{
  switch(el.dataset.action){
   case 'links-refresh':return await renderLinks();
   case 'links-seen':linkFresh=null;return await renderLinks();
   case 'links-copy':{
    const input=$('#link-url');if(!input)return;
    try{await navigator.clipboard.writeText(input.value);toast('Lien copié.');}
    catch{input.select?.();toast('Copie automatique indisponible : le lien est sélectionné, copiez-le au clavier.');}
    return;
   }
   case 'links-revoke':{
    const link=linksData?.links.find(l=>l.id===el.dataset.id);if(!link)return;
    return confirmAction(link.expired?'Retirer ce lien de la liste ?':'Révoquer ce lien ?',link.expired?`Le lien vers « ${link.name} » est déjà échu.`:`Le lien vers « ${link.name} » cesse aussitôt de fonctionner pour tous ceux qui l’ont reçu. Aucun fichier n’est touché.`,link.expired?'Retirer':'Révoquer',async()=>{await api('links/revoke',{id:link.id});return {message:link.expired?'Lien retiré.':'Lien révoqué.'};});
   }
  }
 }catch(error){if(error.name!=='AbortError')toast(error.message,true);}
});
