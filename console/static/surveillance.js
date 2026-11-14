'use strict';
// Application Surveillance du bureau : les cartes existantes (direct, pilotage, relecture, recherche, détection)
// rangées en quatre vues. Mur en images fixes rafraîchies ; le direct n’est ouvert que pour la caméra agrandie.
const SURV_REFRESH=10000,SURV_SHOWN=120;
let survFocus=false,survTimer=null,survEvents=null,survCamera='',survLabel='',survPending=null,survRowsRequest=0;
// Période et tranche horaire demandées dans l’onglet Événements ; null = les sept derniers jours, toute la journée.
let survAsk=null;
// Suite des événements : combien en montrer, et une demande de suite en cours.
let survLimit=SURV_SHOWN,survLoading=false;

function survView(){return typeof deskViewOf==='function'?deskViewOf('cam'):'wall';}
function survGo(view){deskSetView('cam',view);return renderCamera();}
function survSelect(cameras){
 return `<section class="card camera-choice"><label for="camera-select">Caméra</label><select id="camera-select">${cameras.map(c=>`<option value="${esc(c.id)}" ${c.id===selectedCamera?'selected':''}>${esc(c.name)} · ${cameraState(c)}</option>`).join('')}</select>${button('surv-refresh','Actualiser','activity','small')}</section>`;
}
function survShot(camera,now){
 return camera.online?`<img class="sv-still" src="/api/camera/snapshot?camera=${encodeURIComponent(camera.id)}&t=${now}" data-camera="${esc(camera.id)}" alt="Dernière image de ${esc(camera.name)}">`:empty(camera.status==='disabled'?'Caméra en pause.':'Aucune image disponible.','camera');
}
function survTile(camera,now){
 return `<section class="card sv-tile"><button type="button" class="sv-shot cameraimage" data-action="surv-focus" data-camera="${esc(camera.id)}" aria-label="Agrandir ${esc(camera.name)} et ouvrir son direct">${survShot(camera,now)}</button><div class="sv-foot"><div><strong>${esc(camera.name)}</strong>${cameraBadge(camera)}</div>${button('surv-replay','Relecture',null,'small',`data-camera="${esc(camera.id)}"`)}</div></section>`;
}
function survWallHtml(cameras,add,now=Date.now()){
 const received=cameras.filter(c=>c.status==='receiving').length;
 return heading('Toutes vos caméras.','Images rafraîchies toutes les dix secondes. Cliquez sur une caméra pour l’agrandir et ouvrir son direct.',add+button('surv-refresh','Actualiser','activity'))+
  `<p class="sv-count"><span class="badge ${received===cameras.length?'':'warn'}">${received} sur ${cameras.length} reçue${received>1?'s':''}</span></p><div class="sv-wall">${cameras.map(c=>survTile(c,now)).join('')}</div>`+
  '<p class="capacity-note">Une image fixe par caméra : aucun direct n’est ouvert dans cette vue. Une image reçue ne prouve pas que l’enregistrement fonctionne.</p>';
}
function survTick(current){
 clearInterval(survTimer);
 survTimer=setInterval(()=>{
  if(!current()){clearInterval(survTimer);survTimer=null;return;}
  if(document.hidden)return;
  for(const image of document.querySelectorAll('#content img.sv-still'))image.src=`/api/camera/snapshot?camera=${encodeURIComponent(image.dataset.camera)}&t=${Date.now()}`;
 },SURV_REFRESH);
}
async function survWall(cameras,add,current){
 if(!survFocus){cameraDetail=false;$('#content').innerHTML=survWallHtml(cameras,add);return survTick(current);}
 const id=selectedCamera,camera=cameras.find(c=>c.id===id),suffix=cameraQuery();
 cameraDetail=true;
 const results=await Promise.allSettled([api('camera/info'+suffix),api('camera/settings'+suffix)]);
 if(!current()||selectedCamera!==id||!survFocus)return;
 const info=results[0].status==='fulfilled'?results[0].value:{};
 cameraSettings=results[1].status==='fulfilled'?results[1].value:camera;
 const enabled=camera.online&&camera.enabled&&info.features?.includes('pt')&&user.role==='admin',others=cameras.filter(c=>c.id!==id),now=Date.now();
 $('#content').innerHTML=heading(`${esc(camera.name)} en direct.`,'Seule cette caméra reçoit le direct ; les autres restent en images fixes.',button('surv-wall','Revenir au mur','camera')+add)+
  `<div class="camera-grid">${cameraLiveCards(camera,info,suffix,enabled)}</div>${others.length?`<div class="sv-wall sv-strip">${others.map(c=>survTile(c,now)).join('')}</div>`:''}`;
 if(camera.online)watchCamera(id,current);
 survTick(current);
}

