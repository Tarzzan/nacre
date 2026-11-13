'use strict';
// Gestionnaire de fichiers du bureau : arborescence, sélection multiple, glisser-déposer et aperçu.
// Il réutilise l’envoi, le renommage, la corbeille et la création de dossier existants ; déplacer et archiver sont nouveaux côté serveur.
const FM_KINDS=[[/\.(jpe?g|png|gif|webp)$/i,'img','Image'],[/\.(mp4|webm)$/i,'vid','Vidéo'],[/\.pdf$/i,'pdf','PDF'],[/\.(txt|md|csv|log|json|ya?ml|ini|conf)$/i,'txt','Texte'],[/\.(zip|tar|gz|tgz|7z|rar)$/i,'zip','Archive']];
const FM_MARK={dir:'D',lnk:'↗',img:'IMG',vid:'VID',pdf:'PDF',txt:'TXT',zip:'ZIP',file:'·'};
let fmItems=[],fmSel=new Set(),fmLast='',fmView='list',fmPreview=true,fmFilter='',fmSort=['name',1],fmRequest=0,fmDrag=null,fmBusy=false;
// Sous-dossiers déjà vus, par « espace|chemin » : l’arborescence se construit en naviguant.
const fmDirs=new Map();

function fmKind(item){
 if(item.link)return ['lnk','Lien bloqué'];
 if(item.directory)return ['dir','Dossier'];
 const found=FM_KINDS.find(([pattern])=>pattern.test(item.name));
 return found?[found[1],found[2]]:['file','Fichier'];
}
function fmJoin(name,base=currentPath){return [base,name].filter(Boolean).join('/');}
function fmUrl(name,inline=false){return `/api/download?area=${encodeURIComponent(area)}&path=${encodeURIComponent(fmJoin(name))}${inline?'&inline=1':''}`;}
function fmArchive(names){return `/api/archive?area=${encodeURIComponent(area)}&path=${encodeURIComponent(currentPath)}${names.map(n=>'&name='+encodeURIComponent(n)).join('')}`;}
function fmWritable(){return user?.role==='admin'&&!!fileAreas.find(a=>a.id===area)?.writable;}
function fmShown(){
 const needle=fmFilter.trim().toLowerCase(),[key,way]=fmSort;
 return fmItems.filter(i=>!needle||i.name.toLowerCase().includes(needle)).sort((a,b)=>(Number(b.directory)-Number(a.directory))||(key==='name'?a.name.localeCompare(b.name,'fr',{numeric:true}):(a[key]||0)-(b[key]||0))*way);
}
function fmSelected(){return fmItems.filter(i=>fmSel.has(i.name));}
function fmIcon(item){const kind=fmKind(item)[0];return `<span class="fm-ic fm-${kind}" aria-hidden="true">${FM_MARK[kind]}</span>`;}

