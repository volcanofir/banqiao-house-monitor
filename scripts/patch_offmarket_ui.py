from pathlib import Path
import re

PATH = Path('docs/preview/index.html')
text = PATH.read_text(encoding='utf-8')

text = text.replace(
    '<div class="compare-card unavailable"><span>尚未比對</span><strong id="cUnavailable">-</strong></div>',
    '<div class="compare-card unavailable"><span>已下架</span><strong id="cUnavailable">-</strong></div>',
)
text = text.replace(
    '<select id="state"><option value="all">全部上架狀態</option><option value="new">新進案件</option><option value="active">已上架</option></select>',
    '<select id="state"><option value="all">全部上架狀態</option><option value="new">新進案件</option><option value="active">已上架</option><option value="changed">本次異動</option><option value="removed">已下架</option></select>',
)
text = text.replace(
    '<select id="state"><option value="all">全部上架狀態</option><option value="new">新進案件</option><option value="active">已上架</option><option value="removed">已下架</option></select>',
    '<select id="state"><option value="all">全部上架狀態</option><option value="new">新進案件</option><option value="active">已上架</option><option value="changed">本次異動</option><option value="removed">已下架</option></select>',
)
# Rental patch recreates the sale-state options when switching back from rent.
text = text.replace(
    "'<option value=\"all\">全部上架狀態</option><option value=\"new\">新進案件</option><option value=\"active\">已上架</option><option value=\"removed\">已下架</option>'",
    "'<option value=\"all\">全部上架狀態</option><option value=\"new\">新進案件</option><option value=\"active\">已上架</option><option value=\"changed\">本次異動</option><option value=\"removed\">已下架</option>'",
)
text = text.replace(
    "const companyLabel=s=>({company_match:'庫存',review:'待確認',missing:'未接回',unavailable:'尚未比對'}[s]||s||'尚未比對');",
    "const companyLabel=s=>({company_match:'庫存',review:'待確認',missing:'未接回',unavailable:'尚未比對',offmarket:'已下架'}[s]||s||'尚未比對');",
)
text = text.replace(
    "const companyClass=s=>s==='company_match'?'stock':s==='review'?'review':s==='missing'?'missing':'unavailable';",
    "const companyClass=s=>s==='company_match'?'stock':s==='review'?'review':(s==='missing'||s==='offmarket')?'missing':'unavailable';",
)
text = text.replace(
    "document.querySelector('#cUnavailable').textContent=`${c.unavailable??0} 戶`;",
    "document.querySelector('#cUnavailable').textContent=`${GAP.recentOffMarketCount??0} 戶`;",
)
text = text.replace('｜Preview 比對：', '｜委託比對：')

change_css = r'''
.pill.change-new{background:#dcefe7;color:#14503c;border:1px solid #b8daca}
.pill.change-down{background:#f7dadd;color:#972a35;border:1px solid #e9b8bf}
.pill.change-up{background:#e8eef9;color:#35577d;border:1px solid #cad8ef}
.pill.change-removed{background:#eceff1;color:#50575e;border:1px solid #d4d9dd}
.change-price-line{margin-top:8px;padding:8px 10px;border-radius:10px;background:#fff7e1;font-size:13px;font-weight:850;color:#6d5b20}
.change-price-line.down{background:#fff0f1;color:#972a35}
.change-price-line.up{background:#eef4ff;color:#35577d}
'''
if '.pill.change-new{' not in text:
    text = text.replace('</style>', change_css + '\n</style>', 1)

