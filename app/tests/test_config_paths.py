"""Config path resolution: relative paths belong to the config file's folder.

The app is launched two ways -- a direct `python ar_dictate.py` (cwd = app\) and a
double-click on ar-dictate.cmd (cwd = repo root). A relative "dictate.log" used to
follow the cwd, so the double-click path wrote its log outside app\ and the live
probe (which looks in app\) reported "no log" while the app was actually fine.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

import ar_dictate  # noqa: E402


class TestConfigPathResolution(unittest.TestCase):
    def _write(self, tmp: Path, cfg: dict) -> Path:
        p = tmp / "config.json"
        p.write_text(json.dumps(cfg), encoding="utf-8")
        return p

    def test_relative_log_and_model_resolve_against_the_config_folder(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cfg_file = self._write(tmp, {"model": "models/x", "log": "dictate.log"})
            cfg = ar_dictate.load_config(cfg_file)
            self.assertEqual(Path(cfg["log"]), (tmp / "dictate.log").resolve())
            self.assertEqual(Path(cfg["model"]), (tmp / "models" / "x").resolve())

    def test_absolute_paths_are_kept_as_is(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            absolute = str((tmp / "elsewhere.log"))
            cfg_file = self._write(tmp, {"model": "models/x", "log": absolute})
            cfg = ar_dictate.load_config(cfg_file)
            self.assertEqual(cfg["log"], absolute)

    def test_missing_config_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = ar_dictate.load_config(Path(td) / "nope.json")
            self.assertEqual(cfg["sample_rate"], 16000)

    def test_shipped_config_log_is_relative(self):
        """Keeps the shipped config portable -- an absolute path would pin the app
        to one machine's folder layout."""
        raw = json.loads((APP / "config.json").read_text(encoding="utf-8"))
        self.assertFalse(Path(raw["log"]).is_absolute(), f'log must stay relative: {raw["log"]}')

    def test_shipped_config_profiles_resolve_to_real_folders(self):
        """Regression: --profile fast/accurate paths are relative to the app folder.
        They used to be resolved against the launch directory, so the double-click
        launcher (cwd = repo root) died with 'model not found: ..\\models\\...'."""
        raw = json.loads((APP / "config.json").read_text(encoding="utf-8"))
        profiles = raw.get("models") or {}
        self.assertTrue(profiles, "config.json must define models.fast / models.accurate")
        for name, rel in profiles.items():
            with self.subTest(profile=name):
                resolved = (APP / rel).resolve()
                self.assertTrue(
                    resolved.is_dir(),
                    f"models.{name} -> {resolved} is not a directory",
                )
                # must stay inside the repo, not escape to a user folder outside it
                self.assertEqual(resolved.parent, APP.parent / "models")


if __name__ == "__main__":
    unittest.main()