function fmTree(){
 const chain=currentPath?currentPath.split('/'):[];
 const level=(path,depth)=>{
  const next=chain[depth],names=fmDirs.get(area+'|'+path)||(next?[next]:[]);
  return names.map(name=>{const target=fmJoin(name,path);return `<button type="button" class="fm-node ${target===currentPath?'on':''}" data-action="fm-go" data-area="${esc(area)}" data-path="${esc(target)}" data-fm-drop="${esc(target)}" data-depth="${Math.min(depth+1,6)}">${esc(name)}</button>${next===name?level(target,depth+1):''}`;}).join('');
 };
 return fileAreas.map(a=>`<button type="button" class="fm-node fm-area ${a.id===area&&!currentPath?'on':''}" data-action="fm-go" data-area="${esc(a.id)}" data-path="" ${a.id===area?'data-fm-drop=""':''}>${esc(a.name)}${a.writable?'':'<small>lecture seule</small>'}</button>${a.id===area?level('',0):''}`).join('');
}
function fmTools(){
 const chain=currentPath?currentPath.split('/'):[],name=fileAreas.find(a=>a.id===area)?.name||area,write=fmWritable();
 const crumbs=[`<button type="button" data-action="fm-go" data-area="${esc(area)}" data-path="">${esc(name)}</button>`,...chain.map((part,i)=>`<button type="button" data-action="fm-go" data-area="${esc(area)}" data-path="${esc(chain.slice(0,i+1).join('/'))}">${esc(part)}</button>`)].join('<span aria-hidden="true">›</span>');
 return `<div class="fm-crumbs" aria-label="Emplacement">${crumbs}</div><span class="fm-grow"></span><input id="fm-filter" type="search" placeholder="Filtrer ce dossier" value="${esc(fmFilter)}" aria-label="Filtrer ce dossier">${button('fm-view',fmView==='list'?'Grille':'Liste',null,'small')}${button('fm-preview','Aperçu',null,'small',`aria-pressed="${fmPreview}"`)}${write?button('mkdir','Nouveau dossier','plus','small')+button('fm-send','Déposer des fichiers','upload','primary small'):''}`;
}
function fmBar(){
 const chosen=fmSelected(),write=fmWritable();if(!chosen.length)return '';
 const one=chosen.length===1?chosen[0]:null,href=one&&!one.directory&&!one.link?fmUrl(one.name):fmArchive(chosen.map(i=>i.name));
 return `<div class="fm-bar"><strong>${chosen.length} élément${chosen.length>1?'s':''}</strong><span class="fm-grow"></span>${chosen.some(i=>i.link)?'':`<a class="fm-link" href="${esc(href)}">${one&&!one.directory?'Télécharger':'Télécharger en archive'}</a>`}${write?(one?button('rename','Renommer',null,'small',`data-path="${esc(fmJoin(one.name))}" data-name="${esc(one.name)}"`):'')+button('fm-move','Déplacer',null,'small')+button('fm-trash','Corbeille',null,'small'):''}${button('fm-clear','Désélectionner',null,'small')}</div>`;
}
function fmList(){
 const list=fmShown(),write=fmWritable();
 if(!list.length)return fmBar()+empty(fmFilter.trim()?'Aucun élément ne correspond à ce filtre.':write?'Ce dossier est vide. Glissez des fichiers ici pour les envoyer.':'Ce dossier est vide.','folder');
 const attrs=item=>`data-name="${esc(item.name)}"${write?' draggable="true"':''}${item.directory&&!item.link?` data-fm-drop="${esc(fmJoin(item.name))}"`:''}`;
 const detail=item=>item.directory?'—':sizes(item.size),arrow=key=>fmSort[0]===key?(fmSort[1]>0?' ↑':' ↓'):'';
 if(fmView==='grid')return fmBar()+`<div class="fm-grid">${list.map(item=>`<div class="fm-row fm-cell ${fmSel.has(item.name)?'sel':''}" ${attrs(item)}>${fmIcon(item)}<div>${esc(item.name)}</div><small>${detail(item)}</small></div>`).join('')}</div>`;
 return fmBar()+`<table class="fm-table"><thead><tr><th><input type="checkbox" data-action="fm-all" aria-label="Tout sélectionner" ${list.every(i=>fmSel.has(i.name))?'checked':''}></th><th data-action="fm-sort" data-key="name">Nom${arrow('name')}</th><th data-action="fm-sort" data-key="size">Taille${arrow('size')}</th><th data-action="fm-sort" data-key="modified">Modifié${arrow('modified')}</th></tr></thead><tbody>${list.map(item=>`<tr class="fm-row ${fmSel.has(item.name)?'sel':''}" ${attrs(item)}><td><input type="checkbox" data-action="fm-check" aria-label="Sélectionner ${esc(item.name)}" ${fmSel.has(item.name)?'checked':''}></td><td>${fmIcon(item)}${esc(item.name)}</td><td>${detail(item)}</td><td>${date(item.modified)}</td></tr>`).join('')}</tbody></table>`;
}
function fmSide(){
 const chosen=fmSelected();
 if(chosen.length!==1)return `<div class="fm-hint">${chosen.length?`${chosen.length} éléments sélectionnés.`:'Sélectionnez un élément pour le voir ici.'}</div>`;
 const item=chosen[0],[kind,label]=fmKind(item),write=fmWritable();
 const body=kind==='img'?`<img class="fm-shot" src="${esc(fmUrl(item.name,true))}" alt="Aperçu de ${esc(item.name)}">`:kind==='vid'?`<video class="fm-shot" controls preload="metadata" src="${esc(fmUrl(item.name,true))}"></video>`:kind==='txt'?`<pre class="fm-text" id="fm-text" data-name="${esc(item.name)}">Chargement de l’aperçu…</pre>`:kind==='pdf'?'<p class="fm-hint">Un PDF se télécharge pour être ouvert.</p>':kind==='lnk'?'<p class="fm-hint">Lien symbolique : Nacre ne le suit pas.</p>':'';
 return body+`<h3>${esc(item.name)}</h3><dl><dt>Type</dt><dd>${label}</dd>${item.directory?'':`<dt>Taille</dt><dd>${sizes(item.size)}</dd>`}<dt>Modifié</dt><dd>${date(item.modified)}</dd></dl><div class="fm-acts">${item.directory&&!item.link?button('fm-open','Ouvrir',null,'primary small',`data-name="${esc(item.name)}"`):''}${item.link?'':`<a class="fm-link" href="${esc(item.directory?fmArchive([item.name]):fmUrl(item.name))}">${item.directory?'Télécharger en archive':'Télécharger'}</a>`}${write?button('rename','Renommer',null,'small',`data-path="${esc(fmJoin(item.name))}" data-name="${esc(item.name)}"`)+button('fm-trash','Corbeille',null,'small'):''}</div>`;
}
// Aperçu d’un texte : les premiers kilo-octets, lus comme du texte et jamais interprétés.
async function fmLoadText(){
 const box=$('#fm-text');if(!box)return;
 const generation=sessionGeneration,name=box.dataset.name;
 try{
  const response=await fetch(fmUrl(name,true)),text=response.ok?await response.text():null;
  const target=$('#fm-text');if(generation!==sessionGeneration||!target||target.dataset.name!==name)return;
  target.textContent=text===null?'Aperçu indisponible.':text||'Fichier vide.';
 }catch{const target=$('#fm-text');if(target&&target.dataset.name===name)target.textContent='Aperçu indisponible.';}
}
function fmRedraw(tools=false){
 const root=$('#fm'),list=$('#fm-list'),side=$('#fm-side');if(!root||!list||!side)return;
 root.classList.toggle('fm-nopreview',!fmPreview);
 if(tools){const box=$('#fm-tools');if(box)box.innerHTML=fmTools();}
 list.innerHTML=fmList();side.innerHTML=fmSide();fmLoadText();
}
async function renderFileManager(){
 const generation=sessionGeneration,request=++fmRequest,current=()=>generation===sessionGeneration&&page==='files'&&request===fmRequest;
 const areas=await api('areas');if(!current())return;
 fileAreas=areas;
 if(!fileAreas.some(a=>a.id===area)){area='fichiers';currentPath='';toast('Le volume est indisponible. Retour aux fichiers partagés.',true);}
 let data;
 try{data=await api('files?area='+encodeURIComponent(area)+'&path='+encodeURIComponent(currentPath));}
 catch(error){
  if(!current())return;
  if(error.status===404&&currentPath){currentPath='';toast('Ce dossier n’existe plus. Retour à la racine de l’espace.',true);return renderFileManager();}
  throw error;
 }
 if(!current())return;
 fmItems=(Array.isArray(data?.items)?data.items:[]).filter(i=>i&&typeof i.name==='string'&&i.name);
 fmDirs.set(area+'|'+currentPath,fmItems.filter(i=>i.directory&&!i.link).map(i=>i.name));
 fmSel=new Set([...fmSel].filter(name=>fmItems.some(i=>i.name===name)));
 $('#content').innerHTML=`<div class="fm ${fmPreview?'':'fm-nopreview'}" id="fm"><nav class="fm-tree" id="fm-tree" aria-label="Espaces et dossiers">${fmTree()}</nav><div class="fm-main"><div class="fm-tools" id="fm-tools">${fmTools()}</div><div class="fm-list" id="fm-list">${fmList()}</div></div><aside class="fm-side" id="fm-side" aria-label="Aperçu">${fmSide()}</aside><input type="file" id="fm-upload" multiple hidden><div class="fm-drop" id="fm-drop" hidden></div></div>`;
 fmLoadText();
}
function fmGo(space,path){if(space!==area)fmFilter='';area=space;currentPath=path;fmSel.clear();fmLast='';fmFilter='';return renderFileManager();}
// Envoi de plusieurs fichiers, l’un après l’autre, par le transfert existant. Changer de dossier arrête la suite.
async function fmSend(files){
 if(fmBusy||!files.length||!fmWritable())return;
 fmBusy=true;const space=area,path=currentPath,failed=[];let done=0;
 try{
  for(const file of files){
   if(area!==space||currentPath!==path||page!=='files'){failed.push('envoi arrêté : vous avez changé de dossier');break;}
   try{await uploadFile(file);done++;}catch(error){failed.push(`${file.name} : ${error.message}`);}
  }
 }finally{fmBusy=false;}
 toast(`${done} fichier${done>1?'s':''} déposé${done>1?'s':''}.${failed.length?' Non envoyé : '+failed.join(' ; ')+'.':''}`,failed.length>0);
 if(page==='files'&&$('#fm'))await renderFileManager();
}
async function fmMove(names,target){
 if(!names?.length||target===currentPath||!fmWritable())return;
 await api('move',{area,path:currentPath,names,target});
 toast(`${names.length} élément${names.length>1?'s':''} déplacé${names.length>1?'s':''} vers ${target?target.split('/').pop():'la racine de l’espace'}.`);
 fmSel.clear();await renderFileManager();
}
function fmAskTrash(){
 const chosen=fmSelected().map(i=>i.name);if(!chosen.length||!fmWritable())return;
 confirmAction(chosen.length>1?`Mettre ${chosen.length} éléments en corbeille ?`:'Mettre en corbeille ?',chosen.length>1?'Ils seront déplacés dans la corbeille et pourront être restaurés.':`${chosen[0]} sera déplacé dans la corbeille et pourra être restauré.`,'Déplacer',async()=>{
  for(const name of chosen)await api('trash',{path:fmJoin(name),area});
  fmSel.clear();return {message:`${chosen.length} élément${chosen.length>1?'s':''} en corbeille.`};
 });
}
function fmAskMove(){
 const chosen=fmSelected().map(i=>i.name);if(!chosen.length||!fmWritable())return;
 const taken=chosen.map(name=>fmJoin(name)),targets=new Set(['']);
 for(const [key,names] of fmDirs){if(!key.startsWith(area+'|'))continue;const base=key.slice(area.length+1);targets.add(base);for(const name of names)targets.add(fmJoin(name,base));}
 const list=[...targets].filter(t=>t!==currentPath&&!taken.some(p=>t===p||t.startsWith(p+'/'))).sort((a,b)=>a.localeCompare(b,'fr'));
 if(!list.length)return toast('Ouvrez d’abord le dossier de destination dans l’arborescence, ou glissez la sélection dessus.',true);
 modal(`Déplacer ${chosen.length} élément${chosen.length>1?'s':''}`,`<div class="field"><label for="fm-target">Dossier de destination</label><select id="fm-target" name="target">${list.map(t=>`<option value="${esc(t)}">${t?esc('/'+t):'Racine de l’espace'}</option>`).join('')}</select><small>Les dossiers déjà ouverts dans l’arborescence sont proposés. Rien n’est remplacé : un nom déjà pris arrête le déplacement.</small></div>`,'Déplacer',async form=>{
  await api('move',{area,path:currentPath,names:chosen,target:String(form.get('target')||'')});
  fmSel.clear();return {message:`${chosen.length} élément${chosen.length>1?'s':''} déplacé${chosen.length>1?'s':''}.`};
 });
}

