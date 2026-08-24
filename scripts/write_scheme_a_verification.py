import json
from datetime import datetime, timezone
from pathlib import Path


def main():
    p = json.loads(Path('docs/preview/company-gap.json').read_text(encoding='utf-8'))
    s = json.loads(Path('docs/preview/yungching-browser-snapshot.json').read_text(encoding='utf-8'))
    sf = json.loads(Path('docs/preview/sinyi-floor-enrichment.json').read_text(encoding='utf-8'))
    aa = json.loads(Path('docs/preview/scheme-a-ambiguity-audit.json').read_text(encoding='utf-8'))
    d = json.loads(Path('docs/data/listings.json').read_text(encoding='utf-8'))
    comparisons = p.get('comparisons') or []
    candidates = [x.get('companyCandidate') for x in comparisons if x.get('companyCandidate')]
    near = p.get('companyNearTieGuard') or {}

    manifest = {
        'verifiedAt': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'scheme': 'A',
        'integrityVersion': 'scheme-a-canonical-v3-sinyi-floor-neartie',
        'source': 'Sinyi official __NEXT_DATA__ structured floors + Surfshark + system Chrome official Yongching DOM + all-pages direct pg pagination + verified detail cache',
        'fetchMode': p.get('fetchMode'),
        'sourceDataUpdatedAt': p.get('sourceDataUpdatedAt'),
        'safeFloorParser': p.get('safeFloorParser'),
        'sinyiStructuredFloorMatching': p.get('sinyiStructuredFloorMatching'),
        'sinyiFloorEnrichment': sf,
        'companyNearTieGuard': near,
        'ambiguityAudit': {
            'auditedAt': aa.get('auditedAt'),
            'propertyGroupCount': aa.get('propertyGroupCount'),
            'companyListingCount': aa.get('companyListingCount'),
            'companyMatchCount': aa.get('companyMatchCount'),
            'companyNearTieStrongCount': aa.get('companyNearTieStrongCount'),
            'chosenCandidateRecomputeMismatchCount': aa.get('chosenCandidateRecomputeMismatchCount'),
            'weakIdentityAlreadyMergedPairCount': aa.get('weakIdentityAlreadyMergedPairCount'),
        },
        'snapshotCapturedAt': s.get('capturedAt'),
        'companySnapshotCapturedAt': p.get('companySnapshotCapturedAt'),
        'companyGapGeneratedAt': p.get('generatedAt'),
        'browserListingCount': s.get('listingCount'),
        'companyListingCount': p.get('companyListingCount'),
        'propertyGroupCount': p.get('propertyGroupCount'),
        'rawListingCount': p.get('rawListingCount'),
        'comparisonCount': len(comparisons),
        'coveredRoads': p.get('coveredRoads'),
        'roadCounts': {r: (st or {}).get('count') for r, st in (s.get('roadStatus') or {}).items()},
        'pagination': {r: {
            'expected': (st or {}).get('paginationExpected'),
            'lastPage': (st or {}).get('paginationLastPage'),
            'exhausted': (st or {}).get('paginationExhausted'),
            'completeAllPages': (st or {}).get('paginationCompleteAllPages'),
        } for r, st in (s.get('roadStatus') or {}).items()},
        'counts': p.get('counts'),
        'crossPlatformMergedGroupCount': p.get('crossPlatformMergedGroupCount'),
        'crossSourceReviewCount': p.get('crossSourceReviewCount'),
        'preview591Regroup': p.get('preview591Regroup'),
        'schemeAGroupIntegrity': p.get('schemeAGroupIntegrity'),
        'idIntegrityGuard': s.get('idIntegrityGuard'),
        'candidateCount': len(candidates),
        'candidatesWithFloor': sum(1 for x in candidates if x.get('floor')),
        'candidatesWithYcCaseId': sum(1 for x in candidates if x.get('officialCaseId')),
        'detailFloorEnrichment': s.get('detailFloorEnrichment'),
        'legacyFallbacks': False,
        'canonicalPublisher': 'yungching-preview.yml',
        'valid': True,
    }

    assert manifest['sourceDataUpdatedAt'] and manifest['sourceDataUpdatedAt'] == d.get('updatedAt'), (manifest['sourceDataUpdatedAt'], d.get('updatedAt'))
    assert manifest['safeFloorParser'] is True, manifest
    assert manifest['sinyiStructuredFloorMatching'] is True, manifest
    assert sf.get('complete') is True, sf
    assert sf.get('activeSinyiCount') == sf.get('matchedOfficialCount') == sf.get('appliedCount'), sf
    assert int(near.get('remainingAutoNearTieCount') or 0) == 0, near
    assert int(aa.get('companyNearTieStrongCount') or 0) == 0, aa
    assert int(aa.get('chosenCandidateRecomputeMismatchCount') or 0) == 0, aa
    assert manifest['snapshotCapturedAt'] == manifest['companySnapshotCapturedAt'], manifest
    assert manifest['browserListingCount'] == manifest['companyListingCount'], manifest
    assert manifest['propertyGroupCount'] == manifest['comparisonCount'], manifest
    assert all(x.get('completeAllPages') is True and x.get('exhausted') is True for x in manifest['pagination'].values()), manifest['pagination']

    Path('docs/preview/scheme-a-verification.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == '__main__':
    main()
