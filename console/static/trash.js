// Corbeille : restaurer, retirer pour de bon, vider. Ce qui est retiré ne se récupère pas : chaque geste est confirmé,
// et n'est proposé qu'à qui répond de l'espace (chacun dans son espace personnel, un administrateur ailleurs).
const TRASH_STEP=200;
let trashShown=TRASH_STEP;
const trashKept={0:'Jamais vidée seule',7:'7 jours',30:'30 jours',90:'90 jours',365:'1 an'};
function trashPlural(n,word){return `${Number(n).toLocaleString('fr-FR')} ${word}${n>1?'s':''}`;}
function trashName(path){return String(path||'').split('/').pop();}
async function renderTrash(){
 const session=sessionGeneration,target=$('#content'),[items,state]=await Promise.all([api('trash'),api('trash/overview')]);
 if(session!==sessionGeneration||page!=='trash'||target!==$('#content'))return;
 const areas=Array.isArray(state?.areas)?state.areas:[],days=Number(state?.days)||0,list=Array.isArray(items)?items:[],at=Number(state?.at)||0;
 const names=new Map(areas.map(a=>[a.id,a.name]));
 const kept=days?` Au bout de ${trashKept[days]||days+' jours'}, ils sont retirés pour de bon.`:'';
 // Le bouton porte l'instant de cet affichage : le vidage n'efface rien de ce qui aura été jeté depuis.
 const empties=areas.filter(a=>a.erase&&(a.count>0||a.leftovers>0)).map(a=>button('trash-empty',`Vider la corbeille de « ${esc(a.name)} »`,'trash','small',`data-area="${esc(a.id)}" data-name="${esc(a.name)}" data-count="${Number(a.count)||0}" data-left="${Number(a.leftovers)||0}" data-at="${at}"`)).join('');
 const rows=list.slice(0,trashShown).map(i=>`<tr><td><small class="muted">${esc(names.get(i.area)||fileAreas.find(a=>a.id===(i.area||'fichiers'))?.name||i.area||'Fichiers partagés')}</small><br>${esc(i.original)}</td><td>${date(i.ts)}</td><td>${i.restore?button('restore','Restaurer','backup','small',`data-id="${esc(i.id)}"`):''}${i.erase?button('trash-erase','Retirer pour de bon',null,'small',`data-id="${esc(i.id)}" data-name="${esc(trashName(i.original))}"`):''}</td></tr>`);
 const more=list.length>trashShown?`<p class="capacity-note trash-note">Les ${trashPlural(trashShown,'élément')} les plus récents sont affichés, sur ${trashPlural(list.length,'élément')}. ${button('trash-more','Afficher les suivants',null,'small')}</p>`:'';
 const cannot=list.length&&!list.some(i=>i.erase)&&list.some(i=>i.restore)?'<p class="capacity-note trash-note">Dans un espace partagé, retirer pour de bon revient à un administrateur.</p>':'';
 const keep=state?.manage?`<section class="card cardpad" id="trash-keep"><h2>Durée de garde</h2><p class="muted">Sans durée de garde, rien n’est effacé à votre place : la corbeille ne se vide que d’un geste. Avec une durée, tout élément plus ancien est retiré pour de bon, dans tous les espaces, espaces personnels de chacun compris, sans autre confirmation.</p><div class="row"><select id="trash-days" aria-label="Durée de garde de la corbeille">${(Array.isArray(state.choices)?state.choices:[0]).map(c=>`<option value="${Number(c)}" ${Number(c)===days?'selected':''}>${esc(trashKept[c]||c+' jours')}</option>`).join('')}</select>${button('trash-keep','Enregistrer',null,'small')}</div></section>`:'';
 target.innerHTML=heading('Une seconde chance pour vos fichiers.','Les éléments restent récupérables tant qu’ils sont dans cette corbeille.'+kept,button('back-files','Retour aux fichiers','folder'))+`<section class="card">${empties?`<div class="toolbar">${empties}</div>`:''}${list.length?table(['Chemin d’origine','Déplacement',''],rows)+more+cannot:empty('La corbeille est vide.','trash')}</section>`+keep;
}
function trashAsk(count,left){
 const rest=left>0?(count>0?' Les restes d’un effacement interrompu partent aussi.':'Les restes d’un effacement interrompu seront retirés : ils ne sont déjà plus restaurables.'):'';
 if(count<1)return rest||'Rien de listé ne sera effacé.';
 return `${count>1?trashPlural(count,'élément')+' et leurs versions':'Son contenu et ses versions'} seront effacés pour de bon. Cela ne se récupère pas. Ce qui serait jeté entre-temps resterait en corbeille.${rest}`;
}
function trashDone(done){
 const later=Number(done?.later)>0?` ${Number(done.later)>1?trashPlural(done.later,'élément')+' jetés entre-temps sont restés':'1 élément jeté entre-temps est resté'} en corbeille.`:'';
 if(done?.failed)return `Corbeille vidée en partie : ${done.failed>1?trashPlural(done.failed,'élément')+' n’ont pas pu être retirés':'1 élément n’a pas pu être retiré'}. Réessayer.`+later;
 return `Corbeille vidée : ${sizes(done?.bytes)} libérés.`+later;
}
document.addEventListener('click',async e=>{
 const el=e.target.closest?.('[data-action^="trash-"]');if(!el||el.disabled||page!=='trash'||!user||el.dataset.action==='trash-view')return;
 try{
  if(el.dataset.action==='trash-more'){trashShown+=TRASH_STEP;return await renderTrash();}
  if(el.dataset.action==='trash-erase')return confirmAction('Retirer pour de bon ?',`« ${el.dataset.name||''} » et ses versions seront effacés. Cela ne se récupère pas.`,'Retirer pour de bon',async()=>{const done=await api('trash/delete',{id:el.dataset.id,confirm:true});return {message:done?.failed?'Retiré de la corbeille, mais tout n’a pas pu être effacé : vider la corbeille de l’espace pour finir.':'Élément retiré pour de bon.'};});
  if(el.dataset.action==='trash-empty')return confirmAction(`Vider la corbeille de « ${el.dataset.name||''} » ?`,trashAsk(Number(el.dataset.count)||0,Number(el.dataset.left)||0),'Vider la corbeille',async()=>({message:trashDone(await api('trash/empty',{area:el.dataset.area,until:Number(el.dataset.at)||0,confirm:true}))}));
  if(el.dataset.action==='trash-keep'){
   const days=Number($('#trash-days')?.value)||0,save=async()=>{await api('trash/retention',{days,confirm:true});return {message:days?`Durée de garde : ${trashKept[days]}.`:'La corbeille ne se vide plus seule.'};};
   if(!days){const done=await save();toast(done.message);return await renderTrash();}
   return confirmAction('Vider la corbeille après ce délai ?',`Tout élément en corbeille depuis plus de ${trashKept[days]} sera retiré pour de bon, avec ses versions, dans tous les espaces, espaces personnels de chacun compris, même ceux que cette page ne vous montre pas, sans autre confirmation. Ceux qui le sont déjà partiront dans l’heure.`,'Activer',save);
  }
 }catch(error){if(error.name!=='AbortError')toast(error.message,true);}
});
