from pathlib import Path
import json

PREVIEW = Path('docs/preview/index.html')
PRODUCTION = Path('docs/index.html')
VERIFY = Path('docs/preview/scheme-a-verification.json')
SOURCE = Path('docs/data/listings.json')
AUDIT = Path('docs/preview/scheme-a-saved-output-audit.json')
GAP = Path('docs/preview/company-gap.json')
RENTAL = Path('docs/preview/rental-data.json')


def main():
    for p in (PREVIEW, VERIFY, SOURCE, AUDIT, GAP, RENTAL):
        if not p.exists():
            raise RuntimeError(f'Missing production promotion prerequisite: {p}')

    verify = json.loads(VERIFY.read_text(encoding='utf-8'))
    source = json.loads(SOURCE.read_text(encoding='utf-8'))
    audit = json.loads(AUDIT.read_text(encoding='utf-8'))
    gap = json.loads(GAP.read_text(encoding='utf-8'))
    rental = json.loads(RENTAL.read_text(encoding='utf-8'))

    if verify.get('valid') is not True:
        raise RuntimeError('Canonical verification is not valid')
    if audit.get('passed') is not True:
        raise RuntimeError('Canonical saved-output audit did not pass')
    if verify.get('sourceDataUpdatedAt') != source.get('updatedAt'):
        raise RuntimeError(
            f"Canonical/source mismatch: {verify.get('sourceDataUpdatedAt')} != {source.get('updatedAt')}"
        )
    if verify.get('canonicalPublisher') != 'yungching-preview.yml':
        raise RuntimeError('Unexpected canonical publisher')
    if verify.get('integrityVersion') != 'scheme-a-canonical-v3-sinyi-floor-neartie':
        raise RuntimeError('Unexpected canonical integrity version')

    # Off-market history is display-only and must not mutate active company counts.
    if gap.get('recentOffMarketRetentionDays') != 10:
        raise RuntimeError(f"Unexpected off-market retention: {gap.get('recentOffMarketRetentionDays')}")
    offmarket = gap.get('recentOffMarketGroups')
    if not isinstance(offmarket, list):
        raise RuntimeError('Canonical off-market group list is missing')
    if int(gap.get('recentOffMarketCount') or 0) != len(offmarket):
        raise RuntimeError('Canonical off-market count/list mismatch')
    if any(x.get('offMarket') is not True or x.get('active') is not False or not x.get('removedAt') for x in offmarket):
        raise RuntimeError('Canonical off-market group contract failed')

    # Rental data is independently refreshed, but the production UI must only be
    # promoted when its current contract is intact.
    rental_listings = rental.get('listings') or []
    if rental.get('market') != 'rent':
        raise RuntimeError('Rental data market contract failed')
    if int((rental.get('counts') or {}).get('total') or 0) != len(rental_listings):
        raise RuntimeError('Rental data count/list mismatch')
    for source_name in ('591', '信義房屋'):
        if (rental.get('runs') or {}).get(source_name, {}).get('status') != 'ok':
            raise RuntimeError(f'Rental source is not healthy: {source_name}')

    text = PREVIEW.read_text(encoding='utf-8')
    text = text.replace('<meta name="robots" content="noindex,nofollow" />\n', '')
    text = text.replace('板橋新案監控 Preview', '板橋新案監控')
    text = text.replace('<title>Banqiao House Monitor Preview</title>', '<title>Banqiao House Monitor</title>')
    text = text.replace('<div class="preview-banner">🧪 PREVIEW 測試版本｜不影響正式網站</div>\n', '')
    text = text.replace('<div class="top">Banqiao House Monitor · Preview</div>', '<div class="top">Banqiao House Monitor</div>')
    text = text.replace('.top{position:sticky;top:39px;', '.top{position:sticky;top:0;')
    text = text.replace('`../data/listings.json?ts=${Date.now()}`', '`data/listings.json?ts=${Date.now()}`')
    text = text.replace('`company-gap.json?ts=${Date.now()}`', '`preview/company-gap.json?ts=${Date.now()}`')
    text = text.replace('`scheme-a-verification.json?ts=${Date.now()}`', '`preview/scheme-a-verification.json?ts=${Date.now()}`')
    text = text.replace('`rental-data.json?ts=${Date.now()}`', '`preview/rental-data.json?ts=${Date.now()}`')
    text = text.replace('Preview 資料', '網站資料')
    text = text.replace('canonical Preview', 'canonical production')

    if '<meta name="description"' not in text:
        text = text.replace(
            '<meta name="viewport" content="width=device-width,initial-scale=1" />',
            '<meta name="viewport" content="width=device-width,initial-scale=1" />\n<meta name="description" content="板橋指定路段 591、信義房屋刊登與永慶公司庫存比對" />',
            1,
        )

    required = [
        '<title>Banqiao House Monitor</title>',
        'Banqiao House Monitor</div>',
        '`data/listings.json?ts=${Date.now()}`',
        '`preview/company-gap.json?ts=${Date.now()}`',
        '`preview/scheme-a-verification.json?ts=${Date.now()}`',
        '`preview/rental-data.json?ts=${Date.now()}`',
        'function verificationMatches(d,g,v)',
        '案件清單暫停顯示',
        '<span>已下架</span><strong id="cUnavailable">',
        '<option value="removed">已下架</option>',
        'GAP.recentOffMarketCount??0',
        'GAP.recentOffMarketGroups||[]',
        '下架：${fmt(g.removedAt)}',
        'id="marketSwitch"',
        'data-market="sale"',
        'data-market="rent"',
        'function renderRentGroups()',
        'function setMarket(mode)',
        '首次抓到：${fmt(x.firstSeenAt)}',
    ]
    missing = [x for x in required if x not in text]
    if missing:
        raise RuntimeError(f'Production promotion contract failed; missing fragments: {missing}')
    forbidden = [
        'noindex,nofollow',
        'PREVIEW 測試版本',
        'Banqiao House Monitor · Preview',
        '`../data/listings.json?ts=${Date.now()}`',
        '`rental-data.json?ts=${Date.now()}`',
    ]
    present = [x for x in forbidden if x in text]
    if present:
        raise RuntimeError(f'Production promotion contract failed; forbidden fragments remain: {present}')

    PRODUCTION.write_text(text, encoding='utf-8')
    print(json.dumps({
        'promoted': True,
        'sourceDataUpdatedAt': verify.get('sourceDataUpdatedAt'),
        'verifiedAt': verify.get('verifiedAt'),
        'companyListingCount': verify.get('companyListingCount'),
        'propertyGroupCount': verify.get('propertyGroupCount'),
        'counts': verify.get('counts'),
        'recentOffMarketCount': gap.get('recentOffMarketCount'),
        'recentOffMarketRetentionDays': gap.get('recentOffMarketRetentionDays'),
        'rentalListingCount': len(rental_listings),
        'rentalUpdatedAt': rental.get('updatedAt'),
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