// Événements : les soixante plus récents de chaque caméra sur la période, fusionnés du plus récent au plus ancien.
// Par défaut les sept derniers jours ; la période et la tranche horaire se choisissent comme dans la recherche d’une caméra.
function survForm(data){
 const today=data.today||searchToday(),to=survAsk?.to||data.to||today,from=survAsk?.from||data.from||searchShift(to,-6),hours=survAsk?.hours||null;
 return `<div class="pb-go sr-form"><label for="surv-from">Du</label><input id="surv-from" type="date" value="${esc(from)}" max="${esc(today)}"><label for="surv-to">au</label><input id="surv-to" type="date" value="${esc(to)}" max="${esc(today)}"><label for="surv-after">entre</label><input id="surv-after" type="time" value="${esc(hours?.from||'')}" aria-describedby="surv-hours"><label for="surv-before">et</label><input id="surv-before" type="time" value="${esc(hours?.to||'')}" aria-describedby="surv-hours">${button('surv-search','Rechercher',null,'primary small')}${survAsk?button('surv-reset','Sept derniers jours',null,'small'):''}</div>`+
  '<p class="capacity-note" id="surv-hours">Heures facultatives : de 22:00 à 06:00, seules les nuits de la période sont gardées.</p>';
}
// Jusqu’où la liste est complète. Tant qu’une caméra retenue a une suite, rien de plus ancien que son dernier événement
// chargé n’est sûr : d’autres, non chargés, viendraient s’y intercaler. La liste s’arrête donc là, et ne grandit que par la fin.
function survOldest(data,camera){let oldest=Infinity;for(const e of data.items)if(e.camera===camera&&e.start<oldest)oldest=e.start;return oldest;}
function survHorizon(data){
 let horizon=-Infinity;
 for(const c of data.cameras){
  if((survCamera&&c.id!==survCamera)||data.pages?.[c.id]?.next==null)continue;
  const oldest=survOldest(data,c.id);if(oldest!==Infinity&&oldest>horizon)horizon=oldest;
 }
 return horizon;
}
function survVisible(data){const horizon=survHorizon(data);return data.items.filter(e=>(!survCamera||e.camera===survCamera)&&(!survLabel||e.label===survLabel)&&e.start>=horizon);}
function survEventsHtml(data=survEvents){
 if(!data)return '';
 if(data.refused)return survForm(data)+`<div class="notice neutral">${esc(data.refused)}</div>`;
 const all=data.items,labels=[...new Set(all.map(e=>e.label))],shown=survVisible(data),pending=survHorizon(data)>-Infinity;
 const chip=(kind,value,text,count)=>`<button type="button" class="pb-chip" data-action="surv-filter" data-kind="${kind}" data-value="${esc(value)}" aria-pressed="${(kind==='camera'?survCamera:survLabel)===value}">${esc(text)}<b>${count}</b></button>`;
 let previous='';
 const list=shown.slice(0,survLimit).map(e=>{
  const head=e.day===previous?'':`<h4 class="sr-day">${esc(pbDay(e.day))}</h4>`;previous=e.day;
  const meta=[pbClock(e.start),e.ongoing?'en cours':pbDuration(e.end-e.start)].join(' · ');
  return head+`<button type="button" class="pb-event" data-action="surv-open" data-camera="${esc(e.camera)}" data-day="${esc(e.day)}" data-start="${e.start}" data-end="${e.end}"${e.recorded===false?' disabled':''}><img class="pb-thumb" src="/api/camera/event-thumbnail?camera=${encodeURIComponent(e.camera)}&id=${encodeURIComponent(e.id)}" alt="" loading="lazy" width="175" height="175"><strong>${esc(pbLabel(e.label)+(e.sub_label?' · '+e.sub_label:''))}</strong><span>${esc(e.name)} · ${esc(meta)}</span>${e.recorded===false?'<em>Vidéo non conservée</em>':''}</button>`;
 }).join('');
 const none=all.length?'Aucun événement pour ces filtres.':data.hours?'Aucun événement dans cette tranche horaire sur cette période.':survAsk?'Aucun événement sur cette période.':'Aucun événement sur les sept derniers jours.';
 return survForm(data)+
  (data.from?`<p class="pb-summary" id="surv-summary" role="status">${esc(searchPlural(data.total)+(data.more?' parmi les plus récents':'')+', '+searchPeriod(data))}</p>`:'')+
  (data.failed.length?`<div class="notice neutral">Événements indisponibles pour ${data.failed.map(esc).join(', ')}. Les autres caméras sont listées.</div>`:'')+
  `<div class="pb-filter" role="group" aria-label="Filtrer par caméra">${chip('camera','','Toutes les caméras',all.length)}${data.cameras.map(c=>chip('camera',c.id,c.name,all.filter(e=>e.camera===c.id).length)).join('')}</div>`+
  (labels.length>1?`<div class="pb-filter" role="group" aria-label="Filtrer par type">${chip('label','','Tous les types',all.length)}${labels.map(l=>chip('label',l,pbLabel(l),all.filter(e=>e.label===l).length)).join('')}</div>`:'')+
  (shown.length?`<div class="pb-events sv-events">${list}</div>`:empty(none,'camera'))+
  (data.stalled?`<div class="notice neutral" role="alert">La suite n’a pas pu être chargée : ${esc(data.stalled)}</div>`:'')+
  (shown.length&&(pending||shown.length>survLimit)?`<div class="row sv-more">${survLoading?'<span role="status">Recherche de la suite…</span>':button('surv-more','Afficher la suite','activity')}</div>`:'')+
  `<p class="capacity-note">${shown.length&&(pending||shown.length>survLimit)?'Du plus récent au plus ancien ; « Afficher la suite » remonte plus loin dans la période.':'Tous les événements de la période sont listés.'} Les pastilles comptent les événements déjà chargés. Les événements proviennent du suivi d’objets de Frigate ; ils ne sont ni exhaustifs ni une alarme.</p>`;
}
// Charger la suite : montrer d’abord ce qui est déjà là, puis demander la page suivante de la caméra qui borne la liste,
// jusqu’à avoir de quoi remplir, sans dépasser quelques demandes par clic.
async function survMore(){
 const data=survEvents,draw=()=>{const box=$('#surv-events');if(box&&survEvents===data)box.innerHTML=survEventsHtml();};
 if(!data||data.refused||survLoading)return;
 survLimit+=SURV_SHOWN;data.stalled='';survLoading=true;draw();
 try{
  for(let round=0;round<6&&survVisible(data).length<survLimit;round++){
   const horizon=survHorizon(data);if(horizon===-Infinity)break;
   const camera=data.cameras.find(c=>(!survCamera||c.id===survCamera)&&data.pages[c.id]?.next!=null&&survOldest(data,c.id)===horizon);
   if(!camera)break;
   const page=searchValid(await api('camera/search?camera='+encodeURIComponent(camera.id)+data.span+'&before='+encodeURIComponent(data.pages[camera.id].next)));
   if(survEvents!==data)return;
   if(!page)throw new Error('réponse inattendue du serveur.');
   const known=new Set(data.items.map(e=>e.camera+'|'+e.id));
   for(const event of page.events)if(!known.has(camera.id+'|'+event.id))data.items.push({...event,camera:camera.id,name:camera.name});
   data.pages[camera.id].next=page.next;
   data.items.sort((a,b)=>b.start-a.start);
  }
 }catch(error){if(survEvents===data)data.stalled=error.message;}
 finally{survLoading=false;draw();}
}
async function survEventsView(cameras,current){
 cameraDetail=false;survLimit=SURV_SHOWN;survLoading=false;
 $('#content').innerHTML=heading('Ce qui s’est passé.','Les événements de toutes vos caméras, du plus récent au plus ancien.',button('surv-refresh','Actualiser','activity'))+'<div id="surv-events"><p role="status">Recherche des événements…</p></div>';
 const span=survAsk?searchSpan(survAsk.from,survAsk.to,survAsk.hours):'';
 const results=await Promise.allSettled(cameras.map(c=>api('camera/search?camera='+encodeURIComponent(c.id)+span)));
 if(!current())return;
 const items=[],failed=[],known={cameras:cameras.map(c=>({id:c.id,name:c.name}))};
 // Une demande que le serveur refuse pour toutes les caméras (période hors limites) s’explique au lieu d’accuser les caméras.
 const refusal=results.every(r=>r.status==='rejected'&&r.reason?.status===400)?results[0]?.reason?.message:'';
 if(refusal){survEvents={...known,items,failed,refused:String(refusal)};const box=$('#surv-events');if(box)box.innerHTML=survEventsHtml();return;}
 let total=0,more=false,first=null;const pages={};
 results.forEach((result,index)=>{
  const camera=cameras[index],data=result.status==='fulfilled'?searchValid(result.value):null;
  if(!data)return failed.push(camera.name);
  first=first||data;total+=data.facets?data.facets.total:data.events.length;more=more||!!data.facets?.more;pages[camera.id]={next:data.next};
  for(const event of data.events)items.push({...event,camera:camera.id,name:camera.name});
 });
 items.sort((a,b)=>b.start-a.start);
 // La suite se demande sur la période exacte que le serveur a retenue, pour ne pas glisser d’un jour à minuit.
 survEvents={...known,items,failed,total,more,pages,span:first?searchSpan(first.from,first.to,first.hours||null):'',stalled:'',from:first?.from||'',to:first?.to||'',today:first?.today||'',hours:first?.hours||null};
 if(!cameras.some(c=>c.id===survCamera))survCamera='';
 if(!items.some(e=>e.label===survLabel))survLabel='';
 const box=$('#surv-events');if(box)box.innerHTML=survEventsHtml();
}

