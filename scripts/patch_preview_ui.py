from pathlib import Path
import re

PATH = Path('docs/preview/index.html')
text = PATH.read_text(encoding='utf-8')

replacements = {
    '🧪 PREVIEW 測試版本｜信義優先整併測試｜不影響正式網站': '🧪 PREVIEW 測試版本｜不影響正式網站',
    '591 ＋ 信義先整併，再比對永慶公司公開庫存': '比對591、信義刊登案件',
    '<h1>指定路段房屋群組</h1>': '<h1>指定路段案件比對</h1>',
    '<h2>公司委託比對（以戶數計）</h2>': '<h2>委託比對</h2>',
    '.source-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}': '.source-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}',
}
for old, new in replacements.items():
    text = text.replace(old, new)

# Hero explanatory paragraph: remove from display.
text = re.sub(
    r'\n<p>同一戶若同時出現在信義房屋與 591，Preview 會優先以信義資料顯示，591 收進同一戶下方；整併完成後再依坪數、價格、案名與樓層比對公司庫存。</p>',
    '',
    text,
)

# Remove the flow/explanation box entirely.
text = re.sub(
    r'\n<div class="company-note" id="companyNote">.*?</div>',
    '',
    text,
    count=1,
    flags=re.S,
)
text = text.replace('\n<div id="companyNote" hidden></div>', '')
text = re.sub(
    r"const conflict=GAP\.companyConflictDowngradedCount\?\?0;.*?(?=document\.querySelector\('#updated'\))",
    '',
    text,
    count=1,
    flags=re.S,
)

# Data source section should only show 591 and Sinyi. Remove the Yongching source card.
text = re.sub(
    r";const covered=GAP\.coveredRoads\|\|\[\];cards\.push\(.*?\);document\.querySelector\('#sources'\)\.innerHTML=cards\.join\(''\);",
    ";document.querySelector('#sources').innerHTML=cards.join('');",
    text,
    count=1,
    flags=re.S,
)

PATH.write_text(text, encoding='utf-8')
print('Preview UI patched')
