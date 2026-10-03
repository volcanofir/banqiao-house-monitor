import json
import re
from urllib.parse import quote

from playwright.sync_api import sync_playwright

ROAD = "中山路二段"
BASE_URL = f"https://buy.yungching.com.tw/list/{quote('新北市-板橋區')}_c/{quote(ROAD)}_kw?od=80"
PAGES = [1, 2]

INIT = r"""
(() => {
  const P = window.__ycDecodeProbe = {
    api: [],
    fetchApi: [],
    xhrApi: [],
    json: [],
    decoder: [],
    atob: [],
    cryptoDecrypt: [],
    cryptoImportKey: [],
    errors: [],
  };
  const clip = (s, n=5000) => String(s ?? '').slice(0, n);
  const meaningful = (s) => {
    s = String(s ?? '');
    if (s.length < 40) return false;
    return /中山路|house|price|address|total|list|item|building|坪|萬|title|floor/i.test(s)
      || /^[\s]*[\[{]/.test(s);
  };
  const bytesMeta = (buf) => {
    try {
      const u = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
      const head = [...u.slice(0, 48)].map(x => x.toString(16).padStart(2, '0')).join('');
      let text = '';
      try { text = new TextDecoder('utf-8', {fatal:false}).decode(u); } catch(e) {}
      const replacement = (text.match(/\uFFFD/g) || []).length;
      const printable = text ? [...text.slice(0, 5000)].filter(ch => /[\x20-\x7E\u4e00-\u9fff\r\n\t]/.test(ch)).length / Math.min(text.length, 5000) : 0;
      return {len:u.byteLength, head, printable, replacement, text: printable > 0.72 ? clip(text, 8000) : ''};
    } catch(e) { return {error:String(e)}; }
  };
  const push = (key, row, cap=80) => {
    try { P[key].push(row); if(P[key].length > cap) P[key].shift(); } catch(e) {}
  };

  // JSON.parse: captures plaintext if the app decrypts to a JSON string before parsing.
  try {
    const original = JSON.parse;
    JSON.parse = function(s, ...rest) {
      try {
        if (typeof s === 'string' && meaningful(s)) {
          push('json', {len:s.length, prefix:clip(s, 8000)});
        }
      } catch(e) {}
      return original.call(this, s, ...rest);
    };
  } catch(e) { push('errors', {hook:'JSON.parse', error:String(e)}); }

  // TextDecoder: captures plaintext if decrypted bytes are decoded before JSON.parse.
  try {
    const original = TextDecoder.prototype.decode;
    TextDecoder.prototype.decode = function(...args) {
      const out = original.apply(this, args);
      try {
        if (typeof out === 'string' && meaningful(out)) {
          push('decoder', {len:out.length, prefix:clip(out, 8000)});
        }
      } catch(e) {}
      return out;
    };
  } catch(e) { push('errors', {hook:'TextDecoder.decode', error:String(e)}); }

  // atob: records decoded results but only stores text-like outputs.
  try {
    const original = window.atob.bind(window);
    window.atob = function(s) {
      const out = original(s);
      try {
        if (out.length > 32) {
          let printable = 0;
          for (let i=0;i<Math.min(out.length,3000);i++) {
            const c=out.charCodeAt(i);
            if ((c>=32&&c<=126)||c===9||c===10||c===13) printable++;
          }
          const ratio = printable / Math.min(out.length,3000);
          push('atob', {inLen:String(s||'').length, outLen:out.length, printable:ratio, prefix: ratio>0.72 ? clip(out,5000) : ''});
        }
      } catch(e) {}
      return out;
    };
  } catch(e) { push('errors', {hook:'atob', error:String(e)}); }

  // WebCrypto: if Yongching uses native AES/WebCrypto, capture algorithm metadata and plaintext.
  try {
    const proto = SubtleCrypto.prototype;
    const originalDecrypt = proto.decrypt;
    proto.decrypt = async function(algorithm, key, data) {
      const out = await originalDecrypt.call(this, algorithm, key, data);
      try {
        const inMeta = bytesMeta(data);
        const outMeta = bytesMeta(out);
        push('cryptoDecrypt', {
          algorithm: algorithm && typeof algorithm === 'object' ? JSON.parse(JSON.stringify(algorithm)) : String(algorithm),
          keyAlgorithm: key?.algorithm || null,
          keyType: key?.type || null,
          input: {len:inMeta.len, head:inMeta.head},
          output: outMeta,
        }, 30);
      } catch(e) { push('errors',{hook:'crypto.decrypt.capture',error:String(e)}); }
      return out;
    };
  } catch(e) { push('errors', {hook:'crypto.decrypt', error:String(e)}); }

  try {
    const proto = SubtleCrypto.prototype;
    const originalImportKey = proto.importKey;
    proto.importKey = async function(format, keyData, algorithm, extractable, keyUsages) {
      const out = await originalImportKey.call(this, format, keyData, algorithm, extractable, keyUsages);
      try {
        let keyLen = null;
        if (keyData instanceof ArrayBuffer) keyLen = keyData.byteLength;
        else if (ArrayBuffer.isView(keyData)) keyLen = keyData.byteLength;
        push('cryptoImportKey', {
          format, keyLen,
          algorithm: algorithm && typeof algorithm === 'object' ? JSON.parse(JSON.stringify(algorithm)) : String(algorithm),
          extractable, keyUsages,
          resultAlgorithm: out?.algorithm || null,
        }, 30);
      } catch(e) {}
      return out;
    };
  } catch(e) { push('errors', {hook:'crypto.importKey', error:String(e)}); }

  // fetch/XHR wrapper capture: prove the current transport and wrapper shape.
  try {
    const originalFetch = window.fetch.bind(window);
    window.fetch = async function(...args) {
      const resp = await originalFetch(...args);
      try {
        const url = String(resp.url || args?.[0]?.url || args?.[0] || '');
        if (url.includes('/api/v2/list')) {
          resp.clone().json().then(body => {
            push('fetchApi', {
              url, status:resp.status,
              apiStatus:body?.status, apiVersion:body?.apiVersion, method:body?.method,
              dataLen:String(body?.data||'').length, dataPrefix:String(body?.data||'').slice(0,120),
            });
          }).catch(e => push('errors',{hook:'fetch.clone.json',error:String(e)}));
        }
      } catch(e) {}
      return resp;
    };
  } catch(e) { push('errors', {hook:'fetch', error:String(e)}); }

  try {
    const open = XMLHttpRequest.prototype.open;
    const send = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method, url, ...rest) {
      this.__ycUrl = String(url||'');
      this.__ycMethod = method;
      return open.call(this, method, url, ...rest);
    };
    XMLHttpRequest.prototype.send = function(...args) {
      if ((this.__ycUrl||'').includes('/api/v2/list')) {
        this.addEventListener('load', () => {
          try {
            const body = JSON.parse(this.responseText || '{}');
            push('xhrApi', {
              url:this.__ycUrl, method:this.__ycMethod, status:this.status,
              apiStatus:body?.status, apiVersion:body?.apiVersion,
              dataLen:String(body?.data||'').length, dataPrefix:String(body?.data||'').slice(0,120),
            });
          } catch(e) { push('errors',{hook:'xhr.capture',error:String(e)}); }
        });
      }
      return send.apply(this,args);
    };
  } catch(e) { push('errors', {hook:'xhr', error:String(e)}); }
})();
"""