document.addEventListener('click',async e=>{
 if(page!=='files'||!$('#fm')||!user)return;
 const el=e.target.closest?.('[data-action]'),row=e.target.closest?.('.fm-row');
 try{
  if(el){
   const action=el.dataset.action;
   if(action==='fm-go'){if(!fileAreas.some(a=>a.id===el.dataset.area))return;return await fmGo(el.dataset.area,el.dataset.path||'');}
   if(action==='fm-open'){const item=fmItems.find(i=>i.name===el.dataset.name);if(item?.directory&&!item.link)return await fmGo(area,fmJoin(item.name));return;}
   if(action==='fm-view'){fmView=fmView==='list'?'grid':'list';return fmRedraw(true);}
   if(action==='fm-preview'){fmPreview=!fmPreview;return fmRedraw(true);}
   if(action==='fm-sort'){fmSort=[el.dataset.key,fmSort[0]===el.dataset.key?-fmSort[1]:1];return fmRedraw();}
   if(action==='fm-all'){const list=fmShown();fmSel=list.every(i=>fmSel.has(i.name))?new Set():new Set(list.map(i=>i.name));return fmRedraw();}
   if(action==='fm-check'){const name=row?.dataset.name;if(!name)return;fmSel.has(name)?fmSel.delete(name):fmSel.add(name);fmLast=name;return fmRedraw();}
   if(action==='fm-clear'){fmSel.clear();return fmRedraw();}
   if(action==='fm-send')return $('#fm-upload')?.click();
   if(action==='fm-trash')return fmAskTrash();
   if(action==='fm-move')return fmAskMove();
   return;
  }
  if(!row||e.target.closest?.('a'))return;
  const name=row.dataset.name,list=fmShown().map(i=>i.name);
  if(e.shiftKey&&list.includes(fmLast)){const a=list.indexOf(fmLast),b=list.indexOf(name);fmSel=new Set(list.slice(Math.min(a,b),Math.max(a,b)+1));}
  else if(e.ctrlKey||e.metaKey){fmSel.has(name)?fmSel.delete(name):fmSel.add(name);fmLast=name;}
  else{fmSel=new Set([name]);fmLast=name;}
  fmRedraw();
 }catch(error){if(error.name!=='AbortError')toast(error.message,true);}
});
document.addEventListener('dblclick',e=>{
 const row=e.target.closest?.('.fm-row');if(!row||page!=='files'||e.target.closest?.('input,a,button'))return;
 const item=fmItems.find(i=>i.name===row.dataset.name);
 if(item?.directory&&!item.link)fmGo(area,fmJoin(item.name)).catch(error=>{if(error.name!=='AbortError')toast(error.message,true);});
});
document.addEventListener('input',e=>{if(e.target?.id==='fm-filter'&&page==='files'){fmFilter=e.target.value;fmSel.clear();fmRedraw();}});
document.addEventListener('change',e=>{if(e.target?.id==='fm-upload'){const files=[...(e.target.files||[])];e.target.value='';fmSend(files).catch(error=>toast(error.message,true));}});
document.addEventListener('keydown',e=>{
 if(page!=='files'||!$('#fm')||$('#modal')?.open||/^(INPUT|SELECT|TEXTAREA)$/.test(e.target?.tagName||''))return;
 if((e.ctrlKey||e.metaKey)&&String(e.key).toLowerCase()==='a'){e.preventDefault?.();fmSel=new Set(fmShown().map(i=>i.name));return fmRedraw();}
 if(e.key==='Escape'&&fmSel.size){fmSel.clear();return fmRedraw();}
 if(e.key==='Delete'&&fmSel.size)return fmAskTrash();
 if(e.key==='Enter'&&fmSel.size===1){const item=fmSelected()[0];if(item?.directory&&!item.link)fmGo(area,fmJoin(item.name)).catch(error=>{if(error.name!=='AbortError')toast(error.message,true);});}
});
// Glisser une sélection vers un dossier la déplace ; glisser des fichiers de l’ordinateur les envoie dans le dossier ouvert.
document.addEventListener('dragstart',e=>{
 const row=e.target.closest?.('.fm-row');if(!row||page!=='files'||!fmWritable())return;
 if(!fmSel.has(row.dataset.name)){fmSel=new Set([row.dataset.name]);fmLast=row.dataset.name;}
 fmDrag=[...fmSel];e.dataTransfer?.setData('text/plain',fmDrag.join('\n'));if(e.dataTransfer)e.dataTransfer.effectAllowed='move';
});
function fmTarget(e){
 const target=e.target.closest?.('[data-fm-drop]');if(!target||!fmDrag)return null;
 const path=target.dataset.fmDrop,taken=fmDrag.map(name=>fmJoin(name));
 return path===currentPath||taken.some(p=>path===p||path.startsWith(p+'/'))?null:target;
}
document.addEventListener('dragover',e=>{
 if(page!=='files'||!$('#fm'))return;
 if([...(e.dataTransfer?.types||[])].includes('Files')){if(!fmWritable())return;e.preventDefault();const drop=$('#fm-drop');if(drop){drop.hidden=false;drop.textContent=`Déposez pour envoyer dans ${currentPath?currentPath.split('/').pop():fileAreas.find(a=>a.id===area)?.name||'cet espace'}`;}return;}
 for(const over of document.querySelectorAll('#fm .over'))over.classList.remove('over');
 const target=fmTarget(e);if(target){e.preventDefault();target.classList.add('over');}
});
document.addEventListener('dragleave',e=>{if(!e.relatedTarget){const drop=$('#fm-drop');if(drop)drop.hidden=true;}});
document.addEventListener('dragend',()=>{fmDrag=null;for(const over of document.querySelectorAll('#fm .over'))over.classList.remove('over');});
document.addEventListener('drop',e=>{
 if(page!=='files'||!$('#fm'))return;
 const drop=$('#fm-drop');if(drop)drop.hidden=true;
 const entries=[...(e.dataTransfer?.items||[])],files=[...(e.dataTransfer?.files||[])];
 if(files.length){
  e.preventDefault();
  // Un dossier déposé n’est pas un fichier : il est écarté et signalé, pas envoyé à moitié.
  const plain=files.filter((file,index)=>!entries[index]?.webkitGetAsEntry?.()?.isDirectory);
  if(plain.length<files.length)toast('Les dossiers ne s’envoient pas par glisser-déposer : seuls les fichiers sont pris.',true);
  return fmSend(plain).catch(error=>toast(error.message,true));
 }
 const target=fmTarget(e),names=fmDrag;fmDrag=null;
 if(target&&names){e.preventDefault();fmMove(names,target.dataset.fmDrop).catch(error=>{if(error.name!=='AbortError')toast(error.message,true);});}
});
