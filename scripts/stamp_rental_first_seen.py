import json
from datetime import datetime, timezone
from pathlib import Path

CURRENT = Path('docs/preview/rental-data.json')
PREVIOUS = Path('/tmp/rental-data-previous.json')

# User-approved baseline: everything already observed on 2026-08-24 is existing stock.
# Only listings first observed after this instant can receive the 3-day "new" badge.
DEFAULT_NEW_BASELINE_AT = '2026-08-24T13:41:00+00:00'
NEW_WINDOW_DAYS = 3


def load(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def parse_stamp(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def is_new(first_seen, baseline, now):
    first = parse_stamp(first_seen)
    base = parse_stamp(baseline)
    if first is None or base is None or first <= base:
        return False
    age = (now - first).total_seconds()
    return 0 <= age < NEW_WINDOW_DAYS * 86400


def main():
    current = load(CURRENT)
    if not current:
        raise RuntimeError('rental-data.json missing or invalid')

    previous = load(PREVIOUS)
    previous_updated = previous.get('updatedAt')
    current_updated = current.get('updatedAt')
    if not current_updated:
        raise RuntimeError('rental-data.json updatedAt missing')

    baseline = (
        previous.get('newListingBaselineAt')
        or current.get('newListingBaselineAt')
        or DEFAULT_NEW_BASELINE_AT
    )
    if parse_stamp(baseline) is None:
        baseline = DEFAULT_NEW_BASELINE_AT

    previous_first_seen = {}
    for row in previous.get('listings') or []:
        if not isinstance(row, dict) or not row.get('id'):
            continue
        previous_first_seen[row['id']] = row.get('firstSeenAt') or previous_updated

    for row in current.get('listings') or []:
        if not isinstance(row, dict) or not row.get('id'):
            continue
        first_seen = previous_first_seen.get(row['id'])
        if not first_seen:
            first_seen = current_updated
        row['firstSeenAt'] = first_seen
        # Rental site intentionally uses only our own monitoring timestamp.
        row.pop('sourceUpdatedAt', None)
        row.pop('postTime', None)

    now = datetime.now(timezone.utc)
    new_count = sum(
        1
        for row in (current.get('listings') or [])
        if isinstance(row, dict) and is_new(row.get('firstSeenAt'), baseline, now)
    )

    current['firstSeenPolicy'] = 'first_time_observed_by_banqiao_house_monitor'
    current['newListingBaselineAt'] = baseline
    current['newListingWindowDays'] = NEW_WINDOW_DAYS
    current['newListingPolicy'] = 'firstSeenAt_after_baseline_and_within_3_days'
    current['newListingCount'] = new_count
    CURRENT.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({
        'updatedAt': current_updated,
        'listingCount': len(current.get('listings') or []),
        'newListingBaselineAt': baseline,
        'newListingWindowDays': NEW_WINDOW_DAYS,
        'newListingCount': new_count,
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
