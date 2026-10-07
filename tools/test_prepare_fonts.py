"""Regression checks for DejaVu selection, style identity, and provenance."""

import hashlib
import io
import json
import pathlib
import struct
import tarfile
import tempfile
import unittest
import unittest.mock
import zipfile

import prepare_fonts


def true_type_font(face):
    name = face.encode("utf-16-be")
    name_table = struct.pack(">HHH", 0, 1, 18)
    name_table += struct.pack(">HHHHHH", 3, 1, 0x409, 4, len(name), 0) + name
    return (
        b"\x00\x01\x00\x00" + struct.pack(">HHHH", 1, 0, 0, 0)
        + struct.pack(">4sIII", b"name", 0, 28, len(name_table)) + name_table
    )


class PrepareFontsTest(unittest.TestCase):
    def source_archive(self, root, wrong_face=None, missing_style=None):
        source = root / "fonts.tar.bz2"
        with tarfile.open(source, "w:bz2") as archive:
            files = {"LICENSE": b"Original font license bytes\n"}
            for filename, face, _ in prepare_fonts.font_faces().values():
                if filename != missing_style:
                    files["ttf/" + filename] = true_type_font(
                        "Wrong face" if filename == wrong_face else face
                    )
            for name, data in files.items():
                entry = tarfile.TarInfo(prepare_fonts.SOURCE_ROOT + "/" + name)
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
        return source

    def test_preserves_faces_styles_license_and_checksums_reproducibly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = self.source_archive(root)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            first, second = root / "first.zip", root / "second.zip"
            with unittest.mock.patch.object(prepare_fonts, "SOURCE_SHA256", digest):
                prepare_fonts.prepare_fonts(source, first)
                prepare_fonts.prepare_fonts(source, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as package:
                self.assertIsNone(package.testzip())
                self.assertEqual(
                    package.read("jre_override/lib/fonts/DEJAVU-LICENSE.txt"),
                    b"Original font license bytes\n",
                )
                fonts = [name for name in package.namelist() if name.endswith(".ttf")]
                self.assertEqual(len(fonts), 12)
                self.assertFalse(any("Lucida" in name for name in package.namelist()))
                config = package.read("jre_override/lib/fontconfig.properties").decode()
                self.assertEqual(
                    config.encode(), package.read("jre_override/lib/fontconfig.Linux.properties")
                )
                for logical, family in prepare_fonts.LOGICAL_FAMILIES.items():
                    for style in prepare_fonts.STYLES:
                        filename, face, xlfd = prepare_fonts.font_faces()[(family, style)]
                        self.assertIn(f"{logical}.{style}.default={xlfd}\n", config)
                        self.assertIn(
                            "filename." + xlfd.replace(" ", "\\ ")
                            + "=$JRE_LIB_FONTS/" + filename + "\n", config
                        )
                        font_bytes = package.read("jre_override/lib/fonts/" + filename)
                        self.assertEqual(prepare_fonts.font_full_names(font_bytes), {face})
                metadata = json.loads(package.read("jre_override/lib/fonts/FONT-SOURCES.json"))
                self.assertEqual(metadata["sourceArchiveSha256"], digest)
                self.assertEqual(set(metadata["fonts"]), {pathlib.PurePosixPath(f).name for f in fonts})
                for line in package.read("jre_override/FONT-SHA256SUMS").decode().splitlines():
                    expected, name = line.split("  ", 1)
                    self.assertEqual(
                        hashlib.sha256(package.read("jre_override/" + name)).hexdigest(), expected
                    )

    def test_unpinned_archive_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = self.source_archive(root)
            output = root / "fonts.zip"
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                prepare_fonts.prepare_fonts(source, output)
            self.assertFalse(output.exists())

    def test_incorrect_style_face_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = self.source_archive(root, wrong_face="DejaVuSans-BoldOblique.ttf")
            output = root / "fonts.zip"
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            with unittest.mock.patch.object(prepare_fonts, "SOURCE_SHA256", digest):
                with self.assertRaisesRegex(ValueError, "Font face mismatch"):
                    prepare_fonts.prepare_fonts(source, output)
            self.assertFalse(output.exists())

    def test_missing_style_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = self.source_archive(root, missing_style="DejaVuSerif-Italic.ttf")
            output = root / "fonts.zip"
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            with unittest.mock.patch.object(prepare_fonts, "SOURCE_SHA256", digest):
                with self.assertRaises(KeyError):
                    prepare_fonts.prepare_fonts(source, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
