import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT=Path("docs")
DATA=ROOT/"preview"/"rakuya-seven-roads.json"
URL="http://127.0.0.1:8773/preview/"
ROADS=["中山路二段","三民路一段","三民路二段","翠華街","林森街","萬安街","光復街"]


def wait_server():
    end=time.time()+10
    while time.time()<end:
        try:
            with urllib.request.urlopen(URL,timeout=1) as r:
                if r.status==200:
                    return
        except Exception:
            time.sleep(.2)
    raise RuntimeError("Rakuya Preview server did not start")


def main():
    payload=json.loads(DATA.read_text(encoding="utf-8"))
    assert payload.get("complete") is True
    assert payload.get("roads")==ROADS
    road_counts=payload.get("roadCounts") or []
    assert [x.get("road") for x in road_counts]==ROADS
    placement=sum(int(x.get("count") or 0) for x in road_counts)
    assert placement==int(payload.get("placementCount") or -1)
    assert int(payload.get("uniqueListingCount") or -1)==len(payload.get("listings") or [])
    assert len({x.get("listingId") for x in payload.get("listings") or []})==len(payload.get("listings") or [])

    server=subprocess.Popen(
        [sys.executable,"-m","http.server","8773","--bind","127.0.0.1","--directory",str(ROOT)],
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
    )
    try:
        wait_server()
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=["--disable-dev-shm-usage"])
            page=browser.new_page(viewport={"width":390,"height":844},locale="zh-TW")
            errors=[]
            page.on("pageerror",lambda exc: errors.append(str(exc)))
            r=page.goto(URL,wait_until="networkidle",timeout=30000)
            assert r and r.status==200
            page.wait_for_function("document.querySelector('#rkRoadCount')?.textContent !== '-'",timeout=15000)
            assert page.locator("#rakuyaPanel").is_visible()
            assert page.locator("#rkGroups > details.rk-road").count()==7
            assert page.locator("#rkGroups .rk-item").count()==placement
            assert "7" in page.locator("#rkRoadCount").inner_text()
            assert str(placement) in page.locator("#rkListingCount").inner_text()

            first_road=ROADS[0]
            first_count=next(int(x.get("count") or 0) for x in road_counts if x.get("road")==first_road)
            page.select_option("#rkRoad",first_road)
            assert page.locator("#rkGroups > details.rk-road").count()==1
            assert page.locator("#rkGroups .rk-item").count()==first_count

            if payload.get("listings"):
                item=payload["listings"][0]
                page.select_option("#rkRoad","all")
                page.fill("#rkSearch",str(item.get("name") or ""))
                expected=len(item.get("roads") or [item.get("road")])
                assert page.locator("#rkGroups .rk-item").count()>=expected

            assert not errors, errors
            browser.close()

        print(
            f"Rakuya Preview smoke passed: 7 roads, placements={placement}, "
            f"unique={payload.get('uniqueListingCount')}, overlap={payload.get('overlapCount')}"
        )
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__=="__main__":
    main()
