import struct
import unittest

from verify_runtime import inspect_elf


def elf(elf_class, machine, alignment=16384, flags=0, address=0):
    header_format = "<HHIIIIIHHHHHH" if elf_class == 1 else "<HHIQQQIHHHHHH"
    program_format = "<IIIIIIII" if elf_class == 1 else "<IIQQQQQQ"
    header_size = 16 + struct.calcsize(header_format)
    program_size = struct.calcsize(program_format)
    header = struct.pack(header_format, 3, machine, 1, 0, header_size, 0, flags,
                         header_size, program_size, 1, 0, 0, 0)
    program = (1, 0, address, address, 0, 0, 5, alignment) if elf_class == 1 else (
        1, 5, 0, address, address, 0, 0, alignment)
    return b"\x7fELF" + bytes((elf_class, 1, 1)) + bytes(9) + header + struct.pack(program_format, *program)


class ElfVerificationTest(unittest.TestCase):
    def test_arm_android_eabi5_is_accepted(self):
        self.assertEqual(32, inspect_elf(elf(1, 40, flags=0x05000200), "armeabi-v7a")["class"])

    def test_aarch64_is_accepted(self):
        self.assertEqual(64, inspect_elf(elf(2, 183), "arm64-v8a")["class"])

    def test_other_machine_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "shared library"):
            inspect_elf(elf(1, 3, flags=0x05000200), "armeabi-v7a")

    def test_arm_hard_float_calling_convention_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "soft-float"):
            inspect_elf(elf(1, 40, flags=0x05000400), "armeabi-v7a")

    def test_small_page_alignment_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "16 KiB"):
            inspect_elf(elf(2, 183, alignment=4096), "arm64-v8a")

    def test_incongruent_segment_address_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "16 KiB"):
            inspect_elf(elf(2, 183, address=4096), "arm64-v8a")


if __name__ == "__main__":
    unittest.main()
