'use strict';
// Recherche globale du bureau (Ctrl+K) : applications, onglets, réglages nommés comme on les cherche,
// caméras et espaces de fichiers. Elle ouvre une page ; elle ne modifie rien et ne cherche pas dans les fichiers.
const PALETTE_MAX=8;
// [libellé, page, mots associés] : ce que l’on tape rarement comme le titre de la page.
const PALETTE_TOPICS=[
 ['Fuseau horaire','settings','heure horloge utc date'],['Nom du NAS','settings','renommer identité'],['Sessions de la console','settings','déconnecter connexions appareils'],
 ['Mettre à jour Nacre','updates','version paquet installer'],['Copies de retour arrière','updates','rollback restauration version'],
 ['Ajouter une caméra','camera','rtsp tapo onvif','wall'],['Relecture des enregistrements','camera','vidéo frise lecture extrait','replay'],['Événements des caméras','camera','personne voiture détection passage','events'],['Détection et objets suivis','camera','personne véhicule animal','settings'],
 ['Changer un mot de passe','users','compte utilisateur'],['Nouvel utilisateur','users','compte créer lecture seule'],['Nouveau partage','shares','smb samba dossier réseau windows'],
 ['Créer une sauvegarde','backups','archive plan restic'],['Planifier une sauvegarde','backups','plan horaire automatique'],['Restaurer des fichiers','snapshots','récupérer point de restauration'],['Durée de conservation','retention','rétention nettoyage garder'],
 ['État des disques','storage','smart température capacité espace'],['Créer un volume','native','pool raid miroir btrfs zfs'],['Snapshots du volume','native','instantané natif'],
 ['Notifications par courriel','notifications','email smtp webhook alerte'],['Fichiers supprimés','trash','corbeille récupérer'],['Qui a fait quoi','events','journal audit historique']];
let paletteOpen=false,paletteFound=[],palettePick=0,paletteExtra=[],paletteRequest=0;