change_helpers = r'''function monitorRunMs(){
  const raw=DATA?.runs?.priceTracking?.checkedAt||DATA?.updatedAt;
  const ms=new Date(raw||0).getTime();
  return Number.isFinite(ms)?ms:0;
}
function sameMonitorRun(value){
  const a=new Date(value||0).getTime(),b=monitorRunMs();
  return Number.isFinite(a)&&a>0&&b>0&&Math.abs(a-b)<=180000;
}
function allMonitorListings(){
  const out=[],seen=new Set();
  const visit=(row,parentRoad)=>{
    if(!row||typeof row!=='object')return;
    const id=row.id||null;
    if(id&&!seen.has(id)){seen.add(id);out.push({...row,road:row.road||parentRoad});}
    for(const child of (row.mergedListings||[]))visit(child,row.road||parentRoad);
  };
  for(const row of (DATA.listings||[]))visit(row,row?.road);
  return out;
}
function groupListingIds(g){
  const ids=new Set();
  const visit=row=>{
    if(!row||typeof row!=='object')return;
    if(row.id)ids.add(String(row.id));
    for(const child of (row.mergedListings||[]))visit(child);
  };
  if(g?.primaryId)ids.add(String(g.primaryId));
  for(const row of (g?.sourceListings||[]))visit(row);
  return ids;
}
function monitorRowsForGroup(g){
  const ids=groupListingIds(g);
  const rows=allMonitorListings().filter(row=>row?.id&&ids.has(String(row.id)));
  return rows.length?rows:(g?.sourceListings||[]);
}
function latestPriceChange(row){
  const h=(row?.priceHistory||[]).filter(x=>x&&Number.isFinite(Number(x.price))&&x.at);
  if(h.length<2)return null;
  const last=h[h.length-1],prev=h[h.length-2];
  if(!sameMonitorRun(last.at))return null;
  const from=Number(prev.price),to=Number(last.price),delta=to-from;
  if(!Number.isFinite(from)||!Number.isFinite(to)||delta===0)return null;
  return {from,to,delta,at:last.at,id:row.id,source:row.source};
}
function groupChangeInfo(g){
  const rows=monitorRowsForGroup(g);
  const prices=rows.map(latestPriceChange).filter(Boolean).sort((a,b)=>Math.abs(b.delta)-Math.abs(a.delta));
  const hasNew=rows.some(x=>sameMonitorRun(x?.newAt));
  const hasRemoved=!!(g?.offMarket&&sameMonitorRun(g?.removedAt))||rows.some(x=>sameMonitorRun(x?.removedAt));
  const priceChange=prices[0]||null;
  const stamps=[];
  if(priceChange)stamps.push(new Date(priceChange.at).getTime());
  if(hasNew)for(const x of rows)if(sameMonitorRun(x?.newAt))stamps.push(new Date(x.newAt).getTime());
  if(hasRemoved){
    if(g?.removedAt)stamps.push(new Date(g.removedAt).getTime());
    for(const x of rows)if(sameMonitorRun(x?.removedAt))stamps.push(new Date(x.removedAt).getTime());
  }
  return {changed:!!(hasNew||hasRemoved||priceChange),hasNew,hasRemoved,priceChange,timestamp:Math.max(0,...stamps.filter(Number.isFinite))};
}
function currentChangedGroups(){
  const active=(GAP.propertyGroups||[]).filter(g=>groupChangeInfo(g).changed);
  const removed=(GAP.recentOffMarketGroups||[]).filter(g=>groupChangeInfo(g).changed);
  return [...active,...removed];
}
function changeBadges(g){
  const info=groupChangeInfo(g),out=[];
  if(info.hasNew)out.push('<span class="pill change-new">本次新進</span>');
  if(info.priceChange){
    const d=info.priceChange.delta;
    out.push(`<span class="pill ${d<0?'change-down':'change-up'}">${d<0?'降價':'漲價'} ${Math.abs(d).toLocaleString('zh-TW')}萬</span>`);
  }
  if(info.hasRemoved)out.push('<span class="pill change-removed">本次下架</span>');
  return out.join('');
}
function changePriceLine(g){
  const p=groupChangeInfo(g).priceChange;
  if(!p)return '';
  const down=p.delta<0;
  return `<div class="change-price-line ${down?'down':'up'}">${down?'🔻':'🔺'} ${p.from.toLocaleString('zh-TW')}萬 → ${p.to.toLocaleString('zh-TW')}萬｜${down?'降':'漲'} ${Math.abs(p.delta).toLocaleString('zh-TW')}萬</div>`;
}'''
if 'function groupChangeInfo(g)' not in text:
    anchor = 'function bindRoadAccordion(){' if 'function bindRoadAccordion(){' in text else 'function renderGroups(){'
    idx = text.find(anchor)
    if idx < 0:
        raise RuntimeError('Current-change helper anchor not found')
    text = text[:idx] + change_helpers + '\n' + text[idx:]

new_render_groups = r'''function renderGroups(){
  if(typeof MARKET_MODE!=='undefined' && MARKET_MODE==='rent' && typeof renderRentGroups==='function') return renderRentGroups();
  const source=SOURCE_FILTER,state=document.querySelector('#state').value,cs=document.querySelector('#companyState').value,sort=document.querySelector('#sort').value;
  const baseRows=state==='changed'?currentChangedGroups():state==='removed'?(GAP.recentOffMarketGroups||[]):(GAP.propertyGroups||[]);
  let rows=baseRows.filter(g=>{
    const c=cmp(g);
    const sourceOK=source==='all'||(source==='sinyi'&&(g.sources||[]).includes('信義房屋'))||(source==='591'&&(g.sources||[]).includes('591'));
    const stateOK=state==='changed'?groupChangeInfo(g).changed:state==='removed'?g.offMarket===true:(state==='all'||(state==='new'&&isNew(g))||(state==='active'&&!isNew(g)));
    const compOK=(state==='removed'||g.offMarket)?true:(cs==='all'||c?.status===cs);
    return sourceOK&&stateOK&&compOK;
  });
  let html='';
  for(const road of (DATA.watchRoads||defaultRoads)){
    let items=rows.filter(g=>g.road===road);
    if(state==='changed'&&sort==='default')items=[...items].sort((a,b)=>groupChangeInfo(b).timestamp-groupChangeInfo(a).timestamp);
    else if(state==='removed'&&sort==='default')items=[...items].sort((a,b)=>new Date(b.removedAt||0)-new Date(a.removedAt||0));
    else items=sortGroups(items,sort);
    if(!items.length)continue;
    html+=`<details class="road-group"><summary><span>${esc(road)}</span><span class="count">${items.length} 戶</span></summary><div class="list">${items.map(g=>{
      const c=cmp(g),st=g.offMarket?'offmarket':(c?.status||'unavailable'),change=groupChangeInfo(g);
      const removedLine=g.offMarket&&g.removedAt?`<span>下架：${fmt(g.removedAt)}</span>`:'';
      return `<article class="item" data-change="${change.changed?'1':'0'}"><a class="item-title" href="${esc(g.url||'#')}" target="_blank" rel="noopener noreferrer">${esc(g.title||g.primaryId)}</a><div class="row">${sourcePills(g)}<span class="pill ${companyClass(st)}">${companyLabel(st)}</span>${changeBadges(g)}${g.crossPlatformMerged?'<span class="pill merged">信義主資料＋591整併</span>':''}${!g.offMarket&&isNew(g)?'<span class="pill sinyi">新進案件</span>':''}<span>${esc(displayPrice(g))}</span><span>${esc(g.size||'-')}</span><span>${esc(g.address||'-')}</span>${removedLine}</div>${changePriceLine(g)}${g.offMarket?'':candidateLine(g)}${sourceDetails(g)}</article>`;
    }).join('')}</div></details>`;
  }
  document.querySelector('#groups').innerHTML=html||'<div class="empty">目前沒有符合條件的房屋群組。</div>';
  bindRoadAccordion();
}'''

