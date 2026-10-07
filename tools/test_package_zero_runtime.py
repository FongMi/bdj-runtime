"""Host regression for the runtime/debug-symbol archive boundary."""

import pathlib
import tempfile
import unittest
import zipfile

from package_zero_runtime import package_runtime


class PackageZeroRuntimeTest(unittest.TestCase):
    def test_separates_symbols_and_preserves_runtime_bytes_and_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / "source.zip"
            runtime = root / "runtime.zip"
            symbols = root / "symbols.zip"
            entries = {
                "j2re-image/bin/java": (b"executable", 0o100755),
                "j2re-image/lib/aarch64/server/libjvm.so": (b"JVM", 0o100755),
                "j2re-image/lib/rt.jar": (b"classes", 0o100644),
                "j2re-image/LICENSE": (b"license", 0o100644),
                "j2re-image/lib/fonts/font with spaces.ttf": (b"font", 0o100644),
                "j2re-image/lib/aarch64/server/libjvm.diz": (b"debug symbols", 0o100644),
                "j2re-image/bin/java.diz": (b"launcher symbols", 0o100644),
            }
            with zipfile.ZipFile(source, "w") as image:
                for name, (data, mode) in entries.items():
                    entry = zipfile.ZipInfo(name, date_time=(2026, 10, 5, 12, 0, 0))
                    entry.create_system = 3
                    entry.external_attr = mode << 16
                    image.writestr(entry, data, compress_type=zipfile.ZIP_DEFLATED)

            package_runtime(source, runtime, symbols)

            with (
                zipfile.ZipFile(source) as image,
                zipfile.ZipFile(runtime) as runtime_zip,
                zipfile.ZipFile(symbols) as symbols_zip,
            ):
                self.assertIsNone(runtime_zip.testzip())
                self.assertIsNone(symbols_zip.testzip())
                self.assertEqual(
                    set(runtime_zip.namelist()),
                    {name for name in entries if not name.endswith(".diz")},
                )
                self.assertEqual(
                    set(symbols_zip.namelist()),
                    {name for name in entries if name.endswith(".diz")},
                )
                for output in (runtime_zip, symbols_zip):
                    for entry in output.infolist():
                        original = image.getinfo(entry.filename)
                        self.assertEqual(output.read(entry), image.read(original))
                        self.assertEqual(entry.create_system, original.create_system)
                        self.assertEqual(entry.external_attr, original.external_attr)
                        self.assertEqual(entry.date_time, original.date_time)


if __name__ == "__main__":
    unittest.main()
