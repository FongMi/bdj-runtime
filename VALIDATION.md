# Experimental runtime validation

The [Zero 8u482 r1 release](https://github.com/FongMi/bdj-runtime/releases/tag/zero-jdk8u482-r1)
contains independently built ARM32 and ARM64 runtime candidates. The preserved
source inputs are available in [sources-v1](https://github.com/FongMi/bdj-runtime/releases/tag/sources-v1).
These candidates remain experimental pending physical device and full player
acceptance.

## Tested runtime artifacts

| ABI | Runtime archive | Size in bytes | SHA-256 |
| --- | --- | ---: | --- |
| `arm64-v8a` | `j2re-zero-arm64-v8a.zip` | 41,283,648 | `f147cc55cba3d2062697638655fa241e113bc691607e83983b2d00a6dcea8826` |
| `armeabi-v7a` | `j2re-zero-armeabi-v7a.zip` | 40,846,603 | `035995b29f654ab1e9d6ecc6554d20cd51f73ef4386f874bd291be6b5bf2c0ff` |

The ARM32 producer succeeded in
[run 37578481138](https://github.com/FongMi/bdj-runtime/actions/runs/37578481138),
using recipe commit
[`3379685548570ccf0af87ed633ceb0a8d5ce703b`](https://github.com/FongMi/bdj-runtime/commit/3379685548570ccf0af87ed633ceb0a8d5ce703b).
The ARM64 producer job succeeded in
[ARM64 job in run 37578007815](https://github.com/FongMi/bdj-runtime/actions/runs/37578007815/job/112651131837),
using recipe commit
[`e0a8775deca06d7143cb56e70586e0dd27f0aaf3`](https://github.com/FongMi/bdj-runtime/commit/e0a8775deca06d7143cb56e70586e0dd27f0aaf3).
That matrix run's earlier ARM32 test failed; its ARM64 job succeeded.

The final candidates were derived using the notice packaging code at
[`3186fd2ad23dbce4eaa5a247f0d9bc03a098dfb6`](https://github.com/FongMi/bdj-runtime/commit/3186fd2ad23dbce4eaa5a247f0d9bc03a098dfb6).
All 181 original runtime entries retained identical bytes. The additions are
original dependency notices, source access documents and provenance metadata;
native libraries, Java classes and fonts retain their producer bytes. The
archives retain original build provenance and separate packaging provenance.
Future builds bundle these documents directly through the current recipe.

## Android emulator results

Both final candidate archives passed on LDPlayer with Android API 34, an x86
emulator using ARM native bridge translation. ARM32 and ARM64 were tested in
their respective application processes.

The standalone baseline passed JVM/JNI callbacks, class loading, garbage
collection, Java2D drawing, all five logical font families in all four styles
(20 combinations), ASCII glyph coverage, PNG round trip and native thread
attachment. DejaVu Sans, Serif and Sans Mono families were registered.

The BD-J check passed two complete open/close cycles. Each cycle captured the
initial menu and three changed frames after down/right/select input. Eight
frames were captured for each ABI, with six frame changes confirmed by hashes.

| ABI | Baseline elapsed time | BD-J check elapsed time | Captured frames | Frame changes | Minimum visible pixels |
| --- | ---: | ---: | ---: | ---: | ---: |
| `arm64-v8a` | 11,014 ms | 52,385 ms | 8 | 6 | 194,329 |
| `armeabi-v7a` | 8,753 ms | 51,646 ms | 8 | 6 | 194,277 |

Visible pixels have nonzero alpha and nonzero RGB. The reported minimum is
across the eight captured frames. These elapsed times describe the recorded
emulator checks.

## Remaining acceptance

These results cover the standalone runtime and BD-J probe. Physical ARMv7 and
ARM64 devices require independent validation, including menu graphics, input,
close/reopen behavior and DejaVu text layout. Complete ExoPlayer and mpv
menu-to-playback flows also require application acceptance. Results from this
emulator do not establish physical device support or acceptance across real
commercial discs.

The release supplies runtime candidates and source provenance. Application
integration and deployment are separate validation steps.
