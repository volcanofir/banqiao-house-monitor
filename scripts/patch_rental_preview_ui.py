from pathlib import Path

PATH = Path('docs/preview/index.html')
text = PATH.read_text(encoding='utf-8')

# Keep sale and rental source cards on the same wording contract.
text = text.replace('目前保留 ${r?.totalCount??0} 筆', '目前刊登 ${r?.totalCount??0} 筆')
# Keep the two timestamps/status notes readable on mobile: one concept per line.
text = text.replace(
    "document.querySelector('#updated').textContent=`來源資料最近更新：${fmt(DATA.updatedAt)}｜委託比對：${fmt(GAP.generatedAt)}。`;",
    "document.querySelector('#updated').innerHTML=`來源資料最近更新：${fmt(DATA.updatedAt)}<br>委託比對：${fmt(GAP.generatedAt)}。`;",
)

css = r'''
.market-switch{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:16px 0 18px}
.market-btn{appearance:none;border:1.5px solid #dfbf55;background:#fffdf7;color:#2f302f;border-radius:18px;padding:13px 16px;font-size:17px;font-weight:800;cursor:pointer}
.market-btn.active{background:#0f5945;color:#fff;border-color:#0f5945;box-shadow:0 5px 14px rgba(15,89,69,.14)}
.market-note{font-size:13px;color:#777;margin:-6px 0 14px}
.rent-item .row{align-items:center}
.rent-price{font-weight:900;color:#0f5945;font-size:18px}
'''
if '.market-switch{' not in text:
    text = text.replace('</style>', css + '\n</style>', 1)

switch_html = '''<div class="market-switch" id="marketSwitch">
<button type="button" class="market-btn active" data-market="sale">售屋</button>
<button type="button" class="market-btn" data-market="rent">租屋</button>
</div>'''
if 'id="marketSwitch"' not in text:
    text = text.replace('<div class="eyebrow">MONITOR STATUS</div><h2>資料來源</h2>', '<div class="eyebrow">MONITOR STATUS</div><h2>資料來源</h2>' + switch_html, 1)

text = text.replace('<section class="panel"><div class="stripe"></div><div class="inside">\n<div class="eyebrow">COMPANY MATCH</div>', '<section class="panel" id="companyPanel"><div class="stripe"></div><div class="inside">\n<div class="eyebrow">COMPANY MATCH</div>', 1)
text = text.replace('<div class="eyebrow">PROPERTY GROUPS</div><h2>整併後案件列表</h2>', '<div class="eyebrow">PROPERTY GROUPS</div><h2 id="listTitle">整併後案件列表</h2>', 1)

text = text.replace(
    "let DATA={listings:[],runs:{},watchRoads:defaultRoads};let GAP={propertyGroups:[],comparisons:[],counts:{},coveredRoads:[]};let VERIFY=null;let CMAP=new Map();let SOURCE_FILTER='all';",
    "let DATA={listings:[],runs:{},watchRoads:defaultRoads};let GAP={propertyGroups:[],comparisons:[],counts:{},coveredRoads:[]};let VERIFY=null;let RENT={listings:[],runs:{},watchRoads:defaultRoads,counts:{}};let MARKET_MODE='sale';let CMAP=new Map();let SOURCE_FILTER='all';",
    1,
)

text = text.replace('function renderGroups(){\n  const source=', "function renderGroups(){\n  if(MARKET_MODE==='rent') return renderRentGroups();\n  const source=", 1)

