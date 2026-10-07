#!/usr/bin/env bash
# Build a complete Android JRE; never mix native libraries from other runtimes.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
abi=${1:?Usage: build_zero_runtime.sh armeabi-v7a|arm64-v8a}
case "$abi" in
  armeabi-v7a)
    target=arm-linux-androideabi
    cpu=arm
    ndk_arch=arm
    arch_flags='-march=armv7-a -mfloat-abi=softfp -mfpu=vfpv3-d16 -marm'
    ;;
  arm64-v8a)
    target=aarch64-linux-android
    cpu=aarch64
    ndk_arch=arm64
    arch_flags=
    ;;
  *) echo "Unsupported ABI: $abi" >&2; exit 2 ;;
esac

work="$repo_root/buildout/$abi"
cache="$repo_root/buildout/sources"
mkdir -p "$work/artifacts" "$work/debug-symbols"
exec > >(tee "$work/build.log") 2>&1
python3 "$repo_root/tools/fetch_sources.py" --cache "$cache"

# Read only the source fields consumed by the recipe. Archive bytes are checked
# by fetch_sources.py against the committed lock before any extraction.
source_field() {
  python3 - "$repo_root/sources.json" "$1" "$2" <<'PY'
import json, sys
manifest, source, field = sys.argv[1:]
with open(manifest, encoding='utf-8') as stream:
    print(json.load(stream)['sources'][source][field])
PY
}

cd "$work"
for dependency in jdk patches ndk freetype cups libffi fonts; do
  archive="$cache/$(source_field "$dependency" asset)"
  case "$(source_field "$dependency" format)" in
    zip) unzip -q "$archive" ;;
    tar) tar xf "$archive" ;;
    *) echo "Unsupported source archive format: $dependency" >&2; exit 2 ;;
  esac
  test -d "$(source_field "$dependency" root)"
done
jdk="$work/$(source_field jdk root)"
patches="$work/$(source_field patches root)"
ndk="$work/$(source_field ndk root)"
freetype_source="$work/$(source_field freetype root)"
cups="$work/$(source_field cups root)"
ffi_source="$work/$(source_field libffi root)"
fonts="$work/$(source_field fonts root)"
toolchain="$work/toolchain"

# Set up the pinned NDK directly. The Android port's helper scripts are not
# needed to construct an OpenJDK devkit or to select the cross compiler.
bash "$ndk/build/tools/make-standalone-toolchain.sh" \
  --arch="$ndk_arch" --platform=android-21 --install-dir="$toolchain"
cat > "$toolchain/devkit.info.$cpu" <<EOF
DEVKIT_NAME="Android $abi"
DEVKIT_TOOLCHAIN_PATH="\$DEVKIT_ROOT/$target/bin"
DEVKIT_SYSROOT="\$DEVKIT_ROOT/sysroot"
EOF
export PATH="$toolchain/bin:$PATH"
export AR="$toolchain/bin/$target-ar" AS="$toolchain/bin/$target-as"
export CC="$toolchain/bin/$target-gcc" CXX="$toolchain/bin/$target-g++"
export LD="$toolchain/bin/$target-ld" OBJCOPY="$toolchain/bin/$target-objcopy"
export RANLIB="$toolchain/bin/$target-ranlib" STRIP="$toolchain/bin/$target-strip"
android_include="$toolchain/sysroot/usr/include"
export CPPFLAGS="-I$android_include -I$android_include/$target"
export LDFLAGS="$arch_flags -L$ndk/platforms/android-21/arch-$ndk_arch/usr/lib -Wl,-z,max-page-size=16384 -Wl,--enable-new-dtags"

freetype="$work/freetype-target"
(
  cd "$freetype_source"
  CFLAGS="$arch_flags -fPIC" ./configure --host="$target" --prefix="$freetype" \
    --without-zlib --without-bzip2 --without-harfbuzz --without-png --with-brotli=no
  make -j"$(nproc)"
  make install
)
ffi_prefix="$work/libffi-target"
(
  cd "$ffi_source"
  CFLAGS="$arch_flags -fPIC" ./configure --host="$target" --prefix="$ffi_prefix" --libdir="$ffi_prefix/lib" \
    --disable-multi-os-directory --disable-shared --enable-static --with-pic \
    --disable-docs --disable-exec-static-tramp
  make -j"$(nproc)"
  make install
)
export LIBFFI_CFLAGS="-I$ffi_prefix/include"
export LIBFFI_LIBS="$ffi_prefix/lib/libffi.a"
export PKG_CONFIG_LIBDIR="$ffi_prefix/lib/pkgconfig" PKG_CONFIG_PATH=
test -f "$LIBFFI_LIBS"

