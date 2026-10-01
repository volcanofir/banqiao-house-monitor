from pathlib import Path
import re

PATH = Path("docs/preview/index.html")
text = PATH.read_text(encoding="utf-8")

text = re.sub(r'\n?<section class="panel rk-panel" id="rakuyaPanel".*?</section>\s*', '\n', text, flags=re.S)
text = re.sub(r'\n?<link rel="stylesheet" href="rakuya-widget\.css\?v=[^"]+"\s*/>\s*', '\n', text)
text = re.sub(r'\n?<script src="rakuya-widget\.js\?v=[^"]+"></script>\s*', '\n', text)
text = text.replace("比對591、信義刊登案件", "比對591、信義、樂屋刊登案件")

text = text.replace(".source-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}", ".source-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}")
text = text.replace(".source-tabs{grid-column:1/-1;display:grid;grid-template-columns:repeat(3,1fr);gap:8px}", ".source-tabs{grid-column:1/-1;display:grid;grid-template-columns:repeat(4,1fr);gap:8px}")
text = text.replace(".source-tabs{grid-column:1;grid-template-columns:repeat(3,1fr)}", ".source-tabs{grid-column:1;grid-template-columns:repeat(4,1fr)}")
if ".pill.rakuya{" not in text:
    text = text.replace(".pill.m591{background:#e8eef9;color:#35577d}", ".pill.m591{background:#e8eef9;color:#35577d}.pill.rakuya{background:#f2e8ff;color:#6f3f91}")

if 'data-source="rakuya"' not in text:
    text = text.replace(
        '<button type="button" class="source-tab" data-source="591">591</button>',
        '<button type="button" class="source-tab" data-source="591">591</button>\n<button type="button" class="source-tab" data-source="rakuya">樂屋</button>',
        1,
    )

text = re.sub(
    r"function sourcePills\(g\)\{return \(g\.sources\|\|\[\]\)\.map\(s=>\`<span class=\"pill \$\{s==='信義房屋'\?'sinyi':'m591'\}\">.*?</span>\`\)\.join\(''\)\}",
    "function sourceClass(s){return s==='信義房屋'?'sinyi':s==='樂屋網'?'rakuya':'m591'}\nfunction sourcePills(g){return (g.sources||[]).map(s=>\`<span class=\"pill \${sourceClass(s)}\">\${esc(s)}</span>\`).join('')}",
    text,
    count=1,
)
text = text.replace("\${m.source==='信義房屋'?'sinyi':'m591'}", "\${sourceClass(m.source)}")
text = text.replace("\${m.source==='591'&&nested.length?\`<span>591原始刊登 \${nested.length} 筆</span>\`:''}", "\${nested.length?\`<span>\${esc(m.source)}原始刊登 \${nested.length} 筆</span>\`:''}")

source_anchor = "document.querySelector('#sources').innerHTML=cards.join('');"
if "GAP.rakuyaSnapshot" not in text:
    if source_anchor not in text:
        raise RuntimeError("Rakuya integrated UI: source-card anchor missing")
    text = text.replace(
        source_anchor,
        "const rk=GAP.rakuyaSnapshot||{},rkOk=rk.complete===true&&rk.status==='ok';cards.push(\`<div class=\"source-card\"><div class=\"source-head\"><strong>樂屋網</strong><span class=\"badge \${rkOk?'ok':'err'}\">\${rkOk?'正常':'異常/沿用'}</span></div><div class=\"note\">目前刊登 \${rk.totalCount??0} 筆<br>最近更新：\${fmt(rk.updatedAt)}</div></div>\`);" + source_anchor,
        1,
    )

old_filter = "const sourceOK=source==='all'||(source==='sinyi'&&(g.sources||[]).includes('信義房屋'))||(source==='591'&&(g.sources||[]).includes('591'));"
new_filter = "const sourceOK=source==='all'||(source==='sinyi'&&(g.sources||[]).includes('信義房屋'))||(source==='591'&&(g.sources||[]).includes('591'))||(source==='rakuya'&&(g.sources||[]).includes('樂屋網'));"
text = text.replace(old_filter, new_filter)

text = text.replace("信義主資料＋591整併", "跨平台整併")

required = ['data-source="rakuya"', "GAP.rakuyaSnapshot", "includes('樂屋網')", "function sourceClass(s)", "跨平台整併"]
missing = [x for x in required if x not in text]
if missing:
    raise RuntimeError(f"Rakuya integrated UI contract failed: {missing}")
if 'id="rakuyaPanel"' in text:
    raise RuntimeError("standalone Rakuya panel still present")

PATH.write_text(text, encoding="utf-8")
print("Rakuya integrated into main 591/Sinyi Preview UI")
