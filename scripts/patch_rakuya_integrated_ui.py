from pathlib import Path
import re

PATH = Path("docs/preview/index.html")
text = PATH.read_text(encoding="utf-8")

# Remove the old standalone Rakuya widget if an older generated HTML still has it.
text = re.sub(r'\n?<section class="panel rk-panel" id="rakuyaPanel".*?</section>\s*', '\n', text, flags=re.S)
text = re.sub(r'\n?<link rel="stylesheet" href="rakuya-widget\.css\?v=[^"]+"\s*/>\s*', '\n', text)
text = re.sub(r'\n?<script src="rakuya-widget\.js\?v=[^"]+"></script>\s*', '\n', text)

text = text.replace("比對591、信義刊登案件", "比對591、信義、樂屋、5168刊登案件")
text = text.replace("比對591、信義、樂屋刊登案件", "比對591、信義、樂屋、5168刊登案件")

# Sale source cards: 591 / Sinyi / Rakuya / 5168. Tabs include "all", hence 5.
text = text.replace(".source-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}", ".source-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}")
text = text.replace(".source-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}", ".source-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}")
text = text.replace(".source-tabs{grid-column:1/-1;display:grid;grid-template-columns:repeat(3,1fr);gap:8px}", ".source-tabs{grid-column:1/-1;display:grid;grid-template-columns:repeat(5,1fr);gap:8px}")
text = text.replace(".source-tabs{grid-column:1/-1;display:grid;grid-template-columns:repeat(4,1fr);gap:8px}", ".source-tabs{grid-column:1/-1;display:grid;grid-template-columns:repeat(5,1fr);gap:8px}")
text = text.replace(".source-tabs{grid-column:1;grid-template-columns:repeat(3,1fr)}", ".source-tabs{grid-column:1;grid-template-columns:repeat(5,1fr)}")
text = text.replace(".source-tabs{grid-column:1;grid-template-columns:repeat(4,1fr)}", ".source-tabs{grid-column:1;grid-template-columns:repeat(5,1fr)}")

if ".pill.rakuya{" not in text:
    text = text.replace(".pill.m591{background:#e8eef9;color:#35577d}", ".pill.m591{background:#e8eef9;color:#35577d}.pill.rakuya{background:#f2e8ff;color:#6f3f91}")
if ".pill.houseprice{" not in text:
    text = text.replace(".pill.rakuya{background:#f2e8ff;color:#6f3f91}", ".pill.rakuya{background:#f2e8ff;color:#6f3f91}.pill.houseprice{background:#fff0d9;color:#8a5316}")

if 'data-source="rakuya"' not in text:
    text = text.replace(
        '<button type="button" class="source-tab" data-source="591">591</button>',
        '<button type="button" class="source-tab" data-source="591">591</button>\n<button type="button" class="source-tab" data-source="rakuya">樂屋</button>',
        1,
    )
if 'data-source="houseprice"' not in text:
    text = text.replace(
        '<button type="button" class="source-tab" data-source="rakuya">樂屋</button>',
        '<button type="button" class="source-tab" data-source="rakuya">樂屋</button>\n<button type="button" class="source-tab" data-source="houseprice">5168</button>',
        1,
    )

# Upgrade the old two-source sourcePills function, or extend the existing integrated one.
text = re.sub(
    r"function sourcePills\(g\)\{return \(g\.sources\|\|\[\]\)\.map\(s=>`<span class=\"pill \\?\$\{s==='信義房屋'\?'sinyi':'m591'\}\">.*?</span>`\)\.join\(''\)\}",
    "function sourceClass(s){return s==='信義房屋'?'sinyi':s==='樂屋網'?'rakuya':s==='5168'?'houseprice':'m591'}\nfunction sourcePills(g){return (g.sources||[]).map(s=>`<span class=\"pill ${sourceClass(s)}\">${esc(s)}</span>`).join('')}",
    text,
    count=1,
)
text = text.replace(
    "function sourceClass(s){return s==='信義房屋'?'sinyi':s==='樂屋網'?'rakuya':'m591'}",
    "function sourceClass(s){return s==='信義房屋'?'sinyi':s==='樂屋網'?'rakuya':s==='5168'?'houseprice':'m591'}",
)
text = text.replace("${m.source==='信義房屋'?'sinyi':'m591'}", "${sourceClass(m.source)}")
text = text.replace("${m.source==='591'&&nested.length?`<span>591原始刊登 ${nested.length} 筆</span>`:''}", "${nested.length?`<span>${esc(m.source)}原始刊登 ${nested.length} 筆</span>`:''}")

