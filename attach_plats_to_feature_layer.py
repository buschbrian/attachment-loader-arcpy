"""Backward-compatible script entry point for plat/file attachment loading.

This runner lets people execute the repository copy directly without installing
it first. Package installations should use the console script defined in
pyproject.toml instead.
"""

from pathlib import Path
import sys

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from plat_attachment_loader.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