rent_js = r'''
function rentalPrice(x){const n=Number(x?.rent);return Number.isFinite(n)&&n>0?`${Math.round(n).toLocaleString('zh-TW')} 元/月`:'租金未取得'}
function rentalFirstSeenMs(x){const t=new Date(x?.firstSeenAt||0).getTime();return Number.isFinite(t)?t:0}
function rentalIsNew(x){
  const first=rentalFirstSeenMs(x);
  const configured=new Date(RENT.newListingBaselineAt||0).getTime();
  const aug24Baseline=Date.parse('2026-08-24T16:00:00Z');
  const baseline=Math.max(Number.isFinite(configured)?configured:0,aug24Baseline);
  const days=Number(RENT.newListingWindowDays??3);
  if(!Number.isFinite(first)||!Number.isFinite(baseline)||first<baseline||!Number.isFinite(days)||days<=0)return false;
  const age=Date.now()-first;
  return age>=0&&age<days*86400000;
}
function renderRentGroups(){
  const roads=RENT.watchRoads||defaultRoads;
  const source=SOURCE_FILTER;
  const sort=document.querySelector('#sort').value;
  let rows=(RENT.listings||[]).filter(x=>source==='all'||(source==='sinyi'&&x.source==='信義房屋')||(source==='591'&&x.source==='591'));
  if(sort==='priceDesc')rows.sort((a,b)=>(Number(b.rent)||0)-(Number(a.rent)||0));
  if(sort==='priceAsc')rows.sort((a,b)=>(Number(a.rent)||0)-(Number(b.rent)||0));
  if(sort==='timeDesc')rows.sort((a,b)=>rentalFirstSeenMs(b)-rentalFirstSeenMs(a));
  if(sort==='timeAsc')rows.sort((a,b)=>rentalFirstSeenMs(a)-rentalFirstSeenMs(b));
  let html='';
  for(const road of roads){
    const items=rows.filter(x=>x.road===road);
    if(!items.length)continue;
    html+=`<details class="road-group"><summary><span>${esc(road)}</span><span class="count">${items.length} 戶</span></summary><div class="list">${items.map(x=>{
      const cls=x.source==='信義房屋'?'sinyi':'m591';
      const label=x.source==='信義房屋'?'信義':'591';
      const size=Number(x.size); const sizeText=Number.isFinite(size)&&size>0?`${size}坪`:'坪數未取得';
      const newBadge=rentalIsNew(x)?'<span class="pill sinyi">新案</span>':'';
      return `<article class="item rent-item"><a class="item-title" href="${esc(x.url||'#')}" target="_blank" rel="noopener noreferrer">${esc(x.title||x.houseId||'租屋案件')}</a><div class="row"><span class="pill ${cls}">${label}</span>${newBadge}<span class="rent-price">${esc(rentalPrice(x))}</span><span>${esc(sizeText)}</span><span>${esc(x.address||road)}</span><span>首次抓到：${fmt(x.firstSeenAt)}</span></div></article>`;
    }).join('')}</div></details>`;
  }
  document.querySelector('#groups').innerHTML=html||'<div class="empty">目前這 7 條路沒有抓到符合條件的租屋案件。</div>';
}
function renderRent(){
  const roads=RENT.watchRoads||defaultRoads;
  const listings=RENT.listings||[];
  const newCount=listings.filter(rentalIsNew).length;
  document.querySelector('#mRoads').textContent=`${roads.length} 條`;
  document.querySelector('#mGroups').textContent=`${listings.length} 戶`;
  document.querySelector('#mNew').textContent=`${newCount} 戶`;
  document.querySelector('#mMerged').textContent=`${listings.length} 筆`;
  const cards=['591','信義房屋'].map(name=>{const r=RENT.runs?.[name],ok=r?.status==='ok';return `<div class="source-card"><div class="source-head"><strong>${name}</strong><span class="badge ${ok?'ok':'err'}">${ok?'正常':'異常'}</span></div><div class="note">目前刊登 ${r?.totalCount??0} 筆<br>最近更新：${fmt(RENT.updatedAt)}</div></div>`});
  document.querySelector('#sources').innerHTML=cards.join('');
  document.querySelector('#updated').innerHTML=`租屋資料最近更新：${fmt(RENT.updatedAt)}<br>新案以本監控首次抓到時間計算，標籤保留 ${RENT.newListingWindowDays??3} 天。`;
  renderRentGroups();
}
function setMarket(mode){
  MARKET_MODE=mode==='rent'?'rent':'sale'; SOURCE_FILTER='all';
  document.querySelectorAll('.market-btn').forEach(b=>b.classList.toggle('active',b.dataset.market===MARKET_MODE));
  document.querySelectorAll('.source-tab').forEach(b=>b.classList.toggle('active',b.dataset.source==='all'));
  const rent=MARKET_MODE==='rent';
  const company=document.querySelector('#companyPanel'); if(company)company.style.display=rent?'none':'';
  const state=document.querySelector('#state'); if(state){state.style.display=rent?'none':'';state.value='all';}
  const companyState=document.querySelector('#companyState'); if(companyState){companyState.style.display=rent?'none':'';companyState.value='all';}
  const title=document.querySelector('#listTitle'); if(title)title.textContent=rent?'租屋案件列表':'整併後案件列表';
  const sort=document.querySelector('#sort');
  if(sort&&sort.options.length>=5){
    sort.options[1].textContent=rent?'租金：高 → 低':'售價：高 → 低';
    sort.options[2].textContent=rent?'租金：低 → 高':'售價：低 → 高';
    sort.options[3].textContent=rent?'首次抓到：新 → 舊':'上架時間：新 → 舊';
    sort.options[4].textContent=rent?'首次抓到：舊 → 新':'上架時間：舊 → 新';
  }
  if(rent)renderRent(); else render();
}
document.querySelectorAll('.market-btn').forEach(btn=>btn.addEventListener('click',()=>setMarket(btn.dataset.market)));
fetchJson(`rental-data.json?ts=${Date.now()}`,'租屋資料').then(r=>{RENT=r;if(MARKET_MODE==='rent')renderRent()}).catch(e=>{console.warn('Rental Preview unavailable',e)});
'''

