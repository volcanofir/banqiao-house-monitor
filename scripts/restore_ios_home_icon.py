from pathlib import Path
import re

p = Path('docs/index.html')
s = p.read_text(encoding='utf-8')

# Keep the iPhone setup intentionally minimal and stable.
s = re.sub(r'^\s*<meta name="mobile-web-app-capable"[^>]*>\s*\n?', '', s, flags=re.MULTILINE)
s = re.sub(r'^\s*<link\b[^>]*\brel="(?:apple-touch-icon|apple-touch-icon-precomposed|icon|shortcut icon|manifest)"[^>]*>\s*\n?', '', s, flags=re.MULTILINE)

marker = '  <meta name="application-name" content="板橋新案監控" />\n'
block = '''  <meta name="mobile-web-app-capable" content="yes" />
  <link rel="apple-touch-icon" sizes="180x180" href="./apple-touch-icon.png" />
  <link rel="icon" type="image/png" sizes="32x32" href="./icon-safe-32.png" />
'''

if marker not in s:
    raise SystemExit('application-name marker not found')

s = s.replace(marker, marker + block, 1)
p.write_text(s, encoding='utf-8')
print('Restored stable iPhone home-screen metadata.')
