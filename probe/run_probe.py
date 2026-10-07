"""Run an installed probe and collect evidence from its current process."""

import argparse
import hashlib
import json
import pathlib
import re
import struct
import subprocess
import time
import zlib


PACKAGE = "com.fongmi.android.bdjruntime"
ACTIVITY = "com.fongmi.android.bdjzero.ProbeActivity"
ABIS = ("armeabi-v7a", "arm64-v8a")
STEPS = ("initial", "key2", "key4", "key5")


def validate_png(data):
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Invalid PNG signature")
    offset, width, height = 8, 0, 0
    compressed = bytearray()
    row_bytes = 0
    while offset + 12 <= len(data):
        size = struct.unpack_from(">I", data, offset)[0]
        end = offset + 12 + size
        if end > len(data):
            raise ValueError("Truncated PNG chunk")
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + size]
        crc = struct.unpack_from(">I", data, offset + 8 + size)[0]
        if zlib.crc32(kind + payload) & 0xffffffff != crc:
            raise ValueError("PNG chunk checksum mismatch")
        if offset == 8:
            if kind != b"IHDR" or size != 13:
                raise ValueError("Missing PNG header")
            width, height = struct.unpack_from(">II", payload)
            if width == 0 or height == 0:
                raise ValueError("Empty PNG dimensions")
            depth, color, compression, filtering, interlace = payload[8:]
            channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color)
            if channels is None or depth not in (1, 2, 4, 8, 16) or any((compression, filtering, interlace)):
                raise ValueError("Unsupported PNG encoding")
            row_bytes = (width * channels * depth + 7) // 8
        if kind == b"IDAT" and payload:
            compressed.extend(payload)
        if kind == b"IEND":
            if size != 0 or end != len(data) or not compressed:
                raise ValueError("Incomplete PNG image")
            try:
                decoded = zlib.decompress(compressed)
            except zlib.error as error:
                raise ValueError("Invalid compressed PNG pixels") from error
            if len(decoded) != height * (row_bytes + 1):
                raise ValueError("PNG pixel payload does not match its dimensions")
            if any(decoded[row * (row_bytes + 1)] > 4 for row in range(height)):
                raise ValueError("Invalid PNG row filter")
            return width, height
        offset = end
    raise ValueError("Missing PNG end")


