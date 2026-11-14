'use strict';
// Page d’un lien de partage : sans compte, en lecture. Rien d’autre de la console n’est chargé ici.
const pubToken=typeof location==='undefined'?'':(location.pathname.split('/')[2]||'');
let pubPath='';
function pubEsc(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function pubSize(n){if(!Number.isFinite(Number(n)))return '—';let x=Number(n),i=0;while(x>=1024&&i<4){x/=1024;i++;}return `${x.toLocaleString('fr-FR',{maximumFractionDigits:i?1:0})} ${['o','Kio','Mio','Gio','Tio'][i]}`;}
function pubDate(t){return Number.isFinite(t)?new Date(t*1000).toLocaleString('fr-FR',{day:'numeric',month:'long',year:'numeric',hour:'2-digit',minute:'2-digit'}):'—';}
function pubApi(action,path=''){return `/api/public/${encodeURIComponent(pubToken)}${action?'/'+action:''}${path?'?path='+encodeURIComponent(path):''}`;}
function pubGone(text){return `<section class="pub-card"><h1>Lien indisponible</h1><p>${pubEsc(text||'Ce lien n’existe pas ou n’est plus valable.')}</p><p class="muted">Demandez un nouveau lien à la personne qui vous l’a envoyé.</p></section>`;}
function pubLocked(info,error=''){
 return `<section class="pub-card"><h1>${pubEsc(info.name)}</h1><p>Ce partage est protégé par un mot de passe.</p><form id="pub-unlock" method="post"><label for="pub-password">Mot de passe</label><input id="pub-password" name="password" type="password" autocomplete="off" required><p class="error" id="pub-error" role="alert">${pubEsc(error)}</p><button class="primary" type="submit">Ouvrir</button></form></section>`;
}
function pubView(info,path=''){
 const until=`<p class="muted">Disponible jusqu’au ${pubDate(info.expires)}.</p>`;
 if(!info.directory)return `<section class="pub-card"><h1>${pubEsc(info.name)}</h1><p>${pubSize(info.size)}</p>${until}<a class="pub-get" href="${pubEsc(pubApi('download'))}" download>Télécharger</a></section>`;
 const chain=path?path.split('/'):[],join=name=>[...chain,name].join('/');
 const crumbs=[`<button type="button" data-pub-path="">${pubEsc(info.name)}</button>`,...chain.map((part,i)=>`<button type="button" data-pub-path="${pubEsc(chain.slice(0,i+1).join('/'))}">${pubEsc(part)}</button>`)].join('<span aria-hidden="true">›</span>');
 const items=Array.isArray(info.items)?info.items.filter(i=>i&&typeof i.name==='string'):[];
 const rows=items.map(i=>i.directory?`<tr><td><button type="button" class="pub-dir" data-pub-path="${pubEsc(join(i.name))}">${pubEsc(i.name)}</button></td><td>Dossier</td><td></td></tr>`:`<tr><td>${pubEsc(i.name)}</td><td>${pubSize(i.size)}</td><td><a href="${pubEsc(pubApi('download',join(i.name)))}" download>Télécharger</a></td></tr>`).join('');
 return `<section class="pub-card pub-wide"><h1>${pubEsc(info.name)}</h1>${until}<nav class="pub-crumbs" aria-label="Emplacement">${crumbs}</nav>`+
  (rows?`<div class="tablewrap"><table class="table"><thead><tr><th>Nom</th><th>Taille</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`:'<p class="muted">Ce dossier est vide.</p>')+
  `<a class="pub-get" href="${pubEsc(pubApi('archive'))}" download>Tout télécharger en archive</a></section>`;
}
async function pubLoad(path=''){
 const box=document.getElementById('pub');if(!box)return;
 let response,info;
 try{response=await fetch(pubApi('',path),{credentials:'same-origin'});info=await response.json();}
 catch{box.innerHTML=pubGone('Le NAS ne répond pas. Réessayez dans un instant.');return;}
 if(!response.ok||!info||typeof info.name!=='string'){box.innerHTML=pubGone(info?.error);return;}
 pubPath=typeof info.path==='string'?info.path:'';
 document.title=`Nacre — ${info.name}`;
 box.innerHTML=info.locked?pubLocked(info):pubView(info,pubPath);
}
if(typeof document!=='undefined'){
 document.addEventListener('DOMContentLoaded',()=>{pubLoad().catch(()=>{});});
 document.addEventListener('click',e=>{const el=e.target.closest?.('[data-pub-path]');if(el)pubLoad(el.dataset.pubPath).catch(()=>{});});
 document.addEventListener('submit',async e=>{
  if(e.target.id!=='pub-unlock')return;
  e.preventDefault();
  const error=document.getElementById('pub-error'),send=e.target.querySelector('button[type=submit]');
  if(send)send.disabled=true;
  try{
   const response=await fetch(pubApi('unlock'),{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:new FormData(e.target).get('password')})});
   const data=await response.json();
   if(!response.ok){if(error)error.textContent=data?.error||'Mot de passe refusé.';return;}
   await pubLoad();
  }catch{if(error)error.textContent='Le NAS ne répond pas. Réessayez dans un instant.';}
  finally{if(send)send.disabled=false;}
 });
}
