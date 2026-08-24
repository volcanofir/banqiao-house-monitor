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
    '<select id="state"><option value="all">全部上架狀態</option><option value="new">新進案件</option><option value="active">已上架</option><option value="removed">已下架</option></select>',
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

new_render_groups = r'''function renderGroups(){
  if(typeof MARKET_MODE!=='undefined' && MARKET_MODE==='rent' && typeof renderRentGroups==='function') return renderRentGroups();
  const source=SOURCE_FILTER,state=document.querySelector('#state').value,cs=document.querySelector('#companyState').value,sort=document.querySelector('#sort').value;
  const baseRows=state==='removed'?(GAP.recentOffMarketGroups||[]):(GAP.propertyGroups||[]);
  let rows=baseRows.filter(g=>{
    const c=cmp(g);
    const sourceOK=source==='all'||(source==='sinyi'&&(g.sources||[]).includes('信義房屋'))||(source==='591'&&(g.sources||[]).includes('591'));
    const stateOK=state==='removed'?g.offMarket===true:(state==='all'||(state==='new'&&isNew(g))||(state==='active'&&!isNew(g)));
    const compOK=state==='removed'?true:(cs==='all'||c?.status===cs);
    return sourceOK&&stateOK&&compOK;
  });
  let html='';
  for(const road of (DATA.watchRoads||defaultRoads)){
    let items=rows.filter(g=>g.road===road);
    if(state==='removed'&&sort==='default')items=[...items].sort((a,b)=>new Date(b.removedAt||0)-new Date(a.removedAt||0));
    else items=sortGroups(items,sort);
    if(!items.length)continue;
    html+=`<details class="road-group"><summary><span>${esc(road)}</span><span class="count">${items.length} 戶</span></summary><div class="list">${items.map(g=>{
      const c=cmp(g),st=g.offMarket?'offmarket':(c?.status||'unavailable');
      const removedLine=g.offMarket&&g.removedAt?`<span>下架：${fmt(g.removedAt)}</span>`:'';
      return `<article class="item"><a class="item-title" href="${esc(g.url||'#')}" target="_blank" rel="noopener noreferrer">${esc(g.title||g.primaryId)}</a><div class="row">${sourcePills(g)}<span class="pill ${companyClass(st)}">${companyLabel(st)}</span>${g.crossPlatformMerged?'<span class="pill merged">信義主資料＋591整併</span>':''}${!g.offMarket&&isNew(g)?'<span class="pill sinyi">新進案件</span>':''}<span>${esc(displayPrice(g))}</span><span>${esc(g.size||'-')}</span><span>${esc(g.address||'-')}</span>${removedLine}</div>${g.offMarket?'':candidateLine(g)}${sourceDetails(g)}</article>`;
    }).join('')}</div></details>`;
  }
  document.querySelector('#groups').innerHTML=html||'<div class="empty">目前沒有符合條件的房屋群組。</div>';
}'''

# This patch can be run after the rental Preview workflow has already inserted its
# own UI block. In that case the off-market renderer may already be present and
# must not be treated as an error merely because the old regex anchor moved.
render_contract = [
    "state==='removed'?(GAP.recentOffMarketGroups||[]):(GAP.propertyGroups||[])",
    "g.offMarket?'offmarket'",
    '下架：${fmt(g.removedAt)}',
]
already_patched = all(x in text for x in render_contract)

if already_patched:
    print('Off-market renderGroups already patched; keeping existing renderer')
else:
    # Prefer the original anchor, but also tolerate helper functions (for example
    # rentalPrice/renderRentGroups) inserted between renderGroups and source tabs.
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
        raise RuntimeError(f'Off-market UI patch failed to replace renderGroups: {replaced}')

required = [
    '<span>已下架</span><strong id="cUnavailable">',
    '<option value="removed">已下架</option>',
    'GAP.recentOffMarketCount??0',
    "state==='removed'?(GAP.recentOffMarketGroups||[]):(GAP.propertyGroups||[])",
    "g.offMarket?'offmarket'",
    '下架：${fmt(g.removedAt)}',
]
missing = [x for x in required if x not in text]
if missing:
    raise RuntimeError(f'Off-market UI patch contract failed: {missing}')

PATH.write_text(text, encoding='utf-8')
print('10-day grouped off-market UI patched')
