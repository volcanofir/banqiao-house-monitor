from pathlib import Path
import json
import re
import subprocess
import sys

# Keep this canonical Preview patch as the workflow trigger point for UI hardening.
PATH = Path('docs/preview/index.html')
GAP_PATH = Path('docs/preview/company-gap.json')
SNAPSHOT_PATH = Path('docs/preview/yungching-browser-snapshot.json')
RUN_LOG = Path('docs/preview/yungching-preview-run.log')

if GAP_PATH.exists() and SNAPSHOT_PATH.exists():
    gap = json.loads(GAP_PATH.read_text(encoding='utf-8'))
    snap = json.loads(SNAPSHOT_PATH.read_text(encoding='utf-8'))
    official = {f"YC:{x.get('id')}": x for x in (snap.get('listings') or []) if x.get('id')}
    for row in gap.get('comparisons') or []:
        c = row.get('companyCandidate')
        if not c:
            continue
        src = official.get(str(c.get('id')))
        if not src:
            continue
        c['officialId'] = src.get('id')
        c['officialCaseId'] = src.get('officialCaseId')
        c['floor'] = src.get('floor')
        c['floorSourceMode'] = src.get('floorSourceMode')
        c['floorEvidence'] = src.get('floorEvidence')
    GAP_PATH.write_text(json.dumps(gap, ensure_ascii=False, indent=2), encoding='utf-8')

text = PATH.read_text(encoding='utf-8')

# Standalone competitor-store R420 panel was removed from Preview. Strip any
# legacy injected copy on every rebuild; independent store tracking is untouched.
text = re.sub(
    r'\n<section class="panel r420-panel" id="r420Panel" hidden>[\s\S]*?</section>',
    '',
    text,
    count=1,
)
text = re.sub(r'\n?<link rel="stylesheet" href="r420-widget\.css\?v=[^"]+"\s*/>', '', text)
text = re.sub(r'\n?<script src="r420-widget\.js\?v=[^"]+"></script>', '', text)

# Security is fail-closed: the canonical Preview must already contain the
# inline guard before any UI patching or publication can continue.
if 'BQM_INLINE_AUTH_V5' not in text:
    raise RuntimeError('Preview strict one-time access guard is missing; refuse to publish an unprotected page')
if "window.addEventListener('pageshow'" not in text or 'sessionStorage.removeItem(GRANT_KEY)' not in text:
    raise RuntimeError('Preview one-time access guard is incomplete; refuse to publish')
if 'BQM_FOREGROUND_RELOCK_V5' not in text or "document.addEventListener('visibilitychange'" not in text:
    raise RuntimeError('Preview foreground relock is missing; refuse to publish')
if "window.addEventListener('pagehide'" not in text or "window.addEventListener('blur'" not in text or "window.addEventListener('focus'" not in text:
    raise RuntimeError('Preview iOS foreground relock signals are incomplete; refuse to publish')
if "const LOCK_KEY = 'bqm-relock-required-v5';" not in text:
    raise RuntimeError('Preview relock marker key is missing; refuse to publish')
if "const GRACE_KEY = 'bqm-access-grace-v6';" not in text or "const GRACE_MS = 3 * 60 * 1000;" not in text:
    raise RuntimeError('Preview 3-minute access grace is missing; refuse to publish')
if "const AUTH_HASH = 'd75acd6fee3ae85d59dcbb0383178e1b8d670c8fcfe0ea5cb099a23911efe75a';" not in text:
    raise RuntimeError('Preview login credential hash is stale; refuse to publish')
if "access.html?v=20261009h" not in text:
    raise RuntimeError('Preview login page version is stale; refuse to publish')
