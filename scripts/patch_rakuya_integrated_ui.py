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
        "const hp=GAP.housepriceSnapshot||{},hpSourceOK=hp.complete===true&&hp.status==='ok',hpAge=Date.now()-Date.parse(hp.updatedAt||''),hpStale=hpSourceOK&&(!Number.isFinite(hpAge)||hpAge < -300000||hpAge>=240*60000),hpOk=hpSourceOK&&!hpStale;"
        "cards.push(`<div class=\"source-card\"><div class=\"source-head\"><strong>5168</strong><span class=\"badge ${hpStale?'err':hpOk?'ok':'err'}\">${hpStale?'資料過期':hpOk?'正常':'異常/沿用'}</span></div><div class=\"note\">目前刊登 ${hp.totalCount??0} 筆<br>最近更新：${fmt(hp.updatedAt)}${hpStale?'<br>已超過4小時未成功更新，顯示上次成功資料':''}</div></div>`);"
    )
if injection:
    text = text.replace(source_anchor, injection + source_anchor, 1)

# Separate source advertising IDs from merged property counts. The 591 run's
# totalCount is a property estimate, not the count of verified wareList IDs.
# All four sale sources must use the same two explicit units.
count_hook = "const cards=['591','信義房屋'].map(name=>"
count_helper = (
    "const saleSourceIdCount=name=>name==='591'?"
    "(DATA.previewSources?.['591']?.uniqueListingCount??DATA.runs?.['591']?.observedListingIdCount??DATA.runs?.['591']?.totalCount??0):"
    "name==='信義房屋'?(DATA.runs?.['信義房屋']?.totalCount??0):"
    "name==='樂屋網'?(GAP.rakuyaSnapshot?.uniqueListingCount??GAP.rakuyaSnapshot?.totalCount??0):"
    "(GAP.housepriceSnapshot?.uniqueListingCount??GAP.housepriceSnapshot?.totalCount??0);"
    "const saleGroupCount=name=>groups.filter(g=>(g.sources||[]).includes(name)).length;"
)
if count_hook not in text:
    raise RuntimeError("Sale source card count anchor missing")
if "const saleSourceIdCount=" not in text:
    text = text.replace(count_hook, count_helper + count_hook, 1)
text = text.replace(
    "目前刊登 ${r?.totalCount??0} 筆<br>最近更新",
    "刊登 ID ${saleSourceIdCount(name)} 筆<br>涉及整併 ${saleGroupCount(name)} 戶<br>最近更新",
    1,
)
text = text.replace(
    "目前刊登 ${rk.totalCount??0} 筆<br>最近更新",
    "刊登 ID ${saleSourceIdCount('樂屋網')} 筆<br>涉及整併 ${saleGroupCount('樂屋網')} 戶<br>最近更新",
    1,
)
text = text.replace(
    "目前刊登 ${hp.totalCount??0} 筆<br>最近更新",
    "刊登 ID ${saleSourceIdCount('5168')} 筆<br>涉及整併 ${saleGroupCount('5168')} 戶<br>最近更新",
    1,
)
if any(x not in text for x in (
    "saleSourceIdCount(name)", "saleGroupCount(name)",
    "saleGroupCount('樂屋網')", "saleGroupCount('5168')"
)):
    raise RuntimeError("Sale source ID vs property count labels missing")


# Upgrade existing 5168 card as well as new injected cards. Idempotent,
# because the canonical Preview is rebuilt from its already-patched HTML.
hp_old_declaration = "const hp=GAP.housepriceSnapshot||{},hpOk=hp.complete===true&&hp.status==='ok';"
hp_new_declaration = "const hp=GAP.housepriceSnapshot||{},hpSourceOK=hp.complete===true&&hp.status==='ok',hpAge=Date.now()-Date.parse(hp.updatedAt||''),hpStale=hpSourceOK&&(!Number.isFinite(hpAge)||hpAge < -300000||hpAge>=240*60000),hpOk=hpSourceOK&&!hpStale;"
text = text.replace(hp_old_declaration, hp_new_declaration)
# Upgrade older already-patched Preview pages, not only the first installation.
text = text.replace("hpAge>=90*60000", "hpAge>=240*60000")
text = text.replace("已超過90分鐘未成功更新", "已超過4小時未成功更新")
text = text.replace("${hpOk?'正常':'異常/沿用'}", "${hpStale?'資料過期':hpOk?'正常':'異常/沿用'}")
# Scope the class-name replacement to the single 5168 card when present.
text = text.replace(
    '<strong>5168</strong><span class="badge ${hpOk?\'ok\':\'err\'}">',
    '<strong>5168</strong><span class="badge ${hpStale?\'err\':hpOk?\'ok\':\'err\'}">'
)
text = text.replace(
    "最近更新：${fmt(hp.updatedAt)}</div></div>","最近更新：${fmt(hp.updatedAt)}${hpStale?'<br>已超過4小時未成功更新，顯示上次成功資料':''}</div></div>"
)
if "hpStale" not in text:
    raise RuntimeError("5168 freshness status rule missing from Preview UI")

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

# Render the verified 591 listing fields inside the existing group detail
# accordion. Do not infer floor from title or append unverified addresses.
source_date_anchor = "<span>${sourcePublishedText(m)}</span>"
source_591_extra = "${m.source==='591'&&m.structuredFloor?`<span>591來源樓層：${esc(m.structuredFloor)}</span>`:''}${m.source==='591'&&m.structuredLayout?`<span>房型：${esc(m.structuredLayout)}</span>`:''}${m.source==='591'&&m.structuredCommunity?`<span>社區：${esc(m.structuredCommunity)}</span>`:''}"
if source_date_anchor in text and "591來源樓層：" not in text:
    text = text.replace(source_date_anchor, source_date_anchor + source_591_extra, 1)
if "591來源樓層：" not in text:
    raise RuntimeError("591 structured detail UI anchor missing")

nested_anchor = "${esc(n.price||'')} ${esc(n.size||'')}</li>"
nested_extra = "${n.structuredFloor?`｜樓層：${esc(n.structuredFloor)}`:''}${n.structuredLayout?`｜房型：${esc(n.structuredLayout)}`:''}"
if nested_anchor in text and "｜房型：" not in text:
    text = text.replace(nested_anchor, "${esc(n.price||'')} ${esc(n.size||'')}" + nested_extra + "</li>", 1)

# Always show the property-level earliest known publication date, not when
# our monitor discovered it. Source-level "上架" dates remain in the accordion.
earliest_anchor = "<span>${esc(g.address||'-')}</span>${removedLine}</div>"
earliest_label = "首次上架："
# Remove only the parenthetical wording, keeping the verified earliest date.
text = text.replace("首次上架（最早已知）：", earliest_label)
earliest_badge = "<span>首次上架：${groupFirstPublishedMs(g)>0?fmt(groupFirstPublishedMs(g)):'日期未取得'}</span>"
if earliest_anchor in text and earliest_label not in text:
    text = text.replace(earliest_anchor, "<span>${esc(g.address||'-')}</span>${removedLine}" + earliest_badge + "</div>", 1)
if earliest_label not in text:
    raise RuntimeError("Property first publication UI anchor missing")

PATH.write_text(text, encoding="utf-8")
print("Rakuya + 5168 integrated into main 591/Sinyi Preview UI")
