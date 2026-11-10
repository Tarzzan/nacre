'use strict';
let notificationState=null;
const notificationEvents={opened:'Nouvel incident',updated:'Incident actualisé',resolved:'Retour à la normale',test:'Test'};
const notificationStatuses={queued:'En attente',sending:'Envoi en cours',sent:'Accepté',failed:'Échec',cancelled:'Annulé'};
function deliveryRows(d){return d.deliveries.map(item=>`<tr><td>${date(item.created)}<small>${esc(notificationEvents[item.event]||item.event)}</small></td><td>${esc(item.title)}</td><td><span class="badge ${item.status==='failed'?'warn':''}">${esc(notificationStatuses[item.status]||item.status)}</span><small>${esc(item.result)}${item.status==='queued'&&item.attempts?' · Prochaine tentative : '+date(item.next):''}</small></td><td>${item.attempts}</td><td>${item.status==='failed'&&item.config_version===d.config.version?button('notification-retry','Relancer','activity','small',`data-id="${esc(item.id)}" data-version="${d.config.version}"`):''}</td></tr>`);}
async function renderNotifications(){
 const generation=sessionGeneration;
 const d=await api('notifications');
 if(generation!==sessionGeneration||page!=='notifications'||!user)return;
 notificationState=d;const c=d.config;
 $('#content').innerHTML=heading('Restez informé.','Recevez les incidents et leurs retours à la normale sur votre destination.',button('notification-configure','Configurer','server','small')+' '+button('notification-refresh','Actualiser','activity','small'))+
 `<div class="cards notification-section"><section class="card cardpad"><div class="metrichead">Envois automatiques</div><h2>${c.enabled?'Activés':'Désactivés'}</h2><p>${c.configured?esc(c.kind==='ntfy'?'ntfy':'Webhook JSON')+' · '+esc(c.destination):'Aucune destination enregistrée'}</p><small>${c.configured?'Chemin confidentiel masqué · '+(c.has_token?'Jeton enregistré':'Sans jeton Bearer'): 'Aucun envoi tant que vous ne configurez pas de destination.'}</small></section><section class="card cardpad"><div class="metrichead">En attente</div><div class="metric">${d.pending}</div><small>File conservée après redémarrage</small></section><section class="card cardpad"><div class="metrichead">Échecs dans l’historique affiché</div><div class="metric">${d.deliveries.filter(i=>i.status==='failed').length}</div><small>Consultez le résultat avant de relancer</small></section></div>`+
 (d.dropped?`<div class="notice neutral">${d.dropped} notification(s) non ajoutée(s) car la file était pleine. Les incidents locaux restent disponibles.</div>`:'')+
 `<section class="card cardpad notification-section"><div class="cardhead"><h2>Vérifier la destination</h2>${button('notification-test','Envoyer un test','activity','small',c.configured?'':'disabled')}</div><p>Le test envoie un message fictif, même si les envois automatiques sont désactivés. « Accepté » signifie que le serveur a répondu avec succès ; cela ne prouve pas la lecture du message sur votre téléphone.</p><p class="muted">${c.minimum==='critical'?'Incidents critiques uniquement':'Tous les niveaux d’incident'} · Retours à la normale ${c.recovery?'inclus':'exclus'}. Les incidents déjà présents lors de l’activation ne sont pas renvoyés.</p></section>`+
 `<section class="card notification-history"><div class="cardhead"><h2>Livraisons récentes</h2><span class="muted">100 dernières entrées affichées</span></div>${d.deliveries.length?table(['Création','Message','Résultat','Tentatives',''],deliveryRows(d)):empty('Aucun envoi enregistré.','activity')}</section>`+
 '<p class="capacity-note">Les notifications contiennent le titre et le message de l’incident, dont le nom technique de la caméra le cas échéant. Aucun mot de passe caméra, flux vidéo ou fichier n’est envoyé. Nacre doit fonctionner pour émettre une notification. Une interruption après réception peut entraîner un doublon lors de la reprise.</p>';
}
function notificationConfigModal(){
 const c=notificationState.config;
 modal('Notifications externes',`<p>Choisissez votre service. Pour ntfy, indiquez l’URL complète du sujet auquel votre téléphone ou navigateur est abonné.</p><div class="field"><label for="notification-kind">Destination</label><select id="notification-kind" name="kind"><option value="webhook" ${c.kind==='webhook'?'selected':''}>Webhook JSON</option><option value="ntfy" ${c.kind==='ntfy'?'selected':''}>ntfy</option></select></div><div class="field"><label for="notification-url">Adresse de destination</label><input id="notification-url" name="url" type="password" autocomplete="new-password" placeholder="${c.configured?'Laisser vide pour conserver la destination':'https://notifications.example/sujet'}"><small>HTTPS requis. HTTP autorisé uniquement vers 127.0.0.1 ou ::1 pour un relais local. ${c.configured?'Destination actuelle : '+esc(c.destination)+' · chemin masqué.':''}</small></div><div class="field"><label for="notification-token">Jeton Bearer (facultatif)</label><input id="notification-token" name="token" type="password" autocomplete="new-password"><small>${c.has_token?'Un jeton est enregistré ; laisser vide pour le conserver.':'Aucun jeton enregistré.'}</small></div><div class="checks"><label><input type="checkbox" name="clear_token">Supprimer le jeton enregistré</label></div><div class="field"><label for="notification-minimum">Gravité minimale</label><select id="notification-minimum" name="minimum"><option value="warning" ${c.minimum==='warning'?'selected':''}>Tous les incidents</option><option value="critical" ${c.minimum==='critical'?'selected':''}>Critique uniquement</option></select></div><div class="checks"><label><input type="checkbox" name="recovery" ${c.recovery?'checked':''}>Notifier les retours à la normale</label><label><input type="checkbox" name="enabled" ${c.enabled?'checked':''}>Activer les envois automatiques des prochains incidents</label></div><p class="capacity-note">Enregistrer annule les anciens envois en attente. Une requête déjà partie peut toutefois être reçue. Les secrets sont conservés dans la base privée de Nacre et dans ses sauvegardes ; ils ne sont pas réaffichés ici.</p>`,'Enregistrer',async f=>api('notifications/configure',{version:c.version,...Object.fromEntries(f),enabled:f.has('enabled'),recovery:f.has('recovery'),clear_token:f.has('clear_token')}));
}
document.addEventListener('click',async e=>{
 const el=e.target.closest('[data-action]');if(!el)return;
 try{
  if(el.dataset.action==='notification-settings')return await go('notifications');
  if(el.dataset.action==='notification-refresh')return await renderNotifications();
  if(el.dataset.action==='notification-configure'&&notificationState)return notificationConfigModal();
  if(el.dataset.action==='notification-test'&&notificationState){
   const version=notificationState.config.version;
   return confirmAction('Envoyer une notification de test','Un message fictif sera envoyé à la destination enregistrée. Aucun incident réel ne sera inclus.','Envoyer le test',async()=>api('notifications/test',{version}));
  }
  if(el.dataset.action==='notification-retry'){
   el.disabled=true;await api('notifications/retry',{id:el.dataset.id,version:Number(el.dataset.version)});
   if(page==='notifications')await renderNotifications();
  }
 }catch(error){if(error.name!=='AbortError')toast(error.message,true);}
 finally{if(el.dataset.action==='notification-retry')el.disabled=false;}
});