# Legacy external-gate tags are not trusted because browser cache/load failures can leak the page.
text = re.sub(r'\\n?<script src="(?:\\.\\./)?access-gate\\.js\\?v=[^"]+"></script>', '', text)
replacements = {
    '🧪 PREVIEW 測試版本｜信義優先整併測試｜不影響正式網站': '🧪 PREVIEW 測試版本｜不影響正式網站',
    '591 ＋ 信義先整併，再比對永慶公司公開庫存': '比對591、信義刊登案件',
    '<h1>指定路段房屋群組</h1>': '<h1>指定路段上架案件比對</h1>',
    '<h1>指定路段案件比對</h1>': '<h1>指定路段上架案件比對</h1>',
    '<h1>指定路段刊登案件比對</h1>': '<h1>指定路段上架案件比對</h1>',
    '<h2>公司委託比對（以戶數計）</h2>': '<h2>委託比對</h2>',
    '.source-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}': '.source-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}',
    '<div class="metric"><span>原始有效刊登</span><strong id="mRaw">-</strong></div>': '<div class="metric"><span>新進案件</span><strong id="mNew">-</strong></div>',
    '<div class="metric"><span>整併後房屋</span><strong id="mGroups">-</strong></div>': '<div class="metric"><span>刊登中</span><strong id="mGroups">-</strong></div>',
    '<div class="metric"><span>跨平台整併</span><strong id="mMerged">-</strong></div>': '<div class="metric"><span>原始刊登數量</span><strong id="mMerged">-</strong></div>',
    '<option value="new">近期新案</option>': '<option value="new">新進案件</option>',
    '<span class="pill sinyi">近期新案</span>': '<span class="pill sinyi">新進案件</span>',
    '<div class="note" id="updated">': '<div class="note" id="updated" aria-live="polite">',
}
for old, new in replacements.items():
    text = text.replace(old, new)

text = text.replace(
    "scheme-a-canonical-v3-sinyi-floor-neartie",
    "scheme-a-canonical-v5-sinyi-rakuya-5168-floor-neartie",
)

old_esc = '''const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot',"'":'&#39;'}[c]));'''
new_esc = '''const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));'''
text = text.replace(old_esc, new_esc)
text = text.replace('rel="noreferrer"', 'rel="noopener noreferrer"')

# Sale "new listing" is property-level: use the earliest source-provided time
# across all verified same-property adverts, including saved exact-ID history.
# Never use monitoring discovery as the first listing date.
sale_new_policy = r'''const timeMs=v=>{if(v==null||v==='')return 0;const n=Number(v);if(Number.isFinite(n)&&n>0)return n<1e12?n*1000:n;const t=new Date(v).getTime();return Number.isFinite(t)?t:0};
function groupFirstPublishedMs(g){
  // Monitoring discovery is not a valid source publication timestamp.
  const annotated=timeMs(g?.propertyFirstPublishedAt);
  if(annotated>0&&g?.propertyFirstPublishedBasis!=='earliest_monitor_seen_fallback')return annotated;
  const originals=[];
  const walk=x=>{if(!x)return;for(const k of ['sourcePublishedAt','postTime']){const p=timeMs(x[k]);if(p>0)originals.push(p)}for(const m of (x.mergedListings||[]))walk(m);};
  walk(g);for(const m of (g?.sourceListings||[]))walk(m);
  return originals.length?Math.min(...originals):0;
}
const isNew=x=>{const first=groupFirstPublishedMs(x);const days=Number(GAP.newListingWindowDays??7);const age=Date.now()-first;return first>0&&Number.isFinite(days)&&days>0&&age>=0&&age<days*86400000;}'''
policy_start = text.find('const timeMs=v=>')
if policy_start < 0:
    policy_start = text.find('const isNew=')
policy_end = text.find('const cmp=', policy_start) if policy_start >= 0 else -1
if policy_start < 0 or policy_end < 0:
    raise RuntimeError('Preview sale new-listing policy anchor missing')
text = text[:policy_start] + sale_new_policy + '\n' + text[policy_end:]
text = re.sub(
    r"function sortGroups\(items,mode\)\{.*?\}(?=\nfunction render\()",
    "function sortGroups(items,mode){const a=[...items];if(mode==='default')return a;const key=mode.startsWith('price')?priceValue:groupFirstPublishedMs;const dir=mode.endsWith('Desc')?-1:1;return a.sort((x,y)=>(key(x)-key(y))*dir)}",
    text,
    count=1,
    flags=re.S,
)
if 'function groupFirstPublishedMs(g)' not in text or 'GAP.newListingWindowDays??7' not in text:
    raise RuntimeError('Preview property-level 3-day new-listing policy missing')

