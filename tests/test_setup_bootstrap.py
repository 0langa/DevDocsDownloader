from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SETUP_PATH = Path(__file__).resolve().parents[1] / "scripts" / "setup.py"
SPEC = importlib.util.spec_from_file_location("repo_setup", SETUP_PATH)
assert SPEC is not None and SPEC.loader is not None
SETUP_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SETUP_MODULE)


class SetupBootstrapTests(unittest.TestCase):
    def test_ensure_directories_creates_current_runtime_layout(self) -> None:
        expected = [
            "output",
            "output/markdown",
            "output/reports",
            "output/diagnostics",
            "cache",
            "cache/discovered_links",
            "logs",
            "state",
            "tmp",
        ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(SETUP_MODULE, "REPO_ROOT", root):
                SETUP_MODULE.ensure_directories()

            for relative in expected:
                self.assertTrue((root / relative).is_dir(), relative)


if __name__ == "__main__":
    unittest.main()