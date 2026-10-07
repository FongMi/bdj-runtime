"""Verify Android AWT link prerequisites with GNU make's actual dependency graph."""

import argparse
import pathlib
import shutil
import subprocess
import tempfile
import unittest

import prepare_bdj_awt as prepare


options = argparse.Namespace(make=None)
BUILD_RULES = """    LIBAWT_XAWT_FILES := list.c
LDFLAGS_SUFFIX_linux := -lawt -lawt_headless -lm -lsupc++ -ljava -ljvm -lc
$(BUILD_LIBAWT_HEADLESS): $(BUILD_LIBAWT)
$(BUILD_LIBFONTMANAGER): $(BUILD_LIBAWT)
ifneq (, $(findstring $(OPENJDK_TARGET_OS), solaris aix))
  $(BUILD_LIBFONTMANAGER): $(BUILD_LIBAWT_HEADLESS)
endif
"""


def make_graph(make, rules, platform, bits):
    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        source = root / "Makefile"
        source.write_text(
            "BUILD_LIBAWT := libawt.so\n"
            "BUILD_LIBAWT_HEADLESS := libawt_headless.so\n"
            "BUILD_LIBFONTMANAGER := libfontmanager.so\n"
            f"OPENJDK_TARGET_OS := {platform}\nOPENJDK_TARGET_CPU_BITS := {bits}\n"
            + rules
            + ".PHONY: libawt.so libawt_headless.so libfontmanager.so\n"
            "libawt.so libawt_headless.so libfontmanager.so:\n\t@echo $@ $^\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [make, "--no-print-directory", "--dry-run", "-f", str(source), "libfontmanager.so"],
            check=True, capture_output=True, text=True, timeout=5,
        )
        return [line.split()[1:] for line in result.stdout.splitlines() if line.startswith("echo ")]


class PrepareBdjAwtTest(unittest.TestCase):
    def graph(self, platform, bits=32):
        make = options.make or shutil.which("make")
        if not make:
            self.skipTest("Pass --make or put GNU make on PATH for the AWT dependency regression")
        return make_graph(make, prepare.prepare_build_rules(BUILD_RULES), platform, bits)

    def test_android_fontmanager_waits_for_headless_link_input_for_both_abis(self):
        for bits in (32, 64):
            with self.subTest(bits=bits):
                self.assertEqual(self.graph("linux", bits), [
                    ["libawt.so"], ["libawt_headless.so", "libawt.so"],
                    ["libfontmanager.so", "libawt.so", "libawt_headless.so"],
                ])

    def test_solaris_and_aix_keep_normal_headless_prerequisite(self):
        for platform in ("solaris", "aix"):
            with self.subTest(platform=platform):
                self.assertEqual(self.graph(platform), [
                    ["libawt.so"], ["libawt_headless.so", "libawt.so"],
                    ["libfontmanager.so", "libawt.so", "libawt_headless.so"],
                ])

    def test_windows_and_macos_keep_only_existing_awt_prerequisite(self):
        for platform in ("windows", "macosx"):
            with self.subTest(platform=platform):
                self.assertEqual(self.graph(platform), [
                    ["libawt.so"], ["libfontmanager.so", "libawt.so"],
                ])

    def test_unknown_or_duplicate_awt_source_marker_is_rejected(self):
        for text in (BUILD_RULES.replace("list.c", "unknown.c"),
                     BUILD_RULES + "    LIBAWT_XAWT_FILES := list.c\n"):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, "AWT source list changed"):
                    prepare.prepare_build_rules(text)

    def test_unknown_or_duplicate_dependency_block_is_rejected(self):
        block = BUILD_RULES[BUILD_RULES.index("ifneq") :]
        for text in (BUILD_RULES.replace("solaris aix", "solaris aix unknown"), BUILD_RULES + block):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, "AWT dependency block changed"):
                    prepare.prepare_build_rules(text)

    def test_link_flags_and_other_rules_are_preserved(self):
        result = prepare.prepare_build_rules(BUILD_RULES)
        original = BUILD_RULES.splitlines()
        self.assertEqual(result.splitlines()[1:4], original[1:4])
        self.assertEqual(result.splitlines()[5:], original[5:])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--make")
    options, unittest_args = parser.parse_known_args()
    unittest.main(argv=[__file__, *unittest_args])
