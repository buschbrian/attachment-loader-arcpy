from pathlib import Path
import csv
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from plat_attachment_loader.reports import default_metadata, write_attachment_report


class ReportTests(unittest.TestCase):
    def test_write_attachment_report_includes_metadata_and_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.csv"
            metadata = default_metadata("fc", Path("files"), None, "NAME", 10)
            write_attachment_report(path, [{"status": "matched", "oid": 1, "file": "Oak.pdf"}], metadata)
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["input_features"], "fc")
            self.assertEqual(rows[0]["key_field"], "NAME")
            sidecar = path.with_suffix(path.suffix + ".metadata.json")
            self.assertTrue(sidecar.exists())
            self.assertEqual(json.loads(sidecar.read_text(encoding="utf-8"))["input_features"], "fc")


if __name__ == "__main__":
    unittest.main()
