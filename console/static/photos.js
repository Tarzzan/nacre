'use strict';
// Photos : les images de tous les espaces ouverts à la personne, réunies par date. Rien n’est copié ni transformé : la
// vignette est celle que l’appareil a glissée dans le fichier, sinon l’image elle-même quand elle est légère.
const PH_MONTHS=['Janvier','Février','Mars','Avril','Mai','Juin','Juillet','Août','Septembre','Octobre','Novembre','Décembre'];
const PH_FULL=3*1024*1024,PH_BATCH=200;
let phData=null,phItems=[],phArea='',phNext=null,phTimer=null,phShown=-1,phSending=null,phMore=false;
function phValid(d){return d&&Array.isArray(d.items)&&Array.isArray(d.areas)&&d.scan&&typeof d.scan==='object'&&d.items.every(i=>i&&typeof i.area==='string'&&typeof i.path==='string'&&typeof i.name==='string'&&typeof i.taken==='string')?d:null;}
function phCount(n){const count=Number(n)||0;return `${count.toLocaleString('fr-FR')} photo${count>1?'s':''}`;}
function phMonth(key){const [year,month]=String(key).split('-');return `${PH_MONTHS[Number(month)-1]||month} ${year}`;}
function phWhen(taken){const m=/^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d)/.exec(String(taken));return m?`${Number(m[3])} ${(PH_MONTHS[Number(m[2])-1]||m[2]).toLowerCase()} ${m[1]}, ${m[4]} h ${m[5]}`:'';}
function phFile(item,inline){return `/api/download?area=${encodeURIComponent(item.area)}&path=${encodeURIComponent(item.path)}${inline?'&inline=1':''}`;}
function phSmall(item){return item.thumb?`/api/photos/thumb?area=${encodeURIComponent(item.area)}&path=${encodeURIComponent(item.path)}&v=${encodeURIComponent(item.v||'')}`:Number(item.size)<=PH_FULL?phFile(item,true):'';}
function phTile(item,index){
 // Une vignette d’appareil n’est pas redressée par le navigateur : on la tourne ici. L’image entière, elle, l’est d’office.
 const src=phSmall(item),turn=item.thumb&&[3,6,8].includes(item.orient)?` class="ph-o${item.orient}"`:'';
 return `<button type="button" class="ph-tile" data-action="ph-open" data-index="${index}" title="${esc(item.name)}">${src?`<img${turn} src="${esc(src)}" alt="${esc(item.name)}" loading="lazy" decoding="async">`:`<span class="ph-none">${esc(item.name)}</span>`}</button>`;
}
function phGrid(){
 const counts=new Map((Array.isArray(phData?.months)?phData.months:[]).map(m=>[m[0],m[1]]));let html='',month='';
 phItems.forEach((item,index)=>{const key=item.taken.slice(0,7);if(key!==month){html+=(month?'</div></section>':'')+`<section class="ph-month"><h2>${esc(phMonth(key))}${counts.has(key)?` <small>${phCount(counts.get(key))}</small>`:''}</h2><div class="ph-grid">`;month=key;}html+=phTile(item,index);});
 return html+(month?'</div></section>':'')+(phNext?`<div class="ph-more">${button('ph-more','Afficher la suite',null,'')}</div>`:'');
}
function phScan(scan){
 if(scan.running)return `<p class="ph-scan" role="status">Lecture de vos espaces en cours${scan.kept?` — ${phCount(scan.kept)} déjà vue${scan.kept>1?'s':''}`:''}. Les nouvelles photos apparaissent d’elles-mêmes.</p>`;
 if(scan.partial)return '<p class="ph-scan">Lecture arrêtée avant la fin : trop de fichiers pour un seul passage. Les photos déjà lues sont montrées.</p>';
 if(scan.error)return '<p class="ph-scan">La dernière lecture des espaces n’a pas abouti. Utilisez Actualiser.</p>';
 return scan.finished?`<p class="ph-scan">Espaces relus le ${esc(date(scan.finished))}.</p>`:'';
}
function phDraw(){
 const d=phData,total=Number(d.total)||0,add=!!d.personal,several=d.areas.length>1;
 const filter=several?`<label class="ph-filter"><span>Espace</span><select id="ph-area"><option value="">Tous mes espaces</option>${d.areas.map(a=>`<option value="${esc(a.id)}" ${a.id===phArea?'selected':''}>${esc(a.name)}</option>`).join('')}</select></label>`:'';
 const none=d.scan.running?'Lecture de vos espaces en cours : les photos vont apparaître.':`Aucune photo pour l’instant. Déposez des images dans un de vos espaces${add?', ou ajoutez-en depuis cet appareil avec « Ajouter des photos »':''}.`;
 $('#content').innerHTML=heading('Vos photos, par date.',total?`${phCount(total)} dans ${phArea?'cet espace':several?'vos espaces':'votre espace'}, sans rien copier ni déplacer.`:'Les images de vos espaces, réunies et rangées par date.',
  (add?button('ph-add','Ajouter des photos','upload','primary small'):'')+button('ph-refresh','Actualiser','activity','small'))+
  `<input type="file" id="ph-input" accept="image/*,video/*" multiple hidden><div class="ph" id="ph"><div class="ph-bar">${filter}${phScan(d.scan)}</div><div id="ph-body">${phItems.length?phGrid():`<div class="notice neutral">${none}</div>`}</div></div>`;
}
// Tant qu’un parcours tourne, la page se relit seule ; jamais pendant qu’une photo est ouverte ou qu’un envoi est en cours.
function phWatch(){
 clearTimeout(phTimer);
 if(phData?.scan?.running)phTimer=setTimeout(()=>{if(page==='photos'&&!$('#modal')?.open&&!phSending)renderPhotos().catch(()=>{});else phWatch();},2500);
}
async function renderPhotos(){
 const generation=sessionGeneration,current=()=>generation===sessionGeneration&&page==='photos';
 const data=phValid(await api('photos'+(phArea?'?area='+encodeURIComponent(phArea):'')));if(!current())return;
 if(!data){$('#content').innerHTML=heading('Vos photos, par date.','')+'<div class="notice neutral">Réponse illisible du serveur. Utilisez Actualiser.</div>'+button('ph-refresh','Actualiser','activity','small');return;}
 if(phArea&&!data.areas.some(a=>a.id===phArea)){phArea='';return renderPhotos();}
 phData=data;phItems=data.items;phNext=data.next||null;phDraw();phWatch();
}
async function phLoadMore(){
 if(!phNext||phMore)return false;phMore=true;
 try{
  const data=phValid(await api('photos?before='+encodeURIComponent(phNext)+(phArea?'&area='+encodeURIComponent(phArea):'')));
  if(!data||page!=='photos')return false;
  phItems=phItems.concat(data.items);phNext=data.next||null;const body=$('#ph-body');if(body)body.innerHTML=phGrid();return data.items.length>0;
 }finally{phMore=false;}
}
// Dimensions telles qu’on voit la photo : une image rangée couchée par l’appareil se lit debout.
function phSize(item){const w=Number(item.width),h=Number(item.height);if(!w||!h)return '';const turned=[5,6,7,8].includes(item.orient);return ` · ${turned?h:w} × ${turned?w:h}`;}
function phAreaName(id){return phData?.areas?.find(a=>a.id===id)?.name||'Espace';}
function phOpen(index){
 const item=phItems[index];if(!item)return;phShown=index;
 const folder=item.path.split('/').slice(0,-1),last=index>=phItems.length-1&&!phNext,m=$('#modal');
 m.innerHTML=`<div class="ph-view"><div class="modalhead"><h2>${esc(item.name)}</h2><button type="button" class="iconbtn" data-action="close-modal" aria-label="Fermer">${icon('close')}</button></div>`+
  `<div class="ph-stage"><button type="button" class="ph-nav" data-action="ph-prev" aria-label="Photo plus récente" ${index>0?'':'disabled'}>${icon('left')}</button><img src="${esc(phFile(item,true))}" alt="${esc(item.name)}"><button type="button" class="ph-nav" data-action="ph-next" aria-label="Photo plus ancienne" ${last?'disabled':''}>${icon('right')}</button></div>`+
  `<p class="ph-meta">${esc(phWhen(item.taken))}${item.dated?'':' (date du fichier)'} · ${esc([phAreaName(item.area),...folder].join(' › '))} · ${sizes(item.size)}${phSize(item)}${item.model?' · '+esc(item.model):''}</p>`+
  `<div class="modalfoot">${button('ph-reveal','Voir dans Fichiers',null,'')}${button('ph-download','Télécharger','download','')}</div></div>`;
 if(!m.open)m.showModal();
}
async function phStep(by){
 if(phShown<0)return;
 let target=phShown+by;
 if(target>=phItems.length&&phNext&&!(await phLoadMore()))return;
 if(target<0||target>=phItems.length)return;
 phOpen(target);
}
function phReveal(item){
 const parts=item.path.split('/'),name=parts.pop(),folder=parts.join('/');
 $('#modal').close();
 if(typeof deskReveal==='function')return deskReveal(item.area,folder,name);
 area=item.area;currentPath=folder;return go('files');
}
// Envoi depuis l’appareil : le serveur range chaque photo par mois dans l’espace personnel et écarte celles déjà là.
function phPanel(){
 let panel=$('#transfer-panel');const s=phSending;
 if(!s){panel?.remove?.();return;}
 if(!panel){panel=document.createElement('div');panel.id='transfer-panel';document.body.append(panel);}
 panel.innerHTML=`<strong>Envoi des photos</strong><progress max="1" value="${s.total?Math.min(1,(s.done+s.part)/s.total):0}"></progress><span>${s.done} / ${s.total}${s.present?` — ${s.present} déjà là`:''}${s.name?' — '+esc(s.name):''}</span>${button('ph-cancel','Arrêter',null,'small')}`;
}
function phPut(state,space,folder,name,file){
 return new Promise((resolve,reject)=>{
  const xhr=new XMLHttpRequest();state.xhr=xhr;activeUpload=xhr;
  xhr.open('POST','/api/upload?area='+encodeURIComponent(space)+'&path='+encodeURIComponent(folder)+'&name='+encodeURIComponent(name));
  xhr.setRequestHeader('X-CSRF-Token',user.csrf);xhr.setRequestHeader('Content-Type','application/octet-stream');
  xhr.upload.onprogress=e=>{if(e.lengthComputable&&e.total){state.part=e.loaded/e.total;phPanel();}};
  const end=()=>{state.xhr=null;state.part=0;activeUpload=null;};
  xhr.onload=()=>{end();let result={};try{result=JSON.parse(xhr.responseText);}catch{}if(xhr.status>=200&&xhr.status<300)resolve(result);else{const failure=new Error(result.error||'Envoi non abouti.');failure.status=xhr.status;reject(failure);}};
  xhr.onerror=()=>{end();reject(new Error('Connexion interrompue.'));};xhr.onabort=()=>{end();reject(new Error('Envoi arrêté.'));};
  xhr.send(file);
 });
}
function phSummary(s){
 // Rien de neuf dans la pellicule : on le dit simplement, sans « 0 photo ajoutée ».
 if(!s.sent&&s.present&&!s.refused&&!s.failed&&!s.cancel)return `Rien de nouveau : ${phCount(s.present)} déjà là.`;
 const parts=[`${phCount(s.sent)} ajoutée${s.sent>1?'s':''}`];
 if(s.present)parts.push(`${s.present} déjà là`);
 if(s.refused)parts.push(`${s.refused} écartée${s.refused>1?'s':''} (type non pris en charge)`);
 if(s.failed)parts.push(`${s.failed} en échec`);
 return (s.cancel?'Envoi arrêté : ':'')+parts.join(', ')+'.';
}
async function phSend(list){
 const files=[...list];if(!files.length)return;
 if(phSending||activeUpload){toast('Un transfert est déjà en cours.',true);return;}
 const state=phSending={total:files.length,done:0,part:0,sent:0,present:0,refused:0,failed:0,cancel:false,xhr:null,name:''};
 let awake=null,stopped=null;
 // Un téléphone qui s’endort suspend l’envoi : on demande à l’écran de rester allumé le temps qu’il dure, si le navigateur le permet.
 try{awake=await navigator.wakeLock?.request?.('screen');}catch{}
 phPanel();
 try{
  for(let start=0;start<files.length&&!state.cancel;start+=PH_BATCH){
   const batch=files.slice(start,start+PH_BATCH);
   const made=await api('photos/plan',{items:batch.map(f=>({name:String(f.name),size:Number(f.size)||0,modified:Number(f.lastModified)||Date.now()}))});
   for(let i=0;i<batch.length&&!state.cancel;i++){
    const step=made.items?.[i];state.name=batch[i].name;phPanel();
    if(!step||step.state==='refused')state.refused++;
    else if(step.state==='present')state.present++;
    else{
     try{await phPut(state,made.area,step.path,step.as,batch[i]);state.sent++;}
     catch(error){
      if(state.cancel)break;
      // Un nom pris entre-temps est tenu pour déjà là ; un volume plein arrête tout, le reste échouerait de même.
      if(error.status===409)state.present++;else{state.failed++;if(error.status===507||error.status===403||error.status===401)throw error;}
     }
    }
    state.done++;phPanel();
   }
  }
 }catch(error){stopped=error;}
 finally{phSending=null;phPanel();try{await awake?.release?.();}catch{}}
 toast(stopped?`${stopped.message} ${phSummary(state)}`:phSummary(state),!!stopped||state.failed>0);
 if(state.sent){await api('photos/refresh',{}).catch(()=>{});if(page==='photos')await renderPhotos();}
}
document.addEventListener('click',async e=>{
 const el=e.target.closest?.('[data-action^="ph-"]');if(!el||el.disabled||!user)return;
 try{
  switch(el.dataset.action){
   case 'ph-cancel':if(phSending){phSending.cancel=true;phSending.xhr?.abort();}return;
   case 'ph-open':if(page==='photos')phOpen(Number(el.dataset.index));return;
   case 'ph-prev':return await phStep(-1);
   case 'ph-next':return await phStep(1);
   case 'ph-more':if(page==='photos')await phLoadMore();return;
   case 'ph-refresh':if(page!=='photos')return;await api('photos/refresh',{}).catch(()=>{});return await renderPhotos();
   case 'ph-add':if(page==='photos')$('#ph-input')?.click();return;
   case 'ph-download':{const item=phItems[phShown];if(item)location.href=phFile(item,false);return;}
   case 'ph-reveal':{const item=phItems[phShown];if(item)return await phReveal(item);return;}
  }
 }catch(error){if(error.name!=='AbortError')toast(error.message,true);}
});
document.addEventListener('change',async e=>{
 const id=e.target?.id;
 if(id==='ph-area'&&page==='photos'){phArea=String(e.target.value||'');try{await renderPhotos();}catch(error){toast(error.message,true);}}
 else if(id==='ph-input'&&page==='photos'){const list=[...(e.target.files||[])];e.target.value='';await phSend(list);}
});
document.addEventListener('keydown',e=>{
 if(phShown<0||page!=='photos'||!$('#modal')?.open)return;
 if(e.key==='ArrowLeft'){e.preventDefault();phStep(-1).catch(()=>{});}
 else if(e.key==='ArrowRight'){e.preventDefault();phStep(1).catch(()=>{});}
});
$('#modal')?.addEventListener?.('close',()=>{phShown=-1;phWatch();});
