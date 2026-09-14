from pathlib import Path

PATH = Path('docs/preview/index.html')
text = PATH.read_text(encoding='utf-8')

css = r'''
.compare-card strong.metric-filter-link{cursor:pointer;text-decoration:underline;text-decoration-thickness:2px;text-underline-offset:4px}
.compare-card strong.metric-filter-link:focus-visible{outline:3px solid #124b37;outline-offset:4px;border-radius:8px}
'''
if '.compare-card strong.metric-filter-link{' not in text:
    text = text.replace('</style>', css + '\n</style>', 1)

js = r'''
function showCompanyMetricFilter(kind){
  if(typeof MARKET_MODE!=='undefined'&&MARKET_MODE!=='sale'&&typeof setMarket==='function')setMarket('sale');
  SOURCE_FILTER='all';
  document.querySelectorAll('.source-tab').forEach(btn=>btn.classList.toggle('active',btn.dataset.source==='all'));
  const state=document.querySelector('#state');
  const company=document.querySelector('#companyState');
  if(!state||!company)return;
  if(kind==='review'){
    state.value='all';
    company.value='review';
  }else if(kind==='removed'){
    state.value='removed';
    company.value='all';
  }else{
    return;
  }
  renderGroups();
  document.querySelector('#listTitle')?.scrollIntoView({behavior:'smooth',block:'start'});
}
function bindCompanyMetricFilters(){
  const targets=[
    ['cReview','review','查看待確認案件'],
    ['cUnavailable','removed','查看已下架案件'],
  ];
  for(const [id,kind,label] of targets){
    const el=document.getElementById(id);
    if(!el||el.dataset.metricFilterBound==='1')continue;
    el.dataset.metricFilterBound='1';
    el.classList.add('metric-filter-link');
    el.setAttribute('role','button');
    el.setAttribute('tabindex','0');
    el.setAttribute('aria-label',label);
    el.addEventListener('click',()=>showCompanyMetricFilter(kind));
    el.addEventListener('keydown',event=>{
      if(event.key!=='Enter'&&event.key!==' ')return;
      event.preventDefault();
      showCompanyMetricFilter(kind);
    });
  }
}
bindCompanyMetricFilters();
'''
if 'function showCompanyMetricFilter(kind)' not in text:
    idx = text.rfind('</script>')
    if idx < 0:
        raise RuntimeError('Metric filter shortcut patch failed: closing script tag not found')
    text = text[:idx] + js + '\n' + text[idx:]

required = [
    '.compare-card strong.metric-filter-link{',
    'function showCompanyMetricFilter(kind)',
    'function bindCompanyMetricFilters()',
    "['cReview','review','查看待確認案件']",
    "['cUnavailable','removed','查看已下架案件']",
    "state.value='all';",
    "company.value='review';",
    "state.value='removed';",
    "company.value='all';",
    "SOURCE_FILTER='all';",
    "scrollIntoView({behavior:'smooth',block:'start'})",
    'bindCompanyMetricFilters();',
]
missing = [x for x in required if x not in text]
if missing:
    raise RuntimeError(f'Metric filter shortcut Preview patch contract failed: {missing}')

PATH.write_text(text, encoding='utf-8')
print('Preview company metric counts patched as clickable filter shortcuts')
