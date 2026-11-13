'use strict';
// Bureau personnalisable. Widgets et fond : choisis par compte, enregistrés sur le NAS, donc retrouvés sur tout navigateur.
// Fenêtres ouvertes, position et taille : mémorisées par navigateur, parce qu’elles dépendent de la taille de l’écran.
const DESK_WIDGET_NAMES={storage:'Stockage libre',services:'Services',camera:'Surveillance',activity:'Activité récente',memory:'Mémoire',alerts:'Alertes',tasks:'Tâches en cours'};
const DESK_BACKGROUNDS={nacre:'Nacre',lagon:'Lagon',sable:'Sable',ardoise:'Ardoise'};
const DESK_DEFAULT=['storage','services','camera','activity','memory'],DESK_WINDOWS_KEY='nacre-windows:';
let deskPrefs={widgets:[...DESK_DEFAULT],background:'nacre'},deskPrefsOpen=false,deskRestoring=false,deskPrefsRevision=0;

function deskPrefsValid(value){
 const chosen=Array.isArray(value?.widgets)?value.widgets:DESK_DEFAULT,widgets=[];
 for(const id of chosen)if(typeof id==='string'&&DESK_WIDGET_NAMES[id]&&!widgets.includes(id))widgets.push(id);
 return {widgets,background:DESK_BACKGROUNDS[value?.background]?value.background:'nacre'};
}
function applyDeskPrefs(){
 const root=$('#dk-root'),box=$('#dk-widgets');
 if(root?.classList)for(const id of Object.keys(DESK_BACKGROUNDS))root.classList.toggle('dk-bg-'+id,id===deskPrefs.background);
 if(box&&currentOverview&&typeof deskWidgets==='function')box.innerHTML=deskWidgets(currentOverview);
 drawDeskPrefs();
}
async function loadDeskPrefs(){
 const generation=sessionGeneration,revision=deskPrefsRevision;
 let data;try{data=await api('desk');}catch(error){if(error.name==='AbortError'||error.status===401)throw error;return;}
 // Un choix fait pendant la lecture l’emporte sur la réponse, plus ancienne que lui.
 if(generation!==sessionGeneration||!user||revision!==deskPrefsRevision)return;
 deskPrefs=deskPrefsValid(data);applyDeskPrefs();
}
async function saveDeskPrefs(){
 deskPrefsRevision++;applyDeskPrefs();
 try{await api('desk',{widgets:deskPrefs.widgets,background:deskPrefs.background});}
 catch(error){if(error.name!=='AbortError')toast('Préférences du bureau non enregistrées : '+error.message,true);}
}
function deskPrefsButton(){return '<button type="button" class="dk-bell" id="desk-prefs-open" data-action="desk-prefs-toggle" aria-expanded="false" aria-controls="desk-prefs" aria-label="Personnaliser le bureau" title="Personnaliser le bureau"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/></svg></button>';}
function deskPrefsPanel(){
 const shown=deskPrefs.widgets,hidden=Object.keys(DESK_WIDGET_NAMES).filter(id=>!shown.includes(id));
 const row=(id,index)=>`<div class="dk-pref"><label><input type="checkbox" data-action="desk-widget" data-id="${id}" ${index>=0?'checked':''}>${DESK_WIDGET_NAMES[id]}</label>${index>=0?`<span>${button('desk-widget-move','↑',null,'small',`data-id="${id}" data-step="-1" aria-label="Monter ${DESK_WIDGET_NAMES[id]}" ${index===0?'disabled':''}`)}${button('desk-widget-move','↓',null,'small',`data-id="${id}" data-step="1" aria-label="Descendre ${DESK_WIDGET_NAMES[id]}" ${index===shown.length-1?'disabled':''}`)}</span>`:''}</div>`;
 return `<h3>Widgets du bureau</h3>${shown.map(row).join('')}${hidden.map(id=>row(id,-1)).join('')}<h3>Fond</h3><div class="dk-swatches" role="group" aria-label="Fond du bureau">${Object.entries(DESK_BACKGROUNDS).map(([id,name])=>`<button type="button" class="dk-swatch" data-action="desk-background" data-id="${id}" aria-pressed="${id===deskPrefs.background}"><i class="dk-bg-${id}"></i>${name}</button>`).join('')}</div><div class="dk-notefoot">${button('desk-prefs-reset','Rétablir l’affichage d’origine',null,'small')}</div><p class="dk-notehint">Widgets et fond sont enregistrés pour votre compte. Les fenêtres ouvertes, leur place et leur taille sont mémorisées sur ce navigateur.</p>`;
}
function drawDeskPrefs(){
 const panel=$('#desk-prefs'),opener=$('#desk-prefs-open');if(!panel)return;
 panel.hidden=!deskPrefsOpen;opener?.setAttribute('aria-expanded',String(deskPrefsOpen));
 if(deskPrefsOpen)panel.innerHTML=deskPrefsPanel();
}
function closeDeskPrefs(){if(!deskPrefsOpen)return;deskPrefsOpen=false;drawDeskPrefs();}

