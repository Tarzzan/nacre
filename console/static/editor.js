'use strict';
// Éditeur intégré : texte et Markdown, dans la fenêtre Fichiers. Enregistrer garde l’ancien contenu comme version.
const ED_NAMES=['.txt','.md','.markdown','.csv','.json','.yml','.yaml','.ini','.conf','.log','.xml','.html','.css','.js','.py','.sh','.toml','.env','.srt'];
let editorDoc=null,editorBeat=null,editorDraw=null;
function editorCan(item){const name=String(item?.name||'').toLowerCase();return !!item&&!item.directory&&!item.link&&(ED_NAMES.some(s=>name.endsWith(s))||!name.replace(/^\.+/,'').includes('.'))&&Number(item.size)<=2*1024**2;}

// Markdown réduit à l’essentiel. Le texte est échappé avant toute mise en forme : rien de ce qu’il contient n’est interprété comme du HTML.
function mdInline(text){
 const kept=[];
 let out=esc(text).replace(/`([^`]+)`/g,(_,code)=>{kept.push(code);return `\u0000${kept.length-1}\u0000`;});
 out=out.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/(^|[^*\w])\*([^*\s][^*]*)\*/g,'$1<em>$2</em>').replace(/(^|[^_\w])_([^_\s][^_]*)_(?!\w)/g,'$1<em>$2</em>')
  .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,'<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
 return out.replace(/\u0000(\d+)\u0000/g,(_,i)=>`<code>${kept[Number(i)]}</code>`);
}
function mdRender(text){
 const lines=String(text??'').replace(/\r\n?/g,'\n').split('\n'),out=[];let i=0;
 const cells=line=>line.trim().replace(/^\||\|$/g,'').split('|').map(c=>c.trim());
 while(i<lines.length){
  const line=lines[i];
  if(/^```/.test(line)){const code=[];i++;while(i<lines.length&&!/^```/.test(lines[i]))code.push(lines[i++]);i++;out.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`);continue;}
  if(!line.trim()){i++;continue;}
  const head=/^(#{1,6})\s+(.*)$/.exec(line);
  if(head){out.push(`<h${head[1].length}>${mdInline(head[2].replace(/\s+#+\s*$/,''))}</h${head[1].length}>`);i++;continue;}
  if(/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)){out.push('<hr>');i++;continue;}
  if(/^>\s?/.test(line)){const quote=[];while(i<lines.length&&/^>\s?/.test(lines[i]))quote.push(lines[i++].replace(/^>\s?/,''));out.push(`<blockquote>${mdRender(quote.join('\n'))}</blockquote>`);continue;}
  if(/^\s*\|.*\|\s*$/.test(line)&&/^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i+1]||'')&&(lines[i+1]||'').includes('-')){
   const header=cells(line),rows=[];i+=2;while(i<lines.length&&/^\s*\|.*\|\s*$/.test(lines[i]))rows.push(cells(lines[i++]));
   out.push(`<div class="tablewrap"><table class="table"><thead><tr>${header.map(c=>`<th>${mdInline(c)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${header.map((_,k)=>`<td>${mdInline(r[k]||'')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`);continue;}
  const bullet=/^\s*[-*+]\s+/,number=/^\s*\d+[.)]\s+/;
  if(bullet.test(line)||number.test(line)){const ordered=number.test(line),mark=ordered?number:bullet,items=[];
   while(i<lines.length&&mark.test(lines[i])){let item=lines[i++].replace(mark,'');const box=/^\[([ xX])\]\s+/.exec(item);if(box)item=(box[1]===' '?'☐ ':'☑ ')+item.slice(box[0].length);items.push(`<li>${mdInline(item)}</li>`);}
   out.push(`<${ordered?'ol':'ul'}>${items.join('')}</${ordered?'ol':'ul'}>`);continue;}
  const para=[];while(i<lines.length&&lines[i].trim()&&!/^(#{1,6}\s|```|>\s?|\s*[-*+]\s+|\s*\d+[.)]\s+)/.test(lines[i])&&!/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(lines[i]))para.push(lines[i++]);
  if(para.length)out.push(`<p>${para.map(mdInline).join('<br>')}</p>`);else i++;
 }
 return out.join('\n');
}

function editorDirty(){return !!editorDoc&&editorDoc.draft!==editorDoc.text;}
function editorState(){const d=editorDoc;return !d.writable?'Lecture seule':editorDirty()?'Modifications non enregistrées':d.saved?'Enregistré à '+new Date(d.saved).toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit'}):'Aucune modification';}
function editorHtml(){
 const d=editorDoc,split=d.markdown&&d.preview;
 return `<div class="ed" id="ed"><div class="ed-bar"><button type="button" class="small" data-action="ed-close">${icon('left')}<span>Fichiers</span></button><strong class="ed-name">${esc(d.name)}</strong><span class="muted" id="ed-state" role="status">${esc(editorState())}</span><span class="fm-grow"></span>`+
  (d.markdown?button('ed-preview',d.preview?'Masquer l’aperçu':'Aperçu',null,'small',`aria-pressed="${!!d.preview}"`):'')+(d.writable?button('ed-save','Enregistrer','check','primary small','title="Ctrl+S"'):'')+'</div>'+
  (d.others?.length?`<div class="notice neutral" id="ed-others">Aussi ouvert par ${d.others.map(esc).join(', ')}. Le dernier à enregistrer l’emporte ; l’autre contenu reste dans les versions.</div>`:'<div id="ed-others" hidden></div>')+
  `<div class="ed-body ${split?'ed-split':''}"><textarea id="ed-text" class="ed-text" spellcheck="true" aria-label="Contenu de ${esc(d.name)}" ${d.writable?'':'readonly'}>${esc(d.draft)}</textarea>${split?`<article class="ed-view" id="ed-view" aria-label="Aperçu">${mdRender(d.draft)}</article>`:''}</div></div>`;
}
function renderEditor(){
 const d=editorDoc;if(!d)return;
 $('#content').innerHTML=editorHtml();
}
function editorStop(){clearInterval(editorBeat);editorBeat=null;clearTimeout(editorDraw);editorDraw=null;}
async function editorOpen(space,path){
 const data=await api('files/text?area='+encodeURIComponent(space)+'&path='+encodeURIComponent(path));
 if(!data||typeof data.text!=='string'||typeof data.etag!=='string')throw new Error('Réponse illisible du serveur.');
 editorStop();
 editorDoc={area:data.area,path:data.path,name:data.name,text:data.text,draft:data.text,etag:data.etag,writable:data.writable===true,markdown:data.markdown===true,preview:data.markdown===true,others:Array.isArray(data.others)?data.others:[],saved:0};
 const beat=()=>{const d=editorDoc;if(!d||!user)return editorStop();api('files/text-presence',{area:d.area,path:d.path,open:true}).then(r=>{if(editorDoc!==d)return;d.others=Array.isArray(r?.others)?r.others:[];const box=$('#ed-others');if(box){box.hidden=!d.others.length;box.className=d.others.length?'notice neutral':'';box.textContent=d.others.length?`Aussi ouvert par ${d.others.join(', ')}. Le dernier à enregistrer l’emporte ; l’autre contenu reste dans les versions.`:'';}}).catch(()=>{});};
 beat();editorBeat=setInterval(beat,30000);
 if(page==='files')renderEditor();
}
async function editorSave(force=false){
 const d=editorDoc;if(!d||!d.writable||d.saving)return;
 if(!editorDirty()&&!force)return toast('Aucune modification à enregistrer.');
 d.saving=true;const sent=d.draft;
 try{
  const done=await api('files/text-save',{area:d.area,path:d.path,text:sent,etag:d.etag,...(force?{force:true}:{})});
  if(editorDoc!==d)return;
  d.text=sent;d.etag=done.etag;d.saved=Date.now();toast('Enregistré. L’ancien contenu reste dans les versions.');
 }catch(error){
  if(error.status===409&&!force){d.saving=false;return confirmAction('Ce fichier a changé entre-temps','Quelqu’un d’autre, ou vous par le réseau, a modifié ce fichier depuis que vous l’avez ouvert. Enregistrer votre contenu le remplace ; l’autre contenu est gardé parmi les versions, rien n’est perdu.','Enregistrer mon contenu',async()=>{await editorSave(true);return {message:'Votre contenu est enregistré.'};});}
  throw error;
 }finally{d.saving=false;const state=$('#ed-state');if(state&&editorDoc===d)state.textContent=editorState();}
}
function editorClose(){
 const d=editorDoc;if(!d)return;
 const leave=async()=>{editorStop();api('files/text-presence',{area:d.area,path:d.path,open:false}).catch(()=>{});editorDoc=null;if(page==='files')await renderFiles();};
 if(!editorDirty())return leave();
 confirmAction('Fermer sans enregistrer ?',`Les modifications de « ${d.name} » depuis le dernier enregistrement seront perdues.`,'Fermer sans enregistrer',async()=>{editorStop();api('files/text-presence',{area:d.area,path:d.path,open:false}).catch(()=>{});editorDoc=null;return {message:'Document fermé.'};});
}
function editorNew(){
 const where=area,folder=currentPath;
 modal('Nouveau document','<div class="field"><label for="ed-new-name">Nom du document</label><input id="ed-new-name" name="name" type="text" value="Sans titre.md" maxlength="180" autocomplete="off" required><small>.md pour un document mis en forme (Markdown), .txt pour du texte simple.</small></div>','Créer et ouvrir',async form=>{
  const made=await api('files/text-new',{area:where,path:folder,name:String(form.get('name')||'').trim()});
  await editorOpen(where,made.path);return {message:'Document créé.'};
 });
}
document.addEventListener('click',async e=>{
 const el=e.target.closest?.('[data-action^="ed-"]');if(!el||el.disabled||page!=='files'||!user)return;
 try{
  switch(el.dataset.action){
   case 'ed-save':return await editorSave();
   case 'ed-close':return editorClose();
   case 'ed-preview':if(editorDoc){editorDoc.preview=!editorDoc.preview;renderEditor();}return;
   case 'ed-open':{if(typeof fmSelected!=='function')return;const chosen=fmSelected();if(chosen.length!==1||!editorCan(chosen[0]))return;return await editorOpen(area,fmJoin(chosen[0].name));}
   case 'ed-new':return editorNew();
  }
 }catch(error){if(error.name!=='AbortError')toast(error.message,true);}
});
document.addEventListener('input',e=>{
 if(e.target?.id!=='ed-text'||!editorDoc)return;
 editorDoc.draft=e.target.value;
 const state=$('#ed-state');if(state)state.textContent=editorState();
 // L’aperçu suit la frappe avec un léger retard, pour ne pas redessiner à chaque touche.
 clearTimeout(editorDraw);editorDraw=setTimeout(()=>{const view=$('#ed-view');if(view&&editorDoc)view.innerHTML=mdRender(editorDoc.draft);},250);
});
document.addEventListener('keydown',e=>{
 if(!editorDoc||page!=='files'||!(e.ctrlKey||e.metaKey)||String(e.key).toLowerCase()!=='s'||$('#modal')?.open)return;
 e.preventDefault?.();editorSave().catch(error=>{if(error.name!=='AbortError')toast(error.message,true);});
});
if(typeof window!=='undefined'&&window.addEventListener)window.addEventListener('beforeunload',e=>{if(editorDirty()){e.preventDefault();e.returnValue='';}});
