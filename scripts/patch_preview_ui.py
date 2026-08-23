from pathlib import Path
import json
import re

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
}
for old, new in replacements.items():
    text = text.replace(old, new)

text = re.sub(r'\n<p>同一戶若同時出現在信義房屋與 591，Preview 會優先以信義資料顯示，591 收進同一戶下方；整併完成後再依坪數、價格、案名與樓層比對公司庫存。</p>', '', text)
text = re.sub(r'\n<div class="company-note" id="companyNote">.*?</div>', '', text, count=1, flags=re.S)
text = text.replace('\n<div id="companyNote" hidden></div>', '')
text = re.sub(r"const conflict=GAP\.companyConflictDowngradedCount\?\?0;.*?(?=document\.querySelector\('#updated'\))", '', text, count=1, flags=re.S)
text = re.sub(r";const covered=GAP\.coveredRoads\|\|\[\];cards\.push\(.*?\);document\.querySelector\('#sources'\)\.innerHTML=cards\.join\(''\);", ";document.querySelector('#sources').innerHTML=cards.join('');", text, count=1, flags=re.S)
text = re.sub(r"document\.querySelector\('#mRaw'\)\.textContent=`\$\{GAP\.rawListingCount\?\?GAP\.externalActiveCount\?\?0\} 筆`;", "document.querySelector('#mNew').textContent=`${groups.filter(isNew).length} 戶`;", text, count=1)
text = re.sub(r"document\.querySelector\('#mMerged'\)\.textContent=`\$\{GAP\.crossPlatformMergedGroupCount\?\?0\} 戶`;", "document.querySelector('#mMerged').textContent=`${GAP.rawListingCount??GAP.externalActiveCount??0} 筆`;", text, count=1)

text = text.replace(
    "let DATA={listings:[],runs:{},watchRoads:defaultRoads};let GAP={propertyGroups:[],comparisons:[],counts:{},coveredRoads:[]};let CMAP=new Map();let SOURCE_FILTER='all';",
    "let DATA={listings:[],runs:{},watchRoads:defaultRoads};let GAP={propertyGroups:[],comparisons:[],counts:{},coveredRoads:[]};let VERIFY=null;let CMAP=new Map();let SOURCE_FILTER='all';",
)

company_candidate_fn = r'''function candidateLine(g){
  const c=cmp(g);
  if(!c||!c.companyCandidate||!['company_match','review'].includes(c.status))return '';
  const y=c.companyCandidate;
  const link=y.url?`<a href="${esc(y.url)}" target="_blank" rel="noreferrer">${esc(y.title||y.id)}</a>`:esc(y.title||y.id);
  const id=y.officialCaseId||y.officialId||String(y.id||'').replace(/^YC:/,'');
  return `<div class="row candidate">比對庫存：<span class="pill primary">永慶 ID ${esc(id||'-')}</span>${link}${y.price!=null?`｜${esc(y.price)}萬`:''}${y.area!=null?`｜${esc(y.area)}坪`:''}${y.floor?`｜${esc(y.floor)}`:'｜樓層未取得'}</div>`;
}'''
text = re.sub(r"function candidateLine\(g\)\{.*?\}(?=\nfunction sortGroups)", company_candidate_fn, text, count=1, flags=re.S)

runtime_loader = r'''function verificationMatches(g,v){
  return !!(g&&v&&v.valid===true&&v.scheme==='A'&&v.canonicalPublisher==='yungching-preview.yml'&&
    v.snapshotCapturedAt===g.companySnapshotCapturedAt&&v.companyGapGeneratedAt===g.generatedAt&&
    Number(v.companyListingCount)===Number(g.companyListingCount)&&Number(v.propertyGroupCount)===Number(g.propertyGroupCount));
}
Promise.all([
  fetch(`../data/listings.json?ts=${Date.now()}`,{cache:'no-store'}).then(r=>r.json()),
  fetch(`company-gap.json?ts=${Date.now()}`,{cache:'no-store'}).then(r=>r.ok?r.json():null),
  fetch(`scheme-a-verification.json?ts=${Date.now()}`,{cache:'no-store'}).then(r=>r.ok?r.json():null),
]).then(([d,g,v])=>{
  DATA=d; VERIFY=v;
  if(g)GAP=g;
  const verified=verificationMatches(GAP,VERIFY);
  if(!verified){
    const n=Number(GAP.propertyGroupCount??(GAP.propertyGroups||[]).length)||0;
    GAP={...GAP,comparisons:[],counts:{company_match:0,review:0,missing:0,unavailable:n}};
  }
  CMAP=new Map((GAP.comparisons||[]).map(x=>[x.groupId,x]));
  render();
  if(!verified){
    document.querySelector('#updated').textContent=`來源資料最近更新：${fmt(DATA.updatedAt)}｜公司比對完整性驗證未通過，暫不顯示委託狀態。`;
  }
}).catch(e=>{document.querySelector('#updated').textContent='Preview 資料讀取失敗：'+e;});'''
text = re.sub(
    r"Promise\.all\(\[fetch\(`\.\./data/listings\.json\?ts=\$\{Date\.now\(\)\}`.*?\.catch\(e=>\{document\.querySelector\('#updated'\)\.textContent='Preview 資料讀取失敗：'\+e;\}\);",
    runtime_loader,
    text,
    count=1,
    flags=re.S,
)

PATH.write_text(text, encoding='utf-8')
print('Preview UI patched')

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