text = re.sub(r'\n<p>同一戶若同時出現在信義房屋與 591，Preview 會優先以信義資料顯示，591 收進同一戶下方；整併完成後再依坪數、價格、案名與樓層比對公司庫存。</p>', '', text)
text = re.sub(r'\n<div class="company-note" id="companyNote">.*?</div>', '', text, count=1, flags=re.S)
text = text.replace('\n<div id="companyNote" hidden></div>', '')
text = re.sub(r"const conflict=GAP\.companyConflictDowngradedCount\?\?0;.*?(?=document\.querySelector\('#updated'\))", '', text, count=1, flags=re.S)
text = re.sub(r";const covered=GAP\.coveredRoads\|\|\[\];cards\.push\(.*?\);document\.querySelector\('#sources'\)\.innerHTML=cards\.join\(''\);", ";document.querySelector('#sources').innerHTML=cards.join('');", text, count=1, flags=re.S)
text = re.sub(r"document\.querySelector\('#mRaw'\)\.textContent=`\$\{GAP\.rawListingCount\?\?GAP\.externalActiveCount\?\?0\} 筆`;", "document.querySelector('#mNew').textContent=`${groups.filter(isNew).length} 戶`;", text, count=1)
text = re.sub(r"document\.querySelector\('#mMerged'\)\.textContent=`\$\{GAP\.crossPlatformMergedGroupCount\?\?0\} 戶`;", "document.querySelector('#mMerged').textContent=`${GAP.rawListingCount??GAP.externalActiveCount??0} 筆`;", text, count=1)

# Never draw sale results over the rental screen while asynchronous
# source snapshots are completing. This is safe even if render() is
# invoked by another UI callback after switching markets.
text = text.replace(
    "function render(){const roads=DATA.watchRoads||defaultRoads;",
    "function render(){if(MARKET_MODE==='rent'){renderRent();return;}const roads=DATA.watchRoads||defaultRoads;",
    1,
)

text = text.replace(
    "let DATA={listings:[],runs:{},watchRoads:defaultRoads};let GAP={propertyGroups:[],comparisons:[],counts:{},coveredRoads:[]};let CMAP=new Map();let SOURCE_FILTER='all';",
    "let DATA={listings:[],runs:{},watchRoads:defaultRoads};let GAP={propertyGroups:[],comparisons:[],counts:{},coveredRoads:[]};let VERIFY=null;let CMAP=new Map();let SOURCE_FILTER='all';",
)

company_candidate_fn = r'''function candidateLine(g){
  const c=cmp(g);
  if(!c||!c.companyCandidate||!['company_match','review'].includes(c.status))return '';
  const y=c.companyCandidate;
  const link=y.url?`<a href="${esc(y.url)}" target="_blank" rel="noopener noreferrer">${esc(y.title||y.id)}</a>`:esc(y.title||y.id);
  const id=y.officialCaseId||y.officialId||String(y.id||'').replace(/^YC:/,'');
  return `<div class="row candidate">比對庫存：<span class="pill primary">永慶 ID ${esc(id||'-')}</span>${link}${y.price!=null?`｜${esc(y.price)}萬`:''}${y.area!=null?`｜${esc(y.area)}坪`:''}${y.floor?`｜${esc(y.floor)}`:'｜樓層未取得'}</div>`;
}'''
text = re.sub(r"function candidateLine\(g\)\{.*?\}(?=\nfunction sortGroups)", company_candidate_fn, text, count=1, flags=re.S)

