"""PREVIEW-only Yongching DOM snapshot v2.

Extends the existing rendered-card collector with pagination controls that are
implemented as li/span elements instead of normal links/buttons. The click is
accepted only inside a compact pagination-like group so listing-card numbers
(price, room count, floor, etc.) are never treated as page numbers.
"""

import yungching_dom_snapshot as base


def page_controls(page):
    return page.evaluate(
        """() => {
          const clean = s => (s || '').replace(/\s+/g, ' ').trim();
          const selector = 'a,button,[role="button"],li,span';

          function groupScore(el) {
            let node = el;
            let best = 0;
            for (let depth = 0; depth < 6 && node; depth++, node = node.parentElement) {
              const cls = typeof node.className === 'string' ? node.className : '';
              const id = node.id || '';
              const role = node.getAttribute ? (node.getAttribute('role') || '') : '';
              const aria = node.getAttribute ? (node.getAttribute('aria-label') || '') : '';
              const hay = [cls,id,role,aria].join(' ');
              const compact = clean(node.innerText);
              const nums = Array.from(node.querySelectorAll ? node.querySelectorAll(selector) : [])
                .map(x => clean(x.innerText))
                .filter(x => /^\d{1,3}$/.test(x));
              const uniqueNums = new Set(nums);
              let score = 0;
              if (/page|pager|pagination/i.test(hay)) score += 12;
              if (/navigation/i.test(role)) score += 7;
              if (compact.length <= 100 && uniqueNums.size >= 2) score += 6;
              if (compact.length <= 60 && uniqueNums.has('1') && uniqueNums.has('2')) score += 4;
              if (/\.\.\.|…/.test(compact) && compact.length <= 100) score += 3;
              best = Math.max(best, score);
            }
            return best;
          }

          const out = [];
          const seen = new Set();
          for (const el of Array.from(document.querySelectorAll(selector))) {
            const r = el.getBoundingClientRect();
            if (r.width <= 0 || r.height <= 0) continue;
            const text = clean(el.innerText);
            const aria = clean(el.getAttribute && el.getAttribute('aria-label'));
            const title = clean(el.getAttribute && el.getAttribute('title'));
            const cls = typeof el.className === 'string' ? el.className : '';
            const current = (el.getAttribute && el.getAttribute('aria-current')) || '';
            const semantic = /下一|下頁|next|上一|上頁|prev|更多|more|›|»|‹|«/i.test([text,aria,title,cls].join(' '));
            const numeric = /^\d{1,3}$/.test(text);
            const score = groupScore(el);
            if (!semantic && !(numeric && score >= 6)) continue;
            const key = [el.tagName,text,cls,aria,current].join('|');
            if (seen.has(key)) continue;
            seen.add(key);
            out.push({
              tag: el.tagName,
              text: text.slice(0,80),
              aria: aria.slice(0,120),
              title: title.slice(0,120),
              className: cls.slice(0,180),
              ariaCurrent: current,
              href: el.href || null,
              score,
              disabled: !!el.disabled || (el.getAttribute && el.getAttribute('aria-disabled') === 'true'),
            });
          }
          return out.slice(0,100);
        }"""
    )


def click_semantic_next(page):
    return page.evaluate(
        """() => {
          const clean = s => (s || '').replace(/\s+/g, ' ').trim();
          const els = Array.from(document.querySelectorAll('a,button,[role="button"],li,span'));
          for (const el of els) {
            if (el.disabled || (el.getAttribute && el.getAttribute('aria-disabled') === 'true')) continue;
            const r = el.getBoundingClientRect();
            if (r.width <= 0 || r.height <= 0) continue;
            const text = clean(el.innerText);
            const aria = clean(el.getAttribute && el.getAttribute('aria-label'));
            const title = clean(el.getAttribute && el.getAttribute('title'));
            const hay = [text, aria, title].join(' ');
            if (!/(下一頁|下頁|下一页|next page|load more|載入更多|查看更多|更多物件|顯示更多)/i.test(hay)) continue;
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
          const selector = 'a,button,[role="button"],li,span';
          const wanted = String(target);

          function paginationScore(el) {
            let node = el;
            let best = 0;
            for (let depth = 0; depth < 6 && node; depth++, node = node.parentElement) {
              const cls = typeof node.className === 'string' ? node.className : '';
              const id = node.id || '';
              const role = node.getAttribute ? (node.getAttribute('role') || '') : '';
              const aria = node.getAttribute ? (node.getAttribute('aria-label') || '') : '';
              const hay = [cls,id,role,aria].join(' ');
              const compact = clean(node.innerText);
              const nums = Array.from(node.querySelectorAll ? node.querySelectorAll(selector) : [])
                .map(x => clean(x.innerText))
                .filter(x => /^\d{1,3}$/.test(x));
              const uniqueNums = new Set(nums);
              let score = 0;
              if (/page|pager|pagination/i.test(hay)) score += 12;
              if (/navigation/i.test(role)) score += 7;
              if (compact.length <= 100 && uniqueNums.size >= 2) score += 6;
              if (compact.length <= 60 && uniqueNums.has('1') && uniqueNums.has(wanted)) score += 4;
              if (/\.\.\.|…/.test(compact) && compact.length <= 100) score += 3;
              best = Math.max(best, score);
            }
            return best;
          }

          let best = null;
          for (const el of Array.from(document.querySelectorAll(selector))) {
            if (clean(el.innerText) !== wanted) continue;
            if (el.disabled || (el.getAttribute && el.getAttribute('aria-disabled') === 'true')) continue;
            const r = el.getBoundingClientRect();
            if (r.width <= 0 || r.height <= 0) continue;
            const score = paginationScore(el);
            if (score < 6) continue;
            if (!best || score > best.score) best = {el, score};
          }
          if (!best) return {clicked:false};

          const el = best.el;
          const beforeUrl = location.href;
          el.scrollIntoView({block:'center', inline:'center'});
          el.click();
          return {
            clicked:true,
            mode:'numeric-v2',
            target,
            score:best.score,
            tag:el.tagName,
            className:typeof el.className === 'string' ? el.className.slice(0,180) : '',
            text:clean(el.innerText),
            href:el.href || null,
            beforeUrl,
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
