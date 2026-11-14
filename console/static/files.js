'use strict';
// Gestionnaire de fichiers du bureau : arborescence, sélection multiple, glisser-déposer et aperçu.
// Il réutilise l’envoi, le renommage, la corbeille et la création de dossier existants ; déplacer et archiver sont nouveaux côté serveur.
// Le champ du haut filtre le dossier ouvert pendant la saisie ; la recherche par nom dans les sous-dossiers ou tout le NAS se lance, elle, à la demande.
const FM_KINDS=[[/\.(jpe?g|png|gif|webp)$/i,'img','Image'],[/\.(mp4|webm)$/i,'vid','Vidéo'],[/\.pdf$/i,'pdf','PDF'],[/\.(txt|md|csv|log|json|ya?ml|ini|conf)$/i,'txt','Texte'],[/\.(zip|tar|gz|tgz|7z|rar)$/i,'zip','Archive']];
const FM_MARK={dir:'D',lnk:'↗',img:'IMG',vid:'VID',pdf:'PDF',txt:'TXT',zip:'ZIP',file:'·'};
let fmItems=[],fmSel=new Set(),fmLast='',fmView='list',fmPreview=true,fmFilter='',fmSort=['name',1],fmRequest=0,fmDrag=null,fmBusy=false;
// Recherche par nom : null hors recherche ; sinon la demande, sa portée et ses résultats (items null tant qu’elle court).
let fmFound=null,fmHit=-1,fmFindRequest=0,fmPending='',fmPendingBig=false,fmPendingWeigh=false,fmPendingSpaces=false,fmSpacesBusy='';
// Sous-dossiers déjà vus, par « espace|chemin » : l’arborescence se construit en naviguant.
const fmDirs=new Map();

function fmKind(item){
 if(item.link)return ['lnk','Lien bloqué'];
 if(item.directory)return ['dir','Dossier'];
 const found=FM_KINDS.find(([pattern])=>pattern.test(item.name));
 return found?[found[1],found[2]]:['file','Fichier'];
}
function fmJoin(name,base=currentPath){return [base,name].filter(Boolean).join('/');}
function fmUrl(name,inline=false,base=currentPath,space=area){return `/api/download?area=${encodeURIComponent(space)}&path=${encodeURIComponent(fmJoin(name,base))}${inline?'&inline=1':''}`;}
function fmArchive(names,base=currentPath,space=area){return `/api/archive?area=${encodeURIComponent(space)}&path=${encodeURIComponent(base)}${names.map(n=>'&name='+encodeURIComponent(n)).join('')}`;}
function fmWritable(){return !!fileAreas.find(a=>a.id===area)?.writable;}
// Premier espace ouvert : celui de la personne pour un membre, l’espace commun sinon.
let fmHomed=false;
function fmFirst(){return (fileAreas.find(a=>a.id==='fichiers')||fileAreas[0])?.id||'fichiers';}
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
 // Titres de section : espaces d’équipe, puis le reste du NAS, seulement s’il y a des espaces au-dessus.
 let section='';
 return fileAreas.map(a=>{
  const kind=a.kind==='personal'?'':a.kind==='team'?'Équipes':'NAS',head=kind&&kind!==section&&fileAreas.some(x=>x.kind==='personal'||x.kind==='team')?`<p class="fm-group">${kind}</p>`:'';section=kind;
  return head+`<button type="button" class="fm-node fm-area ${a.id===area&&!currentPath?'on':''}" data-action="fm-go" data-area="${esc(a.id)}" data-path="" ${a.id===area?'data-fm-drop=""':''}>${esc(a.name)}${a.writable?'':'<small>lecture seule</small>'}</button>${a.id===area?level('',0):''}`;
 }).join('');
}
function fmTools(){
 const chain=currentPath?currentPath.split('/'):[],name=fileAreas.find(a=>a.id===area)?.name||area,write=fmWritable();
 const crumbs=[`<button type="button" data-action="fm-go" data-area="${esc(area)}" data-path="">${esc(name)}</button>`,...chain.map((part,i)=>`<button type="button" data-action="fm-go" data-area="${esc(area)}" data-path="${esc(chain.slice(0,i+1).join('/'))}">${esc(part)}</button>`)].join('<span aria-hidden="true">›</span>');
 return `<div class="fm-crumbs" aria-label="Emplacement">${crumbs}</div><span class="fm-grow"></span><input id="fm-filter" type="search" placeholder="Filtrer ou rechercher" value="${esc(fmFilter)}" aria-label="Filtrer ce dossier ou rechercher un nom" title="Filtre ce dossier pendant la saisie ; Entrée cherche dans tout le NAS">${button('fm-criteria','Par critères',null,'small','title="Chercher sans nom, ici et dans les sous-dossiers : les plus gros fichiers, les plus récents, par type"')}${button('fm-view',fmView==='list'?'Grille':'Liste',null,'small')}${button('fm-preview','Aperçu',null,'small',`aria-pressed="${fmPreview}"`)}${write?button('mkdir','Nouveau dossier','plus','small')+button('fm-send','Déposer des fichiers','upload','primary small'):''}`;
}
function fmBar(){
 const chosen=fmSelected(),write=fmWritable();if(!chosen.length)return '';
 const one=chosen.length===1?chosen[0]:null,href=one&&!one.directory&&!one.link?fmUrl(one.name):fmArchive(chosen.map(i=>i.name));
 return `<div class="fm-bar"><strong>${chosen.length} élément${chosen.length>1?'s':''}</strong><span class="fm-grow"></span>${chosen.some(i=>i.link)?'':`<a class="fm-link" href="${esc(href)}">${one&&!one.directory?'Télécharger':'Télécharger en archive'}</a>`}${one&&!one.link&&typeof linkAllowed==='function'&&linkAllowed()?button('fm-share','Partager par lien',null,'small'):''}${write?(one?button('rename','Renommer',null,'small',`data-path="${esc(fmJoin(one.name))}" data-name="${esc(one.name)}"`):'')+button('fm-move','Déplacer',null,'small')+button('fm-trash','Corbeille',null,'small'):''}${button('fm-clear','Désélectionner',null,'small')}</div>`;
}
function fmAreaName(id){return fileAreas.find(a=>a.id===id)?.name||id;}
function fmFindable(){return fmFilter.replace(/\s/g,'').length>=2;}
// Sous le champ, dès deux caractères : le filtre reste local, la recherche se lance ici ou par Entrée.
function fmAsk(){
 if(!fmFindable())return '';
 return `<div class="fm-find"><span>Filtre sur ce dossier. Chercher ce nom ailleurs :</span><span class="fm-grow"></span>${button('fm-find',currentPath?'Dans ses sous-dossiers':'Dans cet espace',null,'small','data-scope="here"')}${button('fm-find','Dans tout le NAS',null,'primary small','data-scope="all"')}</div>`;
}
// Filtres des résultats : [paramètre de la recherche, libellé, choix]. Le choix vide ne filtre pas.
const FM_REFINE=[['kind','Type',[['','Tous les types'],['folder','Dossiers'],['image','Images'],['video','Vidéos'],['audio','Sons'],['document','Documents'],['archive','Archives']]],
 ['days','Modifié',[['','À toute date'],['1','Depuis 24 heures'],['7','Depuis 7 jours'],['30','Depuis 30 jours'],['365','Depuis un an']]],
 ['min_size','Taille',[['','Toute taille'],['1048576','Plus de 1 Mio'],['104857600','Plus de 100 Mio'],['1073741824','Plus de 1 Gio']]],
 ['sort','Ordre',[['','Par pertinence'],['size','Les plus gros'],['recent','Les plus récents']]]];
