'use strict';
// Relecture par jour : frise des plages conservées, moments détectés et extraits enchaînés.
// La frise est un SVG : la politique de sécurité de la console interdit les styles en ligne.
let playbackDay='',playbackData=null,playbackRequest=0,playbackClip=null;
const PB_WIDTH=1440,PB_ROWS=300;
function pbZone(){return playbackData?.timezone||user?.timezone||'UTC';}
function pbClock(t){return new Date(t*1000).toLocaleTimeString('fr-FR',{timeZone:pbZone(),hour:'2-digit',minute:'2-digit',second:'2-digit'});}
function pbDay(day,long=true){
 const [y,m,d]=day.split('-').map(Number);
 return new Date(Date.UTC(y,m-1,d,12)).toLocaleDateString('fr-FR',{timeZone:'UTC',weekday:long?'long':'short',day:'numeric',month:long?'long':'short'});
}
function pbDuration(s){
 s=Math.max(0,Math.round(s));const h=Math.floor(s/3600),m=Math.floor(s%3600/60),r=s%60;
 return h?`${h} h ${String(m).padStart(2,'0')} min`:m?`${m} min${r?' '+String(r).padStart(2,'0')+' s':''}`:`${r} s`;
}
function pbX(data,t){return Math.max(0,Math.min(PB_WIDTH,(t-data.start)/(data.end-data.start)*PB_WIDTH));}
// Instant demandé → extrait lisible. Dans un trou, la lecture part du début de la plage suivante.
function playbackLocate(data,t){
 for(const [a,b] of data.intervals){
  if(t<b-1){const start=Math.max(a,t);return {start,end:Math.min(start+data.clip_max,b),moved:start-t>1};}
 }
 return null;
}
function playbackBefore(data,t){
 for(const [a,b] of [...data.intervals].reverse()){
  if(a<t-1){const end=Math.min(b,t);return {start:Math.max(a,end-data.clip_max),end,moved:false};}
 }
 return null;
}
// Heure saisie → instant, à partir des heures civiles fournies par le NAS (changements d’heure compris).
function playbackInstant(data,value){
 const m=/^(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(value||'');if(!m)return null;
 const wanted=Number(m[1])*3600+Number(m[2])*60+Number(m[3]||0);
 for(const h of data.hours){
  const [hh,mm]=h.label.split(':').map(Number),base=hh*3600+mm*60;
  if(wanted>=base&&wanted<base+(h.end-h.start))return h.start+wanted-base;
 }
 return null;
}
function playbackCard(data){
 if(!data)return `<section class="card wide playback" id="playback"><div class="cardhead"><h2>Relecture</h2></div>${empty('Enregistrements temporairement indisponibles. Utilisez Actualiser pour réessayer.','camera')}</section>`;
 const days=data.days.some(d=>d.day===data.day)?data.days:[{day:data.day,recorded:0},...data.days].sort((a,b)=>a.day<b.day?1:-1);
 const index=days.findIndex(d=>d.day===data.day),older=days[index+1],newer=days[index-1];
 const rect=(cls,[a,b])=>{const x=pbX(data,a),w=Math.max(pbX(data,b)-x,2);return `<rect class="${cls}" x="${x.toFixed(1)}" y="0" width="${w.toFixed(1)}" height="34"/>`;};
 const gaps=data.intervals.slice(1).map((v,i)=>[data.intervals[i][1],v[0]]);
 const detected=data.detections.length>0,moments=detected?data.detections:data.intervals.length>1?data.intervals:[];
 const count=data.hours.length,ticks=data.hours.map((h,i)=>i%3?'':`<span class="pb-s${Math.min(3,count-i)}${i%6?' pb-alt':''}">${esc(h.label)}</span>`).join('');
 const first=data.intervals[0]?.[0];
 return `<section class="card wide playback" id="playback"><div class="cardhead"><h2>Relecture</h2><span class="muted">Heures du NAS · ${esc(data.timezone)}</span></div><div class="pb-body">`+
 `<div class="pb-days">${button('playback-day','','left','small',`data-day="${esc(older?.day||'')}" aria-label="Jour enregistré précédent" ${older?'':'disabled'}`)}<select id="playback-day" aria-label="Jour à relire">${days.map(d=>`<option value="${esc(d.day)}" ${d.day===data.day?'selected':''}>${esc(pbDay(d.day))}${d.day===data.today?' (aujourd’hui)':''} · ${d.recorded?pbDuration(d.recorded):'aucun enregistrement'}</option>`).join('')}</select>${button('playback-day','','right','small',`data-day="${esc(newer?.day||'')}" aria-label="Jour enregistré suivant" ${newer?'':'disabled'}`)}</div>`+
 (!data.intervals.length?empty(`Aucun enregistrement conservé pour le ${pbDay(data.day)}.`,'camera'):
 `<p class="pb-summary"><strong>${pbDuration(data.recorded)}</strong> enregistrées en ${data.intervals.length} plage${data.intervals.length>1?'s':''}${detected?` · présence détectée pendant <strong>${pbDuration(data.detected)}</strong>`:''}</p>`+
 `<svg class="pb-track" data-action="playback-seek" viewBox="0 0 ${PB_WIDTH} 34" preserveAspectRatio="none" role="img" aria-label="Frise du ${esc(pbDay(data.day))} : ${pbDuration(data.recorded)} enregistrées, ${data.detections.length} moment(s) avec présence détectée. Cliquer pour lire à cet instant."><rect class="pb-none" x="0" y="0" width="${PB_WIDTH}" height="34"/>${data.now<data.end?rect('pb-future',[data.now,data.end]):''}${data.intervals.map(v=>rect('pb-rec',v)).join('')}${data.detections.map(v=>rect('pb-det',v)).join('')}<rect class="pb-cursor" id="playback-cursor" x="0" y="0" width="4" height="34" visibility="hidden"/></svg>`+
 `<div class="pb-ticks pb-h${count}" aria-hidden="true">${ticks}</div>`+
 `<div class="pb-legend"><span><i class="pb-rec"></i>Enregistré</span><span><i class="pb-det"></i>Présence détectée</span><span><i class="pb-none"></i>Rien de conservé</span>${data.now<data.end?'<span><i class="pb-future"></i>À venir</span>':''}</div>`+
 (gaps.length?`<p class="capacity-note">Sans enregistrement : ${gaps.slice(0,3).map(([a,b])=>`${pbClock(a)} → ${pbClock(b)}`).join(', ')}${gaps.length>3?` et ${gaps.length-3} autre${gaps.length>4?'s':''} période${gaps.length>4?'s':''}`:''}.</p>`:'')+
 `<div class="pb-go"><label for="playback-time">Lire à partir de</label><input id="playback-time" type="time" step="1" value="${esc(pbClock(first))}">${button('playback-go','Lire',null,'primary small')}</div>`+
 `<div id="playback-player"></div>`+
 (moments.length?`<h3>${detected?'Moments avec présence détectée':'Plages enregistrées'}</h3><div class="pb-moments">${table(['Début','Fin','Durée',''],moments.slice(0,PB_ROWS).map(([a,b])=>`<tr><td>${pbClock(a)}</td><td>${pbClock(b)}</td><td>${pbDuration(b-a)}</td><td>${button('playback-moment','Lire',null,'small',`data-start="${Math.max(data.start,a-(detected?5:0))}"`)}</td></tr>`))}</div>${moments.length>PB_ROWS?`<p class="capacity-note">${PB_ROWS} premiers moments affichés sur ${moments.length}. Utilisez la frise ou l’heure pour atteindre les suivants.</p>`:''}`:''))+
 `<p class="capacity-note">Les extraits durent 5 minutes au plus et s’enchaînent jusqu’à la fin de la plage. La présence détectée provient du suivi d’objets de Frigate ; elle n’est ni exhaustive ni une alarme. Au-delà de la conservation continue, Frigate peut ne garder que certains passages.</p></div></section>`;
}
function pbCursor(t){
 const cursor=$('#playback-cursor');if(!cursor||!playbackData)return;
 if(t===null){cursor.setAttribute('visibility','hidden');return;}
 cursor.setAttribute('x',Math.min(PB_WIDTH-4,pbX(playbackData,t)).toFixed(1));cursor.setAttribute('visibility','visible');
}
function pbStatus(text){const panel=$('#playback-player');if(panel)panel.innerHTML=`<p class="pb-status" role="status">${esc(text)}</p>`;}
function playbackShow(clip,note=''){
 const data=playbackData,panel=$('#playback-player');if(!data||!panel)return;
 playbackClip=clip;
 const src=`/api/camera/clip?camera=${encodeURIComponent(data.camera)}&start=${clip.start}&end=${clip.end}`;
 panel.innerHTML=`<p class="pb-status" role="status">${esc(note)}Lecture du ${esc(pbDay(data.day))}, ${pbClock(clip.start)} → ${pbClock(clip.end)}.</p><video class="recordvideo" id="playback-video" controls autoplay playsinline src="${src}"></video><div class="row pb-actions">${button('playback-step','5 min avant','left','small','data-direction="back"')}${button('playback-step','Suite','right','small','data-direction="next"')}<a class="pb-download" href="${src}&download=1" download>${icon('download')}<span>Télécharger cet extrait</span></a></div>`;
 pbCursor(clip.start);
 const input=$('#playback-time');if(input)input.value=pbClock(clip.start);
}
function playbackPlay(t,auto=false){
 if(!playbackData)return;
 const clip=playbackLocate(playbackData,t);
 if(!clip){playbackClip=null;pbCursor(null);return pbStatus(auto?'Fin des enregistrements de cette journée.':`Aucun enregistrement à partir de ${pbClock(t)} ce jour-là.`);}
 playbackShow(clip,clip.moved&&!auto?`Rien de conservé à ${pbClock(t)} : reprise à la plage suivante. `:'');
}
async function playbackLoad(day){
 const generation=sessionGeneration,request=++playbackRequest,camera=selectedCamera;
 const current=()=>generation===sessionGeneration&&page==='camera'&&cameraDetail&&selectedCamera===camera&&request===playbackRequest;
 $('#playback')?.setAttribute('aria-busy','true');
 let data;
 try{data=await api('camera/timeline'+cameraQuery()+'&day='+encodeURIComponent(day));}
 catch(error){if(current())$('#playback')?.removeAttribute('aria-busy');throw error;}
 if(!current())return;
 playbackDay=day;playbackData=data;playbackClip=null;
 const card=$('#playback');if(card)card.outerHTML=playbackCard(data);
}
document.addEventListener('change',e=>{
 if(e.target.id==='playback-day')playbackLoad(e.target.value).catch(error=>{if(error.name!=='AbortError')toast(error.message,true);});
});
document.addEventListener('click',async e=>{
 const el=e.target.closest?.('[data-action^="playback-"]');if(!el||!playbackData||el.disabled)return;
 const data=playbackData;
 try{
  switch(el.dataset.action){
   case 'playback-day':if(el.dataset.day)await playbackLoad(el.dataset.day);return;
   case 'playback-seek':{const box=el.getBoundingClientRect();if(!box.width)return;return playbackPlay(data.start+Math.max(0,Math.min(1,(e.clientX-box.left)/box.width))*(data.end-data.start));}
   case 'playback-go':{const t=playbackInstant(data,$('#playback-time')?.value);if(t===null)return toast('Cette heure n’existe pas ce jour-là. Vérifiez la saisie ou le changement d’heure.',true);return playbackPlay(t);}
   case 'playback-moment':return playbackPlay(Number(el.dataset.start));
   case 'playback-step':{
    if(!playbackClip)return;
    if(el.dataset.direction==='next')return playbackPlay(playbackClip.end,true);
    const clip=playbackBefore(data,playbackClip.start);
    return clip?playbackShow(clip):toast('Aucun enregistrement plus tôt ce jour-là.');
   }
  }
 }catch(error){if(error.name!=='AbortError')toast(error.message,true);}
});
// Les événements des médias ne remontent pas : écoute en phase de capture.
document.addEventListener('ended',e=>{if(e.target.id==='playback-video'&&playbackClip)playbackPlay(playbackClip.end,true);},true);
document.addEventListener('timeupdate',e=>{if(e.target.id==='playback-video'&&playbackClip)pbCursor(Math.min(playbackClip.end,playbackClip.start+e.target.currentTime));},true);
document.addEventListener('error',e=>{if(e.target.id==='playback-video'){playbackClip=null;pbCursor(null);pbStatus('Extrait indisponible : le service vidéo n’a pas fourni cette plage. Utilisez Actualiser, puis réessayez.');}},true);
