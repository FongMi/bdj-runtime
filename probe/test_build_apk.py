"""Validate ABI routing and public probe assets without building an APK."""

import pathlib
import tempfile
import unittest
import zipfile

import build_apk


class BuildProbeTest(unittest.TestCase):
    def stage(self, root, abi, wrong_iso=False):
        artifacts, jars = root / "artifacts", root / "bdj"
        artifacts.mkdir()
        jars.mkdir()

        def elf(name):
            _, elf_class, machine = build_apk.ABIS[name]
            data = bytearray(20)
            data[:6] = b"\x7fELF" + bytes((elf_class, 1))
            data[18:20] = machine.to_bytes(2, "little")
            return bytes(data)

        arch = build_apk.ABIS[abi][0]
        with zipfile.ZipFile(artifacts / f"j2re-zero-{abi}.zip", "w") as runtime:
            runtime.writestr(f"j2re-image/lib/{arch}/server/libjvm.so", elf(abi))
            for name in ("lib/rt.jar", "LICENSE", "THIRD_PARTY_README", "lib/fonts/test.ttf"):
                runtime.writestr("j2re-image/" + name, b"fixture")
        (artifacts / "libbdjzeroprobe.so").write_bytes(elf(abi))
        for name in build_apk.JARS:
            with zipfile.ZipFile(jars / name, "w") as jar:
                jar.writestr("META-INF/MANIFEST.MF", b"fixture")
        with zipfile.ZipFile(artifacts / "zero-smoke.jar", "w") as jar:
            jar.writestr("ZeroSmoke.class", b"fixture")
        aar = root / "iso.aar"
        with zipfile.ZipFile(aar, "w") as archive:
            archive.writestr(f"jni/{abi}/libisoJNI.so", elf("arm64-v8a" if wrong_iso else abi))
        return artifacts, aar, jars

    def test_each_abi_packages_only_matching_native_libraries_and_generic_runtime_asset(self):
        for abi in build_apk.ABIS:
            with self.subTest(abi=abi), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                artifacts, aar, jars = self.stage(root, abi)
                apk_path = root / "probe.apk"
                with zipfile.ZipFile(apk_path, "w") as apk:
                    build_apk.stage_assets(apk, artifacts, aar, jars, abi)
                with zipfile.ZipFile(apk_path) as apk:
                    self.assertEqual(apk.read("assets/abi.txt").decode().strip(), abi)
                    self.assertEqual(
                        {name for name in apk.namelist() if name.startswith("lib/")},
                        {f"lib/{abi}/libisoJNI.so", f"lib/{abi}/libbdjzeroprobe.so"},
                    )
                    self.assertEqual(apk.read("assets/j2re-zero.zip"),
                                     (artifacts / f"j2re-zero-{abi}.zip").read_bytes())
                    self.assertEqual(len(apk.read("assets/runtime.sha256").strip()), 64)

    def test_arm32_rejects_arm64_iso_library_before_packaging_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            artifacts, aar, jars = self.stage(root, "armeabi-v7a", wrong_iso=True)
            with zipfile.ZipFile(root / "probe.apk", "w") as apk:
                with self.assertRaisesRegex(ValueError, "libisoJNI.so does not match"):
                    build_apk.stage_assets(apk, artifacts, aar, jars, "armeabi-v7a")
                self.assertEqual(apk.namelist(), [])

    def test_manifest_application_id_is_distinct_and_native_activity_name_is_retained(self):
        text = pathlib.Path(build_apk.__file__).with_name("AndroidManifest.xml").read_text()
        self.assertIn('package="com.fongmi.android.bdjruntime"', text)
        self.assertIn('android:name="com.fongmi.android.bdjzero.ProbeActivity"', text)


if __name__ == "__main__":
    unittest.main()
