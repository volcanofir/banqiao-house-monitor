import json
from pathlib import Path

from fetch_rental_preview import OUT, WATCH_ROADS, dedupe, fetch_houseprice_api


def main():
    if not OUT.exists():
        raise SystemExit('rental-data.json does not exist; base rental fetch must run first')

    payload = json.loads(OUT.read_text(encoding='utf-8'))

    rows, ok, logs = fetch_houseprice_api()

    listings = [x for x in payload.get('listings', []) if x.get('source') != '5168']
    listings = dedupe(listings + rows)

    payload.setdefault('runs', {})['5168'] = {
        'status': 'ok' if ok else 'error',
        'totalCount': len(rows),
        'logs': logs,
    }

    counts = payload.setdefault('counts', {})
    counts['houseprice'] = len(rows)
    counts['total'] = len(listings)
    counts['roads'] = {
        road: sum(1 for x in listings if x.get('road') == road)
        for road in WATCH_ROADS
    }
    payload['listings'] = listings

    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({
        'source': '5168',
        'status': 'ok' if ok else 'error',
        'count': len(rows),
        'logs': logs,
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
