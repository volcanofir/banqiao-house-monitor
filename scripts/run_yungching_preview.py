import compare_yungching_preview_v2 as v2

_original_fetch_company = v2.fetch_company


def fetch_company_with_verified_fallback():
    company, logs, status = _original_fetch_company()
    road = "板橋區中山路二段"
    st = status.get(road) or {}
    # We already have a verified HAR snapshot for Zhongshan Rd Sec. 2. If the
    # public proxy returns a parsable page but zero direct-company cards, treat
    # that proxy result as unavailable rather than falsely declaring no inventory.
    if st.get("available") and int(st.get("count") or 0) == 0:
        st["available"] = False
        st["mode"] = "proxy_empty_use_har_fallback"
        logs.append(f"{road}: proxy returned 0 direct rows; use verified HAR fallback")
    return company, logs, status


v2.fetch_company = fetch_company_with_verified_fallback
v2.main()
