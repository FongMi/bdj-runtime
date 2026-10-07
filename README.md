# Android BD-J runtime

Builds complete OpenJDK 8u482 Zero runtimes for Android `armeabi-v7a` and
`arm64-v8a`. The JVM, Java classes, AWT, font manager and native dependencies
come from the same build. Runtime ZIPs are separate from application APKs.

Experimental ARM32 and ARM64 candidates are available in the
[Zero 8u482 r1 release](https://github.com/FongMi/bdj-runtime/releases/tag/zero-jdk8u482-r1).
Both passed standalone JVM, font and BD-J menu checks on an Android API 34
x86 emulator using its ARM native bridge. See [validation evidence](VALIDATION.md)
for exact artifact hashes, checks and remaining acceptance requirements.

## Preserved sources

[`sources.json`](sources.json) pins every input by size and SHA-256. OpenJDK,
Android compatibility patches, libffi, FreeType, CUPS and DejaVu source archives
are preserved in the [sources-v1 release](https://github.com/FongMi/bdj-runtime/releases/tag/sources-v1).
Builds do not clone the original Android port or download a Kodi runtime. The independently packaged
DejaVu font input is reproducible using `tools/prepare_fonts.py`.

The NDK r10e compiler is a build tool downloaded from Google's official URL,
with its original pinned size and checksum. A verified local copy is reusable.
GitHub-hosted Ubuntu build packages and the Java 8 bootstrap JDK remain build
environment dependencies. See [third-party notices](SOURCE-NOTICE.md).

## Build

Run **Build Android BD-J Zero runtimes** in GitHub Actions. Select `all`,
`armeabi-v7a` or `arm64-v8a`. The two targets produce independent runtime,
probe, native verification, provenance, checksum and debug-symbol artifacts.
This workflow is manual and does not publish unvalidated runtime releases.

On Ubuntu 22.04 with the dependencies listed in the workflow and a Java 8
bootstrap JDK in `JAVA_HOME`:

```sh
bash tools/build_zero_runtime.sh armeabi-v7a
bash tools/build_zero_runtime.sh arm64-v8a
```

Outputs are under `buildout/<abi>/artifacts/`. Source archives are cached under
`buildout/sources/`. Invalid cached archives fail verification without silently
switching to another source. A fresh build directory is required for a new build.

## ARM32 atomics

The original Zero ARM implementation assumes kernel helper functions at fixed
addresses. Android kernels can omit those helpers. Our ARMv7 patch uses CPU
atomic compare-and-swap, addition, exchange and memory barriers, preserving the
existing OpenJDK return values and memory-order contracts. It rejects ARMv6.

The recipe compiles and disassembles regression probes with the actual target
compiler before building the JVM. Both targets also verify ELF architecture,
Android dependencies, 16 KiB load alignment, static libffi and the 26 upstream
AWT JNI initialization exports.

## Validation boundary

The published candidates passed independent ARM32 and ARM64 JVM/JNI/GC,
Java2D, 20 logical font styles, PNG and repeated BD-J menu checks in the
emulator. They remain experimental pending physical ARM device testing and
complete ExoPlayer/mpv menu-to-playback verification. DejaVu text and layout
also need acceptance across real discs. [VALIDATION.md](VALIDATION.md) records
the tested artifacts and the limits of these results.

## License

New build utilities and modifications are GPL-2.0-only unless stated otherwise.
Upstream files retain their individual copyright and license notices. OpenJDK
Classpath exceptions apply only where granted by the original source. DejaVu
font files retain their original Bitstream/Arev notices and names.
Runtime archives include the original OpenJDK documents, dependency notices,
source manifest and links to the preserved sources and exact build recipe.
See [source provenance and third-party notices](SOURCE-NOTICE.md).
