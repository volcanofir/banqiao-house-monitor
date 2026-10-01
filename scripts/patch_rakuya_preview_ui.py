from pathlib import Path
import re

PATH=Path("docs/preview/index.html")
text=PATH.read_text(encoding="utf-8")

text=re.sub(r'rakuya-widget\.css\?v=[^"\']+','rakuya-widget.css?v=20261001-1',text)
text=re.sub(r'rakuya-widget\.js\?v=[^"\']+','rakuya-widget.js?v=20261001-1',text)

css_tag='<link rel="stylesheet" href="rakuya-widget.css?v=20261001-1" />'
if css_tag not in text:
    text=text.replace("</head>",css_tag+"\n</head>",1)

section='''
<section class="panel rk-panel" id="rakuyaPanel" hidden>
  <div class="stripe"></div>
  <div class="inside">
    <div class="eyebrow">RAKUYA ROAD TRACKING</div>
    <h2>樂屋網｜七路段監控</h2>
    <div class="note">Preview 專用。完整抓取中山路二段、三民路一段、三民路二段、翠華街、林森街、萬安街、光復街。各路段預設收合；同一實體房屋若有不同仲介刊登，會分開計算。</div>
    <div class="rk-summary">
      <div class="rk-stat"><span>監控路段</span><strong id="rkRoadCount">-</strong></div>
      <div class="rk-stat"><span>目前刊登</span><strong id="rkListingCount">-</strong></div>
      <div class="rk-stat"><span>本次新進</span><strong id="rkNewCount">-</strong></div>
      <div class="rk-stat"><span>本次異動</span><strong id="rkChangeCount">-</strong></div>
    </div>
    <div class="rk-chips" id="rkChips"></div>
    <div class="rk-tools">
      <select id="rkRoad"><option value="all">全部路段</option></select>
      <select id="rkState">
        <option value="all">全部案件</option>
        <option value="new">本次新進</option>
        <option value="price">價格異動</option>
        <option value="removed">本次下架</option>
      </select>
      <input id="rkSearch" type="search" placeholder="搜尋案名或路段" autocomplete="off" />
    </div>
    <div class="note" id="rkUpdated">正在讀取樂屋七路段資料…</div>
    <div id="rkGroups"></div>
  </div>
</section>
'''
if 'id="rakuyaPanel"' not in text:
    text=text.replace("</main>",section+"\n</main>",1)

js_tag='<script src="rakuya-widget.js?v=20261001-1"></script>'
if js_tag not in text:
    text=text.replace("</body>",js_tag+"\n</body>",1)

required=[
    'id="rakuyaPanel"',
    'id="rkRoadCount"',
    'id="rkListingCount"',
    'id="rkRoad"',
    'rakuya-widget.css',
    'rakuya-widget.js',
]
missing=[x for x in required if x not in text]
if missing:
    raise RuntimeError(f"Rakuya Preview patch contract failed: {missing}")

PATH.write_text(text,encoding="utf-8")
print("Rakuya seven-road section added to Preview bottom")