// Frise commune : une ligne par caméra pour le jour relu ; un clic lit cette caméra à cette heure.
function survRow(camera,data){
 if(!data||!Array.isArray(data.intervals))return `<div class="sv-row"><span>${esc(camera.name)}</span><p class="muted">Enregistrements indisponibles.</p></div>`;
 const rect=(cls,a,b,h)=>{const x=pbX(data,a),w=Math.max(pbX(data,b)-x,2);return `<rect class="${cls}" x="${x.toFixed(1)}" y="0" width="${w.toFixed(1)}" height="${h}"/>`;};
 return `<div class="sv-row ${camera.id===selectedCamera?'sel':''}"><span>${esc(camera.name)}</span><svg class="pb-track sv-track" data-action="surv-seek" data-camera="${esc(camera.id)}" data-day="${esc(data.day)}" data-start="${data.start}" data-end="${data.end}" viewBox="0 0 ${PB_WIDTH} 20" preserveAspectRatio="none" role="img" aria-label="${esc(camera.name)} : ${pbDuration(data.recorded)} enregistrées le ${esc(pbDay(data.day))}. Cliquer pour lire à cet instant."><rect class="pb-none" x="0" y="0" width="${PB_WIDTH}" height="20"/>${data.intervals.map(([a,b])=>rect('pb-rec',a,b,20)).join('')}${(Array.isArray(data.events)?data.events:[]).map(e=>rect('pb-evt',e.start,e.end,7)).join('')}</svg></div>`;
}
async function survRows(cameras,day,current){
 const box=$('#surv-rows');if(!box||!day)return;
 const request=++survRowsRequest;
 box.setAttribute?.('aria-busy','true');
 const results=await Promise.allSettled(cameras.map(c=>api('camera/timeline?camera='+encodeURIComponent(c.id)+'&day='+encodeURIComponent(day))));
 if(!current()||request!==survRowsRequest||survView()!=='replay')return;
 const target=$('#surv-rows');if(!target)return;
 target.removeAttribute?.('aria-busy');
 target.innerHTML=`<h3>${esc(pbDay(day))} · toutes les caméras</h3>${cameras.map((c,i)=>survRow(c,results[i].status==='fulfilled'?results[i].value:null)).join('')}<p class="capacity-note">Une ligne par caméra. Cliquez sur une ligne pour lire cette caméra à cette heure ; une seule caméra est lue à la fois.</p>`;
}
async function survReplay(cameras,current){
 const id=selectedCamera,pending=survPending;survPending=null;
 cameraDetail=true;
 const day=pending?.day||playbackDay;
 let data=null;
 try{data=await api('camera/timeline'+cameraQuery()+(day?'&day='+encodeURIComponent(day):''));}
 catch(error){if(error.name==='AbortError'||error.status===401)throw error;if(error.status===400)playbackDay='';}
 if(!current()||selectedCamera!==id)return;
 playbackData=data&&Array.isArray(data.intervals)?data:null;if(playbackData)playbackDay=playbackData.day;
 $('#content').innerHTML=heading('Revoir un moment.','Choisissez une caméra et un jour, puis cliquez sur la frise.')+survSelect(cameras)+
  `<div class="camera-grid">${playbackCard(playbackData)}${cameras.length>1?'<section class="card wide cardpad" id="surv-rows"><p role="status">Chargement des autres caméras…</p></section>':''}${searchCard()}${keptCard()}</div>`;
 keptLoad().catch(()=>{});
 if(pending&&playbackData?.day===pending.day){if(pending.end===undefined)playbackPlay(pending.start);else await playbackOpen(pending.day,pending.start,pending.end);}
 if(cameras.length>1&&playbackData)survRows(cameras,playbackData.day,current).catch(error=>{if(error.name!=='AbortError')toast(error.message,true);});
}
async function survSettings(cameras,add,current){
 const id=selectedCamera,camera=cameras.find(c=>c.id===id),suffix=cameraQuery();
 cameraDetail=true;
 const results=await Promise.allSettled([api('camera/settings'+suffix),api('camera/detection'+suffix),api('cameras/storage')]);
 if(!current()||selectedCamera!==id)return;
 cameraSettings=results[0].status==='fulfilled'?results[0].value:camera;
 detectionData=detectionValid(results[1].status==='fulfilled'?results[1].value:null);
 const storage=results[2].status==='fulfilled'?results[2].value:null;
 const admin=user.role==='admin';
 $('#content').innerHTML=heading('Régler chaque caméra.','Détection, conservation et connexion de la caméra choisie.',add)+survSelect(cameras)+
  `<div class="camera-grid">${detectionCard(detectionData)}<section class="card wide cardpad"><h2>Enregistrement et connexion</h2><p>${cameraBadge(camera)} Conservation continue : <strong>${esc(cameraSettings.days)} jour(s)</strong>.</p>${admin?`<div class="quickactions">${button('camera-settings','Modifier la conservation',null,'small')}${button('camera-edit','Modifier la connexion',null,'small')}</div><p class="capacity-note">Modifier la connexion redémarre le service vidéo et interrompt brièvement toutes les caméras. Le compte de la caméra n’est jamais affiché.</p>`:'<p class="capacity-note">Les réglages sont réservés aux administrateurs.</p>'}</section>${keptStorageCard(storage)}</div>`;
}
async function renderSurveillanceApp(){
 clearInterval(cameraHealthTimer);cameraHealthTimer=null;clearInterval(survTimer);survTimer=null;
 const generation=sessionGeneration,request=++cameraRequest,view=survView();
 playbackRequest++;searchRequest++;survRowsRequest++;playbackData=null;playbackClip=null;
 const current=()=>generation===sessionGeneration&&page==='camera'&&request===cameraRequest&&survView()===view;
 $('#content').innerHTML='<p role="status">Chargement des caméras…</p>';
 let cameras;
 try{cameras=await api('cameras');}catch(error){if(!current())return;throw error;}
 if(!current())return;
 cameraCatalog=cameras;
 const add=user.role==='admin'?button('camera-add','Ajouter une caméra','plus','primary'):'';
 if(!cameras.length){selectedCamera='';cameraDetail=false;survFocus=false;$('#content').innerHTML=cameraEmpty(add);return;}
 if(!cameras.some(c=>c.id===selectedCamera)){selectedCamera=cameras[0].id;survFocus=false;}
 if(view==='events')return survEventsView(cameras,current);
 if(view==='replay')return survReplay(cameras,current);
 if(view==='settings')return survSettings(cameras,add,current);
 return survWall(cameras,add,current);
}
// Ouvre une caméra agrandie sur le mur : utilisé par la recherche globale.
function survOpenCamera(id){selectedCamera=id;survFocus=true;deskSetView('cam','wall');}