# 5168 PriceAnalyze exposes newKeyInDate for the grouped property's first listing.
# Keep that semantic explicit; fall back to relative publishDaysTag only when absent.
old_fn = "function sourcePublishedText(m){if(m.source==='樂屋網'){if(m.rakuyaSourcePublishedDate)return `上架：${esc(m.rakuyaSourcePublishedDate)}`;if(m.sourcePublishedAt){const n=Number(m.sourcePublishedAt),d=new Date(Number.isFinite(n)?(n<1e12?n*1000:n):m.sourcePublishedAt);if(!Number.isNaN(d.getTime()))return `上架：${new Intl.DateTimeFormat('zh-TW',{dateStyle:'medium',timeZone:'Asia/Taipei'}).format(d)}`}return '上架：日期未取得'}return `上架：${fmtUnix(m.sourcePublishedAt)}`}"
new_fn = "function sourcePublishedText(m){if(m.source==='樂屋網'){if(m.rakuyaSourcePublishedDate)return `上架：${esc(m.rakuyaSourcePublishedDate)}`;if(m.sourcePublishedAt){const n=Number(m.sourcePublishedAt),d=new Date(Number.isFinite(n)?(n<1e12?n*1000:n):m.sourcePublishedAt);if(!Number.isNaN(d.getTime()))return `上架：${new Intl.DateTimeFormat('zh-TW',{dateStyle:'medium',timeZone:'Asia/Taipei'}).format(d)}`}return '上架：日期未取得'}if(m.source==='5168'){if(m.sourcePublishedAtType==='housepriceGroupNewKeyInDate'&&m.housepriceSourcePublishedDate)return `群組首次上架：${esc(m.housepriceSourcePublishedDate)}`;if(m.housepriceSourcePublishedDate)return `上架：約 ${esc(m.housepriceSourcePublishedDate)}（${esc(m.housepricePublishDaysTag||'來源相對標籤推算')}）`;return m.housepricePublishDaysTag?`上架：${esc(m.housepricePublishDaysTag)}`:'上架：日期未取得'}return `上架：${fmtUnix(m.sourcePublishedAt)}`}"
if old_fn in text:
    text = text.replace(old_fn, new_fn)
elif "function sourcePublishedText(m)" not in text:
    text = text.replace("function sourceDetails(g){const rows=", new_fn + "\nfunction sourceDetails(g){const rows=", 1)
text = text.replace("<span>上架：${fmtUnix(m.sourcePublishedAt)}</span>", "<span>${sourcePublishedText(m)}</span>")

source_anchor = "document.querySelector('#sources').innerHTML=cards.join('');"
if source_anchor not in text:
    raise RuntimeError("Integrated source UI: source-card anchor missing")

# Add only the source card that is actually missing. Re-injecting the Rakuya
# declaration into an already-integrated page would redeclare const rk and stop
# the whole Preview JavaScript before render().
injection = ""
if "GAP.rakuyaSnapshot" not in text:
    injection += (
        "const rk=GAP.rakuyaSnapshot||{},rkOk=rk.complete===true&&rk.status==='ok';"
        "cards.push(`<div class=\"source-card\"><div class=\"source-head\"><strong>樂屋網</strong><span class=\"badge ${rkOk?'ok':'err'}\">${rkOk?'正常':'異常/沿用'}</span></div><div class=\"note\">目前刊登 ${rk.totalCount??0} 筆<br>最近更新：${fmt(rk.updatedAt)}</div></div>`);"
    )
if "GAP.housepriceSnapshot" not in text:
    injection += (
        "const hp=GAP.housepriceSnapshot||{},hpOk=hp.complete===true&&hp.status==='ok';"
        "cards.push(`<div class=\"source-card\"><div class=\"source-head\"><strong>5168</strong><span class=\"badge ${hpOk?'ok':'err'}\">${hpOk?'正常':'異常/沿用'}</span></div><div class=\"note\">目前刊登 ${hp.totalCount??0} 筆<br>最近更新：${fmt(hp.updatedAt)}</div></div>`);"
    )
if injection:
    text = text.replace(source_anchor, injection + source_anchor, 1)

old_filter = "const sourceOK=source==='all'||(source==='sinyi'&&(g.sources||[]).includes('信義房屋'))||(source==='591'&&(g.sources||[]).includes('591'));"
rk_filter = "const sourceOK=source==='all'||(source==='sinyi'&&(g.sources||[]).includes('信義房屋'))||(source==='591'&&(g.sources||[]).includes('591'))||(source==='rakuya'&&(g.sources||[]).includes('樂屋網'));"
new_filter = "const sourceOK=source==='all'||(source==='sinyi'&&(g.sources||[]).includes('信義房屋'))||(source==='591'&&(g.sources||[]).includes('591'))||(source==='rakuya'&&(g.sources||[]).includes('樂屋網'))||(source==='houseprice'&&(g.sources||[]).includes('5168'));"
text = text.replace(old_filter, new_filter)
text = text.replace(rk_filter, new_filter)

text = text.replace("信義主資料＋591整併", "跨平台整併")

required = [
    'data-source="rakuya"', 'data-source="houseprice"',
    "GAP.rakuyaSnapshot", "GAP.housepriceSnapshot",
    "includes('樂屋網')", "includes('5168')",
    "function sourceClass(s)", "function sourcePublishedText(m)", "跨平台整併",
]
missing = [x for x in required if x not in text]
if missing:
    raise RuntimeError(f"Integrated source UI contract failed: {missing}")
if 'id="rakuyaPanel"' in text:
    raise RuntimeError("standalone Rakuya panel still present")

PATH.write_text(text, encoding="utf-8")
print("Rakuya + 5168 integrated into main 591/Sinyi Preview UI")