runtime_loader = r'''function sameCounts(a,b){
  return ['company_match','review','missing','unavailable'].every(k=>Number((a||{})[k]??-1)===Number((b||{})[k]??-2));
}
function verificationMatches(d,g,v){
  return !!(d&&g&&v&&v.valid===true&&v.scheme==='A'&&v.canonicalPublisher==='yungching-preview.yml'&&
    v.integrityVersion==='scheme-a-canonical-v5-sinyi-rakuya-5168-floor-neartie'&&v.fetchMode==='yungching_official_rendered_dom_only'&&
    v.snapshotCapturedAt===g.companySnapshotCapturedAt&&v.companyGapGeneratedAt===g.generatedAt&&
    v.sourceDataUpdatedAt===g.sourceDataUpdatedAt&&d.updatedAt===g.sourceDataUpdatedAt&&
    Number(v.companyListingCount)===Number(g.companyListingCount)&&Number(v.propertyGroupCount)===Number(g.propertyGroupCount)&&
    Number(v.rawListingCount)===Number(g.rawListingCount)&&Number(v.comparisonCount)===Number((g.comparisons||[]).length)&&
    sameCounts(v.counts,g.counts)&&(v.sinyiFloorEnrichment||{}).complete===true&&
    g.preview591Warelist?.mode==='warelist_preview'&&
    v.preview591Warelist?.updatedAt===g.preview591Warelist?.updatedAt&&
    d.previewSources?.['591']?.updatedAt===g.preview591Warelist?.updatedAt);
}
async function fetchJson(url,label){
  const ctl=new AbortController();
  const timer=setTimeout(()=>ctl.abort(),12000);
  try{
    const r=await fetch(url,{cache:'no-store',signal:ctl.signal});
    if(!r.ok)throw new Error(`${label} HTTP ${r.status}`);
    return await r.json();
  }finally{clearTimeout(timer)}
}
Promise.all([
  fetchJson(`preview-monitor-state.json?ts=${Date.now()}`,'監控資料'),
  fetchJson(`company-gap.json?ts=${Date.now()}`,'比對資料'),
  fetchJson(`scheme-a-verification.json?ts=${Date.now()}`,'驗證資料'),
]).then(([d,g,v])=>{
  DATA=d; GAP=g; VERIFY=v;
  const verified=verificationMatches(DATA,GAP,VERIFY);
  if(!verified){
    GAP={...GAP,propertyGroups:[],comparisons:[],propertyGroupCount:0,rawListingCount:0,crossPlatformMergedGroupCount:0,counts:{company_match:0,review:0,missing:0,unavailable:0}};
  }
  CMAP=new Map((GAP.comparisons||[]).map(x=>[x.groupId,x]));
  // An in-flight sale fetch must not overwrite the currently selected rental UI.
  if(MARKET_MODE==='rent')renderRent();else render();
  if(!verified&&MARKET_MODE==='sale'){
    for(const id of ['mGroups','mNew','mMerged','cStock','cReview','cMissing','cUnavailable']){
      const el=document.getElementById(id); if(el)el.textContent='—';
    }
    document.querySelector('#groups').innerHTML='<div class="empty">比對資料同步中。為避免把上一輪案件誤當成最新結果，案件清單暫停顯示。</div>';
    document.querySelector('#updated').textContent=`來源資料最近更新：${fmt(DATA.updatedAt)}｜公司比對資料同步中，完成後會自動恢復顯示。`;
  }
}).catch(e=>{
  console.error(e);
  document.querySelector('#updated').textContent='Preview 資料讀取失敗，請重新整理後再試。';
  document.querySelector('#groups').innerHTML='<div class="empty">目前無法完整載入監控資料，為避免顯示錯誤比對結果，案件列表已暫停顯示。</div>';
});'''
text = re.sub(
    r"function verificationMatches\(g,v\)\{.*?\.catch\(e=>\{document\.querySelector\('#updated'\)\.textContent='Preview 資料讀取失敗：'\+e;\}\);",
    runtime_loader,
    text,
    count=1,
    flags=re.S,
)
if 'async function fetchJson(url,label)' not in text:
    text = re.sub(
        r"Promise\.all\(\[fetch\(`\.\./data/listings\.json\?ts=\$\{Date\.now\(\)\}`.*?\.catch\(e=>\{document\.querySelector\('#updated'\)\.textContent='Preview 資料讀取失敗：'\+e;\}\);",
        runtime_loader,
        text,
        count=1,
        flags=re.S,
    )

# Rewrite the existing modern loader too. The legacy patterns above can be
# no-ops on the current /preview/ page; never silently leave the canonical
# docs/data/listings.json URL in an apparently verified wareList Preview.
text, loader_rewrites = re.subn(
    r"function sameCounts\(a,b\)\{.*?\.catch\(e=>\{.*?\n\}\);",
    lambda match: runtime_loader,
    text,
    count=1,
    flags=re.S,
)
if loader_rewrites != 1:
    raise RuntimeError("Cannot locate original Preview runtime loader; refuse stale 591 data")
if "fetchJson(`../data/listings.json" in text:
    raise RuntimeError("Original Preview still references canonical 591 source")

# The canonical Preview page may already contain the modern fetchJson loader, so the
# legacy regex above can legitimately be a no-op. Force the runtime integrity guard
# to the current 5168-aware v5 value explicitly.
text = text.replace(
    "scheme-a-canonical-v4-sinyi-rakuya-floor-neartie",
    "scheme-a-canonical-v5-sinyi-rakuya-5168-floor-neartie",
)

