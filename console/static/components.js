'use strict';
let selectedCamera='',cameraCatalog=[],cameraDetail=false,cameraRequest=0,cameraHealthTimer=null;
function cameraQuery(){return '?camera='+encodeURIComponent(selectedCamera);}
function deploymentRows(jobs){
 const states={queued:'En attente',running:'En cours',done:'Terminée',failed:'À vérifier',cancelled:'Annulée'};
 return jobs.map(j=>`<tr><td>${date(j.ts)}</td><td>${j.kind==='camera_add'?'Configuration caméra':'Installation · '+esc(({video:'Frigate',fichiers:'Samba',restic:'restic'})[j.component]||'composant')}</td><td><span class="badge ${j.status==='failed'?'warn':''}">${esc(states[j.status]||j.status)}</span></td><td>${esc(j.result.error||j.result.message||j.progress.message||'Préparation…')}</td></tr>`);
}
function componentState(c,service){
 if(c.available)return 'Disponible';
 if(!service)return 'À installer';
 if(service.state!=='running')return 'Arrêté';
 if(service.health==='unhealthy')return 'À vérifier';
 if(service.health==='starting')return 'Démarrage en cours';
 return 'En service';
}
async function renderComponents(){
 const generation=sessionGeneration;
 const [catalog,d]=await Promise.all([api('components'),api('overview')]);
 if(generation!==sessionGeneration||page!=='services')return;
 const busy=catalog.jobs.some(j=>['queued','running'].includes(j.status));
 $('#content').innerHTML=heading('Composez votre NAS.','Installez les composants et suivez leur démarrage depuis cette console.',button('components-refresh','Actualiser','activity'))+
 (!catalog.docker_ready?'<div class="notice neutral"><strong>Docker reste à préparer sur Linux.</strong> Les partages et la vidéo nécessitent Docker Engine et le plugin Compose accessibles au compte Nacre. Le moteur de sauvegarde peut être installé dès maintenant. L’installation des paquets système et les droits du service natif restent du ressort de l’administrateur de l’hôte.</div>':'')+
 `<div class="native-summary">${catalog.components.map(c=>{const service=d.services.find(s=>s.name===c.id);return `<section class="card cardpad"><span class="appicon">${icon(c.id==='video'?'camera':c.id==='restic'?'backup':'folder')}</span><h2>${esc(c.name)}</h2><p>${esc(c.description)}</p><p><span class="badge ${['Disponible','En service'].includes(componentState(c,service))?'':'dim'}">${componentState(c,service)}</span></p>${button('component-install',c.available?'Réinstaller le moteur':service?'Préparer et démarrer':'Installer et démarrer','download','primary',`data-component="${c.id}" ${!c.installable||busy?'disabled':''}`)}${service?`<div class="service-control">${['restart','stop'].map(action=>button('service',action==='restart'?'Redémarrer':'Arrêter',null,'small',`data-name="${c.id}" data-operation="${action}" ${busy?'disabled':''}`)).join('')}</div>`:''}</section>`;}).join('')}</div><section class="card"><div class="cardhead"><h2>Installations et caméras</h2><span class="muted">Le suivi continue après fermeture du navigateur</span></div>${catalog.jobs.length?table(['Date','Opération','État','Progression / résultat'],deploymentRows(catalog.jobs)):empty('Les prochaines installations apparaîtront ici.','server')}</section><p class="capacity-note">Une réinstallation utilise les versions prévues par Nacre. Les données existantes sont conservées. Le démarrage vidéo est distinct de la réception d’un flux caméra.</p>`;
}
function cameraState(camera){
 return ({receiving:'Flux reçu',no_frames:'Aucune image reçue',disabled:'En pause',unknown:'État inconnu',stale:'Mesure périmée'})[camera.status]||'État inconnu';
}
function cameraBadge(camera){return `<span class="badge ${camera.status==='receiving'?'':['no_frames','stale'].includes(camera.status)?'warn':'dim'}">${cameraState(camera)}</span>`;}
function cameraOverview(cameras,add){
 const counts=status=>cameras.filter(c=>c.status===status).length;
 return heading('Votre surveillance, d’un regard.','Choisissez une caméra pour son direct, ses enregistrements et son pilotage.',add+button('camera-overview-refresh','Actualiser','activity'))+
 `<section class="card cardpad"><div class="camera-counts">${['receiving','no_frames','disabled','unknown','stale'].map(status=>`<div><strong>${counts(status)}</strong><span>${cameraState({status})}</span></div>`).join('')}</div><p class="capacity-note">État relevé à l’ouverture ou à l’actualisation de cette page. Un flux reçu ne prouve pas que l’enregistrement fonctionne. Aucun direct n’est ouvert dans cette vue.</p></section><div class="camera-catalog">${cameras.map(c=>`<section class="card cardpad camera-card"><div class="row">${icon('camera')}${cameraBadge(c)}</div><h2>${esc(c.name)}</h2><p class="muted">${esc(c.id)}</p><dl><div><dt>Réception</dt><dd>${c.fps===null?'Non mesurée':esc(c.fps)+' images/s'}</dd></div><div><dt>Mesure Frigate</dt><dd>${c.observed_at?date(c.observed_at):'Indisponible'}</dd></div><div><dt>Conservation configurée</dt><dd>${esc(c.days)} jour(s)</dd></div></dl><p class="capacity-note">${c.status==='disabled'?'Caméra désactivée dans la configuration.':c.status==='stale'?'Les mesures de Frigate ont plus de 90 secondes. Le direct n’est plus confirmé.':c.status==='unknown'?'Frigate n’a pas fourni de mesure datée exploitable.':c.status==='no_frames'?'Frigate annonce un débit nul pour cette caméra.':'Frigate annonce la réception d’images.'}</p>${button('camera-open','Ouvrir '+esc(c.name),'arrow','primary',`data-camera="${esc(c.id)}"`)}</section>`).join('')}</div>`;
}
async function renderSurveillance(){
 clearInterval(cameraHealthTimer);cameraHealthTimer=null;
 const generation=sessionGeneration,request=++cameraRequest,detail=cameraDetail;
 playbackRequest++;searchRequest++;playbackData=null;playbackClip=null;
 const current=()=>generation===sessionGeneration&&page==='camera'&&request===cameraRequest;
 // Retirer le direct précédent dès le changement de caméra ou de vue.
 $('#content').innerHTML='<p role="status">Chargement des caméras…</p>';
 let cameras;
 try{cameras=await api('cameras');}catch(error){if(!current())return;throw error;}
 if(!current())return;
 cameraCatalog=cameras;
 const add=user.role==='admin'?button('camera-add','Ajouter une caméra','plus','primary'):'';
 if(!cameras.length){selectedCamera='';cameraDetail=false;$('#content').innerHTML=heading('Votre surveillance commence ici.','Ajoutez une caméra du réseau local à votre NAS.',add)+`<section class="card cardpad"><h2>Une première caméra, puis les suivantes.</h2><p>Démarrez Frigate dans Services, puis renseignez le compte local de votre caméra. Le profil Tapo propose ses deux flux ; le profil RTSP permet de saisir les chemins du constructeur.</p><button data-page="services">Préparer le service vidéo ${icon('arrow')}</button></section>`;return;}
 if(!detail||!cameras.some(c=>c.id===selectedCamera)){cameraDetail=false;$('#content').innerHTML=cameraOverview(cameras,add);return;}
 const id=selectedCamera,camera=cameras.find(c=>c.id===id),suffix=cameraQuery();
 const results=await Promise.allSettled([api('camera/info'+suffix),api('camera/timeline'+suffix+(playbackDay?'&day='+encodeURIComponent(playbackDay):'')),api('camera/settings'+suffix),api('camera/detection'+suffix)]);
 if(!current()||selectedCamera!==id)return;
 const info=results[0].status==='fulfilled'?results[0].value:{};
 // Une date devenue inconsultable ne doit pas bloquer les actualisations suivantes.
 if(results[1].status==='rejected'&&results[1].reason?.status===400)playbackDay='';
 playbackData=results[1].status==='fulfilled'&&Array.isArray(results[1].value?.intervals)?results[1].value:null;
 cameraSettings=results[2].status==='fulfilled'?results[2].value:camera;
 detectionData=detectionValid(results[3].status==='fulfilled'?results[3].value:null);
 const enabled=camera.online&&camera.enabled&&info.features?.includes('pt')&&user.role==='admin';
 $('#content').innerHTML=heading('Vos caméras, à portée de vue.','Direct local, pilotage manuel et relecture des enregistrements par jour.',button('camera-overview','Toutes les caméras','camera')+add)+
 `<section class="card camera-choice"><label for="camera-select">Caméra</label><select id="camera-select">${cameras.map(c=>`<option value="${esc(c.id)}" ${c.id===id?'selected':''}>${esc(c.name)} · ${cameraState(c)}</option>`).join('')}</select>${user.role==='admin'?button('camera-edit','Connexion',null,'small')+button('camera-settings','Réglages',null,'small'):''}${button('refresh-recordings','Actualiser','activity','small')}</section>`+
 (!camera.online?`<div class="notice neutral">${camera.status==='disabled'?'Cette caméra est en pause. Ses enregistrements restent consultables.':camera.status==='stale'?'Mesures vidéo périmées : le direct n’est plus confirmé. Vérifiez le service vidéo.':camera.status==='unknown'?'État inconnu : aucune mesure exploitable reçue de Frigate. Actualisez ou vérifiez le service vidéo.':'Frigate annonce un débit nul. Vérifiez la connexion de la caméra et son compte local.'}</div>`:'')+
 `<div class="camera-grid"><section class="card"><div class="cardhead"><h2>${esc(camera.name)}</h2><span id="camera-live-state">${cameraBadge(camera)}</span></div><div class="cameraimage" id="camera-live-panel">${camera.online?`<img src="/api/camera/live${suffix}" alt="Direct de ${esc(camera.name)}">`:empty('Aucune image disponible pour cette caméra.','camera')}</div><div class="camerafooter"><span>Aperçu local · jusqu’à 5 images/s</span><span>Conservation : ${esc(cameraSettings.days)} jour(s)</span></div></section><section class="card"><div class="cardhead"><h2>Pilotage</h2>${icon('camera')}</div><div class="ptz"><span id="camera-ptz-state" class="badge ${enabled?'':'dim'}">${enabled?'PTZ disponible':'PTZ indisponible'}</span><div class="ptz-pad">${['blank','up','blank','left','stop','right','blank','down','blank'].map(dir=>dir==='blank'?'<span class="blank"></span>':`<button data-action="ptz" data-direction="${dir}" aria-label="${{left:'Tourner à gauche',right:'Tourner à droite',up:'Monter',down:'Descendre',stop:'Arrêter la caméra'}[dir]}" ${enabled?'':'disabled'}>${icon(dir)}</button>`).join('')}</div><small>Chaque pression effectue un mouvement court, suivi d’un arrêt.</small>${info.presets?.length?`<div class="field"><label for="preset-select">Points de vue</label><select id="preset-select">${info.presets.map(p=>`<option value="${esc(p)}">${esc(p)}</option>`).join('')}</select><button data-action="preset" ${enabled?'':'disabled'}>Aller au point de vue</button></div>`:''}</div></section>${detectionCard(detectionData)}${playbackCard(playbackData)}${searchCard()}</div>`;
 if(camera.online)watchCamera(id,current);

}
function watchCamera(id,current){
 let busy=false,timer=null;
 const clear=()=>{clearInterval(timer);if(cameraHealthTimer===timer)cameraHealthTimer=null;};
 const stop=(camera)=>{
  if(!current()||!cameraDetail||selectedCamera!==id)return;
  clear();
  const panel=$('#camera-live-panel'),state=$('#camera-live-state');
  if(panel)panel.innerHTML=empty((camera.status==='stale'?'Mesures Frigate périmées. ':'')+'Le direct n’est plus confirmé. Utilisez Actualiser pour réessayer.','camera');
  if(state)state.innerHTML=cameraBadge(camera);
  const ptz=$('#camera-ptz-state'),select=$('#camera-select');
  if(ptz){ptz.textContent='Pilotage suspendu';ptz.className='badge dim';}
  if(select)for(const option of select.options){if(option.value===id)option.textContent=(cameraCatalog.find(c=>c.id===id)?.name||id)+' · '+cameraState(camera);}
  document.querySelectorAll('#content [data-action="ptz"],#content [data-action="preset"]').forEach(el=>el.disabled=true);
 };
 const check=async()=>{
  if(!current()||!cameraDetail||selectedCamera!==id){clear();return;}
  if(busy)return;busy=true;
  try{
   const values=await api('cameras');
   if(!current()||!cameraDetail||selectedCamera!==id)return;
   const camera=values.find(c=>c.id===id);
   if(!camera?.online)stop(camera||{status:'unknown'});
  }catch(error){if(error.name!=='AbortError')stop({status:'unknown'});}
  finally{busy=false;}
 };
 timer=setInterval(check,15000);cameraHealthTimer=timer;
 const img=$('#camera-live-panel img');
 if(img)img.addEventListener('error',()=>stop({status:'unknown'}),{once:true});
 return check;
}
function addCameraModal(existing=null){
 modal(existing?'Modifier la connexion':'Ajouter une caméra',`<p>Renseignez le <strong>compte caméra local</strong>, distinct du compte cloud du constructeur. L’enregistrement redémarre Frigate et interrompt brièvement toutes les caméras.</p>`+field('Nom affiché','name',existing?.name||'')+(existing?`<input type="hidden" name="id" value="${esc(existing.id)}"><p>Identifiant : <strong>${esc(existing.id)}</strong>. Renseignez à nouveau les accès de connexion ; les enregistrements et leur durée de conservation sont conservés.</p>`:field('Identifiant unique','id','','text','2 à 32 caractères : lettres minuscules, chiffres et underscores ; commencer par une lettre.'))+`<div class="field"><label for="camera-profile">Profil</label><select name="profile" id="camera-profile"><option value="tapo">Tapo · stream1 / stream2</option><option value="rtsp">RTSP · chemins personnalisés</option></select></div>`+field('Adresse IPv4 locale','host','','text','Exemple : 192.168.50.10')+field('Port RTSP','port','554','number')+field('Compte caméra','username')+field('Mot de passe caméra','password','','password')+`<div class="camera-custom-paths" hidden><div class="field"><label for="camera-path">Chemin principal</label><input id="camera-path" name="path" placeholder="/Streaming/Channels/101"></div><div class="field"><label for="camera-subpath">Chemin secondaire (optionnel)</label><input id="camera-subpath" name="subpath" placeholder="/Streaming/Channels/102"></div></div><div class="checks"><label><input type="checkbox" name="onvif" ${existing?.onvif?'checked':''}>Configurer ONVIF pour le PTZ, avec le même compte caméra</label></div>`+field('Port ONVIF','onvif_port','2020','number','Vérifiez le port du constructeur ; l’option reste désactivée par défaut.')+`<p class="capacity-note">${existing?'La durée de conservation existante est préservée.':'Enregistrement continu : 1 jour, modifiable après l’ajout.'} Le suivi automatique reste désactivé. Les identifiants ne sont pas affichés dans les listes ni dans le journal des tâches.</p>`,existing?'Enregistrer et redémarrer la vidéo':'Ajouter et redémarrer la vidéo',async f=>{
  const result=await api('cameras/add',{...Object.fromEntries(f),port:Number(f.get('port')),onvif_port:Number(f.get('onvif_port')),onvif:f.has('onvif'),confirm:true,replace:!!existing});
  selectedCamera=String(f.get('id'));await go('services');return result;
 });
}
document.addEventListener('change',e=>{
 if(e.target.id==='camera-select'){selectedCamera=e.target.value;cameraDetail=true;renderCamera().catch(error=>toast(error.message,true));}
 if(e.target.id==='camera-profile')$('.camera-custom-paths').hidden=e.target.value!=='rtsp';
});
document.addEventListener('click',async e=>{
 const el=e.target.closest('[data-action]');if(!el)return;
 try{
  if(el.dataset.action==='camera-open'){if(!cameraCatalog.some(c=>c.id===el.dataset.camera))return;selectedCamera=el.dataset.camera;cameraDetail=true;return await renderCamera();}
  if(['camera-overview','camera-overview-refresh'].includes(el.dataset.action)){cameraDetail=false;return await renderCamera();}
  if(el.dataset.action==='camera-add')return addCameraModal();
  if(el.dataset.action==='camera-edit')return addCameraModal(cameraCatalog.find(c=>c.id===selectedCamera));
  if(el.dataset.action==='components-refresh')return await renderComponents();
  if(el.dataset.action==='component-install')return confirmAction('Installer le composant','Nacre téléchargera les fichiers nécessaires. Samba ou Frigate sera démarré ; une relance peut interrompre les accès correspondants. Aucun dépôt de sauvegarde ne sera créé.','Installer',async()=>api('components/install',{component:el.dataset.component,confirm:true}));
 }catch(error){if(error.name!=='AbortError')toast(error.message,true);}
});