def page_url(page_no: int) -> str:
    sep = "&" if "?" in BASE_URL else "?"
    return f"{BASE_URL}{sep}pg={page_no}"

def safe_page_probe(page, page_no: int):
    url = page_url(page_no)
    api = []

    def on_response(resp):
        if "/api/v2/list" not in resp.url:
            return
        try:
            body = resp.json()
            api.append({
                "url": resp.url,
                "http": resp.status,
                "apiStatus": body.get("status") if isinstance(body, dict) else None,
                "apiVersion": body.get("apiVersion") if isinstance(body, dict) else None,
                "method": body.get("method") if isinstance(body, dict) else None,
                "dataLen": len(str(body.get("data") or "")) if isinstance(body, dict) else None,
                "dataPrefix": str(body.get("data") or "")[:120] if isinstance(body, dict) else None,
            })
        except Exception as exc:
            api.append({"url": resp.url, "http": resp.status, "error": f"{type(exc).__name__}: {exc}"})

    page.on("response", on_response)
    nav = None
    try:
        nav = page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5500)
        body_text = page.locator("body").inner_text(timeout=10000)
        cards = page.eval_on_selector_all(
            "a[href*='/house/']",
            """els => [...new Map(els.map(a => {
                const href=String(a.href||'');
                const m=href.match(/\/house\/([0-9]+)/);
                return [m?.[1]||href, {
                  href, text:(a.innerText||a.closest('div')?.innerText||'').replace(/\s+/g,' ').trim().slice(0,700)
                }];
              })).values()].slice(0,8)""",
        )
        state = page.evaluate("window.__ycDecodeProbe")
        resources = page.evaluate(
            """() => performance.getEntriesByType('resource').map(x=>x.name).filter(x=>x.includes('/api/v2/list'))"""
        )
        return {
            "page": page_no,
            "url": url,
            "navHttp": nav.status if nav else None,
            "finalUrl": page.url,
            "title": page.title(),
            "bodyHasRoad": ROAD in body_text,
            "apiResponses": api,
            "performanceApiUrls": resources,
            "sampleHouseAnchors": cards,
            "probe": state,
        }
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel="chrome")
        ctx = browser.new_context(locale="zh-TW", timezone_id="Asia/Taipei")
        page = ctx.new_page()
        page.add_init_script(INIT)

        results = []
        for n in PAGES:
            results.append(safe_page_probe(page, n))

        script_matches = []
        summary = {
            "road": ROAD,
            "pages": PAGES,
            "resultCount": len(results),
            "apiResponseCount": sum(len(x.get("apiResponses") or []) for x in results),
            "cryptoDecryptCount": sum(len(((x.get("probe") or {}).get("cryptoDecrypt") or [])) for x in results),
            "jsonCaptureCount": sum(len(((x.get("probe") or {}).get("json") or [])) for x in results),
            "decoderCaptureCount": sum(len(((x.get("probe") or {}).get("decoder") or [])) for x in results),
            "scriptMatchCount": len(script_matches),
        }
        print("=== YC_DECODE_SUMMARY ===")
        print(json.dumps(summary, ensure_ascii=False))
        print("=== YC_PAGE_RESULTS ===")
        print(json.dumps(results, ensure_ascii=False))
        print("=== YC_SCRIPT_MATCHES ===")
        print(json.dumps(script_matches, ensure_ascii=False))
        browser.close()

if __name__ == "__main__":
    main()