required_fragments = [
    'id="mNew"',
    'id="mGroups"',
    'id="mMerged"',
    'function verificationMatches(d,g,v)',
    'async function fetchJson(url,label)',
    "d.updatedAt===g.sourceDataUpdatedAt",
    "d.previewSources?.[\'591\']?.updatedAt===g.preview591Warelist?.updatedAt",
    'propertyGroups:[]',
    '案件清單暫停顯示',
    'rel="noopener noreferrer"',
    'aria-live="polite"',
    'function groupFirstPublishedMs(g)',
    'GAP.newListingWindowDays??7',
]
missing = [x for x in required_fragments if x not in text]
if missing:
    raise RuntimeError(f'Preview UI patch contract failed; missing fragments: {missing}')
if 'id="companyNote"' in text or 'id="mRaw"' in text:
    raise RuntimeError('Preview UI patch contract failed; legacy UI fragments remain')

PATH.write_text(text, encoding='utf-8')

# Canonical ownership: every rebuild must recreate rental controls first, then layer
# the off-market renderer on top. Rental workflow is data-only and never owns index.html.
subprocess.run([sys.executable, 'scripts/patch_rental_preview_ui.py'], check=True)
subprocess.run([sys.executable, 'scripts/patch_offmarket_ui.py'], check=True)
subprocess.run([sys.executable, 'scripts/patch_rakuya_integrated_ui.py'], check=True)

final_text = PATH.read_text(encoding='utf-8')
# Source card freshness comes from independent verified platform snapshots,
# never from a newer unverified multi-platform comparison.
live_source_script = r'''
// Source health is independent of the property comparison snapshot.
// A newer verified 5168 or 591 capture updates only the four status cards;
// it must never replace GAP, comparisons, first-listing dates or delisting.
const liveSourceReports = {};
function applyLiveSourceReports(){
  if(MARKET_MODE!=='sale')return;
  const names=['591','信義房屋','樂屋網','5168'];
  const cards=[...document.querySelectorAll('#sources .source-card')];
  if(cards.length!==4)return;
  names.forEach((name,i)=>{
    const r=liveSourceReports[name];
    if(!r)return;
    const badge=cards[i].querySelector('.badge'),note=cards[i].querySelector('.note');
    if(!badge||!note)return;
    if(r.error){
      badge.className='badge stale';
      badge.textContent='狀態讀取失敗';
      return;
    }
    const ms=Date.parse(r.at||''),age=Date.now()-ms;
    const stale=!Number.isFinite(ms)||age < -300000||age>=240*60000;
    const ok=r.ok&&!stale;
    badge.className='badge '+(ok?'ok':stale?'stale':'err');
    badge.textContent=ok?'正常':stale?'資料過期':'異常/沿用';
    const homes=(GAP.propertyGroups||[]).filter(g=>(g.sources||[]).includes(name)).length;
    const count=Math.max(0,Number(r.count)||0);
    note.style.whiteSpace='pre-line';
    note.textContent='刊登 ID '+count+' 筆\n最近整併 '+homes+' 戶\n最近成功檢查：'+fmt(r.at)+(stale?'\n超過4小時未成功檢查，顯示上次有效資料':'');
  });
}
async function refreshLiveSourceReports(){
  const urls=[
    ['591','../591-preview/snapshot.json'],
    ['信義房屋','../data/listings.json'],
    ['樂屋網','rakuya-seven-roads.json'],
    ['5168','houseprice-seven-roads.json']
  ];
  await Promise.all(urls.map(async([name,path])=>{
    try{
      const data=await fetchJson(path+'?ts='+Date.now(),name+'來源狀態');
      let report;
      if(name==='591'){
        report={ok:data.complete===true&&data.mode==='warelist_preview',at:data.updatedAt,count:data.counts?.totalListings};
      }else if(name==='信義房屋'){
        const src=data.runs?.['信義房屋']||{};
        report={ok:src.status==='ok',at:src.checkedAt,count:src.totalCount};
      }else{
        report={ok:data.complete===true,at:data.updatedAt,count:data.uniqueListingCount??data.totalCount};
      }
      const date=Date.parse(report.at||'');
      if(!Number.isFinite(date)||!Number.isFinite(Number(report.count))||Number(report.count)<0){
        report={error:true};
      }
      liveSourceReports[name]=report;
    }catch(e){
      console.warn('Source status read failed:',name,e);
      liveSourceReports[name]={error:true};
    }
    applyLiveSourceReports();
  }));
}
'''
if "function refreshLiveSourceReports()" not in final_text:
    anchor = "function sameCounts(a,b){"
    if anchor not in final_text:
        raise RuntimeError("Source health insertion anchor absent")
    final_text = final_text.replace(anchor, live_source_script + anchor, 1)
