from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from plat_attachment_loader.config import MatchingConfig
from plat_attachment_loader.matching import PlatFile
from plat_attachment_loader.planning import (
    build_plan,
    missing_planned_attachment_rows,
    missing_polygon_rows,
    plat_lookup,
    unresolved,
    verified_attached_oids,
)


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.config = MatchingConfig.defaults()

    def test_build_plan_handles_matched_unmatched_ambiguous_and_too_large(self):
        plats = [
            PlatFile(Path("Oak.pdf"), "Oak", 100),
            PlatFile(Path("Pine.pdf"), "Pine", 100),
            PlatFile(Path("Cedar.pdf"), "Cedar", 100),
            PlatFile(Path("Big.pdf"), "Big", 20 * 1024 * 1024),
        ]
        found = {
            "OAK": [(1, "Oak")],
            "CEDAR": [(2, "Cedar"), (3, "Cedar")],
        }
        report, attach = build_plan(10, False, plats, found, self.config)
        statuses = [row["status"] for row in report]
        self.assertIn("matched", statuses)
        self.assertIn("unmatched", statuses)
        self.assertIn("ambiguous", statuses)
        self.assertIn("too_large", statuses)
        self.assertEqual(len(attach), 1)

    def test_unresolved_can_ignore_unmatched_files(self):
        rows = [{"status": "unmatched"}, {"status": "too_large"}, {"status": "matched"}]
        self.assertEqual(len(unresolved(rows)), 2)
        self.assertEqual(len(unresolved(rows, ignore_unmatched_files=True)), 1)

    def test_missing_polygon_rows_pre_and_post_attachment(self):
        plats = [PlatFile(Path("Oak.pdf"), "Oak", 100)]
        lookup = plat_lookup(plats, self.config)
        features = [{"oid": 1, "NAME": "Oak"}, {"oid": 2, "NAME": "Pine"}, {"oid": 3, "NAME": None}]
        pre = missing_polygon_rows(features, "NAME", lookup, 10, self.config, planned={1})
        self.assertEqual({row["missing_reason"] for row in pre}, {"no_matching_attachment_file", "blank_key_field"})
        post = missing_polygon_rows(features, "NAME", lookup, 10, self.config, attached={1})
        self.assertEqual(len(post), 2)

    def test_missing_polygon_rows_reports_matching_file_that_is_not_planned(self):
        plats = [PlatFile(Path("Oak.pdf"), "Oak", 100)]
        lookup = plat_lookup(plats, self.config)
        features = [{"oid": 1, "NAME": "Oak"}]

        rows = missing_polygon_rows(features, "NAME", lookup, 10, self.config, planned=set())

        self.assertEqual(rows[0]["missing_reason"], "not_planned_for_attachment")
        self.assertEqual(rows[0]["file_size_mb"], "0.000")

    def test_verification_checks_expected_filename(self):
        rows = [
            {"oid": 1, "file": "Oak.pdf"},
            {"oid": 2, "file": "Pine.pdf"},
        ]
        existing = {1: {"Oak.pdf"}, 2: {"Other.pdf"}}
        self.assertEqual(verified_attached_oids(rows, existing), {1})
        missing = missing_planned_attachment_rows(rows, existing)
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["oid"], 2)


if __name__ == "__main__":
    unittest.main()