document.addEventListener('click',async e=>{
 const el=e.target.closest?.('[data-action^="surv-"]');if(!el||el.disabled||page!=='camera'||!user)return;
 const known=id=>cameraCatalog.some(c=>c.id===id);
 try{
  switch(el.dataset.action){
   case 'surv-refresh':return await renderCamera();
   case 'surv-wall':survFocus=false;return await renderCamera();
   case 'surv-focus':if(!known(el.dataset.camera))return;survFocus=!(survFocus&&selectedCamera===el.dataset.camera);selectedCamera=el.dataset.camera;return await renderCamera();
   case 'surv-replay':if(!known(el.dataset.camera))return;selectedCamera=el.dataset.camera;return await survGo('replay');
   case 'surv-filter':if(el.dataset.kind==='camera')survCamera=el.dataset.value||'';else survLabel=el.dataset.value||'';{const box=$('#surv-events');if(box)box.innerHTML=survEventsHtml();}return;
   case 'surv-search':{
    const from=$('#surv-from')?.value,to=$('#surv-to')?.value;
    if(!from||!to)return toast('Indiquez le début et la fin de la période.',true);
    if(from>to)return toast('Le début de la période suit sa fin.',true);
    const hours=searchHours($('#surv-after')?.value||'',$('#surv-before')?.value||'');
    if(hours===false)return;
    survAsk={from,to,hours};return await renderCamera();
   }
   case 'surv-reset':survAsk=null;return await renderCamera();
   case 'surv-more':return await survMore();
   case 'surv-open':if(!known(el.dataset.camera))return;selectedCamera=el.dataset.camera;survPending={day:el.dataset.day,start:Number(el.dataset.start),end:Number(el.dataset.end)};return await survGo('replay');
   case 'surv-seek':{
    if(!known(el.dataset.camera))return;
    const box=el.getBoundingClientRect(),from=Number(el.dataset.start),to=Number(el.dataset.end);
    if(!(box.width>0)||!Number.isFinite(from)||!Number.isFinite(to))return;
    const instant=from+Math.max(0,Math.min(1,(e.clientX-box.left)/box.width))*(to-from);
    if(el.dataset.camera===selectedCamera&&playbackData?.day===el.dataset.day)return playbackPlay(instant);
    selectedCamera=el.dataset.camera;survPending={day:el.dataset.day,start:instant};return await renderCamera();
   }
  }
 }catch(error){if(error.name!=='AbortError')toast(error.message,true);}
});
// Changer de jour dans la carte de relecture met la frise commune sur le même jour.
document.addEventListener('change',e=>{
 if(e.target?.id!=='playback-day'||page!=='camera'||survView()!=='replay'||typeof deskMode!=='function'||!deskMode())return;
 const generation=sessionGeneration,request=cameraRequest;
 survRows(cameraCatalog,e.target.value,()=>generation===sessionGeneration&&page==='camera'&&request===cameraRequest).catch(()=>{});
});
