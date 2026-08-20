import re
from pathlib import Path

p = Path("docs/index.html")
s = p.read_text(encoding="utf-8")

# This cleanup runs on every monitor cycle, so keep it idempotent.
# Remove both the old first-seen/last-seen variant and the current
# "系統最後確認"-only line from listing cards.
s = re.sub(r'^\s*const hideFirstDiscovery=.*\n', '', s, flags=re.MULTILINE)
s = re.sub(r'^\s*const systemTimeLine=.*\n', '', s, flags=re.MULTILINE)
s = s.replace('${sourceTimeLine}${systemTimeLine}${mergedAudit(x)}', '${sourceTimeLine}${mergedAudit(x)}')
s = s.replace('${systemTimeLine}${mergedAudit(x)}', '${mergedAudit(x)}')

p.write_text(s, encoding="utf-8")
print("Removed internal system timestamps from listing cards.")
