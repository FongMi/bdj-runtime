#!/usr/bin/env python3
"""Replace JDK 8u482 Zero's ARM kernel helpers with ARMv7 atomics."""

import argparse
import hashlib
import pathlib


JDK_REVISION = "cea3cd4c1d7aa70e998d45ca2e419793a550321e"
HEADER_ROOT = pathlib.Path("hotspot/src/os_cpu/linux_zero/vm")
ATOMIC_HEADER = "atomic_linux_zero.inline.hpp"
ORDER_HEADER = "orderAccess_linux_zero.inline.hpp"
INPUT_HASHES = {
    ATOMIC_HEADER: "01ca4fe3ab0acbcfc283b20fc76fd8d675252025a4b3ecbcc19fa27052227e02",
    ORDER_HEADER: "d382167929f4afe8d14bbf472f2a8087c27cfb82c625c8e276c806cf197b777c",
}
OUTPUT_HASHES = {
    ATOMIC_HEADER: "e4f37c284e4685890a4b9618eaed4f251f8412a606977bddc297d4bdfbd86523",
    ORDER_HEADER: "1e8ef271e6f614a0c9beedb34745eb8a2467ab494a824d86c280a01dba45c8a3",
}

ATOMIC_ARM = """#ifdef ARM

#if !defined(__ARM_ARCH) || __ARM_ARCH < 7
#error Android Zero requires ARMv7 or newer
#endif

// ARMv7 provides native exclusive accesses. Do not call Linux kuser helpers:
// Android kernels may omit their fixed-address user page.
static inline int arm_compare_and_swap(volatile int *ptr,
                                       int oldval,
                                       int newval) {
  return __sync_val_compare_and_swap(ptr, oldval, newval);
}

static inline int arm_add_and_fetch(volatile int *ptr, int add_value) {
  return __sync_add_and_fetch(ptr, add_value);
}

static inline int arm_lock_test_and_set(volatile int *ptr, int newval) {
  // Atomic::xchg requires a full barrier; __sync_lock_test_and_set is acquire-only.
  return __atomic_exchange_n(ptr, newval, __ATOMIC_SEQ_CST);
}
#endif // ARM
"""

ORDER_ARM = """#if defined(ARM)   // ----------------------------------------------------

#if !defined(__ARM_ARCH) || __ARM_ARCH < 7
#error Android Zero requires ARMv7 or newer
#endif

// With -march=armv7-a GCC emits a DMB and a compiler memory barrier.
#define READ_MEM_BARRIER  __sync_synchronize()
#define WRITE_MEM_BARRIER __sync_synchronize()
#define FULL_MEM_BARRIER  __sync_synchronize()

"""


def replace_arm_block(name, data):
    text = data.decode("utf-8")
    if name == ATOMIC_HEADER:
        start = text.index("#ifdef ARM\n")
        end = text.index("#endif // ARM\n", start) + len("#endif // ARM\n")
        replacement = ATOMIC_ARM
    else:
        start = text.index("#if defined(ARM)")
        end = text.index("#elif defined(PPC)", start)
        replacement = ORDER_ARM
    return (text[:start] + replacement + text[end:]).encode("utf-8")


def patch_source(source_root):
    """Validate both pinned inputs before changing either source header."""
    changes = []
    for name, expected_hash in INPUT_HASHES.items():
        path = source_root / HEADER_ROOT / name
        data = path.read_bytes()
        actual_hash = hashlib.sha256(data).hexdigest()
        if actual_hash == OUTPUT_HASHES.get(name):
            continue
        if actual_hash != expected_hash:
            raise ValueError(f"Unexpected {name}; requires OpenJDK {JDK_REVISION}")
        patched = replace_arm_block(name, data)
        if hashlib.sha256(patched).hexdigest() != OUTPUT_HASHES[name]:
            raise ValueError(f"Unexpected patched {name}")
        changes.append((path, patched))
    for path, data in changes:
        path.write_bytes(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=pathlib.Path)
    args = parser.parse_args()
    patch_source(args.source_root)
    print(f"ARMv7 Zero atomics verified for OpenJDK {JDK_REVISION}")


if __name__ == "__main__":
    main()
