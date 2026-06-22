from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from plat_attachment_loader.config import MatchingConfig, load_matching_config, parse_extensions
from plat_attachment_loader.matching import name_from_file, norm, scan_plats


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.config = MatchingConfig.defaults()

    def test_norm_keeps_zero_key(self):
        self.assertEqual(norm(0, self.config), "0")

    def test_norm_applies_drop_words_and_aliases(self):
        self.assertEqual(norm("The Oak Hills Addition Final Plat", self.config), "OAK HILLS ADDN")

    def test_name_from_file_uses_named_group(self):
        path = Path("Oak_Hills_recorded_2024.pdf")
        self.assertEqual(name_from_file(path, r"^(?P<name>.+?)_recorded_\d+\.pdf$"), "Oak_Hills")

    def test_parse_extensions_normalizes_dots(self):
        self.assertEqual(parse_extensions("pdf,jpg,.tif"), frozenset({".pdf", ".jpg", ".tif"}))

    def test_scan_plats_overlay_by_relative_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base"
            overlay = root / "overlay"
            base.mkdir()
            overlay.mkdir()
            (base / "Oak.pdf").write_bytes(b"base")
            (overlay / "Oak.pdf").write_bytes(b"overlay")
            rows = scan_plats(base, False, None, self.config, overlay, "relative-path")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].path, (overlay / "Oak.pdf").resolve())
            self.assertEqual(rows[0].size_bytes, len(b"overlay"))

    def test_scan_plats_overlay_by_normalized_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base"
            overlay = root / "overlay"
            base.mkdir()
            overlay.mkdir()
            (base / "Oak Hills Addition.pdf").write_bytes(b"base")
            (overlay / "Oak Hills Addn reduced.pdf").write_bytes(b"overlay")
            # The default normalization does not drop "reduced", so use a config
            # that treats it as a noise word for this specific organization.
            config = load_matching_config(None)
            config = type(config)(
                drop_words=frozenset(set(config.drop_words) | {"REDUCED"}),
                aliases=config.aliases,
                extensions=config.extensions,
            )
            rows = scan_plats(base, False, None, config, overlay, "normalized-name")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].path, (overlay / "Oak Hills Addn reduced.pdf").resolve())


if __name__ == "__main__":
    unittest.main()
