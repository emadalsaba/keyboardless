"""لا تخرج تفاصيل جهاز معيّن إلى المستودع العام.

The repository is public: machine names, a Windows account folder, and a work
e-mail address belong to the private setup, not to the product. The patterns are
assembled from parts so this file does not trip over itself.
"""

import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
ROOT = APP.parent

#: assembled from pieces on purpose (see the module docstring)
FORBIDDEN = (
    "C:\\Users\\" + "alsaba",
    "C:/Users/" + "alsaba",
    "DESKTOP" + "-SHOME",
    "inmaa" + "albilad",
    "hr@" + "inmaa" + "albilad.com",
)

TEXT_SUFFIXES = {".md", ".py", ".ps1", ".cmd", ".iss", ".spec", ".json", ".txt"}
SKIP_DIRS = {".venv", "venv", "models", "dist", "build", "__pycache__", ".git"}
#: the local config may legitimately record a device chosen on this machine only
SKIP_NAMES = {"config.json"}


def published_files():
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if path.name in SKIP_NAMES:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        yield path


class TestNothingPersonalIsPublished(unittest.TestCase):
    def test_sources_carry_no_machine_or_account_details(self):
        offenders = []
        mine = Path(__file__).resolve()
        for path in published_files():
            if path.resolve() == mine:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for needle in FORBIDDEN:
                if needle.lower() in text.lower():
                    offenders.append(f"{path.relative_to(ROOT)} :: {needle}")
        self.assertEqual(offenders, [], "تفاصيل خاصة بجهاز عماد ستُنشر على GitHub")

    def test_the_readme_points_at_the_public_account(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("github.com/emadalsaba/keyboardless", readme)
        self.assertNotIn("alsebaa", readme.lower())

    def test_the_public_tokens_are_not_in_the_tree(self):
        """رموز GitHub تُخزَّن خارج المشروع، ولا يجوز أن تُنسخ إليه.

        The patterns are split so this file does not flag itself.
        """
        prefixes = ("github" + "_pat_", "ghp" + "_", "github" + "_oauth")
        mine = Path(__file__).resolve()
        for path in list(published_files()):
            if path.resolve() == mine:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for prefix in prefixes:
                self.assertNotIn(prefix, text, str(path))


class TestThePublishedDocsExist(unittest.TestCase):
    EXPECTED = ("README.md", "CHANGELOG.md", "LICENSE", ".gitignore",
                "docs/users-guide.md", "docs/developer-notes.md")

    def test_every_document_is_there(self):
        for name in self.EXPECTED:
            self.assertTrue((ROOT / name).is_file(), name)

    def test_the_documents_are_arabic_and_substantial(self):
        for name in ("README.md", "docs/users-guide.md", "docs/developer-notes.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            letters = len(re.findall(r"[\u0600-\u06FF]", text))
            self.assertGreater(letters, 1500, f"{name}: {letters} حرفًا عربيًا فقط")
            self.assertGreater(len(text), 3000, name)

    def test_the_readme_shows_the_artwork_and_the_guide_is_linked(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/images/icon-ready.png", readme)
        self.assertIn("docs/images/window-settings.png", readme)
        self.assertIn("docs/users-guide.md", readme)
        for image in ("icon-ready", "icon-listening", "icon-paused", "icon-mono",
                      "window-settings", "window-models", "about"):
            self.assertTrue((ROOT / "docs" / "images" / f"{image}.png").is_file(), image)


class TestTheInstallGuideCannotDrift(unittest.TestCase):
    """الأدلة تذكر ما يقوله الكود فعلًا: الاسم، الإصدار، أسماء النماذج، الاختصارات."""

    def setUp(self):
        sys.path.insert(0, str(APP))
        import branding
        self.branding = branding
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.guide = (ROOT / "docs" / "users-guide.md").read_text(encoding="utf-8")

    def test_the_version_in_the_docs_matches_the_product(self):
        for text, name in ((self.readme, "README"), (self.guide, "الدليل")):
            self.assertIn(self.branding.VERSION, text, name)

    def test_the_docs_name_the_hotkeys_that_are_configured(self):
        config = (APP / "config.json").read_text(encoding="utf-8").lower()
        self.assertIn("ctrl+alt+d", config)
        for key in ("ctrl+alt+d", "ctrl+alt+j", "ctrl+alt+m", "ctrl+alt+q"):
            self.assertIn(key, self.readme.replace("`", "").lower())
            self.assertIn(key, self.guide.replace("`", "").lower())

    def test_the_guide_lists_every_model_the_app_can_download(self):
        import model_store
        names = [entry.name for entry in model_store.ARABIC_MODELS]
        for name in names:
            self.assertIn(name, self.guide, name)


if __name__ == "__main__":
    unittest.main()
