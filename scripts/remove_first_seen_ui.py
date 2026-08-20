from pathlib import Path

p = Path("docs/index.html")
s = p.read_text(encoding="utf-8")
old = """      const hideFirstDiscovery=(x.source==='591'&&!!pub)||!!fallbackDiscovery;\n      const systemTimeLine=hideFirstDiscovery?`<div class=\"row\"><span>系統最後確認：${fmt(x.lastSeenAt)}</span></div>`:`<div class=\"row\"><span>系統首次發現：${fmt(x.firstSeenAt)}</span><span>系統最後確認：${fmt(x.lastSeenAt)}</span></div>`;"""
new = """      const systemTimeLine=`<div class=\"row\"><span>系統最後確認：${fmt(x.lastSeenAt)}</span></div>`;"""
if old not in s:
    raise SystemExit("target UI block not found")
p.write_text(s.replace(old, new, 1), encoding="utf-8")
print("Removed system first-seen line from listing cards.")