# Initialize an empty repository only to apply the preserved patches to the
# extracted source. Provenance comes from the checked source archive, not Git.
git -C "$jdk" init -q
# Keep JDK 8's GNU C++98 standard. The unused flags.m4-only C++11 hunk
# conflicts with the Android patch's tinyiconv types.
git -C "$jdk" apply --whitespace=nowarn --exclude=common/autoconf/flags.m4 "$patches/jdk8u_android.diff"
git -C "$jdk" apply --whitespace=nowarn "$patches/jdk8u_android_main.diff"
python3 - "$jdk/common/autoconf" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
# The Android patch omits libjsoundalsa from BUILD_LIBRARIES. Configure must
# agree: ALSA belongs to the Linux desktop backend.
marker = '  # OS specific settings that we never will need to probe.\n  #\n'
android = '''  case "$OPENJDK_TARGET_AUTOCONF_NAME" in
    *-android*) ALSA_NOT_NEEDED=yes ;;
  esac

'''
for name in ('libraries.m4', 'generated-configure.sh'):
    path = root / name
    text = path.read_text()
    if text.count(marker) != 1:
        raise ValueError('Unexpected platform dependency block: ' + name)
    path.write_text(text.replace(marker, marker + android))
PY
python3 "$repo_root/tools/prepare_bdj_awt.py" "$jdk"
python3 - "$jdk/hotspot/src/os/linux/vm/os_linux.cpp" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
text = path.read_text()
old = '''    // libc has clock_getres and clock_gettime
    handle = RTLD_DEFAULT;'''
new = '''    // Bionic provides clocks in libc; LP64 RTLD_DEFAULT is a null sentinel.
    handle = dlopen("libc.so", RTLD_LAZY);'''
if text.count(old) != 1:
    raise ValueError('Android clock fallback changed')
text = text.replace(old, new)
old = '''#ifndef __ANDROID__ // we should not close RTLD_DEFAULT :)
        dlclose(handle);
#endif'''
if text.count(old) != 1:
    raise ValueError('Android clock handle ownership changed')
path.write_text(text.replace(old, '        dlclose(handle);'))
PY
if test "$abi" = armeabi-v7a; then
  python3 "$repo_root/tools/test_patch_zero_arm32.py" --source-root "$jdk" \
    --cxx "$CXX" --objdump "$toolchain/bin/$target-objdump" -v
  python3 "$repo_root/tools/patch_zero_arm32.py" "$jdk"
fi

ln -s /usr/include/X11 "$android_include/X11"
ln -s /usr/include/fontconfig "$android_include/fontconfig"
ln -s "$cups/cups" "$android_include/cups"
mkdir -p dummy_libs
"$AR" cr dummy_libs/libpthread.a
"$AR" cr dummy_libs/libthread_db.a
export CFLAGS="$arch_flags -O3 -D__ANDROID__ -DLE_STANDALONE"
export LDFLAGS="$LDFLAGS -L$work/dummy_libs"
boot_jdk="$JAVA_HOME"
(
  cd "$jdk"
  bash configure --openjdk-target="$target" --with-boot-jdk="$boot_jdk" \
    --with-extra-cflags="$CFLAGS" --with-extra-cxxflags="$CFLAGS" \
    --with-extra-ldflags="$LDFLAGS" --enable-option-checking=fatal \
    --with-jdk-variant=normal --with-jvm-variants=zero --with-debug-level=release \
    --with-devkit="$toolchain" --with-cups-include="$cups" \
    --with-fontconfig-include="$android_include" \
    --with-freetype-lib="$freetype/lib" --with-freetype-include="$freetype/include/freetype2" \
    --x-includes="$android_include/X11" --x-libraries=/usr/lib
  test -f "build/linux-$cpu-normal-zero-release/spec.gmk"
  make JOBS="$(nproc)" images
)

