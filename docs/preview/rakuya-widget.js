let RAKUYA7=null;
function rkEsc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function rkPrice(x){const n=Number(x?.price);return Number.isFinite(n)?n.toLocaleString('zh-TW')+'萬':'價格未取得';}
function rkArea(x){const n=Number(x?.areaBuilding);return Number.isFinite(n)?n+'坪':'坪數未取得';}
function rkChangeBadge(x){
  const c=x?.priceChange;
  if(!c)return '';
  return '<span class="rk-pill change">'+(Number(c.to)<Number(c.from)?'降價':'調價')+' '+rkEsc(c.from)+'→'+rkEsc(c.to)+'萬</span>';
}
function rkItemHtml(x,removed=false,road=''){
  const badges=[
    road?'<span class="rk-pill road">'+rkEsc(road)+'</span>':'',
    !removed&&x.newAt?'<span class="rk-pill new">本次新進</span>':'',
    !removed?rkChangeBadge(x):'',
    removed?'<span class="rk-pill removed">本次下架</span>':''
  ].join('');
  return '<article class="rk-item">'+
    '<a class="rk-title" href="'+rkEsc(x.url||'#')+'" target="_blank" rel="noopener noreferrer">'+rkEsc(x.name||'樂屋案件')+'</a>'+
    '<div class="rk-row">'+badges+
      '<span>'+rkEsc(rkPrice(x))+'</span>'+
      '<span>'+rkEsc(rkArea(x))+'</span>'+
      '<span>'+rkEsc(x.layout||'格局未取得')+'</span>'+
      '<span>'+rkEsc(x.floor||'樓層未取得')+'</span>'+
      '<span>'+rkEsc(x.age||'屋齡未取得')+'</span>'+
    '</div>'+
    '<div class="rk-row">'+
      (x.mainArea!=null?'<span>主建 '+rkEsc(x.mainArea)+'坪</span>':'')+
      (x.unitPrice!=null?'<span>'+rkEsc(x.unitPrice)+'萬/坪</span>':'')+
      (x.sourceUpdateText?'<span>來源：'+rkEsc(x.sourceUpdateText)+'</span>':'')+
      (removed&&x.removedAt?'<span>下架：'+rkEsc(fmt(x.removedAt))+'</span>':'')+
    '</div>'+
  '</article>';
}
function rkRowsForState(){
  if(!RAKUYA7)return [];
  const state=document.getElementById('rkState')?.value||'all';
  let rows=state==='removed'?(RAKUYA7.recentRemoved||[]):(RAKUYA7.listings||[]);
  if(state==='new')rows=rows.filter(x=>!!x.newAt);
  if(state==='price')rows=rows.filter(x=>!!x.priceChange);
  const q=(document.getElementById('rkSearch')?.value||'').trim().toLowerCase();
  if(q)rows=rows.filter(x=>[x.name,x.road,...(x.roads||[])].some(v=>String(v||'').toLowerCase().includes(q)));
  return rows;
}
function renderRakuya7(){
  if(!RAKUYA7)return;
  const panel=document.getElementById('rakuyaPanel');if(!panel)return;
  panel.hidden=false;
  const ch=RAKUYA7.changes||{};
  document.getElementById('rkRoadCount').textContent=(RAKUYA7.roads||[]).length+' 條';
  document.getElementById('rkListingCount').textContent=(RAKUYA7.placementCount??0)+' 筆';
  document.getElementById('rkNewCount').textContent=(ch.newCount??0)+' 筆';
  document.getElementById('rkChangeCount').textContent=(ch.currentChangeCount??0)+' 筆';
  const overlap=Number(RAKUYA7.overlapCount||0);
  const baseline=RAKUYA7.baseline?'｜本次為初始基準，不把既有案件列為新案':'';
  const overlapText=overlap?'｜跨路段重複 '+overlap+' 筆':'';
  document.getElementById('rkUpdated').textContent='樂屋最近更新：'+fmt(RAKUYA7.updatedAt)+'｜七路段刊登 '+(RAKUYA7.placementCount??0)+' 筆'+overlapText+baseline;
  document.getElementById('rkChips').innerHTML=(RAKUYA7.roadCounts||[]).map(x=>'<span class="rk-chip">'+rkEsc(x.road)+' '+x.count+'</span>').join('');
  const roadFilter=document.getElementById('rkRoad')?.value||'all';
  const state=document.getElementById('rkState')?.value||'all';
  const removed=state==='removed';
  const rows=rkRowsForState();
  const roads=roadFilter==='all'?(RAKUYA7.roads||[]):[roadFilter];
  let html='';
  for(const road of roads){
    const items=rows.filter(x=>(x.roads||[x.road]).includes(road));
    if(state!=='all'&&items.length===0)continue;
    html+='<details class="rk-road"><summary><span>'+rkEsc(road)+'</span><span class="count">'+items.length+' 筆</span></summary><div class="rk-list">'+items.map(x=>rkItemHtml(x,removed,road)).join('')+'</div></details>';
  }
  document.getElementById('rkGroups').innerHTML=html||'<div class="empty">目前沒有符合條件的樂屋案件。</div>';
}
function bindRakuya7(){
  const road=document.getElementById('rkRoad');
  for(const r of ['中山路二段','三民路一段','三民路二段','翠華街','林森街','萬安街','光復街']){
    if(road&&!road.querySelector('option[value="'+r+'"]')){
      const o=document.createElement('option');o.value=r;o.textContent=r;road.appendChild(o);
    }
  }
  road?.addEventListener('change',renderRakuya7);
  document.getElementById('rkState')?.addEventListener('change',renderRakuya7);
  document.getElementById('rkSearch')?.addEventListener('input',renderRakuya7);
}
if(location.pathname.includes('/preview/')){
  bindRakuya7();
  fetchJson('rakuya-seven-roads.json?ts='+Date.now(),'樂屋七路段資料')
    .then(x=>{RAKUYA7=x;renderRakuya7();})
    .catch(e=>{
      const panel=document.getElementById('rakuyaPanel');if(panel)panel.hidden=false;
      const u=document.getElementById('rkUpdated');if(u)u.textContent='樂屋七路段資料讀取失敗，請稍後重新整理。';
      console.warn('Rakuya Preview unavailable',e);
    });
}