"""تنزيل النماذج: المسار المخصص، الاستكمال، والأمان.

A downloaded model comes off the internet, so the downloader is treated as
parsing untrusted input: the archive must not be able to write outside the
models folder, and an interrupted 666 MB download must resume rather than start
again from zero.
"""

import http.server
import io
import json
import os
import sys
import threading
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))

import model_store  # noqa: E402
from model_store import ARABIC_MODELS, DEFAULT_MODEL, ModelInfo, download, models_dir  # noqa: E402


def make_archive(path: Path, folder: str, *, extra: dict | None = None,
                 trailer: bytes = b"", with_conf: bool = True) -> Path:
    """A stand-in for a real Vosk archive (same shape, tiny size)."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        if with_conf:
            zf.writestr(f"{folder}/conf/model.conf", "--sample-rate=16000\n")
        zf.writestr(f"{folder}/am/final.mdl", b"x" * 4096)
        zf.writestr(f"{folder}/graph/words.txt", b"word 1\n")
        if trailer:
            zf.writestr(f"{folder}/payload.bin", trailer)
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return path


class RangeHandler(http.server.BaseHTTPRequestHandler):
    """Serves one payload and honours ``Range`` so resume can be tested."""

    payload = b""
    statuses: list[str] = []
    if_ranges: list[str] = []
    honour_range = True
    etag = '"v1"'

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        raw = self.headers.get("Range") or ""
        if not RangeHandler.honour_range:
            raw = ""
        RangeHandler.statuses.append(raw)
        RangeHandler.if_ranges.append(self.headers.get("If-Range") or "")
        start = 0
        if raw.startswith("bytes="):
            start = int(raw.split("=", 1)[1].split("-", 1)[0] or 0)
        body = self.payload[start:]
        self.send_response(206 if start else 200)
        self.send_header("ETag", RangeHandler.etag)
        self.send_header("Content-Length", str(len(body)))
        if start:
            self.send_header("Content-Range",
                             f"bytes {start}-{len(self.payload) - 1}/{len(self.payload)}")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # keep the test output clean
        pass


class ModelServer:
    """A local HTTP server for one archive."""

    def __init__(self, payload: bytes, honour_range: bool = True):
        RangeHandler.payload = payload
        RangeHandler.statuses = []
        RangeHandler.if_ranges = []
        RangeHandler.honour_range = honour_range
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}/model.zip"

    @property
    def requests(self) -> list[str]:
        return RangeHandler.statuses

    @property
    def conditionals(self) -> list[str]:
        return RangeHandler.if_ranges

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class TestModelCatalogue(unittest.TestCase):
    def test_every_catalogue_entry_is_free_and_arabic(self):
        self.assertTrue(ARABIC_MODELS)
        for info in ARABIC_MODELS:
            self.assertTrue(info.name.startswith("vosk-model"))
            self.assertIn("ar", info.name, "the catalogue is Arabic-only")
            self.assertTrue(info.archive.startswith("https://"))
            self.assertGreater(info.size_mb, 0)
            self.assertTrue(info.title and info.note)

    def test_sizes_are_download_sizes_and_plausible(self):
        """``size_mb`` is what the user downloads, not the unpacked size."""
        for info in ARABIC_MODELS:
            self.assertGreaterEqual(info.size_mb, 50, info.name)
            self.assertLessEqual(info.size_mb, 2000, info.name)

    def test_a_plausible_but_missing_model_name_is_not_in_the_catalogue(self):
        """``vosk-model-ar-0.22-lgraph`` looked right and was a 404.

        Only a real request showed it; ``--verify-urls`` is how the list is
        re-checked, and this pins the correction.
        """
        self.assertIsNone(model_store.find("vosk-model-ar-0.22-lgraph"))
        names = [info.name for info in ARABIC_MODELS]
        self.assertIn("vosk-model-ar-0.22-linto-1.1.0", names)
        self.assertEqual(names[0], DEFAULT_MODEL, "the default is downloaded first")

    def test_default_model_is_in_the_catalogue(self):
        self.assertIsNotNone(model_store.find(DEFAULT_MODEL))

    def test_installed_detection_needs_the_real_folder_shape(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertFalse(model_store.is_installed(DEFAULT_MODEL, root))
            (root / DEFAULT_MODEL / "am").mkdir(parents=True)
            self.assertFalse(model_store.is_installed(DEFAULT_MODEL, root),
                             "a half-copied model is not an installed model")
            (root / DEFAULT_MODEL / "conf").mkdir()
            self.assertTrue(model_store.is_installed(DEFAULT_MODEL, root))

    def test_dedicated_path_can_be_forced(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(models_dir(Path(tmp)), Path(tmp))

    def test_environment_override_wins(self):
        with TemporaryDirectory() as tmp:
            old = os.environ.get("AR_DICTATE_MODELS")
            os.environ["AR_DICTATE_MODELS"] = tmp
            try:
                self.assertEqual(models_dir(), Path(tmp))
            finally:
                if old is None:
                    os.environ.pop("AR_DICTATE_MODELS", None)
                else:
                    os.environ["AR_DICTATE_MODELS"] = old


class TestDownload(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.archive_path = make_archive(self.root / "archive.zip", "fake-model",
                                         trailer=b"z" * 200_000)
        self.payload = self.archive_path.read_bytes()
        self.server = ModelServer(self.payload)
        self.info = ModelInfo("fake-model", "تجربة", 12, "for tests", self.server.url)

    def tearDown(self):
        self.server.close()
        self.tmp.cleanup()

    def test_download_extracts_into_the_dedicated_folder(self):
        target = download(self.info, self.root / "models")
        self.assertEqual(target, self.root / "models" / "fake-model")
        self.assertTrue((target / "conf" / "model.conf").exists())
        self.assertTrue((target / "am" / "final.mdl").exists())
        self.assertTrue(model_store.is_installed("fake-model", self.root / "models"))

    def test_the_archive_is_not_left_behind(self):
        download(self.info, self.root / "models")
        leftovers = list((self.root / "models").glob("*.zip*"))
        self.assertEqual(leftovers, [], "the .part file must be cleaned up")

    def test_progress_reports_both_phases(self):
        seen = []
        download(self.info, self.root / "models",
                 progress=lambda name, done, total, phase: seen.append(phase))
        self.assertIn("downloading", seen)
        self.assertEqual(seen[-1], "installed")

    def test_an_installed_model_is_never_downloaded_again(self):
        download(self.info, self.root / "models")
        before = len(self.server.requests)
        # even with an unreachable url: the folder is already there
        dead = ModelInfo("fake-model", "تجربة", 12, "", "http://127.0.0.1:1/model.zip")
        target = download(dead, self.root / "models")
        self.assertTrue(target.exists())
        self.assertEqual(len(self.server.requests), before)

    def test_an_interrupted_download_resumes(self):
        models = self.root / "models"
        models.mkdir()
        cut = len(self.payload) // 2
        (models / "fake-model.zip.part").write_bytes(self.payload[:cut])
        (models / "fake-model.zip.meta").write_text(
            json.dumps({"validator": RangeHandler.etag}), encoding="utf-8")
        download(self.info, models)
        self.assertTrue(model_store.is_installed("fake-model", models))
        self.assertTrue(any(r.startswith("bytes=") for r in self.server.requests),
                        "the partial file must be sent back as a Range request")
        self.assertIn(RangeHandler.etag, self.server.conditionals,
                      "the server must be asked whether the file is still the same one")

    def test_a_partial_without_a_fingerprint_starts_over(self):
        """Proving nothing about the bytes we already have means not trusting them."""
        models = self.root / "models"
        models.mkdir()
        (models / "fake-model.zip.part").write_bytes(self.payload[:1000])
        download(self.info, models)
        self.assertEqual(self.server.requests, [""], "a fresh, un-ranged download")
        self.assertTrue(model_store.is_installed("fake-model", models))

    def test_a_corrupt_partial_file_is_replaced_not_appended(self):
        models = self.root / "models"
        models.mkdir()
        (models / "fake-model.zip.part").write_bytes(b"junk" * 100)
        (models / "fake-model.zip.meta").write_text(
            json.dumps({"validator": RangeHandler.etag}), encoding="utf-8")
        target = download(self.info, models)
        self.assertTrue((target / "conf" / "model.conf").exists(),
                        "a corrupt partial download must be thrown away and redone")

    def test_a_server_that_ignores_range_is_handled(self):
        models = self.root / "models"
        models.mkdir()
        (models / "fake-model.zip.part").write_bytes(self.payload[:1000])
        (models / "fake-model.zip.meta").write_text(
            json.dumps({"validator": RangeHandler.etag}), encoding="utf-8")
        self.server.close()
        self.server = ModelServer(self.payload, honour_range=False)
        plain = ModelInfo("fake-model", "تجربة", 12, "", self.server.url)
        target = download(plain, models)
        self.assertTrue((target / "conf" / "model.conf").exists())

    def test_progress_is_reported_for_an_already_installed_model(self):
        download(self.info, self.root / "models")
        seen = []
        download(self.info, self.root / "models",
                 progress=lambda n, d, t, phase: seen.append(phase))
        self.assertEqual(seen, ["installed"])


class TestUntrustedArchives(unittest.TestCase):
    """A model archive is downloaded input: it must not escape its folder."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _serve(self, archive: Path) -> tuple[ModelServer, ModelInfo]:
        server = ModelServer(archive.read_bytes())
        self.addCleanup(server.close)
        return server, ModelInfo("evil-model", "خطر", 1, "", server.url)

    def test_traversal_entries_are_refused(self):
        archive = self.root / "evil.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("evil-model/conf/model.conf", "")
            zf.writestr("../../startup.bat", "whoami")
        server, info = self._serve(archive)
        with self.assertRaises(RuntimeError) as caught:
            download(info, self.root / "models")
        self.assertIn("غير آمن", str(caught.exception))
        self.assertFalse((self.root / "startup.bat").exists())
        self.assertFalse((self.root.parent / "startup.bat").exists())

    def test_an_archive_without_a_recogniser_is_refused(self):
        archive = make_archive(self.root / "notamodel.zip", "junk", with_conf=False)
        server, info = self._serve(archive)
        with self.assertRaises(RuntimeError):
            download(info, self.root / "models")

    def test_failed_download_leaves_no_partial_install(self):
        archive = make_archive(self.root / "notamodel.zip", "junk", with_conf=False)
        server, info = self._serve(archive)
        with self.assertRaises(RuntimeError):
            download(info, self.root / "models")
        self.assertFalse((self.root / "models" / "evil-model").exists())


