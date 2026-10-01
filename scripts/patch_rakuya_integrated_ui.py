from pathlib import Path
import re

PATH = Path("docs/preview/index.html")
text = PATH.read_text(encoding="utf-8")

# Remove the old standalone Rakuya panel/assets. Rakuya is now part of the main
# 591/Sinyi property-group UI.
text = re.sub(r'\n?<section class="panel rk-panel" id="rakuyaPanel".*?</section>\s*', '\n', text, flags=re.S)
text = re.sub(r'\n?<link rel="stylesheet" href="rakuya-widget\.css\?v=[^"]+"\s*/>\s*', '\n', text)
text = re.sub(r'\n?<script src="rakuya-widget\.js\?v=[^"]+"></script>\s*', '\n', text)

text = text.replace("比對591、信義刊登案件", "比對591、信義、樂屋刊登案件")

text = text.replace(
    ".source-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}",
    ".source-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}",
)
text = text.replace(
    ".source-tabs{grid-column:1/-1;display:grid;grid-template-columns:repeat(3,1fr);gap:8px}",
    ".source-tabs{grid-column:1/-1;display:grid;grid-template-columns:repeat(4,1fr);gap:8px}",
)
text = text.replace(
    ".source-tabs{grid-column:1;grid-template-columns:repeat(3,1fr)}",
    ".source-tabs{grid-column:1;grid-template-columns:repeat(4,1fr)}",
)
if ".pill.rakuya{" not in text:
    text = text.replace(
        ".pill.m591{background:#e8eef9;color:#35577d}",
        ".pill.m591{background:#e8eef9;color:#35577d}.pill.rakuya{background:#f2e8ff;color:#6f3f91}",
    )

old_tabs = '''<button type="button" class="source-tab active" data-source="all">全部曈件</button>
<button type="button" class="source-tab" data-source="sinyi">信義</button>
<button type="button" class="source-tab" data-source="591">591</button>'''
new_tabs = '''<button type="button" class="source-tab active" data-source="all">全部案件</button>
<button type="button" class="source-tab" data-source="sinyi">信義</button>
<button type="button" class="source-tab" data-source="591">591</button>
<button type="button" class="source-tab" data-source="rakuya">樂屋</button>'''
text = text.replace(old_tabs, new_tabs)

old_pills = '''function sourcePills(g){return (g.sources||[]).map(s=>`<span class="pill ${s==='信義房屋'?'sinyi':'m591'}">${esc(s)}</span>`).join('')}'''
new_pills = '''function sourceClass(s){return s==='信義房屋'?'sinyi':s==='樂屋網'?'rakuya':'m591'}
function sourcePills(g){return (g.sources||[]).map(s=>`<span class="pill ${sourceClass(s)}">${esc(s)}</span>`).join('')}'''
text = text.replace(old_pills, new_pills)

text = text.replace(
    '''<span class="pill ${m.source==='信義房屋'?'sinyi':'m591'}">${esc(m.source)}</span>''',
    '''<span class="pill ${sourceClass(m.source)}">${esc(m.source)}</span>''',
)
text = text.replace(
    '''${m.source==='591'&&nested.length?`<span>591原始刊登 ${nested.length} 筆</span>`:''}''',
    '''${nested.length?`<span>${esc(m.source)}原始刊登 ${nested.length} 筆</span>`:''}''',
)

old_cards = """const cards=['591','信義房屋'].map(name=>{const r=DATA.runs?.[name],ok=r?.status==='ok';return `<div class=\"source-card\"><div class=\"source-head\"><strong>${name}</strong><span class=\"badge ${ok?'ok':'err'}\">${ok?'正常':'異常/沿用'}</span></div><div class=\"note\">目前刊登 ${r?.totalCount??0} 筆<br>最近更新：${fmt(r?.checkedAt)}</div></div>`});document.querySelector('#sources').innerHTML=cards.join('');"""