render_contract = [
    "state==='changed'?currentChangedGroups()",
    "state==='removed'?(GAP.recentOffMarketGroups||[]):(GAP.propertyGroups||[])",
    "g.offMarket?'offmarket'",
    'changeBadges(g)',
    'changePriceLine(g)',
    '下架：${fmt(g.removedAt)}',
]
already_patched = all(x in text for x in render_contract)

if not already_patched:
    patterns = [
        r"function renderGroups\(\)\{.*?\}(?=\ndocument\.querySelectorAll\('\.source-tab'\))",
        r"function renderGroups\(\)\{.*?\n\}(?=\n+(?:function\s+[A-Za-z_$][\w$]*\s*\(|document\.querySelectorAll\('\.source-tab'\)))",
    ]
    replaced = 0
    for pattern in patterns:
        text, replaced = re.subn(pattern, new_render_groups, text, count=1, flags=re.S)
        if replaced == 1:
            break
    if replaced != 1:
        raise RuntimeError(f'Off-market/current-change UI patch failed to replace renderGroups: {replaced}')

accordion_helper = r'''function bindRoadAccordion(){
  document.querySelectorAll('#groups details.road-group').forEach(group=>{
    if(group.dataset.singleOpenBound==='1')return;
    group.dataset.singleOpenBound='1';
    group.addEventListener('toggle',()=>{
      if(!group.open)return;
      document.querySelectorAll('#groups details.road-group[open]').forEach(other=>{
        if(other!==group)other.open=false;
      });
    });
  });
}'''
if 'function bindRoadAccordion()' not in text:
    anchor = 'function renderGroups(){'
    idx = text.find(anchor)
    if idx < 0:
        raise RuntimeError('Road accordion helper anchor not found')
    text = text[:idx] + accordion_helper + '\n' + text[idx:]

sale_render_line = "  document.querySelector('#groups').innerHTML=html||'<div class=\"empty\">目前沒有符合條件的房屋群組。</div>';"
rent_render_line = "  document.querySelector('#groups').innerHTML=html||'<div class=\"empty\">目前這 7 條路沒有抓到符合條件的租屋案件。</div>';"
if sale_render_line + "\n  bindRoadAccordion();" not in text:
    text = text.replace(sale_render_line, sale_render_line + "\n  bindRoadAccordion();", 1)
if rent_render_line + "\n  bindRoadAccordion();" not in text:
    text = text.replace(rent_render_line, rent_render_line + "\n  bindRoadAccordion();", 1)

required = [
    '<span>已下架</span><strong id="cUnavailable">',
    '<option value="changed">本次異動</option>',
    'GAP.recentOffMarketCount??0',
    "state==='changed'?currentChangedGroups()",
    "state==='removed'?(GAP.recentOffMarketGroups||[]):(GAP.propertyGroups||[])",
    'function groupChangeInfo(g)',
    'function currentChangedGroups()',
    'function changeBadges(g)',
    'function changePriceLine(g)',
    '本次新進',
    '本次下架',
    'change-down',
    'change-up',
    'data-change="${change.changed?',
    'function bindRoadAccordion()',
    "group.dataset.singleOpenBound='1'",
    "document.querySelectorAll('#groups details.road-group[open]')",
    sale_render_line + "\n  bindRoadAccordion();",
    rent_render_line + "\n  bindRoadAccordion();",
]
missing = [x for x in required if x not in text]
if missing:
    raise RuntimeError(f'Off-market/current-change UI patch contract failed: {missing}')

PATH.write_text(text, encoding='utf-8')
print('10-day off-market + current-change Preview UI patched with single-open road accordion')
