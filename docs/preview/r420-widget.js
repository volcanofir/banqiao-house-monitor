let R420=null;
function r420Esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function r420Price(x){const n=Number(x?.price);return Number.isFinite(n)?n.toLocaleString('zh-TW')+'萬':'價格未取得';}
function r420Floor(x){return x?.floor?(String(x.floor)+(x.totalfloor?'/'+x.totalfloor+'樓':'')):'樓層未取得';}
function r420FirstDisplay(x){const v=String(x?.firstDisplay||'').trim();if(!v)return '最早上架時間未取得';return '最早上架：'+v.replace(/-/g,'/');}
const R420_PUQIAN_ROADS=['中山路二段','三民路一段','三民路二段','翠華街','林森街','萬安街','光復街','富山街','懷仁街','永豐街','光環路一段','光環路二段','太和街','民享街'];
function r420PuqianRoad(x){return x?.puqianRoadMatch||x?.coreRoadMatch||R420_PUQIAN_ROADS.find(road=>String(x?.address||'').includes(road))||null;}
function r420MarketArea(x){if(r420PuqianRoad(x))return '埔墘區';if(x?.marketArea)return x.marketArea;if(x?.region==='新北市板橋區')return '板橋區';return '其他行政區';}
function r420SortAreas(rows){const order=['埔墘區','板橋區','其他行政區'];const m=new Map(order.map(x=>[x,[]]));for(const x of rows){const k=r420MarketArea(x);if(!m.has(k))m.set(k,[]);m.get(k).push(x);}return [...m.entries()].filter(([,items])=>items.length).sort((a,b)=>order.indexOf(a[0])-order.indexOf(b[0]));}
function r420ItemHtml(x,removed=false){
  const change=x.priceChange;
  const badges=[
    r420MarketArea(x)==='埔墘區'?'<span class="r420-pill core">埔墘區｜'+r420Esc(r420PuqianRoad(x)||'埔墘')+'</span>':'',
    !removed&&x.newAt?'<span class="r420-pill new">本次新進</span>':'',
    !removed&&change?'<span class="r420-pill down">'+(Number(change.to)<Number(change.from)?'降價':'調價')+' '+r420Esc(change.from)+'→'+r420Esc(change.to)+'萬</span>':'',
    removed?'<span class="r420-pill removed">本次下架</span>':''
  ].join('');
  return '<article class="r420-item">'+
    '<a class="r420-title" href="'+r420Esc(x.url||'#')+'" target="_blank" rel="noopener noreferrer">'+r420Esc(x.name||'R420案件')+'</a>'+
    '<div class="r420-row">'+badges+
      '<span>'+r420Esc(r420Price(x))+'</span>'+
      '<span>'+r420Esc(x.areaBuilding!=null?x.areaBuilding+'坪':'坪數未取得')+'</span>'+
      '<span>'+r420Esc(x.layout||'格局未取得')+'</span>'+
      '<span>'+r420Esc(r420Floor(x))+'</span>'+
      '<span>'+r420Esc(x.age||'屋齡未取得')+'</span>'+
    '</div>'+
    '<div class="r420-row"><span>'+r420Esc(x.region||'')+'</span><span>'+r420Esc(x.address||'地址未取得')+'</span></div>'+
    '<div class="r420-row"><span>'+r420Esc(r420FirstDisplay(x))+'</span>'+(removed&&x.removedAt?'<span>下架：'+r420Esc(fmt(x.removedAt))+'</span>':'')+'</div>'+
  '</article>';
}
function renderR420(){if(!R420)return;const panel=document.getElementById('r420Panel');if(!panel)return;panel.hidden=false;const changes=R420.changes||{};document.getElementById('r420Total').textContent=(R420.totalCount??0)+' 戶';document.getElementById('r420Puqian').textContent=(R420.puqianCount??R420.coreRoadCount??0)+' 戶';document.getElementById('r420Banqiao').textContent=(R420.banqiaoOtherCount??Math.max(0,(R420.banqiaoCount??0)-(R420.coreRoadCount??0)))+' 戶';document.getElementById('r420Other').textContent=(R420.otherAreaCount??Math.max(0,(R420.totalCount??0)-(R420.banqiaoCount??0)))+' 戶';document.getElementById('r420Changes').textContent=(changes.currentChangeCount??0)+' 戶';const baselineNote=R420.baseline?'｜本次為初始基準，不把既有案件列為新案':'';document.getElementById('r420Updated').textContent='R420 最近更新：'+fmt(R420.updatedAt)+'｜官方總數 '+(R420.sourceTotalCount??'-')+' 戶'+baselineNote;const district=document.getElementById('r420District');if(district.options.length===1){for(const x of (R420.areas||[])){const o=document.createElement('option');o.value=x.area;o.textContent=x.area+'（'+x.count+'）';district.appendChild(o);}}document.getElementById('r420RegionChips').innerHTML=(R420.areas||[]).map(x=>'<span class="r420-chip">'+r420Esc(x.area)+' '+x.count+'</span>').join('');const state=document.getElementById('r420State').value;const areaFilter=district.value;const q=(document.getElementById('r420Search').value||'').trim().toLowerCase();let rows=state==='removed'?(R420.recentRemoved||[]):(R420.listings||[]);if(state==='new')rows=rows.filter(x=>!!x.newAt);if(state==='price')rows=rows.filter(x=>!!x.priceChange);if(areaFilter!=='all')rows=rows.filter(x=>r420MarketArea(x)===areaFilter);if(q)rows=rows.filter(x=>[x.houseNo,x.name,x.address,x.region,r420MarketArea(x)].some(v=>String(v||'').toLowerCase().includes(q)));rows=[...rows].sort((a,b)=>{const ca=a.priceChange?.at||a.newAt||a.removedAt||a.firstSeenAt||'';const cb=b.priceChange?.at||b.newAt||b.removedAt||b.firstSeenAt||'';return new Date(cb||0)-new Date(ca||0);});let html='';for(const [area,items] of r420SortAreas(rows)){html+='<details class="r420-region"><summary><span>'+r420Esc(area)+'</span><span class="count">'+items.length+' 戶</span></summary><div class="r420-list">'+items.map(x=>r420ItemHtml(x,state==='removed')).join('')+'</div></details>';}document.getElementById('r420Groups').innerHTML=html||'<div class="empty">目前沒有符合條件的 R420 案件。</div>';}
function bindR420(){for(const id of ['r420District','r420State'])document.getElementById(id)?.addEventListener('change',renderR420);document.getElementById('r420Search')?.addEventListener('input',renderR420);}
if(location.pathname.includes('/preview/')){bindR420();fetchJson('r420-store.json?ts='+Date.now(),'R420 相對店資料').then(x=>{R420=x;renderR420();}).catch(e=>{const panel=document.getElementById('r420Panel');if(panel)panel.hidden=false;const u=document.getElementById('r420Updated');if(u)u.textContent='R420 資料讀取失敗，請稍後重新整理。';console.warn('R420 Preview unavailable',e);});}