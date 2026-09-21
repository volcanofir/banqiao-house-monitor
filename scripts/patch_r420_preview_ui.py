from pathlib import Path
import re

PATH = Path('docs/preview/index.html')
text = PATH.read_text(encoding='utf-8')


text = text.replace('Preview 專用。案件依行政區收整，板橋區優先顯示；各區預設收合，避免 72 筆案件把頁面拉太長。','Preview 專用。案件分成埔墘區、板橋區、其他行政區三類，各區預設收合。')
text = text.replace('<div class="r420-stat"><span>板橋區</span><strong id="r420Banqiao">-</strong></div>\n      <div class="r420-stat"><span>核心 7 路段</span><strong id="r420Core">-</strong></div>\n      <div class="r420-stat"><span>本次異動</span><strong id="r420Changes">-</strong></div>', '<div class="r420-stat"><span>埔墘區</span><strong id="r420Puqian">-</strong></div>\n      <div class="r420-stat"><span>板橋區</span><strong id="r420Banqiao">-</strong></div>\n      <div class="r420-stat"><span>其他行政區</span><strong id="r420Other">-</strong></div>\n      <div class="r420-stat"><span>本次異動</span><strong id="r420Changes">-</strong></div>')
text = text.replace('<select id="r420District"><option value="all">全部地區</option></select>', '<select id="r420District"><option value="all">全部區域</option></select>')

text = re.sub(r'r420-widget\.css\?v=[^"\']+', 'r420-widget.css?v=20260921-3', text)
text = re.sub(r'r420-widget\.js\?v=[^"\']+', 'r420-widget.js?v=20260921-3', text)
css_tag = '<link rel="stylesheet" href="r420-widget.css?v=20260921-3" />'
if css_tag not in text:
    text = text.replace('</head>', css_tag + '\n</head>', 1)

section = '''
<section class="panel r420-panel" id="r420Panel" hidden>
  <div class="stripe"></div>
  <div class="inside">
    <div class="eyebrow">COMPETITOR STORE TRACKING</div>
    <h2>相對店追蹤｜信義板橋中山店 R420</h2>
    <div class="note">Preview 專用。案件分成埔墘區、板橋區、其他行政區三類，各區預設收合。</div>
    <div class="r420-summary">
      <div class="r420-stat"><span>目前刊登</span><strong id="r420Total">-</strong></div>
      <div class="r420-stat"><span>埔墘區</span><strong id="r420Puqian">-</strong></div>
      <div class="r420-stat"><span>板橋區</span><strong id="r420Banqiao">-</strong></div>
      <div class="r420-stat"><span>其他行政區</span><strong id="r420Other">-</strong></div>
      <div class="r420-stat"><span>本次異動</span><strong id="r420Changes">-</strong></div>
    </div>
    <div class="r420-region-chips" id="r420RegionChips"></div>
    <div class="r420-tools">
      <select id="r420District"><option value="all">全部區域</option></select>
      <select id="r420State"><option value="all">全部案件</option><option value="new">本次新進</option><option value="price">價格異動</option><option value="removed">本次下架</option></select>
      <input id="r420Search" type="search" placeholder="搜尋案名、地址、物件編號" autocomplete="off" />
    </div>
    <div class="note" id="r420Updated">正在讀取 R420 資料…</div>
    <div id="r420Groups"></div>
  </div>
</section>
'''
if 'id="r420Panel"' not in text:
    text = text.replace('</main>', section + '\n</main>', 1)

js_tag = '<script src="r420-widget.js?v=20260921-3"></script>'
if js_tag not in text:
    text = text.replace('</body>', js_tag + '\n</body>', 1)

required = ['id="r420Panel"','id="r420Total"','id="r420Puqian"','id="r420Banqiao"','id="r420Other"','id="r420District"','r420-widget.css','r420-widget.js']
missing = [x for x in required if x not in text]
if missing:
    raise RuntimeError(f'R420 Preview UI patch contract failed: {missing}')

PATH.write_text(text, encoding='utf-8')
print('R420 competitor-store section added to Preview bottom')