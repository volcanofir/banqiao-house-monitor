import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT=Path('docs')
DATA=ROOT/'preview'/'r420-store.json'
URL='http://127.0.0.1:8772/preview/'

def wait_server():
    end=time.time()+10
    while time.time()<end:
        try:
            with urllib.request.urlopen(URL,timeout=1) as r:
                if r.status==200:return
        except Exception:
            time.sleep(.2)
    raise RuntimeError('R420 Preview server did not start')

def main():
    payload=json.loads(DATA.read_text(encoding='utf-8'))
    total=int(payload.get('totalCount') or 0)
    assert total == int(payload.get('sourceTotalCount') or -1)
    assert total == len(payload.get('listings') or [])
    assert len({x.get('houseNo') for x in payload.get('listings') or []}) == total
    assert [x.get('area') for x in (payload.get('areas') or [])] == ['埔墘區','板橋區','其他行政區']
    assert sum(int(x.get('count') or 0) for x in (payload.get('areas') or [])) == total
    server=subprocess.Popen([sys.executable,'-m','http.server','8772','--bind','127.0.0.1','--directory',str(ROOT)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        wait_server()
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=['--disable-dev-shm-usage'])
            page=browser.new_page(viewport={'width':390,'height':844},locale='zh-TW')
            errors=[]
            page.on('pageerror',lambda exc: errors.append(str(exc)))
            r=page.goto(URL,wait_until='networkidle',timeout=30000)
            assert r and r.status==200
            page.wait_for_function("document.querySelector('#r420Total')?.textContent !== '-'",timeout=15000)
            assert page.locator('#r420Panel').is_visible()
            assert page.locator('#r420Groups .r420-item').count()==total
            assert str(total) in page.locator('#r420Total').inner_text()
            assert page.locator('#r420Groups > details.r420-region').count() == 3
            summaries=[page.locator('#r420Groups > details.r420-region > summary').nth(i).inner_text() for i in range(3)]
            assert summaries[0].startswith('埔墘區'), summaries
            assert summaries[1].startswith('板橋區'), summaries
            assert summaries[2].startswith('其他行政區'), summaries
            first=(payload.get('listings') or [{}])[0].get('houseNo')
            if first:
                page.fill('#r420Search',str(first))
                assert page.locator('#r420Groups .r420-item').count()==1
            page.fill('#r420Search','4986WV')
            assert page.locator('#r420Groups .r420-item').count()==1
            assert '埔墘區｜富山街' in page.locator('#r420Groups .r420-item').inner_text()
            assert page.locator('#r420Groups .r420-pill.core').count()==1
            assert not errors, errors
            browser.close()
        print(f'R420 Preview smoke passed: {total} unique listings grouped into 埔墘區 / 板橋區 / 其他行政區')
    finally:
        server.terminate()
        try: server.wait(timeout=5)
        except subprocess.TimeoutExpired: server.kill()

if __name__=='__main__':
    main()