sale_section_start=final_text.find("function render(){")
sale_section_end=final_text.find("function monitorRunMs()",sale_section_start)
if sale_section_start < 0 or sale_section_end < sale_section_start:
    raise RuntimeError("Source health sale renderer boundaries absent")
sale_section=final_text[sale_section_start:sale_section_end]
source_card_anchor="document.querySelector('#sources').innerHTML=cards.join('');"
if source_card_anchor not in sale_section:
    raise RuntimeError("Source health sale card anchor absent")
if "applyLiveSourceReports();" not in sale_section:
    sale_section=sale_section.replace(source_card_anchor,source_card_anchor+"applyLiveSourceReports();",1)
    final_text=final_text[:sale_section_start]+sale_section+final_text[sale_section_end:]
loader_anchor = "  render();\n  if(!verified){"
if loader_anchor not in final_text:
    raise RuntimeError("Source health verified loader anchor missing")
if "  refreshLiveSourceReports();\n  if(!verified){" not in final_text:
    final_text=final_text.replace(loader_anchor,"  render();\n  refreshLiveSourceReports();\n  if(!verified){",1)
if "function refreshLiveSourceReports()" not in final_text:
    raise RuntimeError("Source health status script was not installed")
PATH.write_text(final_text, encoding="utf-8")


# Layer patches must never regress the runtime guard back to the pre-5168 v4 value.
if "scheme-a-canonical-v4-sinyi-rakuya-floor-neartie" in final_text:
    final_text = final_text.replace(
        "scheme-a-canonical-v4-sinyi-rakuya-floor-neartie",
        "scheme-a-canonical-v5-sinyi-rakuya-5168-floor-neartie",
    )
    PATH.write_text(final_text, encoding='utf-8')
if "scheme-a-canonical-v5-sinyi-rakuya-5168-floor-neartie" not in final_text:
    raise RuntimeError("Canonical Preview UI composition failed; v5 integrity guard missing")
if "scheme-a-canonical-v4-sinyi-rakuya-floor-neartie" in final_text:
    raise RuntimeError("Canonical Preview UI composition failed; stale v4 integrity guard remains")
if final_text.count("function verificationMatches(") != 1:
    raise RuntimeError("Canonical Preview UI composition failed; duplicate verificationMatches runtime")
final_required = [
    'id="marketSwitch"',
    'data-market="sale"',
    'data-market="rent"',
    'function renderRentGroups()',
    'rental-data.json',
    'id="companyPanel"',
    '<option value="removed">已下架</option>',
    'GAP.recentOffMarketGroups||[]',
    '下架：${fmt(g.removedAt)}',
    'data-source="rakuya"',
    'data-source="houseprice"',
    'GAP.rakuyaSnapshot',
    'GAP.housepriceSnapshot',
    'function sourceClass(s)',
    '跨平台整併',
    'function groupFirstPublishedMs(g)',
    'GAP.newListingWindowDays??7',
]
final_missing = [x for x in final_required if x not in final_text]
if final_missing:
    raise RuntimeError(f'Canonical Preview UI composition failed; missing fragments: {final_missing}')
if 'id="rakuyaPanel"' in final_text or 'rakuya-widget.js' in final_text:
    raise RuntimeError('Canonical Preview UI composition failed; standalone Rakuya UI remains')

if 'id="r420Panel"' in final_text or 'r420-widget.js' in final_text or 'r420-widget.css' in final_text:
    raise RuntimeError('Removed R420 standalone panel must not reappear in Preview')

print('Preview UI patched with rental + off-market + integrated Rakuya composition (R420 panel removed)')

try:
    import validate_scheme_a_preview_v3 as validator
    validator.main()
except Exception as exc:
    try:
        with RUN_LOG.open('a', encoding='utf-8') as f:
            f.write(f"\nVALIDATION_ERROR {type(exc).__name__}: {exc}\n")
    except Exception:
        pass
    raise