build="$jdk/build/linux-$cpu-normal-zero-release"
image="$build/images/j2re-image"
test -f "$image/lib/$cpu/server/libjvm.so"
test -f "$image/lib/rt.jar"
test -f "$image/lib/$cpu/libfontmanager.so"
# Bundle the target Freetype under the SONAME required by libfontmanager.
cp -L "$freetype/lib/libfreetype.so" "$image/lib/$cpu/libfreetype.so"
# Prefer the preserved DejaVu configuration over build-generated desktop maps.
python3 - "$image/lib" <<'PY'
import pathlib, sys
for path in pathlib.Path(sys.argv[1]).glob('fontconfig*.bfc'):
    path.unlink()
PY
cp -R "$fonts/lib/." "$image/lib/"
cp "$fonts/FONT-SHA256SUMS" "$image/FONT-SHA256SUMS"
cp "$build/spec.gmk" "$work/artifacts/spec.gmk"
cp "$repo_root/sources.json" "$work/artifacts/sources.json"
cp "$jdk/jdk/src/solaris/native/sun/xawt/AwtInitIDs.c" "$work/artifacts/AwtInitIDs.c"

# Build the app-embedded probe against this runtime's own JNI headers/classes.
mkdir -p "$work/probe-classes"
"$boot_jdk/bin/javac" -source 8 -target 8 -d "$work/probe-classes" "$repo_root/tools/ZeroSmoke.java"
"$boot_jdk/bin/jar" cf "$work/artifacts/zero-smoke.jar" -C "$work/probe-classes" .
"$CC" $arch_flags -fPIC -shared -Wl,-z,max-page-size=16384 \
  -DBDJ_JRE_ARCH=\"$cpu\" \
  -I"$jdk/jdk/src/share/javavm/export" -I"$jdk/jdk/src/solaris/javavm/export" \
  "$repo_root/tools/zero_probe.c" -ldl -llog -o "$work/artifacts/libbdjzeroprobe.so"
python3 "$repo_root/tools/verify_runtime.py" --image "$image" --abi "$abi" \
  --awt-source "$work/artifacts/AwtInitIDs.c" --probe "$work/artifacts/libbdjzeroprobe.so" \
  --report "$work/artifacts/native-verification.json"

python3 - "$repo_root" "$work/artifacts" "$abi" <<'PY'
import hashlib, json, os, pathlib, subprocess, sys
repo, out = map(pathlib.Path, sys.argv[1:3])
abi = sys.argv[3]
manifest_bytes = (repo / 'sources.json').read_bytes()
manifest = json.loads(manifest_bytes)
recipe_commit = os.environ.get('GITHUB_SHA') or subprocess.check_output(
    ['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
(out / 'provenance.json').write_text(json.dumps({
    'experimental': True, 'abi': abi, 'jvmVariant': 'zero', 'androidApi': 21,
    'androidPortRevision': manifest['sources']['patches']['revision'],
    'jdkRevision': manifest['sources']['jdk']['revision'],
    'jdkTag': 'jdk8u482-ga', 'ndk': manifest['sources']['ndk']['version'],
    'libffi': manifest['sources']['libffi']['version'],
    'heapTaggingDisabled': False, 'recipeCommit': recipe_commit,
    'sourceRelease': manifest['release'],
    'sourcesManifestSha256': hashlib.sha256(manifest_bytes).hexdigest(),
    'sources': manifest['sources'],
    'awtSourceSha256': hashlib.sha256((out / 'AwtInitIDs.c').read_bytes()).hexdigest(),
}, indent=2) + '\n')
PY
(
  cd "$(dirname "$image")"
  zip -qr "$work/j2re-zero-$abi-with-symbols.zip" j2re-image
)
python3 "$repo_root/tools/package_zero_runtime.py" \
  --source "$work/j2re-zero-$abi-with-symbols.zip" \
  --runtime "$work/artifacts/j2re-zero-$abi.zip" \
  --symbols "$work/debug-symbols/j2re-zero-$abi-symbols.zip"
(
  cd "$work/debug-symbols"
  sha256sum "j2re-zero-$abi-symbols.zip" > SHA256SUMS
)
cd "$work/artifacts"
sha256sum "j2re-zero-$abi.zip" libbdjzeroprobe.so zero-smoke.jar \
  provenance.json sources.json native-verification.json AwtInitIDs.c > SHA256SUMS
