# Android runtime probe

This app validates a candidate JRE independently of Media and TV. Its application ID is
`com.fongmi.android.bdjruntime`. The Java activity remains
`com.fongmi.android.bdjzero.ProbeActivity` because the native probe exports that JNI name.
The manifest uses the full activity name, so those identifiers can differ safely.

Supply your Android SDK, Java home (or its `bin` directory), an external Android debug
keystore, one ABI's producer artifacts, a matching Media ISO AAR, and the two matching
libbluray 1.4.1 JARs. The build does not install an app. No SDK, keystore, commercial
disc or generated APK belongs in this repository.

```sh
python3 probe/build_apk.py --sdk "$ANDROID_SDK_ROOT" --java "$JAVA_HOME" \
  --artifacts "$ARTIFACTS" --media-iso-aar "$ISO_AAR" --bdj-assets "$BDJ_JARS" \
  --output "$NEW_OUTPUT" --abi armeabi-v7a --keystore "$DEBUG_KEYSTORE"
```

The default SDK build tools are `37.0.0` and platform is `android-36`; use
`--build-tools` and `--platform` to select installed versions. Signing uses the public
Android debug password `android`. The output directory must be new. The input runtime
is `j2re-zero-<abi>.zip`; the APK contains it as `assets/j2re-zero.zip`. Native libraries
are packaged for exactly the selected ABI, so `armeabi-v7a` forces a 32 bit process on
a device supporting that ABI. Android API 23 or later is required.

After installing the matching APK on an explicitly selected device, run the baseline
and BD-J checks separately. Each command starts a new process; a JVM cannot be created
again in a process after the baseline destroys it.

```sh
python3 probe/run_probe.py --adb "$ADB" --serial "$SERIAL" --port "$ADB_PORT" \
  --abi armeabi-v7a --runtime-sha256 "$RUNTIME_SHA256" --output "$BASELINE_OUTPUT"
python3 probe/run_probe.py --adb "$ADB" --serial "$SERIAL" --port "$ADB_PORT" \
  --abi armeabi-v7a --runtime-sha256 "$RUNTIME_SHA256" --output "$BDJ_OUTPUT" \
  --bdj --fixture "$DEVICE_BDJ_ISO_PATH"
```

Repeat with `arm64-v8a` and its APK for ARM64. The baseline asserts the Zero VM, JNI,
class loading, GC, thread attachment, Java2D, fonts and PNG round trip. Both modes assert
the process ABI and candidate archive SHA-256. The BD-J check requires visible menu
pixels, changed frames after down/right/select, and a second open/close cycle. Each run
replaces only the probe's extracted `files/candidate` directory to prevent stale runtime
files or menu frames from satisfying the check. An explicit fixture is required.

The helper saves device identity, native diagnostics, process maps, current-process
logs, a screenshot and all eight BD-J frames. Missing captures, invalid PNGs, unchanged
menu frames or failed ADB commands make the result fail. Use your lawful local disc
fixture; no media is included. This verifies JVM and authored menu behavior; it does not
test full video playback, audio or HDR.

```sh
python3 -m unittest discover -s probe -p 'test_*.py' -v
```