function paletteNorm(text){return String(text??'').normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase();}
function paletteButton(){return `<button type="button" class="dk-search" id="palette-open" data-action="palette-open" aria-label="Rechercher" title="Rechercher (Ctrl+K)"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.500-4.500"/></svg><span>Rechercher…</span><kbd>Ctrl K</kbd></button>`;}
function palettePanel(){return '<section class="dk-palette" id="palette" aria-label="Recherche" hidden><input id="palette-q" type="search" placeholder="Une application, un réglage, une caméra…" autocomplete="off" aria-label="Rechercher dans Nacre" aria-controls="palette-results"><div id="palette-results" role="listbox"></div></section>';}
// L’index ne contient que ce que le compte peut ouvrir : une page absente de ses applications n’est jamais proposée.
function paletteIndex(){
 const entries=[];
 for(const app of deskApps()){
  const pages=deskPages(app);
  entries.push({label:app.name,hint:'Application',page:pages[0][0],words:pages.map(p=>p[1]).join(' ')});
  if(pages.length>1)for(const [target,label] of pages)entries.push({label,hint:app.name,page:target,words:titles[target]||''});
  else if(app.views)for(const [view,label] of app.views)entries.push({label,hint:app.name,page:pages[0][0],view:[app.id,view],words:''});
 }
 for(const [label,target,words,view] of PALETTE_TOPICS){const app=deskApp(target);if(!app)continue;const name=view?app.views?.find(v=>v[0]===view)?.[1]:null;entries.push({label,hint:`${app.name} · ${name||deskPages(app).find(p=>p[0]===target)[1]}`,page:target,words,...(name?{view:[app.id,view]}:{})});}
 entries.push({label:'Affichage classique',hint:'Revenir au menu à gauche',shell:'classic',words:'ancien menu barre latérale'});
 return [...entries,...paletteExtra];
}
function paletteSearch(text){
 const tokens=paletteNorm(text).split(/\s+/).filter(Boolean);
 const scored=[];
 paletteIndex().forEach((entry,order)=>{
  // Un mot saisi doit commencer un mot de l’entrée : « gar » trouve Garage, pas Sauvegardes.
  const label=paletteNorm(entry.label),words=`${label} ${paletteNorm(entry.hint)} ${paletteNorm(entry.words)}`.split(/[^a-z0-9]+/);
  if(!tokens.every(token=>words.some(word=>word.startsWith(token))))return;
  // Sans saisie, seules les applications ; sinon le libellé qui commence par la saisie passe devant.
  if(!tokens.length&&entry.hint!=='Application')return;
  scored.push({entry,rank:tokens.length&&label.startsWith(tokens[0])?0:tokens.length&&tokens.every(token=>label.split(/[^a-z0-9]+/).some(word=>word.startsWith(token)))?1:2,order});
 });
 return scored.sort((a,b)=>a.rank-b.rank||a.order-b.order).slice(0,PALETTE_MAX).map(item=>item.entry);
}
function drawPalette(){
 const panel=$('#palette'),results=$('#palette-results'),opener=$('#palette-open');if(!panel||!results)return;
 panel.hidden=!paletteOpen;opener?.setAttribute('aria-expanded',String(paletteOpen));
 if(!paletteOpen)return;
 palettePick=Math.min(palettePick,Math.max(paletteFound.length-1,0));
 results.innerHTML=paletteFound.length?paletteFound.map((entry,index)=>`<button type="button" role="option" class="dk-note ${index===palettePick?'on':''}" aria-selected="${index===palettePick}" data-action="palette-run" data-index="${index}">${esc(entry.label)}<small>${esc(entry.hint)}</small></button>`).join(''):'<p class="dk-notehint">Aucun résultat. Essayez le nom d’une application ou d’un réglage.</p>';
}
function closePalette(){if(!paletteOpen)return;paletteOpen=false;drawPalette();}
function openPalette(){
 if(!user||!$('#palette')||$('#modal')?.open)return;
 paletteOpen=true;palettePick=0;paletteFound=paletteSearch('');drawPalette();
 const input=$('#palette-q');if(input){input.value='';input.focus?.();}
 loadPaletteExtra().catch(()=>{});
}
// Caméras et espaces de fichiers, relus à chaque ouverture ; une lecture en échec laisse simplement ces entrées absentes.
async function loadPaletteExtra(){
 const generation=sessionGeneration,request=++paletteRequest;
 const soft=promise=>promise.catch(error=>{if(error.name==='AbortError'||error.status===401)throw error;return [];});
 const [cameras,areas]=await Promise.all([soft(api('cameras')),soft(api('areas'))]);
 if(generation!==sessionGeneration||!user||request!==paletteRequest)return;
 const named=list=>Array.isArray(list)?list.filter(item=>item&&typeof item.id==='string'&&item.id):[];
 paletteExtra=[...named(cameras).map(c=>({label:String(c.name||c.id),hint:'Caméra',camera:c.id,words:`camera surveillance direct relecture ${c.id}`})),
  ...named(areas).map(a=>({label:String(a.name||a.id),hint:'Espace de fichiers',area:a.id,words:`fichiers dossier ${a.id}`}))];
 if(paletteOpen){paletteFound=paletteSearch($('#palette-q')?.value||'');drawPalette();}
}
async function runPalette(entry){
 if(!entry||!user)return;
 closePalette();
 if(entry.shell)return deskSwitch(entry.shell);
 // Dans le bureau, le résultat s’ouvre dans la fenêtre de son application, avec ce qu’il faut y montrer.
 if($('#dk-wins')){
  if(entry.camera)return void deskOpenPage('camera',{view:'wall',camera:entry.camera});
  if(entry.area)return void deskOpenPage('files',{area:entry.area});
  if(entry.page&&deskApp(entry.page))return void deskOpenPage(entry.page,entry.view?{view:entry.view[1]}:{});
  return;
 }
 if(entry.camera){if(typeof survOpenCamera==='function')survOpenCamera(entry.camera);else if(typeof cameraCatalog!=='undefined'){selectedCamera=entry.camera;cameraDetail=true;}return go('camera');}
 if(entry.area){area=entry.area;currentPath='';return go('files');}
 if(entry.page&&deskApp(entry.page)){if(entry.view)deskSetView(...entry.view);return go(entry.page);}
}

document.addEventListener('click',e=>{
 const target=e.target,run=target.closest?.('[data-action="palette-run"]');
 if(run)return runPalette(paletteFound[Number(run.dataset.index)]).catch(error=>{if(error.name!=='AbortError')toast(error.message,true);});
 if(target.closest?.('[data-action="palette-open"]'))return paletteOpen?closePalette():openPalette();
 if(paletteOpen&&!target.closest?.('#palette'))closePalette();
});
document.addEventListener('input',e=>{
 if(e.target?.id!=='palette-q'||!paletteOpen)return;
 palettePick=0;paletteFound=paletteSearch(e.target.value);drawPalette();
});
document.addEventListener('keydown',e=>{
 if((e.ctrlKey||e.metaKey)&&!e.altKey&&String(e.key).toLowerCase()==='k'){if(typeof deskEmbedded==='function'&&deskEmbedded()){e.preventDefault?.();try{window.parent.openPalette();}catch{}return;}if(!$('#palette'))return;e.preventDefault?.();return paletteOpen?closePalette():openPalette();}
 if(!paletteOpen)return;
 if(e.key==='Escape'){closePalette();$('#palette-open')?.focus?.();return;}
 if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault?.();if(paletteFound.length){palettePick=(palettePick+(e.key==='ArrowDown'?1:paletteFound.length-1))%paletteFound.length;drawPalette();}return;}
 if(e.key==='Enter'){e.preventDefault?.();runPalette(paletteFound[palettePick]).catch(error=>{if(error.name!=='AbortError')toast(error.message,true);});}
});
