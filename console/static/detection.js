// Détection d’une caméra : état appliqué par Frigate et choix des types d’objets suivis.
let detectionData=null;
function detectionValid(d){
 const text=v=>typeof v==='string'&&v.length>0&&v.length<=64;
 if(!d||typeof d.enabled!=='boolean'||!Array.isArray(d.tracked)||!d.tracked.every(text)||!Array.isArray(d.groups))return null;
 if(!d.groups.every(g=>g&&text(g.name)&&Array.isArray(g.labels)&&g.labels.every(text)))return null;
 return d;
}
function detectionCard(data){
 if(!data)return `<section class="card wide detection" id="detection"><div class="cardhead"><h2>Détection</h2><span class="badge dim">Indisponible</span></div><p class="capacity-note dt-note">État de la détection temporairement indisponible. Utilisez Actualiser pour réessayer.</p></section>`;
 const types=data.tracked.length?data.tracked.map(l=>`<span class="dt-type">${esc(pbLabel(l))}</span>`).join(''):'<span class="muted">aucun</span>';
 return `<section class="card wide detection" id="detection"><div class="cardhead"><h2>Détection</h2><span class="badge ${data.enabled?'':'dim'}">${data.enabled?'Active':'En pause'}</span></div><div class="dt-body"><div class="dt-types"><span class="muted">Objets suivis</span>${types}</div>${user.role==='admin'?button('detection-edit','Modifier',null,'small'):''}</div>${data.enabled?'':'<p class="capacity-note dt-note">Détection en pause : la caméra enregistre, mais aucun événement n’est créé dans la relecture.</p>'}</section>`;
}
function detectionModal(){
 const d=detectionData,name=cameraCatalog.find(c=>c.id===selectedCamera)?.name||selectedCamera;
 if(!d)return;
 const group=g=>`<fieldset class="dt-group"><legend>${esc(g.name)}</legend><div class="checks">${g.labels.map(l=>`<label><input type="checkbox" name="track" value="${esc(l)}" ${d.tracked.includes(l)?'checked':''}>${esc(pbLabel(l))}</label>`).join('')}</div></fieldset>`;
 modal('Détection · '+name,`<p class="muted">Appliqué sans redémarrer le service vidéo : l’enregistrement continue. Les nouveaux types donnent des événements dans la relecture à partir de maintenant.</p><div class="checks"><label><input type="checkbox" name="enabled" ${d.enabled?'checked':''}>Détection active</label></div>${d.groups.map(group).join('')}<p class="capacity-note">Seuls les types que le modèle installé sait reconnaître sont proposés. La détection utilise le processeur du NAS.</p>`,'Appliquer',
  async f=>api('camera/detection',{camera:selectedCamera,enabled:f.has('enabled'),track:f.getAll('track')}));
}
document.addEventListener('click',e=>{
 const el=e.target.closest?.('[data-action="detection-edit"]');
 if(el&&user?.role==='admin'&&page==='camera')detectionModal();
});
