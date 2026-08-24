import json
from pathlib import Path

CURRENT = Path('docs/preview/rental-data.json')
PREVIOUS = Path('/tmp/rental-data-previous.json')


def load(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def main():
    current = load(CURRENT)
    if not current:
        raise RuntimeError('rental-data.json missing or invalid')

    previous = load(PREVIOUS)
    previous_updated = previous.get('updatedAt')
    current_updated = current.get('updatedAt')
    if not current_updated:
        raise RuntimeError('rental-data.json updatedAt missing')

    previous_first_seen = {}
    for row in previous.get('listings') or []:
        if not isinstance(row, dict) or not row.get('id'):
            continue
        previous_first_seen[row['id']] = row.get('firstSeenAt') or previous_updated

    new_count = 0
    for row in current.get('listings') or []:
        if not isinstance(row, dict) or not row.get('id'):
            continue
        first_seen = previous_first_seen.get(row['id'])
        if not first_seen:
            first_seen = current_updated
            new_count += 1
        row['firstSeenAt'] = first_seen
        # Rental Preview intentionally uses only our own monitoring timestamp.
        row.pop('sourceUpdatedAt', None)
        row.pop('postTime', None)

    current['firstSeenPolicy'] = 'first_time_observed_by_banqiao_house_monitor'
    current['newListingCount'] = new_count
    CURRENT.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({
        'updatedAt': current_updated,
        'listingCount': len(current.get('listings') or []),
        'newListingCount': new_count,
        'preservedFirstSeenCount': len(current.get('listings') or []) - new_count,
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
