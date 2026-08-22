"""PREVIEW-only Yongching DOM snapshot v2.

Extends the rendered-card collector with pagination discovery that also handles
page numbers rendered as plain li/span/div text rather than normal links/buttons.
The click is accepted only in a compact pagination-like group near the lower part
of the result page, so listing-card numbers are not treated as page numbers.
"""

import yungching_dom_snapshot as base


def page_controls(page):
    return page.evaluate(
        """() => {
          const clean = s => (s || '').replace(/\s+/g, ' ').trim();
          const visibleRect = r => r && r.width > 0 && r.height > 0;
          const out = [];
          const seen = new Set();

          function push(el, text, source, rect) {
            if (!el || !visibleRect(rect)) return;
            const aria = clean(el.getAttribute && el.getAttribute('aria-label'));
            const title = clean(el.getAttribute && el.getAttribute('title'));
            const cls = typeof el.className === 'string' ? el.className : '';
            const current = (el.getAttribute && el.getAttribute('aria-current')) || '';
            let node = el;
            let context = '';
            let contextClass = '';
            for (let depth = 0; depth < 7 && node; depth++, node = node.parentElement) {
              const t = clean(node.innerText);
              const meta = String(node.className || '') + ' ' + (node.id || '') + ' ' + (node.getAttribute?.('role') || '');
              if (t.length <= 140 && (/\b1\s+2\b/.test(t) || /page|pager|pagination/i.test(meta))) {
                context = t;
                contextClass = String(node.className || '').slice(0,180);
                break;
              }
            }
            const key = [source,el.tagName,text,cls,Math.round(rect.top + scrollY)].join('|');
            if (seen.has(key)) return;
            seen.add(key);
            out.push({
              source,
              tag:el.tagName,
              text:text.slice(0,100),
              aria:aria.slice(0,120),
              title:title.slice(0,120),
              className:cls.slice(0,180),
              ariaCurrent:current,
              href:el.href || null,
              y:Math.round(rect.top + scrollY),
              pageHeight:Math.round(document.body.scrollHeight),
              context:context.slice(0,180),
              contextClass,
            });
          }

          // Normal semantic/clickable controls.
          for (const el of Array.from(document.querySelectorAll('a,button,[role="button"],li,span,div'))) {
            const r = el.getBoundingClientRect();
            if (!visibleRect(r)) continue;
            const text = clean(el.innerText);
            const aria = clean(el.getAttribute && el.getAttribute('aria-label'));
            const title = clean(el.getAttribute && el.getAttribute('title'));
            const cls = typeof el.className === 'string' ? el.className : '';
            const hay = [text,aria,title,cls].join(' ');
            if (/^(?:1|2|3|4|5)$/.test(text) || /下一|下頁|next|上一|上頁|prev|page|pager|pagination|更多|more|›|»|‹|«/i.test(hay)) {
              push(el,text,'element',r);
            }
          }

          // Some Yongching builds render the pagination label as a plain text node.
          const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
          let n;
          while ((n = walker.nextNode())) {
            const raw = n.nodeValue || '';
            const text = clean(raw);
            if (!text || text.length > 40) continue;
            if (!/^(?:1|2|3|4|5)$/.test(text) && !/\b1\s+2\b/.test(text)) continue;
            const range = document.createRange();
            range.selectNodeContents(n);
            const r = range.getBoundingClientRect();
            push(n.parentElement,text,'text-node',r);
          }
          return out.slice(-160);
        }"""
    )


def click_semantic_next(page):
    return page.evaluate(
        """() => {
          const clean = s => (s || '').replace(/\s+/g, ' ').trim();
          for (const el of Array.from(document.querySelectorAll('a,button,[role="button"],li,span,div'))) {
            if (el.disabled || (el.getAttribute && el.getAttribute('aria-disabled') === 'true')) continue;
            const r = el.getBoundingClientRect();
            if (r.width <= 0 || r.height <= 0) continue;
            const text = clean(el.innerText);
            const aria = clean(el.getAttribute && el.getAttribute('aria-label'));
            const title = clean(el.getAttribute && el.getAttribute('title'));
            if (!/(下一頁|下頁|下一页|next page|load more|載入更多|查看更多|更多物件|顯示更多)/i.test([text,aria,title].join(' '))) continue;
            el.scrollIntoView({block:'center'});
            el.click();
            return {clicked:true, mode:'semantic-v2', text, aria, title, href:el.href || null};
          }
          return {clicked:false};
        }"""
    )


