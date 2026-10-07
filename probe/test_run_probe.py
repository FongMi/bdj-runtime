"""Device-free regression for current-process assertions and fail-closed capture."""

import contextlib
import io
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from unittest import mock

import run_probe


HASH = "a" * 64


def png(value=1, height=1, compressed=None):
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))
    pixels = zlib.compress(bytes((0, value, 0, 0, 255))) if compressed is None else compressed
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", pixels) + chunk(b"IEND", b""))


class RunProbeTest(unittest.TestCase):
    def run_probe(self, output, abi="armeabi-v7a", bdj=True, fault=None):
        def adb(command, **kwargs):
            args = command[5:]
            code, text = 0, ""
            if args == ["get-state"]:
                text = "offline\n" if fault == "offline" else "device\n"
            elif args[:2] == ["shell", "getprop"]:
                text = "armeabi-v7a,arm64-v8a\n" if args[-1].endswith("abilist") else "identity\n"
            elif args == ["shell", "pidof", run_probe.PACKAGE]:
                text = "1234\n"
            elif args[-1] == "files/result.txt" and "cat" in args:
                text = ("PASS native BD-J menu pixels, down/right/select, close/reopen; "
                        "menuFrames=8; changedFrames=6; visiblePixelsMin=100" if bdj else
                        "PASS tag=0; OpenJDK Zero VM; logical font styles 20; "
                        "JNI callback, class loading, GC, Java2D, fonts, PNG PASS")
                actual_abi = "arm64-v8a" if fault == "wrong_abi" else abi
                text += f"; processAbi={actual_abi}; runtimeSha256={HASH}; elapsedMs=100"
            elif args[0] == "exec-out":
                code = int(fault == "missing_frame" and args[-1].endswith("cycle1-key5.png"))
                value = 1
                if "bdj-frames" in args[-1] and fault != "same_frame":
                    value = 1 + run_probe.STEPS.index(args[-1].rsplit("-", 1)[-1][:-4])
                image = png(value)
                if fault == "bad_png":
                    image = image[:12]
                return subprocess.CompletedProcess(command, code, b"" if code else image, b"")
            elif args[-1].endswith("native-stderr.txt") and "cat" in args:
                code = int(fault == "missing_diagnostic")
                text = "Current diagnostics\n"
            elif args[-1].endswith("libbluray-debug.txt") and "cat" in args:
                text = "Current BD-J diagnostics\n"
            elif args[-1].endswith("/maps"):
                arch = "aarch64" if abi == "arm64-v8a" else "arm"
                text = f"files/candidate/j2re-image/lib/{arch}/server/libjvm.so\n"
                if fault == "wrong_maps":
                    text = "wrong-runtime/libjvm.so\n"
            elif args[0] == "logcat":
                code = int(fault == "logcat")
                text = ("10-05 12:00:00.000  1111  1112 I BdjZero : OLD PASS\n"
                        "10-05 12:01:00.000  1234  1235 I BdjZero : CURRENT PASS\n")
                if fault == "old_logs":
                    text = "10-05 12:00:00.000  1111  1112 I BdjZero : OLD PASS\n"
            return subprocess.CompletedProcess(command, code, text, "")

        arguments = ["run_probe.py", "--adb", "adb", "--serial", "explicit-device", "--abi", abi,
                     "--output", str(output), "--runtime-sha256", HASH]
        if bdj:
            arguments += ["--bdj", "--fixture", "/sdcard/explicit-fixture.iso"]
        with mock.patch.object(sys, "argv", arguments), mock.patch.object(
            run_probe.subprocess, "run", side_effect=adb
        ), mock.patch.object(run_probe.time, "sleep"), contextlib.redirect_stdout(io.StringIO()):
            run_probe.main()

    def test_each_abi_baseline_and_bdj_reports_pass_with_current_evidence(self):
        for abi in run_probe.ABIS:
            for bdj in (False, True):
                with self.subTest(abi=abi, bdj=bdj), tempfile.TemporaryDirectory() as temporary:
                    output = pathlib.Path(temporary) / "run"
                    self.run_probe(output, abi=abi, bdj=bdj)
                    self.assertTrue((output / "result.txt").read_text().startswith("PASS "))
                    self.assertTrue((output / "screen.png").is_file())
                    if bdj:
                        self.assertEqual(len(list((output / "frames").glob("*.png"))), 8)
                    current = (output / "logcat-current-process.txt").read_text()
                    self.assertIn("CURRENT PASS", current)
                    self.assertNotIn("OLD PASS", current)

    def test_missing_corrupt_unchanged_or_uncaptured_evidence_fails_after_native_pass(self):
        for fault in ("missing_frame", "missing_diagnostic", "bad_png", "same_frame", "logcat",
                      "wrong_abi", "offline", "wrong_maps", "old_logs"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                output = pathlib.Path(temporary) / "run"
                with self.assertRaises(SystemExit) as failure:
                    self.run_probe(output, fault=fault)
                self.assertEqual(failure.exception.code, 1)
                self.assertTrue((output / "result.txt").read_text().startswith("FAIL "))
                self.assertTrue((output / "commands.json").is_file())

    def test_png_validator_rejects_header_only_truncation_and_bad_crc(self):
        self.assertEqual(run_probe.validate_png(png()), (1, 1))
        for data in (b"\x89PNG\r\n\x1a\n", png()[:-2], png()[:-1] + b"x",
                     png(height=2), png(compressed=b"invalid-deflate")):
            with self.assertRaises(ValueError):
                run_probe.validate_png(data)

    def test_baseline_rejects_missing_font_assertion_and_runtime_mismatch(self):
        valid = ("PASS OpenJDK Zero VM; logical font styles 20; "
                 "JNI callback, class loading, GC, Java2D, fonts, PNG PASS; "
                 f"processAbi=armeabi-v7a; runtimeSha256={HASH}; elapsedMs=1")
        for result, digest in ((valid.replace("fonts, ", ""), HASH), (valid, "b" * 64)):
            with self.assertRaises(ValueError):
                run_probe.validate_result(result, "armeabi-v7a", False, digest)

    def test_baseline_rejects_missing_or_incomplete_logical_font_style_matrix(self):
        valid = ("PASS OpenJDK Zero VM; logical font styles 20; "
                 "JNI callback, class loading, GC, Java2D, fonts, PNG PASS; "
                 f"processAbi=armeabi-v7a; runtimeSha256={HASH}; elapsedMs=1")
        run_probe.validate_result(valid, "armeabi-v7a", False, HASH)
        results = [valid.replace("; logical font styles 20", "")]
        results += [valid.replace("logical font styles 20", f"logical font styles {count}")
                    for count in (0, 19, 21, 200)]
        for result in results:
            with self.subTest(result=result), self.assertRaisesRegex(ValueError, "style matrix"):
                run_probe.validate_result(result, "armeabi-v7a", False, HASH)


if __name__ == "__main__":
    unittest.main()