def validate_result(result, abi, bdj, runtime_hash):
    if not result or not result.startswith("PASS "):
        raise ValueError(result or "Probe produced no result")
    if f"processAbi={abi};" not in result:
        raise ValueError("Probe process ABI does not match requested ABI")
    found = re.search(r"runtimeSha256=([0-9a-f]{64})(?:;|$)", result)
    if found is None or (runtime_hash and found.group(1) != runtime_hash):
        raise ValueError("Probe runtime SHA-256 does not match the candidate")
    if bdj:
        if not result.startswith("PASS native BD-J menu pixels, down/right/select, close/reopen;"):
            raise ValueError("Unexpected BD-J result")
        if "menuFrames=8;" not in result or "changedFrames=6;" not in result:
            raise ValueError("BD-J frame transition metrics are incomplete")
        visible = re.search(r"visiblePixelsMin=(\d+);", result)
        if visible is None or int(visible.group(1)) == 0:
            raise ValueError("BD-J menu has no visible pixels")
    elif "Zero" not in result or "JNI callback, class loading, GC, Java2D, fonts, PNG PASS" not in result:
        raise ValueError("Zero VM, font, PNG or JNI baseline assertions are missing")
    elif "; logical font styles 20;" not in result:
        raise ValueError("Zero baseline logical font style matrix is incomplete")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", type=pathlib.Path, required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--port", default="5037")
    parser.add_argument("--abi", choices=ABIS, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--runtime-sha256")
    parser.add_argument("--bdj", action="store_true")
    parser.add_argument("--fixture")
    args = parser.parse_args()
    if args.bdj and not args.fixture:
        parser.error("--bdj requires an explicit device --fixture path")
    if args.runtime_sha256 and not re.fullmatch(r"[0-9a-f]{64}", args.runtime_sha256):
        parser.error("--runtime-sha256 must be a lowercase SHA-256 digest")
    args.output.mkdir(parents=True, exist_ok=False)
    prefix = [str(args.adb), "-P", args.port, "-s", args.serial]
    commands, pids, collection_errors = [], set(), []
    selected = False

    def adb(*command, check=True):
        full = prefix + list(command)
        result = subprocess.run(full, capture_output=True, encoding="utf-8", errors="replace", timeout=30)
        commands.append({"command": full, "returncode": result.returncode,
                         "stdout": result.stdout, "stderr": result.stderr})
        if check and result.returncode:
            raise RuntimeError(result.stderr or result.stdout or "ADB command failed")
        return result

    def collect_text(name, *command):
        try:
            captured = adb(*command)
            (args.output / name).write_text(captured.stdout, encoding="utf-8")
            return captured.stdout
        except Exception as error:
            collection_errors.append(f"Could not collect {name}: {error}")
            return ""

    def collect_png(name, *command):
        try:
            full = prefix + list(command)
            captured = subprocess.run(full, capture_output=True, timeout=30)
            commands.append({"command": full, "returncode": captured.returncode,
                             "bytes": len(captured.stdout)})
            if captured.returncode:
                raise RuntimeError("ADB binary capture failed")
            width, height = validate_png(captured.stdout)
            digest = hashlib.sha256(captured.stdout).hexdigest()
            (args.output / name).write_bytes(captured.stdout)
            commands[-1].update(sha256=digest, width=width, height=height)
            return digest
        except Exception as error:
            collection_errors.append(f"Could not collect {name}: {error}")
            return None

    result = None
    try:
        if adb("get-state").stdout.strip() != "device":
            raise RuntimeError("Selected device is not online")
        selected = True
        identity = {name: adb("shell", "getprop", name).stdout.strip() for name in (
            "ro.serialno", "ro.product.manufacturer", "ro.product.model",
            "ro.build.version.sdk", "ro.product.cpu.abilist")}
        if any(not value for value in identity.values()):
            raise RuntimeError("Device identity is incomplete")
        if args.abi not in identity["ro.product.cpu.abilist"].split(","):
            raise RuntimeError("Requested ABI is absent from the selected device")
        (args.output / "identity.json").write_text(json.dumps(identity, indent=2), encoding="utf-8")
        adb("shell", "am", "force-stop", PACKAGE)
        adb("shell", "run-as", PACKAGE, "rm", "-f", "files/result.txt")
        start = ["shell", "am", "start", "-W", "-n", PACKAGE + "/" + ACTIVITY]
        if args.bdj:
            start += ["--ez", "bdj", "true", "--es", "fixture", args.fixture]
        started = adb(*start)
        if "Error:" in started.stdout or "Exception" in started.stdout:
            raise RuntimeError("Probe Activity launch failed")
        deadline = time.monotonic() + (1500 if args.bdj else 180)
        while time.monotonic() < deadline:
            pid = adb("shell", "pidof", PACKAGE, check=False).stdout.strip()
            pids.update(value for value in pid.split() if value.isdigit())
            completed = adb("shell", "run-as", PACKAGE, "cat", "files/result.txt", check=False)
            if completed.returncode == 0 and completed.stdout.strip():
                result = completed.stdout.strip()
                break
            if not pid:
                raise RuntimeError("Probe process exited without a result")
            time.sleep(2)
        validate_result(result, args.abi, args.bdj, args.runtime_sha256)
        time.sleep(1)
        if not pids or not adb("shell", "pidof", PACKAGE).stdout.strip():
            raise RuntimeError("Probe process exited immediately after reporting PASS")
    except Exception as error:
        result = "FAIL " + str(error)
    finally:
        if selected:
            if args.bdj:
                (args.output / "frames").mkdir()
                for cycle in range(2):
                    hashes = []
                    for step in STEPS:
                        name = f"cycle{cycle}-{step}.png"
                        hashes.append(collect_png("frames/" + name, "exec-out", "run-as", PACKAGE,
                                                  "cat", "files/candidate/bdj-frames/" + name))
                    if any(value is None for value in hashes):
                        collection_errors.append(f"Expected 4 complete BD-J frames in cycle {cycle}")
                    elif any(hashes[index] == hashes[index - 1] for index in range(1, 4)):
                        collection_errors.append(f"BD-J frame pixels did not change in cycle {cycle}")
            collect_png("screen.png", "exec-out", "screencap", "-p")
            collect_text("native-stderr.txt", "shell", "run-as", PACKAGE, "cat", "files/candidate/native-stderr.txt")
            if args.bdj:
                collect_text("libbluray-debug.txt", "shell", "run-as", PACKAGE, "cat", "files/candidate/libbluray-debug.txt")
            try:
                candidate_files = adb("shell", "run-as", PACKAGE, "ls", "files/candidate").stdout
                for name in candidate_files.splitlines():
                    if re.fullmatch(r"hs_err_pid\d+\.log", name):
                        collect_text(name, "shell", "run-as", PACKAGE, "cat", "files/candidate/" + name)
            except Exception as error:
                collection_errors.append(f"Could not list current native crash diagnostics: {error}")
            for pid in sorted(pids):
                maps = collect_text(f"maps-{pid}.txt", "shell", "run-as", PACKAGE, "cat", f"/proc/{pid}/maps")
                arch = "aarch64" if args.abi == "arm64-v8a" else "arm"
                if f"files/candidate/j2re-image/lib/{arch}/server/libjvm.so" not in maps:
                    collection_errors.append(f"Current process {pid} did not map the expected JVM")
            logs = collect_text("logcat.txt", "logcat", "-d", "-v", "threadtime", "-t", "4000", "-s",
                                "BdjZero:I", "System.err:W", "AndroidRuntime:E", "libc:F", "DEBUG:F")
            current_lines = [line for line in logs.splitlines()
                             if len(line.split()) > 2 and line.split()[2] in pids]
            if not current_lines:
                collection_errors.append("No current-process probe logs were collected")
            (args.output / "logcat-current-process.txt").write_text("\n".join(current_lines) + "\n", encoding="utf-8")
        (args.output / "pids.json").write_text(json.dumps(sorted(pids)), encoding="utf-8")
        (args.output / "commands.json").write_text(json.dumps(commands, indent=2), encoding="utf-8")
    if result and result.startswith("PASS ") and collection_errors:
        result = "FAIL evidence collection: " + "; ".join(collection_errors)
    (args.output / "result.txt").write_text((result or "FAIL no result") + "\n", encoding="utf-8")
    print(result, flush=True)
    if not result or not result.startswith("PASS "):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
