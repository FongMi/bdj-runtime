"""Regressions for preserved source integrity and offline cache reuse."""

import hashlib
import pathlib
import tempfile
import unittest
from unittest import mock

from fetch_sources import fetch


class FetchSourcesTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache = pathlib.Path(self.directory.name)
        self.payload = b"preserved source payload"
        self.manifest = {
            "release": {"repository": "FongMi/bdj-runtime", "tag": "sources-v1"},
            "sources": {"jdk": {"asset": "source.zip", "size": len(self.payload),
                                "sha256": hashlib.sha256(self.payload).hexdigest()}},
        }

    def test_valid_cache_does_not_access_network(self):
        (self.cache / "source.zip").write_bytes(self.payload)
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")):
            fetch(self.manifest, self.cache)

    def test_corrupt_cache_rejects_without_network(self):
        (self.cache / "source.zip").write_bytes(b"x" * len(self.payload))
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")):
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                fetch(self.manifest, self.cache)

    def test_wrong_size_rejects_without_network(self):
        (self.cache / "source.zip").write_bytes(b"truncated")
        with self.assertRaisesRegex(ValueError, "size mismatch"):
            fetch(self.manifest, self.cache)

    def test_missing_offline_source_is_reported(self):
        with self.assertRaises(FileNotFoundError):
            fetch(self.manifest, self.cache, verify_only=True)

    def test_download_verification_failure_removes_partial_archive(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.side_effect = [b"corrupt", b""]
        with mock.patch("urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(ValueError, "size mismatch"):
                fetch(self.manifest, self.cache)
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_asset_path_cannot_leave_cache(self):
        self.manifest["sources"]["jdk"]["asset"] = "../source.zip"
        with self.assertRaisesRegex(ValueError, "asset name"):
            fetch(self.manifest, self.cache)


if __name__ == "__main__":
    unittest.main()
