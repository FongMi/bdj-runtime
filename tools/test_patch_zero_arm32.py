#!/usr/bin/env python3
"""Test pinned Zero headers and optionally their ARMv7 compiler output."""

import argparse
import hashlib
import pathlib
import re
import subprocess
import tempfile
import unittest

import patch_zero_arm32 as patch


options = argparse.Namespace(source_root=None, cxx=None, cxx_arg=[], objdump=None)


def arm_blocks(atomic, order):
    atomic_start = atomic.index("#ifdef ARM\n")
    atomic_end = atomic.index("#endif // ARM\n", atomic_start) + len("#endif // ARM\n")
    order_start = order.index("#if defined(ARM)")
    order_end = order.index("#elif defined(PPC)", order_start)
    return atomic[atomic_start:atomic_end], order[order_start:order_end] + "#endif\n"


class PatchZeroArm32Test(unittest.TestCase):
    def setUp(self):
        if options.source_root is None:
            self.skipTest("Run this suite with --source-root pointing to the pinned OpenJDK checkout")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = pathlib.Path(self.directory.name)
        headers = self.root / patch.HEADER_ROOT
        headers.mkdir(parents=True)
        for name in patch.INPUT_HASHES:
            data = (options.source_root / patch.HEADER_ROOT / name).read_bytes()
            self.assertIn(
                hashlib.sha256(data).hexdigest(),
                (patch.INPUT_HASHES[name], patch.OUTPUT_HASHES[name]),
                f"Regression input is not the pinned or patched {name}",
            )
            (headers / name).write_bytes(data)

    def read(self, name):
        return (self.root / patch.HEADER_ROOT / name).read_text(encoding="utf-8")

    def test_patches_pinned_headers_and_preserves_other_architectures_and_api(self):
        before = {name: self.read(name) for name in patch.INPUT_HASHES}
        patch.patch_source(self.root)
        for name in patch.INPUT_HASHES:
            text = self.read(name)
            if name == patch.ATOMIC_HEADER:
                start, end = "#ifdef ARM\n", "#endif // ARM\n"
                self.assertEqual(text.split(end, 1)[1], before[name].split(end, 1)[1])
            else:
                start, end = "#if defined(ARM)", "#elif defined(PPC)"
                self.assertEqual(text.split(end, 1)[1], before[name].split(end, 1)[1])
            self.assertEqual(text.split(start, 1)[0], before[name].split(start, 1)[0])
            self.assertNotRegex(text, r"__kernel_(?:cmpxchg|dmb)|0xffff0f(?:c0|a0)")
            self.assertEqual(
                hashlib.sha256((self.root / patch.HEADER_ROOT / name).read_bytes()).hexdigest(),
                patch.OUTPUT_HASHES[name],
            )

    def test_repeated_application_preserves_exact_bytes(self):
        patch.patch_source(self.root)
        before = {
            name: (self.root / patch.HEADER_ROOT / name).read_bytes() for name in patch.INPUT_HASHES
        }
        patch.patch_source(self.root)
        for name, data in before.items():
            self.assertEqual((self.root / patch.HEADER_ROOT / name).read_bytes(), data)

    def test_unknown_second_header_leaves_both_inputs_untouched(self):
        order = self.root / patch.HEADER_ROOT / patch.ORDER_HEADER
        order.write_bytes(order.read_bytes() + b"\n// Changed upstream\n")
        before = {
            name: (self.root / patch.HEADER_ROOT / name).read_bytes() for name in patch.INPUT_HASHES
        }
        with self.assertRaisesRegex(ValueError, "Unexpected orderAccess"):
            patch.patch_source(self.root)
        for name, data in before.items():
            self.assertEqual((self.root / patch.HEADER_ROOT / name).read_bytes(), data)

    def test_armv7_output_uses_exclusive_instructions_and_full_barriers(self):
        if options.cxx is None:
            self.skipTest("Pass --cxx and --objdump for ARMv7 machine-code verification")
        patch.patch_source(self.root)
        atomic, order = arm_blocks(self.read(patch.ATOMIC_HEADER), self.read(patch.ORDER_HEADER))
        probe = "#define ARM 1\n" + atomic + order + """
extern "C" int bdj_cas(volatile int *p, int oldval, int newval) {
  return arm_compare_and_swap(p, oldval, newval);
}
extern "C" int bdj_add(volatile int *p, int value) {
  return arm_add_and_fetch(p, value);
}
extern "C" int bdj_exchange(volatile int *p, int value) {
  return arm_lock_test_and_set(p, value);
}
extern "C" long long bdj_cas64(volatile long long *p, long long oldval, long long newval) {
  return __sync_val_compare_and_swap(p, oldval, newval);
}
extern "C" void bdj_acquire() { READ_MEM_BARRIER; }
extern "C" void bdj_release() { WRITE_MEM_BARRIER; }
extern "C" void bdj_fence() { FULL_MEM_BARRIER; }
"""
        source = self.root / "armv7-atomics.cpp"
        source.write_text(probe, encoding="utf-8")
        object_file = self.root / "armv7-atomics.o"
        assembly_file = self.root / "armv7-atomics.s"
        command = [
            options.cxx, *options.cxx_arg, "-march=armv7-a", "-mfloat-abi=softfp",
            "-std=gnu++98", "-O2", "-fPIC", "-ffreestanding", "-Wall", "-Wextra", "-Werror",
        ]
        subprocess.run([*command, "-c", str(source), "-o", str(object_file)], check=True)
        subprocess.run([*command, "-S", str(source), "-o", str(assembly_file)], check=True)
        disassembly = subprocess.check_output([options.objdump, "-dr", str(object_file)], text=True)
        self.assertRegex(disassembly.lower(), r"(?:elf32|file format).*arm")
        self.assertNotRegex(disassembly, r"__kernel_|__sync_|__atomic_|ffff0f(?:c0|a0)")
        assembly = assembly_file.read_text(encoding="utf-8")
        for name in ("bdj_cas", "bdj_add", "bdj_exchange", "bdj_cas64"):
            body = re.search(rf"^{name}:.*?(?=^\s*\.size\s+{name})", assembly, re.M | re.S)
            self.assertIsNotNone(body, name)
            text = body.group(0)
            load, store = ("ldrexd", "strexd") if name == "bdj_cas64" else ("ldrex", "strex")
            self.assertRegex(text, rf"\b{load}\b")
            self.assertRegex(text, rf"\b{store}\b")
            self.assertRegex(text, rf"(?s)\bdmb\s+ish\b.*?\b{load}\b")
            self.assertRegex(text, rf"(?s)\b{store}\b.*?\bdmb\s+ish\b")
        for name in ("bdj_acquire", "bdj_release", "bdj_fence"):
            body = re.search(rf"^{name}:.*?(?=^\s*\.size\s+{name})", assembly, re.M | re.S)
            self.assertIsNotNone(body, name)
            self.assertRegex(body.group(0), r"\bdmb\s+ish\b")
        source.write_text(
            "#undef __ARM_ARCH\n#define __ARM_ARCH 6\n" + probe, encoding="utf-8"
        )
        rejected = subprocess.run(
            [*command, "-c", str(source), "-o", str(object_file)], text=True, capture_output=True
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("Android Zero requires ARMv7 or newer", rejected.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=pathlib.Path)
    parser.add_argument("--cxx")
    parser.add_argument("--cxx-arg", action="append", default=[])
    parser.add_argument("--objdump")
    options, unittest_args = parser.parse_known_args()
    if bool(options.cxx) != bool(options.objdump):
        parser.error("--cxx and --objdump must be supplied together")
    unittest.main(argv=[__file__, *unittest_args])