// Un classement n’est pas un filtre : « Retirer les filtres » le garde.
function fmRefined(filters){return FM_REFINE.some(([key])=>key!=='sort'&&filters?.[key]);}
// Choix d’ordre proposés : pas de pertinence sans nom (« bare »), pas de taille pour des dossiers, qui n’en ont pas en propre.
function fmOrders(filters,bare){return FM_REFINE[3][2].filter(([value])=>!(bare&&!value)&&!(filters?.kind==='folder'&&value==='size'));}
function fmRefineRow(filters,busy,bare){
 return `<div class="fm-find fm-refine" role="group" aria-label="Affiner les résultats">${FM_REFINE.map(([key,label,choices])=>`<label for="fm-ref-${key}">${label}</label><select id="fm-ref-${key}" data-refine="${key}"${busy?' disabled':''}>${(key==='sort'?fmOrders(filters,bare):choices).map(([value,text])=>`<option value="${value}"${(filters?.[key]||'')===value?' selected':''}>${text}</option>`).join('')}</select>`).join('')}<span class="fm-grow"></span>${fmRefined(filters)&&!busy?button('fm-refine-clear','Retirer les filtres',null,'small'):''}</div>`;
}
// Poids des dossiers : chaque élément du dossier ouvert avec tout ce qu’il contient, du plus lourd au plus léger.
function fmUsageList(){
 const {where,items,partial,visited,total,hidden,others}=fmFound;
 const name=where.path?where.path.split('/').pop():fmAreaName(where.area),least=state=>state==='whole'?'':'au moins ',many=n=>`${n.toLocaleString('fr-FR')} élément${n>1?'s':''}`;
 const head=text=>`<div class="fm-find"><span>${text}</span><span class="fm-grow"></span>${where.path&&items?button('fm-weigh-up','Peser le dossier parent',null,'small'):''}${items?button('fm-spaces','Comparer les espaces',null,'small','title="La dernière pesée de chaque espace, côte à côte"'):''}${button('fm-find-close','Fermer',null,'small')}</div>`;
 if(!items)return head(`Pesée de « ${esc(name)} »…`)+'<p class="fm-hint">Calcul en cours…</p>';
 const note=partial?`Pesée arrêtée après ${visited.toLocaleString('fr-FR')} éléments parcourus : un poids précédé de « au moins » est un minimum, et un dossier « non pesé » n’a pas été commencé. Pesez un sous-dossier pour aller plus loin.`:total.state!=='whole'?'Un dossier au moins n’a pas pu être lu en entier : son poids est un minimum.':'';
 const title=head(`<strong>« ${esc(name)} » pèse ${least(total.state)}${sizes(total.size)}</strong> pour ${many(total.count)}`)+(note?`<p class="fm-note">${esc(note)}</p>`:'');
 if(!items.length&&!hidden.count)return title+empty('Ce dossier est vide.','folder');
 const share=size=>!total.size?'—':size*100<total.size?(size?'&lt; 1 %':'0 %'):Math.round(size*100/total.size)+' %';
 const rest=(label,group,state)=>group.count?`<tr class="fm-rest"><td>${label}</td><td>${many(group.count)}</td><td>${least(state)}${sizes(group.size)}</td><td>${share(group.size)}</td></tr>`:'';
 return title+`<table class="fm-table fm-hits fm-usage"><thead><tr><th>Nom</th><th>Contenu</th><th>Poids</th><th>Part</th></tr></thead><tbody>${items.map((item,index)=>`<tr class="fm-hit ${index===fmHit?'sel':''}" data-hit="${index}"><td>${fmIcon(item)}${esc(item.name)}</td><td>${item.directory&&item.state!=='waiting'?many(item.count):'—'}</td><td>${item.state==='waiting'?'non pesé':least(item.state)+sizes(item.size)}</td><td>${item.state==='waiting'?'—':share(item.size)}</td></tr>`).join('')}${rest('Autres éléments, plus légers',others,'whole')}${rest('Éléments cachés et corbeille',hidden,hidden.state)}</tbody></table>`;
}
// Poids des espaces : la dernière pesée gardée de chacun, côte à côte. Peser un espace met la sienne à jour ; rien d'autre ne relit le disque.
function fmSpacesList(){
 const list=fmFound.list,many=n=>`${n.toLocaleString('fr-FR')} élément${n>1?'s':''}`;
 const head=text=>`<div class="fm-find"><span>${text}</span><span class="fm-grow"></span>${list&&list.length?button('fm-spaces-all','Peser tous les espaces',null,'small',fmSpacesBusy?'disabled':''):''}${button('fm-find-close','Fermer',null,'small')}</div>`;
 if(!list)return head('Poids des espaces…')+'<p class="fm-hint">Lecture des pesées gardées…</p>';
 const known=list.filter(s=>s.kept),sum=known.reduce((n,s)=>n+s.kept.size,0),least=known.some(s=>s.kept.state!=='whole');
 const share=size=>!sum?'—':size*100<sum?(size?'&lt; 1 %':'0 %'):Math.round(size*100/sum)+' %';
 const title=head(known.length?`<strong>${known.length} espace${known.length>1?'s':''} pesé${known.length>1?'s':''} sur ${list.length}</strong> · ${least?'au moins ':''}${sizes(sum)} en tout`:'<strong>Aucun espace n’a encore été pesé.</strong>');
 const note='Chaque poids est celui de la dernière pesée de l’espace entier, à la date indiquée : il ne suit pas ce qui a changé depuis. La part est calculée entre les espaces pesés.';
 return title+`<p class="fm-note">${note}</p><table class="fm-table fm-hits fm-usage fm-spaces"><thead><tr><th>Espace</th><th>Contenu</th><th>Poids</th><th>Part</th><th>Pesé le</th><th></th></tr></thead><tbody>${list.map(s=>{
  const busy=fmSpacesBusy===s.id,k=s.kept;
  return `<tr><td>${icon('folder')}${esc(s.name)}</td><td>${k?many(k.count):'—'}</td><td>${busy?'pesée en cours…':k?(k.state==='whole'?'':'au moins ')+sizes(k.size):'non pesé'}</td><td>${k?share(k.size):'—'}</td><td>${k?date(k.at):'—'}</td><td>${button('fm-space-weigh',k?'Repeser':'Peser',null,'small',`data-area="${esc(s.id)}"${fmSpacesBusy?' disabled':''}`)}${k?button('fm-space-open','Détail',null,'small',`data-area="${esc(s.id)}" title="Ouvrir cet espace et peser ses dossiers"`):''}</td></tr>`;}).join('')}</tbody></table>`;
}
function fmFoundList(){
 if(fmFound.spaces)return fmSpacesList();
 if(fmFound.usage)return fmUsageList();
 const {query,where,items,partial,visited,skipped,limit,filters,matched}=fmFound;
 const bare=!query,order=filters.sort==='recent'?'plus récents':'plus gros';
 const place=where?(where.path?`dans « ${where.path.split('/').pop()} » et ses sous-dossiers`:`dans ${fmAreaName(where.area)}`):'dans tout le NAS';
 const head=text=>`<div class="fm-find"><span>${text}</span><span class="fm-grow"></span>${bare&&items?button('fm-weigh','Poids des dossiers',null,'small','title="Ce que pèse chaque dossier du dossier ouvert, avec tout son contenu"'):''}${where&&items?button('fm-find-wide','Étendre à tout le NAS',null,'small'):''}${button('fm-find-close','Fermer la recherche',null,'small')}</div>`;
 if(!items)return head(bare?`Recherche des ${order} ${esc(place)}…`:`Recherche de « ${esc(query)} » ${esc(place)}…`)+fmRefineRow(filters,true,bare)+'<p class="fm-hint">Recherche en cours…</p>';
 const notes=[];
 if(partial==='results')notes.push(`Seuls les ${limit} premiers résultats sont affichés : précisez le nom, ou affinez par type, date ou taille.`);
 else if(partial)notes.push(`Recherche arrêtée après ${visited.toLocaleString('fr-FR')} éléments parcourus : ${filters.sort?'le classement ne porte que sur ce qui a été vu':'tout n’a pas été vu'}. Cherchez depuis un dossier pour aller plus loin.`);
 if(filters.sort&&matched>items.length)notes.push(`Seuls les ${items.length} ${order} sont affichés, sur ${matched.toLocaleString('fr-FR')} correspondances.`);
 if(skipped.length)notes.push(`Espace indisponible, non parcouru : ${skipped.map(fmAreaName).join(', ')}.`);
 const note=notes.map(text=>`<p class="fm-note">${esc(text)}</p>`).join('');
 const count=`<strong>${items.length} ${bare?'élément':'résultat'}${items.length>1?'s':''}</strong>`;
 const title=head(bare?`${count} ${esc(place)}, les ${order} d’abord`:`${count} pour « ${esc(query)} » ${esc(place)}`)+fmRefineRow(filters,false,bare);
 if(!items.length)return title+note+empty(fmRefined(filters)?'Aucun résultat avec ces filtres.':bare?'Rien à classer ici.':where?'Aucun nom ne correspond ici. Essayez dans tout le NAS.':'Aucun fichier ni dossier ne porte ce nom. Les restaurations ne sont parcourues que depuis leur espace.','folder');
 return title+note+`<table class="fm-table fm-hits"><thead><tr><th>Nom</th><th>Emplacement</th><th>Taille</th><th>Modifié</th></tr></thead><tbody>${items.map((item,index)=>`<tr class="fm-hit ${index===fmHit?'sel':''}" data-hit="${index}"><td>${fmIcon(item)}${esc(item.name)}</td><td>${esc(fmAreaName(item.area)+(item.path?' › '+item.path.split('/').join(' › '):''))}</td><td>${item.directory?'—':sizes(item.size)}</td><td>${date(item.modified)}</td></tr>`).join('')}</tbody></table>`;
}
function fmList(){
 if(fmFound)return fmFoundList();
 const list=fmShown(),write=fmWritable();
 if(!list.length)return fmAsk()+fmBar()+empty(fmFilter.trim()?'Aucun élément ne correspond à ce filtre.':write?'Ce dossier est vide. Glissez des fichiers ici pour les envoyer.':'Ce dossier est vide.','folder');
 const attrs=item=>`data-name="${esc(item.name)}"${write?' draggable="true"':''}${item.directory&&!item.link?` data-fm-drop="${esc(fmJoin(item.name))}"`:''}`;
 const detail=item=>item.directory?'—':sizes(item.size),arrow=key=>fmSort[0]===key?(fmSort[1]>0?' ↑':' ↓'):'';
 if(fmView==='grid')return fmAsk()+fmBar()+`<div class="fm-grid">${list.map(item=>`<div class="fm-row fm-cell ${fmSel.has(item.name)?'sel':''}" ${attrs(item)}>${fmIcon(item)}<div>${esc(item.name)}</div><small>${detail(item)}</small></div>`).join('')}</div>`;
 return fmAsk()+fmBar()+`<table class="fm-table"><thead><tr><th><input type="checkbox" data-action="fm-all" aria-label="Tout sélectionner" ${list.every(i=>fmSel.has(i.name))?'checked':''}></th><th data-action="fm-sort" data-key="name">Nom${arrow('name')}</th><th data-action="fm-sort" data-key="size">Taille${arrow('size')}</th><th data-action="fm-sort" data-key="modified">Modifié${arrow('modified')}</th></tr></thead><tbody>${list.map(item=>`<tr class="fm-row ${fmSel.has(item.name)?'sel':''}" ${attrs(item)}><td><input type="checkbox" data-action="fm-check" aria-label="Sélectionner ${esc(item.name)}" ${fmSel.has(item.name)?'checked':''}></td><td>${fmIcon(item)}${esc(item.name)}</td><td>${detail(item)}</td><td>${date(item.modified)}</td></tr>`).join('')}</tbody></table>`;
}
// Carte d’aperçu d’un élément, dans le dossier ouvert ou parmi des résultats : seul l’emplacement change.
function fmCard(item,base,space,acts){
 const [kind,label]=fmKind(item),src=esc(fmUrl(item.name,true,base,space));
 const body=kind==='img'?`<img class="fm-shot" src="${src}" alt="Aperçu de ${esc(item.name)}">`:kind==='vid'?`<video class="fm-shot" controls preload="metadata" src="${src}"></video>`:kind==='txt'?`<pre class="fm-text" id="fm-text" data-name="${esc(item.name)}" data-src="${src}">Chargement de l’aperçu…</pre>`:kind==='pdf'?'<p class="fm-hint">Un PDF se télécharge pour être ouvert.</p>':kind==='lnk'?'<p class="fm-hint">Lien symbolique : Nacre ne le suit pas.</p>':'';
 const link=item.link?'':`<a class="fm-link" href="${esc(item.directory?fmArchive([item.name],base,space):fmUrl(item.name,false,base,space))}">${item.directory?'Télécharger en archive':'Télécharger'}</a>`;
 return body+`<h3>${esc(item.name)}</h3><dl><dt>Type</dt><dd>${label}</dd>${item.directory?'':`<dt>Taille</dt><dd>${sizes(item.size)}</dd>`}<dt>Modifié</dt><dd>${date(item.modified)}</dd>${acts.where?`<dt>Emplacement</dt><dd>${esc(acts.where)}</dd>`:''}</dl><div class="fm-acts">${acts.before||''}${link}${acts.after||''}</div>`;
}
function fmSide(){
 if(fmFound){
  const hit=fmFound.items?.[fmHit];
  if(!hit)return `<div class="fm-hint">${fmFound.items?.length?'Sélectionnez un résultat pour le voir ici.':''}</div>`;
  const folder=hit.directory&&!hit.link,weigh=fmFound.usage&&folder?button('fm-weigh','Peser ce dossier',null,'primary small',`data-name="${esc(hit.name)}"`):'';
  return fmCard(hit,hit.path,hit.area,{where:fmAreaName(hit.area)+(hit.path?' › '+hit.path.split('/').join(' › '):''),before:weigh+(folder?button('fm-reveal','Ouvrir ce dossier',null,weigh?'small':'primary small','data-inside="1"'):'')+(weigh?'':button('fm-reveal','Afficher dans son dossier',null,folder?'small':'primary small'))});
 }
 const chosen=fmSelected();
 if(chosen.length!==1)return `<div class="fm-hint">${chosen.length?`${chosen.length} éléments sélectionnés.`:'Sélectionnez un élément pour le voir ici.'}</div>`;
 const item=chosen[0],write=fmWritable();
 return fmCard(item,currentPath,area,{before:item.directory&&!item.link?button('fm-open','Ouvrir',null,'primary small',`data-name="${esc(item.name)}"`)+button('fm-weigh','Peser ce dossier',null,'small',`data-name="${esc(item.name)}"`):'',after:write?button('rename','Renommer',null,'small',`data-path="${esc(fmJoin(item.name))}" data-name="${esc(item.name)}"`)+button('fm-trash','Corbeille',null,'small'):''});
}
// Aperçu d’un texte : les premiers kilo-octets, lus comme du texte et jamais interprétés.
async function fmLoadText(){
 const box=$('#fm-text');if(!box)return;
 const generation=sessionGeneration,name=box.dataset.name;
 try{
  const source=box.dataset.src||fmUrl(name,true),response=await fetch(source),text=response.ok?await response.text():null;
  const target=$('#fm-text');if(generation!==sessionGeneration||!target||target.dataset.name!==name||(target.dataset.src||source)!==source)return;
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
 // Une recherche demandée depuis la recherche globale : le nom arrive dans le champ, puis elle part sur tout le NAS.
 const asked=fmPending,big=fmPendingBig,weigh=fmPendingWeigh,spaces=fmPendingSpaces;fmPending='';fmPendingBig=fmPendingWeigh=fmPendingSpaces=false;if(asked||big||weigh||spaces){fmFilter=asked;fmFound=null;}
 const areas=await api('areas');if(!current())return;
 fileAreas=areas;
 if(!fmHomed){fmHomed=true;const mine=fileAreas.find(a=>a.kind==='personal');if(user?.role==='member'&&mine&&area==='fichiers'&&!currentPath)area=mine.id;}
 if(!fileAreas.some(a=>a.id===area)){const gone=area!=='fichiers';area=fmFirst();currentPath='';if(gone)toast('Cet espace n’est plus disponible. Retour au premier espace ouvert.',true);}
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
 if(asked||big||weigh||spaces)(asked?fmFind('all'):big?fmCriteria('all'):weigh?fmUsage():fmSpaces()).catch(error=>{if(error.name!=='AbortError')toast(error.message,true);});
}
// À lancer à la prochaine ouverture de Fichiers : la recherche d’un nom, « big » pour les plus gros fichiers du NAS, ou « weigh » pour le poids des dossiers.
function fmQueue(text,big=false,weigh=false,spaces=false){fmPending=String(text||'').trim().slice(0,80);fmPendingBig=!!big&&!fmPending;fmPendingWeigh=!!weigh&&!fmPending&&!fmPendingBig;fmPendingSpaces=!!spaces&&!fmPending&&!fmPendingBig&&!fmPendingWeigh;}
// Recherche par nom, lancée à la demande : dans le dossier ouvert et ses sous-dossiers (« here ») ou dans tous les espaces.
// Avec « refine », la même recherche est relancée avec d’autres filtres : nom et portée ne changent pas.
function fmFind(scope,refine=null){
 if(refine)return fmFound?.items&&!fmFound.usage?fmSearch(fmFound.query,fmFound.where,refine,fmFound):undefined;
 if(!fmFindable())return toast('Saisissez au moins deux caractères du nom recherché.',true);
 return fmSearch(fmFilter.trim(),scope==='here'?{area,path:currentPath}:null,{},null);
}
// Recherche par critères seuls, sans nom : d’abord les plus gros fichiers, puis type, date, taille et ordre s’ajustent.
function fmCriteria(scope){
 fmFilter='';const box=$('#fm-filter');if(box)box.value='';
 return fmSearch('',scope==='all'?null:{area,path:currentPath},{sort:'size'},null);
}
// La même recherche, étendue du dossier ou de l’espace à tout le NAS.
function fmWiden(){return fmFound?.items&&fmFound.where&&!fmFound.usage?fmSearch(fmFound.query,null,fmFound.filters,fmFound):undefined;}
async function fmSearch(text,where,chosen,before){
 // Seuls les filtres réellement choisis sont gardés. Sans nom, la recherche est toujours classée.
 const filters=Object.fromEntries(FM_REFINE.map(([key])=>[key,String(chosen?.[key]||'')]).filter(([,value])=>value));
 if(filters.sort&&!fmOrders(filters,!text).some(([value])=>value===filters.sort))delete filters.sort;
 if(!text&&!filters.sort)filters.sort=fmOrders(filters,true)[0][0];
 const generation=sessionGeneration,request=++fmFindRequest;
 const current=()=>generation===sessionGeneration&&request===fmFindRequest&&page==='files'&&!!fmFound;
 fmSel.clear();fmHit=-1;fmFound={query:text,where,filters,items:null};fmRedraw();
 let data;
 try{data=await api('files/search?q='+encodeURIComponent(text)+(where?`&area=${encodeURIComponent(where.area)}&path=${encodeURIComponent(where.path)}`:'')+FM_REFINE.map(([key])=>filters[key]?`&${key}=${encodeURIComponent(filters[key])}`:'').join(''));}
 // Une recherche refusée ramène au dossier ; un affinage refusé laisse les résultats précédents.
 catch(error){if(current()){fmFound=before;fmRedraw();}throw error;}
 if(!current())return;
 // Ne sont gardés que les résultats bien formés, dans un espace que ce compte voit.
 const items=(Array.isArray(data?.items)?data.items:[]).filter(i=>i&&typeof i.name==='string'&&i.name&&typeof i.path==='string'&&fileAreas.some(a=>a.id===i.area));
 fmFound={query:text,where,filters,items,partial:typeof data?.partial==='string'?data.partial:'',visited:Number(data?.visited)||0,matched:Math.max(Number(data?.matched)||0,items.length),skipped:(Array.isArray(data?.skipped)?data.skipped:[]).filter(x=>typeof x==='string'),limit:Number(data?.limit)||items.length};
 fmRedraw();
}
// Poids des dossiers d’un dossier de l’espace ouvert : on s’y rend, puis il est pesé. La pesée porte toujours sur le dossier ouvert.
function fmWeigh(path){
 path=String(path||'');
 if(path===currentPath&&$('#fm'))return fmUsage();
 fmFindRequest++;fmFound=null;fmHit=-1;currentPath=path;fmSel.clear();fmLast='';fmFilter='';fmPendingWeigh=true;
 return renderFileManager();
}
async function fmUsage(){
 fmFilter='';const box=$('#fm-filter');if(box)box.value='';
 const where={area,path:currentPath},generation=sessionGeneration,request=++fmFindRequest;
 const current=()=>generation===sessionGeneration&&request===fmFindRequest&&page==='files'&&!!fmFound;
 fmSel.clear();fmHit=-1;fmFound={usage:true,query:'',where,filters:{},items:null};fmRedraw();
 let data;
 try{data=await api(`files/usage?area=${encodeURIComponent(where.area)}&path=${encodeURIComponent(where.path)}`);}
 catch(error){if(current()){fmFound=null;fmRedraw();}throw error;}
 if(!current())return;
 const amount=value=>Math.max(0,Number(value)||0),group=value=>({size:amount(value?.size),count:amount(value?.count),state:value?.state==='whole'?'whole':'partial'});
 // Ne sont gardées que les lignes bien formées ; un état inconnu est lu comme un minimum.
 const items=(Array.isArray(data?.items)?data.items:[]).filter(i=>i&&typeof i.name==='string'&&i.name&&!i.name.includes('/')).map(i=>({area:where.area,path:where.path,name:i.name,directory:!!i.directory,link:!!i.link,size:amount(i.size),modified:amount(i.modified),count:amount(i.count),state:i.state==='whole'||i.state==='waiting'?i.state:'partial'}));
 fmFound={usage:true,query:'',where,filters:{},items,partial:typeof data?.partial==='string'?data.partial:'',visited:amount(data?.visited),total:group(data?.total),hidden:group(data?.hidden),others:group(data?.others)};
 fmRedraw();
}
function fmFindClose(){fmFindRequest++;fmFound=null;fmHit=-1;fmSpacesBusy='';fmRedraw();}
// Lire les pesées gardées. `fmFound.items` reste vide : cette vue n'a ni résultat à sélectionner, ni aperçu.
async function fmSpaces(){
 fmFilter='';const box=$('#fm-filter');if(box)box.value='';
 const generation=sessionGeneration,request=++fmFindRequest,kept=fmFound?.spaces?fmFound.list:null;
 const current=()=>generation===sessionGeneration&&request===fmFindRequest&&page==='files'&&!!fmFound?.spaces;
 fmSel.clear();fmHit=-1;fmFound={spaces:true,usage:true,query:'',where:{area,path:''},filters:{},items:[],list:kept};fmRedraw();
 let data;
 try{data=await api('files/usage-spaces');}
 catch(error){if(current()){fmFound=null;fmRedraw();}throw error;}
 if(!current())return;
 const amount=value=>Math.max(0,Number(value)||0);
 fmFound.list=(Array.isArray(data?.spaces)?data.spaces:[]).filter(s=>s&&typeof s.id==='string'&&typeof s.name==='string'&&fileAreas.some(a=>a.id===s.id))
  .map(s=>({id:s.id,name:s.name,kept:s.kept&&Number.isFinite(s.kept.at)?{at:s.kept.at,size:amount(s.kept.size),count:amount(s.kept.count),state:s.kept.state==='whole'?'whole':'partial'}:null}));
 fmRedraw();
}
// Peser un espace entier, puis relire les pesées gardées. Un refus est dit ; les autres lignes ne bougent pas.
async function fmSpaceWeigh(id){
 if(fmSpacesBusy||!fmFound?.spaces||!fileAreas.some(a=>a.id===id))return false;
 fmSpacesBusy=id;fmRedraw();
 let done=true;
 try{await api(`files/usage?area=${encodeURIComponent(id)}&path=`);}
 catch(error){done=false;if(error.name!=='AbortError')toast(`${fmAreaName(id)} : ${error.message}`,true);}
 fmSpacesBusy='';
 if(fmFound?.spaces)await fmSpaces();
 return done;
}
async function fmSpacesAll(){for(const space of [...(fmFound?.list||[])]){if(!fmFound?.spaces)return;await fmSpaceWeigh(space.id);}}
// Depuis un résultat : ouvrir le dossier trouvé, ou son dossier parent avec l’élément sélectionné.
function fmReveal(hit,inside){
 if(!hit||!fileAreas.some(a=>a.id===hit.area))return;
 fmFindRequest++;fmFound=null;fmHit=-1;fmFilter='';area=hit.area;currentPath=inside?fmJoin(hit.name,hit.path):hit.path;
 fmSel=inside?new Set():new Set([hit.name]);fmLast=inside?'':hit.name;
 return renderFileManager();
}
function fmGo(space,path){fmFindRequest++;fmFound=null;fmHit=-1;area=space;currentPath=path;fmSel.clear();fmLast='';fmFilter='';return renderFileManager();}
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
   if(action==='fm-share'){const chosen=fmSelected();if(chosen.length!==1||chosen[0].link||typeof linkAsk!=='function'||!linkAllowed())return;return linkAsk(fmJoin(chosen[0].name),chosen[0]);}
   if(action==='fm-trash')return fmAskTrash();
   if(action==='fm-move')return fmAskMove();
   if(action==='fm-find')return await fmFind(el.dataset.scope==='here'?'here':'all');
   if(action==='fm-find-close')return fmFindClose();
   if(action==='fm-refine-clear')return await fmFind('',{sort:fmFound?.filters?.sort});
   if(action==='fm-criteria')return await fmCriteria('here');
   if(action==='fm-find-wide')return await fmWiden();
   if(action==='fm-weigh')return await fmWeigh(el.dataset.name?fmJoin(el.dataset.name):currentPath);
   if(action==='fm-weigh-up')return await fmWeigh(currentPath.split('/').slice(0,-1).join('/'));
   if(action==='fm-spaces')return await fmSpaces();
   if(action==='fm-space-weigh')return void await fmSpaceWeigh(el.dataset.area);
   if(action==='fm-spaces-all')return await fmSpacesAll();
   if(action==='fm-space-open'){if(!fileAreas.some(a=>a.id===el.dataset.area))return;area=el.dataset.area;currentPath='';fmFindRequest++;fmFound=null;fmHit=-1;fmSel.clear();fmLast='';fmFilter='';fmPendingWeigh=true;return await renderFileManager();}
   if(action==='fm-reveal')return await fmReveal(fmFound?.items?.[fmHit],el.dataset.inside==='1');
   return;
  }
  const hit=e.target.closest?.('.fm-hit');
  if(hit&&fmFound?.items){fmHit=Number(hit.dataset.hit);return fmRedraw();}
  if(!row||e.target.closest?.('a'))return;
  const name=row.dataset.name,list=fmShown().map(i=>i.name);
  if(e.shiftKey&&list.includes(fmLast)){const a=list.indexOf(fmLast),b=list.indexOf(name);fmSel=new Set(list.slice(Math.min(a,b),Math.max(a,b)+1));}
  else if(e.ctrlKey||e.metaKey){fmSel.has(name)?fmSel.delete(name):fmSel.add(name);fmLast=name;}
  else{fmSel=new Set([name]);fmLast=name;}
  fmRedraw();
 }catch(error){if(error.name!=='AbortError')toast(error.message,true);}
});
document.addEventListener('dblclick',e=>{
 const hit=e.target.closest?.('.fm-hit');
 if(hit&&page==='files'&&fmFound?.items){const found=fmFound.items[Number(hit.dataset.hit)],folder=!!found?.directory&&!found.link;Promise.resolve(fmFound.usage&&folder?fmWeigh(fmJoin(found.name)):fmReveal(found,folder)).catch(error=>{if(error.name!=='AbortError')toast(error.message,true);});return;}
 const row=e.target.closest?.('.fm-row');if(!row||page!=='files'||e.target.closest?.('input,a,button'))return;
 const item=fmItems.find(i=>i.name===row.dataset.name);
 if(item?.directory&&!item.link)fmGo(area,fmJoin(item.name)).catch(error=>{if(error.name!=='AbortError')toast(error.message,true);});
});
// Retoucher le champ quitte les résultats : on revient au dossier, filtré par la saisie.
document.addEventListener('input',e=>{if(e.target?.id==='fm-filter'&&page==='files'){fmFilter=e.target.value;fmSel.clear();if(fmFound){fmFindRequest++;fmFound=null;fmHit=-1;}fmRedraw();}});
// Un filtre choisi relance la même recherche ; le choix doit être l’un de ceux proposés.
document.addEventListener('change',e=>{
 const key=e.target?.dataset?.refine;if(!key||page!=='files'||!fmFound?.items||fmFound.usage)return;
 const value=String(e.target.value||''),id=e.target.id;
 if(!(key==='sort'?fmOrders(fmFound.filters,!fmFound.query):FM_REFINE.find(r=>r[0]===key)?.[2])?.some(choice=>choice[0]===value))return;
 return fmFind('',{...fmFound.filters,[key]:value}).then(()=>$('#'+id)?.focus?.()).catch(error=>{if(error.name!=='AbortError')toast(error.message,true);});
});
document.addEventListener('change',e=>{if(e.target?.id==='fm-upload'){const files=[...(e.target.files||[])];e.target.value='';fmSend(files).catch(error=>toast(error.message,true));}});
document.addEventListener('keydown',e=>{
 if(page!=='files'||!$('#fm')||$('#modal')?.open)return;
 if(e.target?.id==='fm-filter'&&e.key==='Enter'&&fmFindable()){e.preventDefault?.();fmFind('all').catch(error=>{if(error.name!=='AbortError')toast(error.message,true);});return;}
 if(/^(INPUT|SELECT|TEXTAREA)$/.test(e.target?.tagName||''))return;
 if(fmFound){if(e.key==='Escape')fmFindClose();return;}
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
