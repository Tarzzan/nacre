'use strict';
// Recherche d’événements sur plusieurs jours : période, tranche horaire, type d’objet, résultats par pages.
// Un résultat ouvre son jour dans la carte Relecture, qui reste seule à lire la vidéo.
let searchData=null,searchRequest=0;
function searchValid(d){
 const text=v=>typeof v==='string'&&v.length>0&&v.length<=80,day=v=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(v);
 if(!d||!text(d.camera)||!day(d.from)||!day(d.to)||typeof d.label!=='string'||!Array.isArray(d.events))return null;
 if(!d.events.every(e=>e&&text(e.id)&&text(e.label)&&day(e.day)&&Number.isFinite(e.start)&&Number.isFinite(e.end)))return null;
 if(d.next!==null&&!Number.isFinite(d.next))return null;
 if(d.hours!=null&&!(searchClock(d.hours.from)&&searchClock(d.hours.to)))return null;
 const f=d.facets;
 if(f&&!(Number.isFinite(f.total)&&Number.isFinite(f.matched)&&Array.isArray(f.types)&&f.types.every(t=>t&&text(t.label)&&Number.isFinite(t.count))&&Array.isArray(f.days)&&f.days.every(x=>x&&day(x.day)&&Number.isFinite(x.count))))return null;
 return d;
}
function searchClock(v){return typeof v==='string'&&/^([01]\d|2[0-3]):[0-5]\d$/.test(v);}
function searchToday(){return playbackData?.today||new Date().toLocaleDateString('en-CA',{timeZone:pbZone()});}
function searchShift(day,n){const [y,m,d]=day.split('-').map(Number);return new Date(Date.UTC(y,m-1,d+n)).toISOString().slice(0,10);}
function searchPlural(n){return `${n} événement${n>1?'s':''}`;}
function searchPeriod(d){return (d.from===d.to?`le ${pbDay(d.from)}`:`du ${pbDay(d.from)} au ${pbDay(d.to)}`)+(d.hours?`, entre ${d.hours.from} et ${d.hours.to}`:'');}
function searchSummary(d){
 const f=d.facets,more=f.more?' parmi les plus récents':'';
 return (d.label?`${f.matched} sur ${searchPlural(f.total)} · ${pbLabel(d.label)}`:searchPlural(f.total))+more+', '+searchPeriod(d);
}
// Vignettes d’une page, avec un titre à chaque changement de jour.
function searchItems(d,events,previous=''){
 const counts=new Map(d.facets.days.map(x=>[x.day,x.count]));
 return events.map(e=>{
  const head=e.day===previous?'':`<h4 class="sr-day">${esc(pbDay(e.day))}${counts.has(e.day)?` · ${searchPlural(counts.get(e.day))}`:''}</h4>`;previous=e.day;
  const what=pbLabel(e.label)+(e.sub_label?' · '+e.sub_label:''),meta=[pbClock(e.start),e.ongoing?'en cours':pbDuration(e.end-e.start),e.score?e.score+' %':''].filter(Boolean).join(' · ');
  return head+`<button type="button" class="pb-event" data-action="search-open" data-day="${esc(e.day)}" data-start="${e.start}" data-end="${e.end}"${e.recorded===false?' disabled':''}><img class="pb-thumb" src="/api/camera/event-thumbnail?camera=${encodeURIComponent(d.camera)}&id=${encodeURIComponent(e.id)}" alt="" loading="lazy" width="175" height="175"><strong>${esc(what)}</strong><span>${esc(meta)}</span>${e.recorded===false?'<em>Vidéo non conservée</em>':''}</button>`;
 }).join('');
}
function searchResults(d){
 if(!d)return '<p class="capacity-note">Choisissez une période pour retrouver un passage sans parcourir les jours un à un.</p>';
 const f=d.facets,chip=(label,text,n)=>`<button type="button" class="pb-chip" data-action="search-filter" data-label="${esc(label)}" aria-pressed="${label===d.label}">${esc(text)}<b>${n}</b></button>`;
 return `<p class="pb-summary" id="search-summary" role="status">${esc(searchSummary(d))}</p>`+
 (f.types.length>1?`<div class="pb-filter" role="group" aria-label="Filtrer les résultats par type d’objet">${chip('','Tous',f.total)}${f.types.map(t=>chip(t.label,pbLabel(t.label),t.count)).join('')}</div>`:'')+
 (d.events.length?`<div class="pb-events sr-events" id="search-events">${searchItems(d,d.events)}</div>`:empty(d.hours?'Aucun événement dans cette tranche horaire sur cette période.':'Aucun événement sur cette période.','camera'))+
 `<div class="sr-more" id="search-more">${d.next===null?'':button('search-more','Afficher la suite',null,'small')}</div>`+
 (f.more?'<p class="capacity-note">Période très chargée : les compteurs portent sur les événements les plus récents. La suite reste accessible.</p>':'')+
 '<p class="capacity-note">Un résultat ouvre son jour dans la relecture, cinq secondes avant l’événement. Les événements peuvent être gardés plus longtemps que la vidéo.</p>';
}
function searchCard(){
 if(searchData&&searchData.camera!==selectedCamera)searchData=null;
 const d=searchData,today=searchToday(),to=d?.to||today,from=d?.from||searchShift(to,-6);
 return `<section class="card wide playback" id="search"><div class="cardhead"><h2>Recherche d’événements</h2></div><div class="pb-body">`+
 `<div class="pb-go sr-form"><label for="search-from">Du</label><input id="search-from" type="date" value="${esc(from)}" max="${esc(today)}"><label for="search-to">au</label><input id="search-to" type="date" value="${esc(to)}" max="${esc(today)}"><label for="search-after">entre</label><input id="search-after" type="time" value="${esc(d?.hours?.from||'')}" aria-describedby="search-hours"><label for="search-before">et</label><input id="search-before" type="time" value="${esc(d?.hours?.to||'')}" aria-describedby="search-hours">${button('search-run','Rechercher',null,'primary small')}</div>`+
 `<p class="capacity-note" id="search-hours">Heures facultatives : laissez-les vides pour toute la journée. De 22:00 à 06:00, la recherche ne garde que la nuit.</p>`+
 `<div id="search-results">${searchResults(d)}</div></div></section>`;
}
// Nouvelle recherche, changement de type ou page suivante (before) : même garde contre les réponses tardives.
async function searchLoad(from,to,label,before=null,hours=null){
 const generation=sessionGeneration,request=++searchRequest,camera=selectedCamera;
 const current=()=>generation===sessionGeneration&&page==='camera'&&cameraDetail&&selectedCamera===camera&&request===searchRequest;
 $('#search')?.setAttribute('aria-busy','true');
 let data;
 try{data=searchValid(await api('camera/search'+cameraQuery()+'&from='+encodeURIComponent(from)+'&to='+encodeURIComponent(to)+(label?'&label='+encodeURIComponent(label):'')+(hours?'&time_from='+encodeURIComponent(hours.from)+'&time_to='+encodeURIComponent(hours.to):'')+(before===null?'':'&before='+before)));}
 finally{if(current())$('#search')?.removeAttribute('aria-busy');}
 if(!current())return;
 if(!data||(before===null&&!data.facets))throw new Error('Réponse de recherche illisible. Réessayez.');
 if(before===null){searchData=data;const box=$('#search-results');if(box)box.innerHTML=searchResults(data);return;}
 const d=searchData;if(!d)return;
 const last=d.events[d.events.length-1]?.day||'';
 d.events.push(...data.events);d.next=data.next;
 // Ajout en fin de liste : les vignettes déjà chargées ne sont pas redemandées.
 $('#search-events')?.insertAdjacentHTML?.('beforeend',searchItems(d,data.events,last));
 const more=$('#search-more');if(more&&d.next===null)more.innerHTML='';
}
document.addEventListener('click',async e=>{
 const el=e.target.closest?.('[data-action^="search-"]');if(!el||el.disabled||page!=='camera')return;
 const d=searchData;
 try{
  switch(el.dataset.action){
   case 'search-run':{
    const from=$('#search-from')?.value,to=$('#search-to')?.value;
    if(!from||!to)return toast('Indiquez le début et la fin de la période.',true);
    if(from>to)return toast('Le début de la période suit sa fin.',true);
    const after=$('#search-after')?.value||'',until=$('#search-before')?.value||'';
    if(!after!==!until)return toast('Indiquez le début et la fin de la tranche horaire, ou laissez les deux vides.',true);
    if(after&&(!searchClock(after)||!searchClock(until)))return toast('Tranche horaire illisible. Format attendu : 22:00.',true);
    if(after&&after===until)return toast('Le début et la fin de la tranche horaire sont identiques.',true);
    const hours=after?{from:after,to:until}:null,same=d&&d.from===from&&d.to===to&&(d.hours?.from||'')===after&&(d.hours?.to||'')===until;
    return await searchLoad(from,to,same?d.label:'',null,hours);
   }
   case 'search-filter':if(d)await searchLoad(d.from,d.to,el.dataset.label||'',null,d.hours||null);return;
   case 'search-more':if(d&&d.next!==null)await searchLoad(d.from,d.to,d.label,d.next,d.hours||null);return;
   case 'search-open':return await playbackOpen(el.dataset.day,Number(el.dataset.start),Number(el.dataset.end));
  }
 }catch(error){if(error.name!=='AbortError')toast(error.message,true);}
});
