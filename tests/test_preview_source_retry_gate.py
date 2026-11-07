import unittest
from datetime import datetime, timedelta, timezone
from scripts.preview_source_retry_gate import decision


NOW = datetime(2026, 11, 7, 15, 0, tzinfo=timezone.utc)


def iso(minutes_ago):
    return (NOW - timedelta(minutes=minutes_ago)).isoformat()


def snapshot(minutes_ago, source="樂屋網"):
    return {"source": source, "complete": True, "updatedAt": iso(minutes_ago)}


def run(minutes_ago, conclusion="failure", status="completed", source="rakuya"):
    return {"displayTitle": "preview-source:" + source, "createdAt": iso(minutes_ago),
            "conclusion": conclusion, "status": status}


class RefreshPolicyTests(unittest.TestCase):
    def test_recent_snapshot_prevents_unnecessary_retry(self):
        self.assertFalse(decision("rakuya", snapshot(40), [run(35)], NOW)[0])

    def test_failure_retries_after_thirty_minutes_when_stale(self):
        self.assertFalse(decision("rakuya", snapshot(300), [run(29)], NOW)[0])
        self.assertTrue(decision("rakuya", snapshot(300), [run(31)], NOW)[0])

    def test_healthy_schedule_uses_three_hours(self):
        self.assertFalse(decision("rakuya", snapshot(179), [], NOW)[0])
        self.assertTrue(decision("rakuya", snapshot(180), [], NOW)[0])

    def test_running_workflow_blocks_duplicate_dispatch(self):
        self.assertFalse(decision("rakuya", snapshot(400),
                                  [run(50, status="in_progress")], NOW)[0])

    def test_succeeded_attempt_protects_against_spam(self):
        self.assertFalse(decision("rakuya", snapshot(360),
                                  [run(40, conclusion="success")], NOW)[0])
        self.assertTrue(decision("rakuya", snapshot(360),
                                 [run(181, conclusion="success")], NOW)[0])

    def test_591_uses_distinct_workflow(self):
        s = snapshot(360, "591_public_warelist_initial_state")
        self.assertTrue(decision("591", s, [dict(run(31), displayTitle="591 feed")], NOW)[0])

    def test_incomplete_crawl_does_not_clear_or_delist(self):
        self.assertFalse(decision("houseprice", {"source": "5168", "complete": False},
                                  [run(10, source="houseprice")], NOW)[0])
        self.assertTrue(decision("houseprice", {"source": "5168", "complete": False},
                                 [run(31, source="houseprice")], NOW)[0])

    def test_per_source_dispatch_ignores_other_sources(self):
        self.assertTrue(decision("sinyi", {}, [run(5, source="rakuya")], NOW)[0])


if __name__ == "__main__":
    unittest.main()
