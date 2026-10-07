"""Verify target ELF files, Android dependencies, and upstream AWT JNI exports."""

import argparse
import hashlib
import json
import pathlib
import re
import struct
import subprocess


TARGETS = {"armeabi-v7a": (1, 40, "arm"), "arm64-v8a": (2, 183, "aarch64")}
ANDROID_LIBRARIES = {"libc.so", "libm.so", "libdl.so", "liblog.so", "libz.so", "libstdc++.so"}


def inspect_elf(data, abi):
    elf_class, machine, _ = TARGETS[abi]
    if data[:4] != b"\x7fELF" or data[4:6] != bytes((elf_class, 1)):
        raise ValueError("Expected little-endian target ELF: " + abi)
    header_format = "<HHIIIIIHHHHHH" if elf_class == 1 else "<HHIQQQIHHHHHH"
    header = struct.unpack_from(header_format, data, 16)
    if header[0] != 3 or header[1] != machine:
        raise ValueError("Expected target shared library: " + abi)
    flags = header[6]
    if elf_class == 1 and (flags & 0xFF000000 != 0x05000000 or flags & 0x400):
        raise ValueError("Expected ARM EABI 5 with Android soft-float calling convention")
    program_offset, entry_size, count = header[4], header[8], header[9]
    program_format = "<IIIIIIII" if elf_class == 1 else "<IIQQQQQQ"
    if entry_size != struct.calcsize(program_format):
        raise ValueError("Unexpected ELF program header size")
    alignments = []
    for index in range(count):
        program = struct.unpack_from(program_format, data, program_offset + index * entry_size)
        if program[0] != 1:
            continue
        offset, address = (program[1], program[2]) if elf_class == 1 else (program[2], program[3])
        alignment = program[7]
        if alignment < 16384 or offset % 16384 != address % 16384:
            raise ValueError("ELF load segment is not aligned for 16 KiB pages")
        alignments.append(alignment)
    if not alignments:
        raise ValueError("ELF library has no load segments")
    return {"class": elf_class * 32, "machine": machine, "flags": flags, "loadAlignments": alignments}


def verify(image, abi, awt_source, probe=None):
    _, _, cpu = TARGETS[abi]
    libraries = sorted(image.rglob("*.so"))
    if not libraries:
        raise ValueError("Runtime has no native libraries")
    jvm = image / "lib" / cpu / "server/libjvm.so"
    awt = image / "lib" / cpu / "libawt_xawt.so"
    for required in (jvm, awt, image / "lib/rt.jar", image / "lib" / cpu / "libfontmanager.so"):
        if not required.is_file():
            raise ValueError("Missing runtime component: " + str(required))
    bundled = {path.name for path in libraries}
    records = {}
    for path in libraries + ([probe] if probe is not None else []):
        data = path.read_bytes()
        record = inspect_elf(data, abi)
        dynamic = subprocess.check_output(["readelf", "-d", str(path)], text=True)
        needed = sorted(set(re.findall(r"\(NEEDED\).*?\[(.*?)\]", dynamic)))
        missing = set(needed) - bundled - ANDROID_LIBRARIES
        if missing:
            raise ValueError("Missing Android dependencies for %s: %s" % (path.name, sorted(missing)))
        if "(RPATH)" in dynamic:
            raise ValueError("Unsupported Android RPATH: " + path.name)
        if path == jvm and "libffi.so" in needed:
            raise ValueError("Zero must link target libffi statically")
        record.update({"sha256": hashlib.sha256(data).hexdigest(), "needed": needed})
        name = str(path.relative_to(image)).replace("\\", "/") if path != probe else "probe/" + path.name
        records[name] = record
    symbols = re.findall(r"JNIEXPORT\s+void\s+JNICALL\s+(Java_\w+)\s*\(", awt_source.read_text())
    if len(symbols) != 26 or len(set(symbols)) != 26:
        raise ValueError("Unexpected upstream AWT JNI entry count")
    exports = subprocess.check_output(["nm", "-D", str(awt)], text=True)
    for symbol in symbols:
        if not re.search(r"\bT\s+" + re.escape(symbol) + r"(?:@|\s|$)", exports):
            raise ValueError("Missing upstream AWT JNI export: " + symbol)
    return {"abi": abi, "libraries": records, "verifiedAwtExports": symbols}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=pathlib.Path, required=True)
    parser.add_argument("--abi", choices=TARGETS, required=True)
    parser.add_argument("--awt-source", type=pathlib.Path, required=True)
    parser.add_argument("--probe", type=pathlib.Path)
    parser.add_argument("--report", type=pathlib.Path, required=True)
    args = parser.parse_args()
    report = verify(args.image, args.abi, args.awt_source, args.probe)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print("Verified %d target libraries and 26 upstream AWT JNI exports" % len(report["libraries"]))


if __name__ == "__main__":
    main()