def click_numeric_page(page, target: int):
    return page.evaluate(
        """(target) => {
          const clean = s => (s || '').replace(/\s+/g, ' ').trim();
          const wanted = String(target);
          const docHeight = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
          const candidates = [];

          function numericTokens(s) {
            return new Set((clean(s).match(/\b\d{1,3}\b/g) || []));
          }

          function addCandidate(el, rect, source) {
            if (!el || !rect || rect.width <= 0 || rect.height <= 0) return;
            let node = el;
            let best = null;
            for (let depth = 0; depth < 7 && node; depth++, node = node.parentElement) {
              const text = clean(node.innerText);
              if (!text || text.length > 160) continue;
              const cls = typeof node.className === 'string' ? node.className : '';
              const id = node.id || '';
              const role = node.getAttribute ? (node.getAttribute('role') || '') : '';
              const aria = node.getAttribute ? (node.getAttribute('aria-label') || '') : '';
              const nums = numericTokens(text);
              let score = 0;
              if (/page|pager|pagination/i.test([cls,id,role,aria].join(' '))) score += 12;
              if (/navigation/i.test(role)) score += 5;
              if (nums.size >= 2) score += 7;
              if (nums.has('1') && nums.has(wanted)) score += 7;
              if (text.length <= 50) score += 3;
              const nr = node.getBoundingClientRect();
              const y = nr.top + scrollY;
              if (y > docHeight * 0.55) score += 4;
              if (y > docHeight * 0.75) score += 2;
              if (!best || score > best.score) best = {node,score,text,nums:[...nums],y};
            }
            if (best) candidates.push({...best,leaf:el,rect,source});
          }

          // Element-level candidates.
          for (const el of Array.from(document.querySelectorAll('body *'))) {
            if (clean(el.innerText) !== wanted) continue;
            const r = el.getBoundingClientRect();
            addCandidate(el,r,'element');
          }

          // Text-node candidates, including a single text node like "1 2".
          const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
          let n;
          while ((n = walker.nextNode())) {
            const raw = n.nodeValue || '';
            const compact = clean(raw);
            if (!compact || compact.length > 40) continue;
            const tokens = compact.match(/\b\d{1,3}\b/g) || [];
            if (!tokens.includes(wanted)) continue;
            const idx = raw.indexOf(wanted);
            if (idx < 0) continue;
            try {
              const range = document.createRange();
              range.setStart(n, idx);
              range.setEnd(n, Math.min(raw.length, idx + wanted.length));
              const r = range.getBoundingClientRect();
              const hit = document.elementFromPoint(r.left + r.width/2, r.top + r.height/2) || n.parentElement;
              addCandidate(hit,r,'text-node');
            } catch (_) {}
          }

          candidates.sort((a,b) => b.score - a.score || b.y - a.y);
          const best = candidates.find(x => x.score >= 18 && x.nums.includes('1') && x.nums.includes(wanted));
          if (!best) {
            return {
              clicked:false,
              target,
              candidateCount:candidates.length,
              topCandidates:candidates.slice(0,5).map(x => ({score:x.score,source:x.source,text:x.text.slice(0,120),nums:x.nums,y:Math.round(x.y)})),
            };
          }

          let clickEl = best.leaf;
          const clickable = clickEl.closest && clickEl.closest('a,button,[role="button"]');
          if (clickable && best.node.contains(clickable)) clickEl = clickable;
          clickEl.scrollIntoView({block:'center',inline:'center'});
          const beforeUrl = location.href;
          clickEl.click();
          return {
            clicked:true,
            mode:'numeric-text-v2',
            target,
            score:best.score,
            source:best.source,
            tag:clickEl.tagName,
            leafTag:best.leaf.tagName,
            groupText:best.text.slice(0,160),
            nums:best.nums,
            y:Math.round(best.y),
            beforeUrl,
            href:clickEl.href || null,
          };
        }""",
        target,
    )


def main():
    base.page_controls = page_controls
    base.click_semantic_next = click_semantic_next
    base.click_numeric_page = click_numeric_page
    base.main()


if __name__ == "__main__":
    main()
