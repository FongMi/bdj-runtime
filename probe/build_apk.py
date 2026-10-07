"""Package one candidate runtime in an independent Android probe APK."""

import argparse
import hashlib
import os
import pathlib
import subprocess
import zipfile


PACKAGE = "com.fongmi.android.bdjruntime"
ABIS = {"armeabi-v7a": ("arm", 1, 40), "arm64-v8a": ("aarch64", 2, 183)}
JARS = ("libbluray-j2se-1.4.1.jar", "libbluray-awt-j2se-1.4.1.jar")


def verify_elf(data, abi, name):
    _, elf_class, machine = ABIS[abi]
    if (len(data) < 20 or data[:4] != b"\x7fELF" or data[4] != elf_class
            or data[5] != 1 or int.from_bytes(data[18:20], "little") != machine):
        raise ValueError(f"{name} does not match {abi}")


def stage_assets(apk, artifacts, media_iso_aar, bdj_assets, abi):
    runtime = artifacts / f"j2re-zero-{abi}.zip"
    arch = ABIS[abi][0]
    with zipfile.ZipFile(runtime) as image:
        if image.testzip() is not None:
            raise ValueError("Damaged runtime archive")
        names = set(image.namelist())
        for name in ("j2re-image/lib/rt.jar", "j2re-image/LICENSE", "j2re-image/THIRD_PARTY_README"):
            if name not in names:
                raise ValueError(f"Runtime is missing {name}")
        verify_elf(image.read(f"j2re-image/lib/{arch}/server/libjvm.so"), abi, "libjvm.so")
        if not any(name.startswith("j2re-image/lib/fonts/") and name.endswith(".ttf") for name in names):
            raise ValueError("Runtime lacks its bundled fonts")
    probe = (artifacts / "libbdjzeroprobe.so").read_bytes()
    verify_elf(probe, abi, "libbdjzeroprobe.so")
    with zipfile.ZipFile(media_iso_aar) as aar:
        iso_jni = aar.read(f"jni/{abi}/libisoJNI.so")
        verify_elf(iso_jni, abi, "libisoJNI.so")
    for name in JARS:
        with zipfile.ZipFile(bdj_assets / name) as jar:
            if jar.testzip() is not None:
                raise ValueError(f"Damaged {name}")
    with zipfile.ZipFile(artifacts / "zero-smoke.jar") as jar:
        if "ZeroSmoke.class" not in jar.namelist() or jar.testzip() is not None:
            raise ValueError("Incomplete zero-smoke.jar")
    apk.write(runtime, "assets/j2re-zero.zip")
    apk.writestr("assets/abi.txt", abi + "\n")
    apk.writestr("assets/runtime.sha256", hashlib.sha256(runtime.read_bytes()).hexdigest() + "\n")
    apk.write(artifacts / "zero-smoke.jar", "assets/zero-smoke.jar")
    apk.writestr(f"lib/{abi}/libbdjzeroprobe.so", probe)
    apk.writestr(f"lib/{abi}/libisoJNI.so", iso_jni)
    for name in JARS:
        apk.write(bdj_assets / name, "assets/" + name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sdk", "java", "artifacts", "media-iso-aar", "bdj-assets", "output", "keystore"):
        parser.add_argument("--" + name, required=True, type=pathlib.Path)
    parser.add_argument("--abi", choices=ABIS, required=True)
    parser.add_argument("--build-tools", default="37.0.0")
    parser.add_argument("--platform", default="android-36")
    args = parser.parse_args()
    source = pathlib.Path(__file__).resolve().parent
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    classes, dex = output / "classes", output / "dex"
    classes.mkdir()
    dex.mkdir()
    tools = args.sdk / "build-tools" / args.build_tools
    android = args.sdk / "platforms" / args.platform / "android.jar"
    java_home = args.java.parent if args.java.name.lower() == "bin" else args.java
    java_bin = java_home / "bin"
    executable, script = (".exe", ".bat") if os.name == "nt" else ("", "")
    environment = {**os.environ, "JAVA_HOME": str(java_home),
                   "PATH": str(java_bin) + os.pathsep + os.environ.get("PATH", "")}

    def run(*command):
        subprocess.run([str(arg) for arg in command], check=True, env=environment)

    run(java_bin / ("javac" + executable), "--release", "8", "-cp", android, "-d", classes,
        source / "ProbeActivity.java", source / "IsoNavigationSession.java")
    run(tools / ("d8" + script), "--min-api", "23", "--lib", android, "--output", dex,
        *classes.rglob("*.class"))
    unsigned = output / "unsigned.apk"
    run(tools / ("aapt2" + executable), "link", "-I", android, "--manifest",
        source / "AndroidManifest.xml", "-o", unsigned)
    with zipfile.ZipFile(unsigned, "a", compression=zipfile.ZIP_STORED) as apk:
        apk.write(dex / "classes.dex", "classes.dex")
        stage_assets(apk, args.artifacts, args.media_iso_aar, args.bdj_assets, args.abi)
    aligned = output / "aligned.apk"
    run(tools / ("zipalign" + executable), "-f", "-P", "16", "4", unsigned, aligned)
    result = output / f"bdj-runtime-probe-{args.abi}.apk"
    run(tools / ("apksigner" + script), "sign", "--ks", args.keystore,
        "--ks-pass", "pass:android", "--key-pass", "pass:android", "--out", result, aligned)
    run(tools / ("apksigner" + script), "verify", "--verbose", result)
    print(result)


if __name__ == "__main__":
    main()
