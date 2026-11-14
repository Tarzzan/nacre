'use strict';
// Accès par le réseau : ouvrir la console en HTTPS sous des noms déclarés. Page réservée aux administrateurs.
let networkData=null;
function networkValid(d){
 if(!d||typeof d.enabled!=='boolean'||!Number.isInteger(d.port)||!Array.isArray(d.hosts)||!d.hosts.every(h=>typeof h==='string')||!Array.isArray(d.addresses)||!Array.isArray(d.urls))return null;
 if(d.certificate!==null&&(typeof d.certificate!=='object'||typeof d.certificate.fingerprint!=='string'))return null;
 return ['admins','everyone'].includes(d.require_totp)?d:null;
}
function networkHosts(text){return [...new Set(String(text||'').split(/[\s,;]+/).map(h=>h.trim().toLowerCase()).filter(Boolean))];}
function networkHtml(d){
 const state=d.enabled?(d.running?['','Ouvert']:['warn','Ouvert, mais à l’arrêt']):['dim','Fermé'],cert=d.certificate;
 const hint=d.addresses.filter(a=>!d.hosts.includes(a));
 return heading('Joindre le NAS ailleurs que sur la machine.','La console répond en HTTPS, sous les noms que vous déclarez.',button('network-refresh','Actualiser','activity','small'))+
  `<div class="stack"><section class="card cardpad" id="network-state"><h2>État</h2><p><span class="badge ${state[0]}">${state[1]}</span> ${d.enabled?'La console répond sur le réseau, en plus de la machine elle-même.':'La console ne répond que sur la machine elle-même.'}</p>`+
  (d.error?`<div class="notice neutral" role="alert">${esc(d.error)}</div>`:'')+
  (d.urls.length?`<ul class="net-urls">${d.urls.map(u=>`<li>${esc(u)}</li>`).join('')}</ul>`:'')+
  (d.enabled&&!d.my_totp?'<div class="notice neutral">Votre compte n’a pas la double authentification : par le réseau, il sera refusé. Activez-la dans Mon compte.</div>':'')+'</section>'+
  `<section class="card cardpad" id="network-settings"><h2>Réglages</h2><form id="network-form" method="post"><div class="field"><label for="network-hosts">Noms ou adresses de ce NAS</label><input id="network-hosts" name="hosts" type="text" value="${esc(d.hosts.join(', '))}" autocomplete="off" placeholder="nas.local, 192.168.1.20"><small>Ce que l’on tapera dans le navigateur, sans « https:// » ni port. ${d.hosts_max||8} au plus, séparés par des virgules.</small>${hint.length?`<div class="net-hints">${hint.map(a=>button('network-add','Ajouter '+esc(a),'plus','small',`data-host="${esc(a)}"`)).join('')}</div>`:''}</div>`+
  `<div class="formgrid"><div class="field"><label for="network-port">Port</label><input id="network-port" name="port" type="number" min="1024" max="65535" value="${d.port}" required></div><div class="field"><label for="network-policy">Double authentification exigée par le réseau</label><select id="network-policy" name="require_totp"><option value="admins" ${d.require_totp==='admins'?'selected':''}>Pour les administrateurs</option><option value="everyone" ${d.require_totp==='everyone'?'selected':''}>Pour tout le monde</option></select></div></div>`+
  `<p id="network-error" class="error" role="alert"></p><div class="row">${d.enabled?'<button class="primary" type="submit" name="mode" value="save">Enregistrer</button>'+button('network-close','Fermer l’accès réseau',null,''):'<button class="primary" type="submit" name="mode" value="open">Ouvrir l’accès réseau</button>'}</div></form>`+
  '<p class="capacity-note">Le lien de connexion locale reste réservé à la machine elle-même. Par le réseau, un administrateur ne se connecte qu’avec la double authentification.</p></section>'+
  `<section class="card cardpad" id="network-cert"><h2>Certificat</h2>${cert?`<p>${d.provided?'Certificat fourni par vos soins.':'Certificat autosigné : le navigateur affichera un avertissement à la première visite. Comparez alors son empreinte à celle-ci.'}</p><p class="net-print">SHA-256 ${esc(cert.fingerprint)}</p><p class="muted">${cert.expires?'Valable jusqu’au '+date(cert.expires)+'. ':''}${Array.isArray(cert.names)&&cert.names.length?'Noms couverts : '+cert.names.map(esc).join(', ')+'.':''}</p>`:`<p class="muted">Aucun certificat pour l’instant : il sera produit à l’ouverture de l’accès réseau${d.openssl?'':', ce qui demande OpenSSL, introuvable sur cette machine'}.</p>`}<div class="row">${cert&&d.openssl&&d.hosts.length?button('network-regenerate','Refaire le certificat autosigné',null,'small'):''}${button('network-provide','Fournir un certificat',null,'small')}</div></section></div>`+
  '<p class="capacity-note">Ouvrir la console au réseau l’expose à tous les appareils qui peuvent atteindre ce port. Sur un réseau domestique, c’est votre box qui décide de ce qui vient d’Internet : n’y redirigez ce port qu’en connaissance de cause. Les liens de partage fonctionnent là où la console est joignable.</p>';
}
async function renderNetwork(){
 const generation=sessionGeneration,current=()=>generation===sessionGeneration&&page==='network';
 if(user?.role!=='admin'){$('#content').innerHTML=heading('Accès réseau.','')+'<div class="notice neutral">Cette page est réservée aux administrateurs.</div>';return;}
 const data=networkValid(await api('network'));if(!current())return;
 if(!data){$('#content').innerHTML=heading('Accès réseau.','')+'<div class="notice neutral">Réponse illisible du serveur. Utilisez Actualiser.</div>';return;}
 networkData=data;$('#content').innerHTML=networkHtml(data);
}
// Envoi des réglages, puis une relecture un instant plus tard : le point d’écoute change juste après la réponse.
function networkSettle(){return new Promise(resolve=>setTimeout(resolve,900));}
async function networkSend(body,message){
 await api('network/configure',body);toast(message);
 await networkSettle();
 if(page==='network')await renderNetwork();
}
function networkRead(){
 const port=Number($('#network-port')?.value),hosts=networkHosts($('#network-hosts')?.value);
 return {hosts,port,require_totp:$('#network-policy')?.value==='everyone'?'everyone':'admins'};
}
document.addEventListener('submit',async e=>{
 if(e.target.getAttribute?.('id')!=='network-form')return;
 e.preventDefault();
 const d=networkData,error=$('#network-error'),values=networkRead();if(!d)return;
 if(error)error.textContent='';
 if(!Number.isInteger(values.port)||values.port<1024||values.port>65535){if(error)error.textContent='Port invalide : entre 1024 et 65535.';return;}
 if(!values.hosts.length){if(error)error.textContent='Indiquez au moins un nom ou une adresse.';return;}
 try{
  if(d.enabled)return await networkSend({...values,enabled:true,confirm:true},'Réglages de l’accès réseau enregistrés.');
  confirmAction('Ouvrir la console au réseau ?',`La console répondra en HTTPS sur le port ${values.port}, pour tout appareil qui peut atteindre cette machine, sous : ${values.hosts.join(', ')}. ${d.my_totp?'':'Votre compte n’a pas la double authentification : il sera refusé par le réseau tant que vous ne l’aurez pas activée. '}Vous pourrez refermer cet accès à tout moment.`,'Ouvrir',
   async()=>{await api('network/configure',{...values,enabled:true,confirm:true});await networkSettle();return {message:'Accès réseau ouvert.'};});
 }catch(failure){if(failure.name!=='AbortError'&&error)error.textContent=failure.message;}
});
document.addEventListener('click',async e=>{
 const el=e.target.closest?.('[data-action^="network-"]');if(!el||el.disabled||page!=='network'||user?.role!=='admin'||!networkData)return;
 const d=networkData;
 try{
  switch(el.dataset.action){
   case 'network-refresh':return await renderNetwork();
   case 'network-add':{const input=$('#network-hosts');if(input)input.value=[...networkHosts(input.value),el.dataset.host].join(', ');return;}
   case 'network-close':return confirmAction('Fermer l’accès réseau ?','La console ne répondra plus que sur la machine elle-même. Les sessions ouvertes par le réseau s’arrêteront, et les liens de partage ne seront plus joignables de l’extérieur.','Fermer',
    async()=>{await api('network/configure',{hosts:d.hosts,port:d.port,require_totp:d.require_totp,enabled:false});await networkSettle();return {message:'Accès réseau fermé.'};});
   case 'network-regenerate':return confirmAction('Refaire le certificat ?','Un nouveau certificat autosigné remplace l’actuel : les navigateurs afficheront de nouveau leur avertissement, avec une nouvelle empreinte.','Refaire',
    async()=>{await api('network/certificate',{action:'regenerate'});await networkSettle();return {message:'Certificat refait.'};});
   case 'network-provide':return modal('Fournir un certificat','<p class="muted">Collez le certificat et sa clé privée au format PEM. Ils sont vérifiés ensemble avant de remplacer quoi que ce soit.</p><div class="field"><label for="network-pem">Certificat (et chaîne)</label><textarea id="network-pem" class="pem" name="certificate" required spellcheck="false"></textarea></div><div class="field"><label for="network-key">Clé privée</label><textarea id="network-key" class="pem" name="key" required spellcheck="false"></textarea></div>','Installer',
    async form=>{await api('network/certificate',{action:'provide',certificate:String(form.get('certificate')||''),key:String(form.get('key')||'')});await networkSettle();return {message:'Certificat installé.'};});
  }
 }catch(error){if(error.name!=='AbortError')toast(error.message,true);}
});
