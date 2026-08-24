import json
from datetime import datetime, timezone
from pathlib import Path

CURRENT = Path('docs/preview/rental-data.json')
PREVIOUS = Path('/tmp/rental-data-previous.json')

# User-approved baseline: every rental first observed on 2026-08-24 Taiwan time
# is existing stock. New-listing eligibility begins at 2026-08-25 00:00 +08:00.
DEFAULT_NEW_BASELINE_AT = '2026-08-24T16:00:00+00:00'
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


def later_baseline(*values):
    candidates = [(parse_stamp(v), v) for v in values if v]
    candidates = [(dt, raw) for dt, raw in candidates if dt is not None]
    if not candidates:
        return DEFAULT_NEW_BASELINE_AT
    dt, _ = max(candidates, key=lambda x: x[0])
    return dt.isoformat(timespec='seconds')


def is_new(first_seen, baseline, now):
    first = parse_stamp(first_seen)
    base = parse_stamp(baseline)
    if first is None or base is None or first < base:
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

    baseline = later_baseline(
        previous.get('newListingBaselineAt'),
        current.get('newListingBaselineAt'),
        DEFAULT_NEW_BASELINE_AT,
    )

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
    current['newListingPolicy'] = 'firstSeenAt_on_or_after_baseline_and_within_3_days'
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
