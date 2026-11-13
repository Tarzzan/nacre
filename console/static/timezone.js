'use strict';
// Fuseau horaire de la console : proposition tant qu’il n’a jamais été choisi, et aide à la saisie.
let zoneBusy=false,zoneError='';
const zoneRefused=new Set();
const ZONE_UTC=/^(Etc\/)?(UTC|UCT|GMT|GMT[+-]?0|Universal|Zulu|Greenwich)$/;

function zoneTime(zone,now=Date.now()){return new Date(now).toLocaleTimeString('fr-FR',{timeZone:zone,hour:'2-digit',minute:'2-digit'});}
function zoneOffset(zone,now=Date.now()){
 try{return new Intl.DateTimeFormat('fr-FR',{timeZone:zone,timeZoneName:'shortOffset'}).formatToParts(new Date(now)).find(p=>p.type==='timeZoneName')?.value||'';}catch{return '';}
}
function zonePromptVisible(){return !!(user&&user.role==='admin'&&user.timezone_unset&&!user.setup_required);}
// Le fuseau de ce navigateur, s’il apporte autre chose que l’UTC déjà en place et que le serveur ne l’a pas refusé.
function zoneSuggestion(){const zone=browserZone();return zoneKnown(zone)&&!ZONE_UTC.test(zone)&&!zoneRefused.has(zone)?zone:null;}
function zonePrompt(now=Date.now()){
 if(!zonePromptVisible())return '';
 const zone=zoneSuggestion();
 const text=zone?`Nacre affiche les heures en UTC : pour lui, il est ${zoneTime('UTC',now)}. D’après ce navigateur, il est ${zoneTime(zone,now)} chez vous (${esc(zone)}).`:`Nacre affiche les heures en UTC (${zoneTime('UTC',now)}), faute d’avoir reçu un fuseau.`;
 return `<section class="notice zone-prompt" aria-label="Fuseau horaire de la console"><div><strong>Choisissez le fuseau horaire.</strong> ${text}${zoneError?`<p class="error" role="alert">${esc(zoneError)}</p>`:''}</div><div class="row">${zone?button('zone-use',`Utiliser ${esc(zone)}`,null,'primary small',`data-zone="${esc(zone)}"`):''}${button('zone-choose',zone?'Choisir un autre fuseau':'Choisir un fuseau',null,'small')}${button('zone-keep','Garder UTC',null,'small')}</div></section>`;
}
function drawZonePrompt(){const box=$('#zone-prompt');if(box)box.innerHTML=zonePrompt();}

async function saveZone(zone){
 if(zoneBusy||!zonePromptVisible())return;
 const generation=sessionGeneration;zoneBusy=true;zoneError='';
 try{
  // La révision 0 est celle d’une console jamais réglée : un réglage fait ailleurs entre-temps est refusé, pas écrasé.
  const saved=await api('control-panel/configure',{name:user.nas_name||'Nacre',timezone:zone,revision:0});
  user.nas_name=saved.name;user.timezone=saved.timezone;user.timezone_unset=false;
  toast(ZONE_UTC.test(saved.timezone)?'Les heures restent affichées en UTC.':`Heures affichées dans le fuseau ${saved.timezone}.`);
 }catch(error){
  if(generation!==sessionGeneration||error.name==='AbortError'||!user)return;
  if(error.status===409){
   try{const me=await api('me');user.nas_name=me.nas_name;user.timezone=me.timezone;user.timezone_unset=!!me.timezone_unset;toast('Le fuseau vient d’être réglé depuis une autre session.');}
   catch(later){if(generation!==sessionGeneration||later.name==='AbortError'||!user)return;zoneError=later.message;}
  }else if(error.status===400&&zone!=='UTC'){zoneRefused.add(zone);zoneError=`Ce serveur ne connaît pas le fuseau ${zone}. Choisissez-en un dans la liste.`;}
  else zoneError=error.message;
 }finally{zoneBusy=false;}
 if(generation!==sessionGeneration||!user)return;
 const clock=$('#topclock');if(clock)clock.textContent=date(Date.now()/1000);
 drawZonePrompt();
 // Les dates déjà affichées sont redessinées, et le panneau reprend la révision enregistrée.
 if(!user.timezone_unset)await go(page);
}

// Champ de fuseau avec la liste du serveur réduite aux noms que ce navigateur sait afficher, et l’heure correspondante.
function zoneField(label,value,zones,note=''){
 const known=(Array.isArray(zones)?zones:[]).filter(z=>typeof z==='string'&&zoneKnown(z));
 return `<div class="field"><label for="field-timezone">${label}</label><input id="field-timezone" name="timezone" type="text" value="${esc(value)}" list="zone-list" autocomplete="off" maxlength="100" required><datalist id="zone-list">${known.map(z=>`<option value="${esc(z)}"></option>`).join('')}</datalist><small id="zone-preview" aria-live="polite">${esc(zonePreview(value))}</small>${note?`<small>${note}</small>`:''}</div>`;
}
function zonePreview(value,now=Date.now()){
 const zone=String(value||'').trim();
 if(!zone)return '';
 return zoneKnown(zone)?`Dans ce fuseau, il est ${zoneTime(zone,now)} (${zoneOffset(zone,now)||zone}).`:'Choisissez un nom de la liste, par exemple America/Cayenne ou Europe/Paris.';
}

document.addEventListener('input',e=>{
 if(e.target?.id!=='field-timezone'||!e.target.closest?.('#control-preferences,#setup-finish'))return;
 const preview=$('#zone-preview');if(preview)preview.textContent=zonePreview(e.target.value);
});
document.addEventListener('click',async e=>{
 const el=e.target.closest?.('[data-action]');if(!el?.dataset.action?.startsWith('zone-'))return;
 try{
  if(el.dataset.action==='zone-use'&&el.dataset.zone===zoneSuggestion())return await saveZone(el.dataset.zone);
  if(el.dataset.action==='zone-keep')return await saveZone('UTC');
  if(el.dataset.action==='zone-choose'){await go('settings');const input=$('#field-timezone');if(input&&page==='settings'){input.focus();input.select?.();}}
 }catch(error){if(error.name!=='AbortError')toast(error.message,true);}
});
