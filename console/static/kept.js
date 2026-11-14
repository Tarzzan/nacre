'use strict';
// Passages conservés : une copie à part d’un extrait, gardée tant qu’on ne la retire pas.
// Stockage vidéo : espace libre rapporté au débit d’enregistrement mesuré par le service vidéo.
const KEPT_RECHECK=3000,KEPT_RECHECKS=6;
let keptData=null,keptRequest=0,keptTimer=null;

function keptValid(d){
 const text=v=>typeof v==='string'&&v.length<=80,size=v=>v===null||(Number.isFinite(v)&&v>=0);
 if(!d||!text(d.camera)||!d.camera||!Array.isArray(d.items)||!Number.isFinite(d.size))return null;
 if(!d.items.every(e=>e&&text(e.id)&&e.id&&text(e.name)&&/^\d{4}-\d{2}-\d{2}$/.test(e.day)&&Number.isFinite(e.start)&&(e.end===null||(Number.isFinite(e.end)&&e.end>e.start))&&size(e.size)&&typeof e.pending==='boolean'))return null;
 return d;
}
function keptPlural(n){return `${n} passage${n>1?'s':''} conservé${n>1?'s':''}`;}
function keptWhen(e){return `${pbDay(e.day)}, ${pbClock(e.start)}${e.end===null?'':' → '+pbClock(e.end)}`;}
function keptSource(camera,id){return `/api/camera/kept-video?camera=${encodeURIComponent(camera)}&id=${encodeURIComponent(id)}`;}
// Bouton placé sous le lecteur de la relecture ; réservé aux administrateurs.
function keptAction(){return user?.role==='admin'?button('kept-keep','Conserver cet extrait','check','small'):'';}
function keptList(d){
 if(!d)return '<p role="status">Recherche des passages conservés…</p>';
 if(d.failed)return `<div class="notice neutral">${esc(d.failed)}</div>`;
 const admin=user?.role==='admin';
 if(!d.items.length)return empty(admin?'Aucun passage conservé. Lisez un extrait dans la relecture, puis « Conserver cet extrait ».':'Aucun passage conservé pour cette caméra.','camera');
 const rows=d.items.map(e=>{
  const source=keptSource(d.camera,e.id);
  const actions=e.pending?'<span class="badge dim" role="status">Copie en cours</span>':
   `<div class="row">${button('kept-play','Lire',null,'small',`data-id="${esc(e.id)}"`)}<a class="pb-download" href="${source}&download=1" download>${icon('download')}<span>Télécharger</span></a>${admin?button('kept-remove','Retirer',null,'small',`data-id="${esc(e.id)}"`):''}</div>`;
  return `<tr><td><strong>${esc(e.name||'Extrait')}</strong><br><small class="muted">${esc(keptWhen(e))}</small></td><td>${e.end===null?'—':pbDuration(e.end-e.start)}</td><td>${e.size===null?'—':sizes(e.size)}</td><td>${actions}</td></tr>`;
 });
 return `<p class="pb-summary" id="kept-summary" role="status">${esc(keptPlural(d.items.length))} · ${sizes(d.size)}</p><div id="kept-player"></div>`+
  table(['Passage','Durée','Taille',''],rows)+
  (d.more?`<p class="capacity-note">Seuls les ${d.items.length} passages les plus récents sont listés.</p>`:'');
}
function keptCard(){
 if(keptData&&keptData.camera!==selectedCamera)keptData=null;
 return `<section class="card wide playback" id="kept"><div class="cardhead"><h2>Passages conservés</h2>${button('kept-refresh','Actualiser',null,'small')}</div><div class="pb-body"><div id="kept-list">${keptList(keptData)}</div>`+
  '<p class="capacity-note">Un passage conservé est une copie à part : ni la durée de conservation ni un volume plein ne l’effacent. Il occupe de la place sur le volume vidéo tant qu’il n’est pas retiré.</p></div></section>';
}
// Lecture de la liste ; tant qu’une copie est en cours, quelques relectures espacées, sans jamais boucler indéfiniment.
async function keptLoad(round=0){
 clearTimeout(keptTimer);keptTimer=null;
 const generation=sessionGeneration,request=++keptRequest,camera=selectedCamera;
 const current=()=>generation===sessionGeneration&&page==='camera'&&selectedCamera===camera&&request===keptRequest;
 let data;
 try{data=keptValid(await api('camera/kept'+cameraQuery()));if(!data)throw new Error('Réponse illisible du serveur. Utilisez Actualiser.');}
 catch(error){if(error.name==='AbortError'||error.status===401)throw error;data={camera,items:[],size:0,failed:error.message};}
 if(!current())return;
 const playing=$('#kept-player video');
 keptData=data;
 // Une lecture en cours n’est pas interrompue par une relecture de la liste.
 const box=$('#kept-list');if(box&&!(playing&&round))box.innerHTML=keptList(data);
 if(!data.failed&&round<KEPT_RECHECKS&&data.items.some(e=>e.pending))keptTimer=setTimeout(()=>{if(current())keptLoad(round+1).catch(()=>{});},KEPT_RECHECK);
}
// Demande de conservation de l’extrait en cours de lecture.
function keptAsk(){
 const data=playbackData,clip=playbackClip;
 if(!data||!clip)return toast('Lisez d’abord un extrait dans la relecture.',true);
 const max=keptData?.name_max||60;
 modal('Conserver cet extrait',
  `<p><strong>${esc(pbDay(data.day))}, ${pbClock(clip.start)} → ${pbClock(clip.end)}</strong> · ${pbDuration(clip.end-clip.start)}</p>`+
  `<div class="field"><label for="kept-name">Nom (facultatif)</label><input id="kept-name" name="name" type="text" maxlength="${max}" autocomplete="off"><small>Pour le retrouver : « livraison », « portail resté ouvert »…</small></div>`+
  '<p class="capacity-note">Une copie de cet extrait est gardée à part. Elle n’est plus effacée automatiquement et occupe de la place tant que vous ne la retirez pas.</p>',
  'Conserver',async form=>{
   await api('camera/keep',{camera:data.camera,start:clip.start,end:clip.end,name:String(form.get('name')||'')});
   // La page est redessinée après une fenêtre : la relecture reprend au même extrait.
   if(typeof survPending!=='undefined'&&typeof deskMode==='function'&&deskMode())survPending={day:data.day,start:clip.start};
   return {message:'Extrait conservé. La copie se termine en arrière-plan.'};
  });
}
function keptPlay(id){
 const d=keptData,e=d?.items.find(x=>x.id===id),panel=$('#kept-player');if(!e||e.pending||!panel)return;
 panel.innerHTML=`<p class="pb-status" role="status">Lecture du passage conservé : ${esc(keptWhen(e))}.</p><video class="recordvideo" id="kept-video" controls autoplay playsinline src="${keptSource(d.camera,e.id)}"></video>`;
 panel.scrollIntoView?.({block:'nearest'});
}
function keptRemove(id){
 const d=keptData,e=d?.items.find(x=>x.id===id);if(!e||e.pending)return;
 confirmAction('Retirer ce passage conservé ?',`La copie du ${keptWhen(e)} sera supprimée définitivement. Si l’enregistrement d’origine a déjà été effacé par la durée de conservation, il n’en restera rien.`,'Retirer',
  async()=>{await api('camera/unkeep',{camera:d.camera,id:e.id,confirm:true});return {message:'Passage retiré.'};});
}
document.addEventListener('click',async e=>{
 const el=e.target.closest?.('[data-action^="kept-"]');if(!el||el.disabled||page!=='camera'||!user)return;
 try{
  switch(el.dataset.action){
   case 'kept-keep':return keptAsk();
   case 'kept-refresh':{const box=$('#kept-list');if(box)box.innerHTML=keptList(null);return await keptLoad();}
   case 'kept-play':return keptPlay(el.dataset.id);
   case 'kept-remove':return keptRemove(el.dataset.id);
  }
 }catch(error){if(error.name!=='AbortError')toast(error.message,true);}
});
document.addEventListener('error',e=>{
 if(e.target.id==='kept-video'){const panel=$('#kept-player');if(panel)panel.innerHTML='<p class="pb-status" role="status">Passage indisponible : le service vidéo n’a pas fourni cette copie. Utilisez Actualiser, puis réessayez.</p>';}
},true);

