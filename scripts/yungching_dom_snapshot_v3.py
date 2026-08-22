"""PREVIEW-only Yongching DOM snapshot v3.

The Yongching pager can render page numbers as bare DIV/text nodes and can also be
covered by the site's AI hint backdrop. Prefer Playwright force-click on Yongching's
actual .paginationPageListItem element, then fall back to generic DOM discovery.
A paginated road is accepted only when the final DOM proves that page 2 became active.
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


def click_yungching_pager_class(page, target: int):
    """Use the actual Yongching pager node and bypass overlays with force=True."""
    try:
        items = page.locator(".paginationPageListItem")
        for i in range(items.count()):
            item = items.nth(i)
            text = re.sub(r"\s+", " ", item.inner_text(timeout=1500)).strip()
            if text != str(target):
                continue
            cls = item.get_attribute("class") or ""
            before = page.evaluate(
                """() => Array.from(document.querySelectorAll('.paginationPageListItem')).map(x => ({text:(x.innerText||'').trim(), cls:x.className||''}))"""
            )
            item.scroll_into_view_if_needed(timeout=2000)
            item.click(force=True, timeout=3000)
            return {
                "clicked": True,
                "mode": "yungching-pagination-class-v3",
                "target": target,
                "tag": "DIV",
                "className": cls,
                "beforePages": before,
            }
    except Exception as exc:
        return {
            "clicked": False,
            "mode": "yungching-pagination-class-v3",
            "target": target,
            "error": f"{type(exc).__name__}: {str(exc)[:180]}",
        }
    return {"clicked": False, "mode": "yungching-pagination-class-v3", "target": target}


def click_numeric_page(page, target: int):
    # Yongching's current production DOM exposes this exact class. Using the element
    # itself with a Playwright force-click prevents the AI hint backdrop from stealing
    # the mouse event.
    action = click_yungching_pager_class(page, target)
    if action.get("clicked"):
        return action

    # Keep the generic text-node/element strategy for future DOM variants.
    action = v2.click_numeric_page(page, target)
    if action.get("clicked"):
        return action

    # Last fallback: click the exact screen coordinate occupied by numeric text.
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

    controls = status.get("controls") or []
    page_texts = {
        str(c.get("text") or "").strip()
        for c in controls
        if "pagination" in str(c.get("className") or c.get("contextClass") or "").lower()
    }
    if "1" in page_texts and "2" in page_texts:
        return True

    for c in controls:
        text = str(c.get("text") or "").strip()
        context = str(c.get("context") or c.get("contextText") or "")
        if text == "2" and ("1" in context or c.get("source") == "text-node"):
            return True

    if int(status.get("count") or 0) >= 25:
        summary = " ".join(str(x) for x in (status.get("summary") or []))
        if re.search(r"(?:^|\s)1\s+2(?:\s|$)", summary):
            return True
    return False


def active_pager_page(status: dict):
    for c in status.get("controls") or []:
        text = str(c.get("text") or "").strip()
        cls = str(c.get("className") or "").lower()
        if text.isdigit() and ("actived" in cls or "active" in cls):
            try:
                return int(text)
            except ValueError:
                pass
    return None


def enforce_pagination_completeness():
    payload = json.loads(base.OUT.read_text(encoding="utf-8"))
    road_status = payload.get("roadStatus") or {}

    for road, status in road_status.items():
        expected = pager_expected(status)
        active_page = active_pager_page(status)
        status["paginationExpected"] = expected
        status["paginationActivePage"] = active_page
        status["paginationComplete"] = not expected or (
            int(status.get("pageRounds") or 0) > 0 and active_page is not None and active_page >= 2
        )
        if expected and not status["paginationComplete"]:
            status["available"] = False
            status["paginationIncomplete"] = True
            status["error"] = "偵測到永慶第二頁，但 DOM 未證實已切到第2頁；為避免漏案，此路段不進 Preview 公司比對"

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
