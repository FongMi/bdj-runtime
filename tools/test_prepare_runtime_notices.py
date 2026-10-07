"""Check binary preservation and complete notice inputs before packaging."""

import json
import pathlib
import tempfile
import unittest

from prepare_runtime_notices import (
    FREETYPE_NOTICES, IMAGE_NOTICES, PATCH_NOTICES, prepare_notices,
)


class PrepareRuntimeNoticesTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = pathlib.Path(self.directory.name)
        self.image = root / "j2re-image"
        self.repo = root / "repo"
        self.ffi = root / "libffi"
        self.freetype = root / "freetype"
        self.patches = root / "patches"
        self.manifest = {
            "release": {"repository": "FongMi/bdj-runtime", "tag": "sources-v1"},
            "sources": {"libffi": {"version": "3.4.8"}},
        }
        self.provenance = {
            "sources": self.manifest["sources"],
            "sourceRelease": self.manifest["release"],
            "recipeCommit": "1234567890" * 4,
        }
        for name in IMAGE_NOTICES:
            self.write(self.image / name, b"Original runtime notice\r\n")
        self.write(self.image / "provenance.json", json.dumps(self.provenance).encode())
        self.write(self.image / "lib/arm/server/libjvm.so", b"original native bytes")
        self.write(self.image / "lib/rt.jar", b"original class archive bytes")
        self.write(self.ffi / "LICENSE", b"libffi original license\r\n")
        for name in FREETYPE_NOTICES:
            self.write(self.freetype / name, (name + " original bytes\r\n").encode())
        for name in PATCH_NOTICES:
            self.write(self.patches / name, (name + " original bytes\n").encode())
        self.write(self.repo / "SOURCE-NOTICE.md", b"Original source notice\r\n")
        self.write(self.repo / "sources.json", json.dumps(self.manifest).encode())

    @staticmethod
    def write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def snapshot(self):
        return {path.relative_to(self.image): path.read_bytes()
                for path in self.image.rglob("*") if path.is_file()}

    def prepare(self):
        prepare_notices(self.image, self.repo, self.ffi, self.freetype, self.patches)

    def test_preserves_original_bytes_and_bundles_all_notices_and_source_links(self):
        before = self.snapshot()
        self.prepare()
        for name, data in before.items():
            self.assertEqual((self.image / name).read_bytes(), data)
        self.assertEqual((self.image / "third-party/libffi/LICENSE").read_bytes(),
                         (self.ffi / "LICENSE").read_bytes())
        for prefix, source, names in (
            ("third-party/freetype", self.freetype, FREETYPE_NOTICES),
            ("third-party/android-port", self.patches, PATCH_NOTICES),
            ("", self.repo, ("SOURCE-NOTICE.md", "sources.json")),
        ):
            for name in names:
                self.assertEqual((self.image / prefix / name).read_bytes(),
                                 (source / name).read_bytes())
        access = (self.image / "SOURCE-AVAILABILITY.txt").read_text()
        self.assertIn("https://github.com/FongMi/bdj-runtime/releases/tag/sources-v1", access)
        self.assertIn("/archive/" + self.provenance["recipeCommit"] + ".zip", access)
        after = self.snapshot()
        self.prepare()
        self.assertEqual(self.snapshot(), after)

    def test_each_missing_dependency_notice_prevents_any_image_changes(self):
        paths = [self.ffi / "LICENSE", self.repo / "SOURCE-NOTICE.md", self.repo / "sources.json"]
        paths += [self.freetype / name for name in FREETYPE_NOTICES]
        paths += [self.patches / name for name in PATCH_NOTICES]
        for path in paths:
            with self.subTest(path=path):
                original = path.read_bytes()
                before = self.snapshot()
                path.unlink()
                with self.assertRaises(FileNotFoundError):
                    self.prepare()
                self.assertEqual(self.snapshot(), before)
                self.write(path, original)

    def test_missing_original_image_license_is_rejected(self):
        (self.image / "LICENSE").unlink()
        before = self.snapshot()
        with self.assertRaises(FileNotFoundError):
            self.prepare()
        self.assertEqual(self.snapshot(), before)

    def test_different_runtime_source_manifest_is_rejected(self):
        self.manifest["sources"]["libffi"]["version"] = "different source"
        self.write(self.repo / "sources.json", json.dumps(self.manifest).encode())
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "manifest differ"):
            self.prepare()
        self.assertEqual(self.snapshot(), before)

    def test_abbreviated_recipe_commit_is_rejected(self):
        self.provenance["recipeCommit"] = "1234567"
        self.write(self.image / "provenance.json", json.dumps(self.provenance).encode())
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "complete recipe commit"):
            self.prepare()
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
