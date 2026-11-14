'use strict';
// Code QR minimal, sans dépendance : octets, correction M, versions 1 à 10. Sert à montrer la clé de double authentification.
const QR_BLOCKS=[null,[10,[[1,16]]],[16,[[1,28]]],[26,[[1,44]]],[18,[[2,32]]],[24,[[2,43]]],[16,[[4,27]]],[18,[[4,31]]],[22,[[2,38],[2,39]]],[22,[[3,36],[2,37]]],[26,[[4,43],[1,44]]]];
const QR_ALIGN=[null,[],[6,18],[6,22],[6,26],[6,30],[6,34],[6,22,38],[6,24,42],[6,26,46],[6,28,50]];
const QR_EXP=new Uint8Array(512),QR_LOG=new Uint8Array(256);
(()=>{let x=1;for(let i=0;i<255;i++){QR_EXP[i]=x;QR_LOG[x]=i;x<<=1;if(x&256)x^=0x11d;}for(let i=255;i<512;i++)QR_EXP[i]=QR_EXP[i-255];})();
function qrMul(a,b){return a&&b?QR_EXP[QR_LOG[a]+QR_LOG[b]]:0;}
// Octets de correction de Reed-Solomon d’un bloc.
function qrCorrection(data,count){
 let gen=[1];
 for(let i=0;i<count;i++){const next=new Array(gen.length+1).fill(0);for(let j=0;j<gen.length;j++){next[j]^=gen[j];next[j+1]^=qrMul(gen[j],QR_EXP[i]);}gen=next;}
 const rest=new Array(count).fill(0);
 for(const byte of data){const factor=byte^rest.shift();rest.push(0);for(let j=0;j<count;j++)rest[j]^=qrMul(gen[j+1],factor);}
 return rest;
}
function qrCapacity(version){return QR_BLOCKS[version][1].reduce((n,[blocks,size])=>n+blocks*size,0)-(version<10?2:3);}
// Octets du message, mode et longueur compris, entrelacés avec leur correction.
function qrCodewords(bytes,version){
 const [ec,groups]=QR_BLOCKS[version],total=groups.reduce((n,[blocks,size])=>n+blocks*size,0),bits=[];
 const push=(value,length)=>{for(let i=length-1;i>=0;i--)bits.push(value>>i&1);};
 push(4,4);push(bytes.length,version<10?8:16);for(const byte of bytes)push(byte,8);
 push(0,Math.min(4,total*8-bits.length));while(bits.length%8)bits.push(0);
 const data=[];for(let i=0;i<bits.length;i+=8)data.push(bits.slice(i,i+8).reduce((n,bit)=>n<<1|bit,0));
 for(let pad=0;data.length<total;pad^=1)data.push(pad?0x11:0xec);
 const blocks=[];let at=0;
 for(const [count,size] of groups)for(let i=0;i<count;i++){const block=data.slice(at,at+size);at+=size;blocks.push([block,qrCorrection(block,ec)]);}
 const out=[],longest=Math.max(...blocks.map(b=>b[0].length));
 for(let i=0;i<longest;i++)for(const block of blocks)if(i<block[0].length)out.push(block[0][i]);
 for(let i=0;i<ec;i++)for(const block of blocks)out.push(block[1][i]);
 return out;
}
function qrBch(value,length,generator){let rest=value<<length;const top=31-Math.clz32(generator);for(let i=31-Math.clz32(rest);i>=top;i=31-Math.clz32(rest))rest^=generator<<(i-top);return value<<length|rest;}
const QR_MASKS=[(r,c)=>(r+c)%2===0,(r,c)=>r%2===0,(r,c)=>c%3===0,(r,c)=>(r+c)%3===0,(r,c)=>(Math.floor(r/2)+Math.floor(c/3))%2===0,(r,c)=>r*c%2+r*c%3===0,(r,c)=>(r*c%2+r*c%3)%2===0,(r,c)=>((r+c)%2+r*c%3)%2===0];
// Grille sans masque : motifs fixes posés, données placées en zigzag. `fixed` marque ce que le masque ne touche pas.
function qrLayout(version,codewords){
 const size=17+4*version,grid=Array.from({length:size},()=>new Array(size).fill(false)),fixed=Array.from({length:size},()=>new Array(size).fill(false));
 const set=(r,c,dark)=>{if(r>=0&&c>=0&&r<size&&c<size){grid[r][c]=dark;fixed[r][c]=true;}};
 const finder=(row,col)=>{for(let r=-1;r<=7;r++)for(let c=-1;c<=7;c++)set(row+r,col+c,r>=0&&r<=6&&c>=0&&c<=6&&(r===0||r===6||c===0||c===6||(r>=2&&r<=4&&c>=2&&c<=4)));};
 finder(0,0);finder(0,size-7);finder(size-7,0);
 const centres=QR_ALIGN[version];
 for(const r of centres)for(const c of centres){if((r===6&&c===6)||(r===6&&c===size-7)||(r===size-7&&c===6))continue;for(let y=-2;y<=2;y++)for(let x=-2;x<=2;x++)set(r+y,c+x,Math.max(Math.abs(y),Math.abs(x))!==1);}
 for(let i=8;i<size-8;i++){if(!fixed[6][i])set(6,i,i%2===0);if(!fixed[i][6])set(i,6,i%2===0);}
 set(size-8,8,true);
 // Emplacements du format et de la version, réservés avant les données.
 for(let i=0;i<9;i++){if(!fixed[8][i])set(8,i,false);if(!fixed[i][8])set(i,8,false);}
 for(let i=0;i<8;i++){set(8,size-1-i,false);if(!fixed[size-1-i][8])set(size-1-i,8,false);}
 if(version>=7){const info=qrBch(version,12,0x1f25);for(let i=0;i<18;i++){const dark=(info>>i&1)===1,a=Math.floor(i/3),b=size-11+i%3;set(a,b,dark);set(b,a,dark);}}
 let index=0,up=true;
 for(let col=size-1;col>0;col-=2){
  if(col===6)col--;
  for(let step=0;step<size;step++){
   const row=up?size-1-step:step;
   for(const c of [col,col-1]){if(fixed[row][c])continue;grid[row][c]=index<codewords.length*8&&(codewords[index>>3]>>(7-(index&7))&1)===1;index++;}
  }
  up=!up;
 }
 return {size,grid,fixed};
}
function qrApply(layout,mask){
 const {size,grid,fixed}=layout,out=grid.map(row=>row.slice());
 for(let r=0;r<size;r++)for(let c=0;c<size;c++)if(!fixed[r][c]&&QR_MASKS[mask](r,c))out[r][c]=!out[r][c];
 const format=qrBch(mask,10,0x537)^0x5412,bit=i=>(format>>i&1)===1;
 for(let i=0;i<=5;i++)out[8][i]=bit(14-i);
 out[8][7]=bit(8);out[8][8]=bit(7);out[7][8]=bit(6);
 for(let i=9;i<=14;i++)out[14-i][8]=bit(14-i);
 for(let i=0;i<=6;i++)out[size-1-i][8]=bit(14-i);
 for(let i=7;i<=14;i++)out[8][size-15+i]=bit(14-i);
 out[size-8][8]=true;
 return out;
}
function qrPenalty(m){
 const size=m.length;let score=0,dark=0;
 const line=cells=>{let run=1;for(let i=1;i<=size;i++){if(i<size&&cells[i]===cells[i-1])run++;else{if(run>=5)score+=run-2;run=1;}}
  for(let i=0;i+11<=size;i++){const s=cells.slice(i,i+11).map(Number).join('');if(s==='10111010000'||s==='00001011101')score+=40;}};
 for(let r=0;r<size;r++){line(m[r]);line(m.map(row=>row[r]));}
 for(let r=0;r<size-1;r++)for(let c=0;c<size-1;c++)if(m[r][c]===m[r][c+1]&&m[r][c]===m[r+1][c]&&m[r][c]===m[r+1][c+1])score+=3;
 for(const row of m)for(const cell of row)if(cell)dark++;
 return score+Math.floor(Math.abs(dark*20-size*size*10)/(size*size))*10;
}
// Matrice d’un texte : tableau de lignes de booléens (vrai = module sombre), ou null si le texte est trop long.
function qrMatrix(text,forced=null){
 const bytes=[...new TextEncoder().encode(String(text))];
 let version=1;while(version<=10&&qrCapacity(version)<bytes.length)version++;
 if(version>10)return null;
 const layout=qrLayout(version,qrCodewords(bytes,version));
 if(forced!==null)return qrApply(layout,forced);
 let best=null,low=Infinity;
 for(let mask=0;mask<8;mask++){const candidate=qrApply(layout,mask),penalty=qrPenalty(candidate);if(penalty<low){low=penalty;best=candidate;}}
 return best;
}
// Dessin SVG : un seul tracé, marge de quatre modules, sans style en ligne.
function qrSvg(text,label='Code QR'){
 const m=qrMatrix(text);if(!m)return '';
 const size=m.length,quiet=4,full=size+quiet*2;let path='';
 for(let r=0;r<size;r++)for(let c=0;c<size;c++)if(m[r][c])path+=`M${c+quiet} ${r+quiet}h1v1h-1z`;
 return `<svg class="qr" viewBox="0 0 ${full} ${full}" role="img" aria-label="${label}" shape-rendering="crispEdges"><rect class="qr-bg" width="${full}" height="${full}"/><path class="qr-fg" d="${path}"/></svg>`;
}