// Mémoire des fenêtres : écrite à chaque changement une fois qu’une fenêtre a été ouverte, relue à l’ouverture du bureau.
function deskRemember(){
 if(deskRestoring||!deskTouched||!user)return;
 const wins=[...deskWins].sort((a,b)=>a.z-b.z).map(w=>({app:w.app,page:w.page,view:w.view||'',left:w.left,top:w.top,width:w.width,height:w.height,max:!!w.max,min:!!w.min}));
 try{localStorage.setItem(DESK_WINDOWS_KEY+user.name,JSON.stringify({wins}));}catch{}
}
function deskRestore(){
 if(!user||!$('#dk-wins'))return 0;
 let saved;try{saved=JSON.parse(localStorage.getItem(DESK_WINDOWS_KEY+user.name)||'null');}catch{saved=null;}
 const list=Array.isArray(saved?.wins)?saved.wins.slice(0,DESK_APPS.length):[],number=(value,low,high,fallback)=>Number.isFinite(value)?Math.max(low,Math.min(high,Math.round(value))):fallback;
 const stage=$('#dk-stage')?.getBoundingClientRect?.(),wide=stage?.width>0?stage.width:4000,high=stage?.height>0?stage.height:4000;
 deskRestoring=true;
 try{
  for(const item of list){
   // Une page devenue inaccessible à ce compte, ou inconnue, est simplement oubliée.
   if(!item||typeof item.page!=='string'||deskApp(item.page)?.id!==item.app||deskWindow(item.app))continue;
   if(!deskOpenPage(item.page,typeof item.view==='string'&&item.view?{view:item.view}:{}))continue;
   const win=deskWindow(item.app);
   win.width=item.width?number(item.width,DESK_MIN[0],wide,0):0;win.height=item.height?number(item.height,DESK_MIN[1],high,0):0;
   win.left=number(item.left,120-(win.width||DESK_MIN[0]),wide-120,win.left);win.top=number(item.top,0,Math.max(0,high-60),win.top);
   win.max=item.max===true;win.min=item.min===true;
  }
 }finally{deskRestoring=false;}
 return deskWins.length;
}

document.addEventListener('click',async e=>{
 const el=e.target.closest?.('[data-action]'),action=el?.dataset.action||'';
 if(action==='desk-prefs-toggle'){deskPrefsOpen=!deskPrefsOpen;drawDeskPrefs();return;}
 if(!action.startsWith('desk-widget')&&action!=='desk-background'&&action!=='desk-prefs-reset'){if(deskPrefsOpen&&!e.target.closest?.('#desk-prefs'))closeDeskPrefs();return;}
 if(!deskPrefsOpen||!user)return;
 const id=el.dataset.id,list=deskPrefs.widgets;
 if(action==='desk-widget'){if(!DESK_WIDGET_NAMES[id])return;deskPrefs.widgets=list.includes(id)?list.filter(x=>x!==id):[...list,id];}
 else if(action==='desk-widget-move'){const from=list.indexOf(id),to=from+Number(el.dataset.step);if(from<0||!(to>=0&&to<list.length))return;list.splice(to,0,list.splice(from,1)[0]);}
 else if(action==='desk-background'){if(!DESK_BACKGROUNDS[id]||id===deskPrefs.background)return;deskPrefs.background=id;}
 else deskPrefs={widgets:[...DESK_DEFAULT],background:'nacre'};
 await saveDeskPrefs();
});
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeDeskPrefs();});
