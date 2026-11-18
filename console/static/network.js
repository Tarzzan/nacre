'use strict';
// Accès par le réseau : ouvrir la console en HTTPS sous des noms déclarés. Page réservée aux administrateurs.
let networkData=null;
function networkValid(d){
 if(!d||typeof d.enabled!=='boolean'||!Number.isInteger(d.port)||!Array.isArray(d.hosts)||!d.hosts.every(h=>typeof h==='string')||!Array.isArray(d.addresses)||!Array.isArray(d.urls))return null;
 if(d.certificate!==null&&(typeof d.certificate!=='object'||typeof d.certificate.fingerprint!=='string'))return null;
 return ['admins','everyone'].includes(d.require_totp)?d:null;
}
// Faire reconnaître le NAS par un appareil : on y installe une fois le certificat de l’autorité locale, qui n’est pas un secret.
function trustCard(authority,admin=false){
 if(!authority||typeof authority.fingerprint!=='string')return '';
 const extra=Array.isArray(authority.extra)&&authority.extra.length?` Elle couvre aussi : ${authority.extra.map(esc).join(', ')}.`:'';
 return `<section class="card cardpad" id="trust"><h2>Faire reconnaître ce NAS par vos appareils</h2><p>Par le réseau, un navigateur avertit tant qu’il ne connaît pas l’autorité qui a signé le certificat de ce NAS. Installez-la une fois sur chaque appareil : l’avertissement disparaît, et il ne reviendra pas quand le certificat sera renouvelé.</p>`+
  `<p class="net-print">SHA-256 ${esc(authority.fingerprint)}</p>${typeof authority.fingerprint_sha1==='string'?`<p class="net-print">SHA-1 ${esc(authority.fingerprint_sha1)} <span class="muted">(celle qu’affiche Windows)</span></p>`:''}`+
  `<p class="muted">Cette autorité ne peut certifier que des noms locaux et des adresses privées.${extra} Android et les applications Java n’appliquent pas cette limite : sur ces appareils, tout repose sur le secret de sa clé, qui ne quitte pas ce NAS.${authority.expires?' Valable jusqu’au '+date(authority.expires)+'.':''}</p>`+
  `<div class="row"><a class="fm-link" href="/api/network/authority" download="nacre-autorite-locale.crt">Télécharger l’autorité</a></div>`+
  `<details class="trust-how"><summary>Où l’installer</summary><ul><li><strong>iPhone, iPad</strong> : ouvrir le fichier, puis Réglages → Profil téléchargé → Installer ; enfin Réglages → Général → Informations → Réglages des certificats, et activer la confiance.</li><li><strong>Android</strong> : Paramètres → Sécurité et confidentialité → Autres paramètres de sécurité → Chiffrement et identifiants → Installer un certificat → Certificat CA. Les menus varient selon la marque : en cas de doute, cherchez « certificat » dans les Paramètres.</li><li><strong>Mac</strong> : ouvrir le fichier dans Trousseaux d’accès, puis « Toujours approuver ».</li><li><strong>Windows</strong> : ouvrir le fichier → Installer le certificat → Autorités de certification racines de confiance.</li><li><strong>Firefox</strong> : Paramètres → Vie privée et sécurité → Certificats → Gérer les certificats (« Afficher les certificats… » sur les versions plus anciennes) → onglet Autorités → Importer…, puis cocher « Confirmer cette AC pour identifier des sites web ».</li></ul>`+
  `<p class="muted">${admin?'Avant d’activer la confiance sur un appareil, comparez l’empreinte qu’il affiche à celle lue ici, sur la console ouverte depuis la machine elle-même. Celle d’une page atteinte par le réseau ne suffit pas si le navigateur a averti en y arrivant.':'Demandez cette empreinte à l’administrateur de ce NAS avant d’installer, et comparez-la à celle que l’appareil affiche : celle de cette page ne suffit pas si le navigateur vous a averti en y arrivant.'}</p></details></section>`;
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
  `<section class="card cardpad" id="network-cert"><h2>Certificat</h2>${cert?`<p>${d.provided?'Certificat fourni par vos soins.':d.kind==='authority'?'Certificat de serveur signé par l’autorité locale de ce NAS. Il se renouvelle seul avant son échéance, sans rien demander aux appareils qui connaissent l’autorité.':'Ancien certificat autosigné : chaque appareil doit l’accepter, et de nouveau à chaque changement. Refaites-le pour passer à une autorité locale, que les appareils installent une fois pour toutes.'}</p><p class="net-print">SHA-256 ${esc(cert.fingerprint)}</p><p class="muted">${cert.expires?'Valable jusqu’au '+date(cert.expires)+'. ':''}${Array.isArray(cert.names)&&cert.names.length?'Noms couverts : '+cert.names.map(esc).join(', ')+'.':''}</p>`:`<p class="muted">Aucun certificat pour l’instant : il sera produit à l’ouverture de l’accès réseau${d.openssl?'':', ce qui demande OpenSSL, introuvable sur cette machine'}.</p>`}<div class="row">${cert&&d.openssl&&d.hosts.length?button('network-regenerate',d.kind==='authority'?'Refaire le certificat de serveur':'Passer à une autorité locale',null,'small')+(d.authority?button('network-authority','Refaire l’autorité',null,'small'):''):''}${button('network-provide','Fournir un certificat',null,'small')}</div></section>${d.provided?'':trustCard(d.authority,true)}</div>`+
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
const NETWORK_REMADE='Autorité locale refaite : installez la nouvelle sur vos appareils.';
async function networkSend(body,message){
 const done=await api('network/configure',body);toast(done?.authority_made?NETWORK_REMADE:message);
 await networkSettle();
 if(page==='network')await renderNetwork();
}
// Refus de l’autorité pour un nom hors de son domaine : la refaire se propose ici, avec ce que cela coûte.
function networkWiden(values,failure){
 if(failure?.status!==409||failure.reason!=='authority')return false;
 const ask=()=>confirmAction('Refaire l’autorité locale pour y ajouter ce nom ?',`${failure.message} Tant qu’ils n’auront pas installé la nouvelle autorité, les appareils afficheront un avertissement ou refuseront la connexion.`,'Refaire l’autorité',
  async()=>{await api('network/configure',{...values,enabled:true,confirm:true,authority:'renew'});await networkSettle();return {message:NETWORK_REMADE};});
 // Une fenêtre de confirmation est peut-être encore ouverte : la question n’arrive qu’une fois celle-ci refermée.
 const m=$('#modal');if(m?.open)m.addEventListener('close',()=>setTimeout(ask,0),{once:true});else ask();
 return true;
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
  // Changer les noms d’un ancien certificat autosigné le remplace : on le dit avant, jamais après.
  const names=d.certificate?.names||[],moved=d.kind==='self'&&d.certificate&&(names.length!==values.hosts.length||values.hosts.some(h=>!names.map(n=>String(n).toLowerCase()).includes(h)));
  if(moved)return confirmAction('Remplacer le certificat ?',`${d.enabled?'':`La console répondra en HTTPS sur le port ${values.port}, sous : ${values.hosts.join(', ')}. `}Changer les noms remplace l’ancien certificat autosigné par une autorité locale et un nouveau certificat. Les appareils qui avaient accepté l’ancien devront accepter le nouveau, ou installer l’autorité une fois pour toutes.`,'Remplacer',
   async()=>{await api('network/configure',{...values,enabled:true,confirm:true,replace:true});await networkSettle();return {message:d.enabled?'Réglages enregistrés, certificat remplacé.':'Accès réseau ouvert, certificat remplacé.'};});
  if(d.enabled)return await networkSend({...values,enabled:true,confirm:true},'Réglages de l’accès réseau enregistrés.');
  confirmAction('Ouvrir la console au réseau ?',`La console répondra en HTTPS sur le port ${values.port}, pour tout appareil qui peut atteindre cette machine, sous : ${values.hosts.join(', ')}. ${d.my_totp?'':'Votre compte n’a pas la double authentification : il sera refusé par le réseau tant que vous ne l’aurez pas activée. '}Vous pourrez refermer cet accès à tout moment.`,'Ouvrir',
   async()=>{
    try{await api('network/configure',{...values,enabled:true,confirm:true});}
    catch(failure){if(!networkWiden(values,failure))throw failure;await networkSettle();return {message:'L’autorité locale ne couvre pas ce nom.'};}
    await networkSettle();return {message:'Accès réseau ouvert.'};});
 }catch(failure){if(failure.name!=='AbortError'&&!networkWiden(values,failure)&&error)error.textContent=failure.message;}
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
   case 'network-regenerate':{
    // « Sous la même autorité » ne se promet que si elle est là : sinon une autorité neuve sera créée, et on le dit.
    const same=d.kind==='authority'&&!!d.authority;
    return confirmAction(same?'Refaire le certificat de serveur ?':'Passer à une autorité locale ?',same?'Un nouveau certificat de serveur remplace l’actuel, sous la même autorité : les appareils qui la connaissent n’ont rien à refaire. Les autres verront une nouvelle empreinte.':'Une autorité locale et un nouveau certificat remplacent le certificat actuel. Les appareils qui l’avaient accepté devront accepter le nouveau, ou installer l’autorité une fois pour toutes.','Refaire',
     async()=>{const done=await api('network/certificate',{action:'regenerate'});await networkSettle();return {message:done?.authority_made?NETWORK_REMADE:'Certificat refait.'};});}
   case 'network-authority':return confirmAction('Refaire l’autorité locale ?',`Une nouvelle autorité remplace l’actuelle, avec un nouveau certificat de serveur. Tous les appareils qui avaient installé l’ancienne devront installer la nouvelle : jusque-là, ils afficheront un avertissement ou refuseront la connexion. À ne faire que si sa clé a pu être copiée, ou pour y ajouter un nom public. Dans le premier cas, retirez aussi l’ancienne autorité de vos appareils${typeof d.authority?.fingerprint==='string'?' (empreinte SHA-256 '+d.authority.fingerprint.slice(0,23)+'…)':''} : elle y resterait valable.`,'Refaire l’autorité',
    async()=>{await api('network/certificate',{action:'authority',confirm:true});await networkSettle();return {message:NETWORK_REMADE};});
   case 'network-provide':return modal('Fournir un certificat','<p class="muted">Collez le certificat et sa clé privée au format PEM. Ils sont vérifiés ensemble avant de remplacer quoi que ce soit.</p><div class="field"><label for="network-pem">Certificat (et chaîne)</label><textarea id="network-pem" class="pem" name="certificate" required spellcheck="false"></textarea></div><div class="field"><label for="network-key">Clé privée</label><textarea id="network-key" class="pem" name="key" required spellcheck="false"></textarea></div>','Installer',
    async form=>{await api('network/certificate',{action:'provide',certificate:String(form.get('certificate')||''),key:String(form.get('key')||'')});await networkSettle();return {message:'Certificat installé.'};});
  }
 }catch(error){if(error.name!=='AbortError')toast(error.message,true);}
});