class TestCli(unittest.TestCase):
    def test_list_reports_every_catalogue_entry(self):
        with TemporaryDirectory() as tmp:
            stream = io.StringIO()
            old, sys.stdout = sys.stdout, stream
            try:
                code = model_store.cli(["--list", "--json", "--dir", tmp])
            finally:
                sys.stdout = old
            self.assertEqual(code, 0)
            payload = json.loads(stream.getvalue())
            self.assertEqual(len(payload["models"]), len(ARABIC_MODELS))
            self.assertEqual(payload["models_dir"], tmp)
            self.assertTrue(any(m["default"] for m in payload["models"]))

    def test_ensure_default_installs_the_default_model(self):
        archive = make_archive(Path(self.tmp.name) / "small.zip", DEFAULT_MODEL)
        server = ModelServer(archive.read_bytes())
        self.addCleanup(server.close)
        original = model_store.find(DEFAULT_MODEL)
        patched = ModelInfo(DEFAULT_MODEL, original.title, original.size_mb,
                            original.note, server.url)
        model_store.ARABIC_MODELS = tuple(
            patched if m.name == DEFAULT_MODEL else m for m in ARABIC_MODELS)
        self.addCleanup(lambda: setattr(model_store, "ARABIC_MODELS", ARABIC_MODELS))
        models = Path(self.tmp.name) / "models"
        target = model_store.ensure_default(models, progress=lambda *a: None)
        self.assertTrue(model_store.is_installed(DEFAULT_MODEL, models))
        self.assertTrue((target / "conf" / "model.conf").exists())

    def setUp(self):
        self.tmp = TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