// Stockage vidéo : autonomie et place prise, pour toutes les caméras.
function keptSpan(hours){
 if(hours<48)return `${Math.max(1,Math.round(hours))} heure${Math.round(hours)>1?'s':''}`;
 const days=Math.round(hours/24);return `${days.toLocaleString('fr-FR')} jours`;
}
function keptDays(n){return `${n.toLocaleString('fr-FR',{maximumFractionDigits:1})} jour${n>=2?'s':''}`;}
function keptStorageValid(d){
 const n=v=>Number.isFinite(v)&&v>=0,opt=v=>v===null||n(v);
 if(!d||d.available!==true)return null;
 if(!n(d.total)||!n(d.free)||!n(d.recorded)||!opt(d.rate)||!opt(d.hours)||!opt(d.needed)||!opt(d.reach_days)||!d.kept||!n(d.kept.count)||!n(d.kept.size))return null;
 return ['full','short','ample','unknown'].includes(d.state)?d:null;
}
function keptStorageCard(raw){
 const d=keptStorageValid(raw),head='<section class="card wide cardpad" id="video-storage"><h2>Stockage vidéo</h2>';
 if(!d)return head+'<p class="muted">Mesures indisponibles : le service vidéo ne fournit pas l’état de son volume. Utilisez Actualiser.</p></section>';
 const used=Math.min(100,Math.round((d.total-d.free)/d.total*100));
 const verdict={
  full:['alert','Volume plein','Il reste moins d’une heure d’enregistrement. Le service vidéo efface les enregistrements les plus anciens pour continuer ; les passages conservés ne sont pas touchés.'],
  short:['warn','Conservation hors de portée',`La durée de conservation réglée demande plus de place que le volume n’en offre. Au débit actuel, les enregistrements remontent à ${d.reach_days===null?'moins loin que prévu':'environ '+keptDays(d.reach_days)} ; au-delà, les plus anciens sont effacés pour continuer.`],
  ample:['','Espace suffisant','L’espace libre couvre la durée de conservation réglée.'],
  unknown:['dim','Débit non mesuré','Le service vidéo n’a pas encore mesuré le débit d’enregistrement : l’autonomie ne peut pas être estimée.']}[d.state];
 return head+`<p><span class="badge ${verdict[0]}">${verdict[1]}</span> ${esc(verdict[2])}</p>`+
  `<dl class="vs-facts"><div><dt>Autonomie</dt><dd>${d.hours===null?'—':'environ '+keptSpan(d.hours)}</dd></div><div><dt>Espace libre</dt><dd>${sizes(d.free)} sur ${sizes(d.total)}</dd></div><div><dt>Débit d’enregistrement</dt><dd>${d.rate===null?'—':sizes(d.rate*24)+' par jour'}</dd></div><div><dt>Enregistrements</dt><dd>${sizes(d.recorded)}</dd></div><div><dt>Passages conservés</dt><dd>${d.kept.count?d.kept.count.toLocaleString('fr-FR')+' · '+sizes(d.kept.size):'aucun'}</dd></div></dl>`+
  `<progress class="vs-bar" max="100" value="${used}" aria-label="Volume vidéo occupé à ${used} %"></progress>`+
  '<p class="capacity-note">L’autonomie est le temps d’enregistrement que l’espace libre représente au débit actuel, toutes caméras confondues. C’est une estimation : le volume peut aussi recevoir d’autres fichiers, et le débit varie avec l’activité. Quand le volume est plein, l’enregistrement continue en effaçant les plus anciens.</p></section>';
}
