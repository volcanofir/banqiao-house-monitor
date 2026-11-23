"""Fail closed when GitHub or Pages shows missing, older or malformed Sinyi data."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from verify_sinyi_publication import (
    PAGES_HTML, PAGES_JSON, verify_public_site, verify_snapshot,
)
from test_preview_source_freshness import verified_sinyi, stamp


class PublicationTests(unittest.TestCase):
    def test_exact_verified_published_snapshot(self):
        expected = verified_sinyi(60)
        self.assertEqual(verify_snapshot(expected, copy.deepcopy(expected), "remote"), expected)

    def test_newer_verified_snapshot_safely_wins_concurrent_write(self):
        self.assertEqual(verify_snapshot(verified_sinyi(60), verified_sinyi(30), "remote")["updatedAt"], stamp(30))

    def test_older_remote_must_not_pass(self):
        with self.assertRaisesRegex(ValueError, "older"):
            verify_snapshot(verified_sinyi(30), verified_sinyi(60), "remote")

    def test_same_time_different_ids_must_not_pass(self):
        expected = verified_sinyi(30)
        corrupted = copy.deepcopy(expected)
        corrupted["listings"][0]["id"] = "信義房屋:DIFFERENT"
        with self.assertRaisesRegex(ValueError, "content differs"):
            verify_snapshot(expected, corrupted, "remote")

    def test_incomplete_source_cannot_be_published(self):
        corrupted = verified_sinyi(30)
        corrupted["complete"] = False
        with self.assertRaisesRegex(ValueError, "incomplete"):
            verify_snapshot(verified_sinyi(30), corrupted, "remote")

    def test_page_must_embed_source_loader(self):
        expected = verified_sinyi(30)
        from json import dumps
        with patch("verify_sinyi_publication.fetch_text", side_effect=[dumps(expected), "<html>old preview</html>"]):
            with self.assertRaisesRegex(RuntimeError, "not confirmed"):
                verify_public_site(expected, retries=1, delay=0)

    def test_page_and_json_are_verified(self):
        from json import dumps
        expected = verified_sinyi(30)
        seen = []

        def fake_fetch(url):
            seen.append(url)
            if url == PAGES_JSON:
                return dumps(expected)
            if url == PAGES_HTML:
                return "<html>refreshLiveSourceReports('sinyi-source.json')</html>"
            raise AssertionError(url)

        with patch("verify_sinyi_publication.fetch_text", side_effect=fake_fetch):
            self.assertEqual(verify_public_site(expected, retries=1, delay=0), expected)
        self.assertEqual(seen, [PAGES_JSON, PAGES_HTML])


if __name__ == "__main__":
    unittest.main()
