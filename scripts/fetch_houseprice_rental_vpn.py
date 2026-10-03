import json
from pathlib import Path
from datetime import datetime, timezone

from fetch_rental_preview import OUT, WATCH_ROADS, dedupe, fetch_houseprice_api


def main():
    if not OUT.exists():
        raise SystemExit('rental-data.json does not exist; base rental fetch must run first')

    payload = json.loads(OUT.read_text(encoding='utf-8'))

    rows, ok, logs = fetch_houseprice_api()
    if not ok:
        print(json.dumps({
            'source': '5168',
            'status': 'error',
            'count': len(rows),
            'logs': logs,
        }, ensure_ascii=False))
        raise SystemExit(2)

    checked_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    listings = [x for x in payload.get('listings', []) if x.get('source') != '5168']
    listings = dedupe(listings + rows)

    payload.setdefault('runs', {})['5168'] = {
        'status': 'ok',
        'totalCount': len(rows),
        'checkedAt': checked_at,
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

    last_good = {
        'updatedAt': checked_at,
        'source': '5168',
        'run': payload['runs']['5168'],
        'listings': rows,
    }
    Path('docs/preview/rental-houseprice-last-good.json').write_text(
        json.dumps(last_good, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )

    print(json.dumps({
        'source': '5168',
        'status': 'ok',
        'count': len(rows),
        'checkedAt': checked_at,
        'logs': logs,
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