start = text.find('function rentalPrice(x)')
end_marker = "document.querySelectorAll('.source-tab').forEach(btn=>btn.addEventListener('click'"
end = text.find(end_marker, start if start >= 0 else 0)
if start >= 0 and end > start:
    text = text[:start] + rent_js + '\n' + text[end:]
elif 'function renderRentGroups()' not in text:
    idx = text.find(end_marker)
    if idx < 0:
        raise RuntimeError('Rental Preview patch anchor not found')
    text = text[:idx] + rent_js + '\n' + text[idx:]

text = text.replace('<details class="road-group" open>', '<details class="road-group">')

required = [
    'id="marketSwitch"',
    'data-market="sale"',
    'data-market="rent"',
    'function renderRentGroups()',
    'function rentalIsNew(x)',
    "Date.parse('2026-08-24T16:00:00Z')",
    'newListingBaselineAt',
    'newListingWindowDays',
    '<span class="pill sinyi">新案</span>',
    'function setMarket(mode)',
    'rental-data.json',
    'id="companyPanel"',
    '首次抓到：${fmt(x.firstSeenAt)}',
    'listings.filter(rentalIsNew).length',
    '<strong>${name}</strong>',
    '目前刊登 ${r?.totalCount??0} 筆',
    '<br>委託比對：${fmt(GAP.generatedAt)}。',
    '<br>新案以本監控首次抓到時間計算',
]
missing = [x for x in required if x not in text]
if missing:
    raise RuntimeError(f'Rental Preview UI patch failed: {missing}')
forbidden = [
    '目前保留 ${r?.totalCount??0} 筆',
    '目前抓到 ${r?.totalCount??0} 筆',
    "${name}${name==='591'?' 租屋':'租屋'}",
]
present = [x for x in forbidden if x in text]
if present:
    raise RuntimeError(f'Rental Preview UI wording patch failed; old fragments remain: {present}')
if '<details class="road-group" open>' in text:
    raise RuntimeError('Rental Preview UI patch failed: road groups still default-open')

PATH.write_text(text, encoding='utf-8')
print('Rental Preview UI patched with two-line update notes, unified source-card wording, 3-day new badges and collapsed details')
