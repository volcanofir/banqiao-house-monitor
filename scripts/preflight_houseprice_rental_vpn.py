import json
import sys

import requests
from curl_cffi import requests as curl_requests

from fetch_rental_preview import SEARCH_HOUSEPRICE, USER_AGENT, WATCH_ROADS, houseprice_api_url


def main():
    road = next(iter(WATCH_ROADS))
    url = houseprice_api_url(road, 1)
    session = curl_requests.Session(impersonate='chrome')
    session.headers.update({
        'User-Agent': USER_AGENT,
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
    })
    try:
        resp = session.get(
            url,
            headers={'Referer': requests.utils.requote_uri(SEARCH_HOUSEPRICE[road])},
            timeout=8,
        )
        status = int(resp.status_code or 0)
        ok = False
        payload_status = None
        if status == 200:
            try:
                payload = resp.json()
                payload_status = payload.get('status')
                ok = payload_status == 'Success' and isinstance(payload.get('data'), dict)
            except Exception:
                ok = False
        print(json.dumps({
            'road': road,
            'httpStatus': status,
            'payloadStatus': payload_status,
            'usable': ok,
        }, ensure_ascii=False))
        raise SystemExit(0 if ok else 2)
    except SystemExit:
        raise
    except Exception as exc:
        print(json.dumps({
            'road': road,
            'usable': False,
            'error': f'{type(exc).__name__}: {exc}',
        }, ensure_ascii=False))
        raise SystemExit(3)


if __name__ == '__main__':
    main()
