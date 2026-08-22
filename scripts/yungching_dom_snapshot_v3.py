"""PREVIEW-only Yongching DOM snapshot v3.

The Yongching pager can render page numbers as bare text nodes instead of normal
links/buttons. This version locates the visual text node for page 2/3/... and clicks
its real screen coordinate, but only when it sits inside a compact pagination-like
container. It also refuses to mark a road complete when a second page is visibly
present but no page transition was performed.
"""

import json
import re

import yungching_dom_snapshot_v2 as v2
import yungching_dom_snapshot as base


def numeric_page_target(page, target: int):
    return page.evaluate(
        """(target) => {
          const wanted = String(target);
          const clean = s => (s || '').replace(/\s+/g, ' ').trim();
          const badListingText = /(?:萬|建坪|房\(室\)|房|廳|衛|新北市|台北市)/;

          function numericTextTokens(root) {
            const out = [];
            const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
            let n;
            while ((n = w.nextNode())) {
              const t = clean(n.nodeValue);
              if (/^\d{1,3}$/.test(t)) out.push(t);
              if (out.length > 20) break;
            }
            return [...new Set(out)];
          }

          function scoreContext(el) {
            let node = el;
            let best = null;
            for (let depth = 0; depth < 7 && node && node !== document.body; depth++, node = node.parentElement) {
              const text = clean(node.innerText);
              if (!text || text.length > 120 || badListingText.test(text)) continue;
              const nums = numericTextTokens(node);
              if (!nums.includes('1') || !nums.includes(wanted) || nums.length < 2) continue;
              const cls = typeof node.className === 'string' ? node.className : '';
              const id = node.id || '';
              const role = node.getAttribute ? (node.getAttribute('role') || '') : '';
              const aria = node.getAttribute ? (node.getAttribute('aria-label') || '') : '';
              const hay = [cls,id,role,aria].join(' ');
              let score = 10;
              if (text.length <= 60) score += 5;
              if (/page|pager|pagination/i.test(hay)) score += 12;
              if (/navigation/i.test(role)) score += 7;
              if (nums.length <= 8) score += 3;
              if (!best || score > best.score) best = {node, score, text, nums};
            }
            return best;
          }

          const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
          const candidates = [];
          let textNode;
          while ((textNode = walker.nextNode())) {
            if (clean(textNode.nodeValue) !== wanted) continue;
            const parent = textNode.parentElement;
            if (!parent) continue;
            const context = scoreContext(parent);
            if (!context) continue;

            const range = document.createRange();
            range.selectNodeContents(textNode);
            const rect = range.getBoundingClientRect();
            if (!rect || rect.width <= 0 || rect.height <= 0) continue;
            const x = rect.left + rect.width / 2;
            const y = rect.top + rect.height / 2;
            if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) continue;
            const hit = document.elementFromPoint(x, y) || parent;
            const hitStyle = getComputedStyle(hit);
            let clickScore = context.score;
            if (hitStyle.cursor === 'pointer') clickScore += 5;
            if (hit.closest && hit.closest('a,button,[role="button"]')) clickScore += 6;
            candidates.push({
              x, y,
              score: clickScore,
              contextText: context.text,
              nums: context.nums,
              hitTag: hit.tagName,
              hitClass: typeof hit.className === 'string' ? hit.className.slice(0,180) : '',
              parentTag: parent.tagName,
              parentClass: typeof parent.className === 'string' ? parent.className.slice(0,180) : '',
            });
          }
          candidates.sort((a,b) => b.score - a.score);
          return candidates[0] || null;
        }""",
        target,
    )


def click_numeric_page(page, target: int):
    # First keep the broader text-node/element strategy from v2.
    action = v2.click_numeric_page(page, target)
    if action.get("clicked"):
        return action

    # Fallback: click the exact screen coordinate occupied by the numeric text.
    candidate = numeric_page_target(page, target)
    if not candidate:
        return {"clicked": False, "mode": "numeric-text-v3", "target": target}

    page.mouse.click(candidate["x"], candidate["y"])
    return {
        "clicked": True,
        "mode": "numeric-text-v3",
        "target": target,
        "score": candidate.get("score"),
        "contextText": candidate.get("contextText"),
        "nums": candidate.get("nums"),
        "hitTag": candidate.get("hitTag"),
        "hitClass": candidate.get("hitClass"),
        "parentTag": candidate.get("parentTag"),
        "parentClass": candidate.get("parentClass"),
    }


def pager_expected(status: dict) -> bool:
    """Return True when the rendered result clearly advertises a second page."""
    if not status:
        return False

    # New v2 diagnostics expose the pager as element/text-node candidates.
    controls = status.get("controls") or []
    for c in controls:
        text = str(c.get("text") or "").strip()
        context = str(c.get("context") or c.get("contextText") or "")
        if text == "2" and ("1" in context or c.get("source") == "text-node"):
            return True

    # Conservative fallback for Yongching's footer: a full first page (roughly 30
    # parsed cards) followed by the literal sequence "1 2" means another page exists.
    if int(status.get("count") or 0) >= 25:
        summary = " ".join(str(x) for x in (status.get("summary") or []))
        if re.search(r"(?:^|\s)1\s+2(?:\s|$)", summary):
            return True
    return False


def enforce_pagination_completeness():
    payload = json.loads(base.OUT.read_text(encoding="utf-8"))
    road_status = payload.get("roadStatus") or {}

    for road, status in road_status.items():
        expected = pager_expected(status)
        status["paginationExpected"] = expected
        status["paginationComplete"] = not expected or int(status.get("pageRounds") or 0) > 0
        if expected and not status["paginationComplete"]:
            status["available"] = False
            status["paginationIncomplete"] = True
            status["error"] = "偵測到永慶第二頁，但本輪未完成翻頁；為避免漏案，此路段不進 Preview 公司比對"

    payload["availableRoads"] = [
        road for road, status in road_status.items() if status.get("available")
    ]
    payload["paginationGuard"] = True
    base.OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    base.page_controls = v2.page_controls
    base.click_semantic_next = v2.click_semantic_next
    base.click_numeric_page = click_numeric_page
    base.main()
    enforce_pagination_completeness()


if __name__ == "__main__":
    main()
