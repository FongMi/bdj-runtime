package com.fongmi.android.bdjzero;

import android.app.Activity;
import android.os.Bundle;
import android.os.Process;
import android.os.SystemClock;
import android.system.Os;
import android.util.Log;
import android.widget.TextView;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

public final class ProbeActivity extends Activity {
  private static native String runProbe(String home, String jar);

  @Override
  public void onCreate(Bundle savedInstanceState) {
    super.onCreate(savedInstanceState);
    TextView output = new TextView(this);
    output.setId(android.R.id.text1);
    output.setText("RUNNING BD-J Zero probe");
    setContentView(output);
    new Thread(
            () -> {
              long started = SystemClock.elapsedRealtime();
              String result;
              String abi = Process.is64Bit() ? "arm64-v8a" : "armeabi-v7a";
              String runtimeHash = "unverified";
              try {
                String packagedAbi = readAssetText("abi.txt");
                if (!abi.equals(packagedAbi)) {
                  throw new AssertionError("Process ABI " + abi + " differs from " + packagedAbi);
                }
                runtimeHash = verifyRuntimeArchive();
                System.loadLibrary("bdjzeroprobe");
                File root = new File(getFilesDir(), "candidate");
                extract(root);
                File jar = new File(root, "zero-smoke.jar");
                try (InputStream input = getAssets().open("zero-smoke.jar");
                    FileOutputStream target = new FileOutputStream(jar)) {
                  copy(input, target);
                }
                File home = new File(root, "j2re-image");
                verifyJvm(home, abi);
                try (FileOutputStream errors =
                    new FileOutputStream(new File(root, "native-stderr.txt"))) {
                  Os.dup2(errors.getFD(), 2);
                }
                Os.setenv(
                    "_JAVA_OPTIONS",
                    "-Djava.io.tmpdir="
                        + getCacheDir()
                        + " -XX:ErrorFile="
                        + new File(root, "hs_err_pid%p.log"),
                    true);
                if (getIntent().getBooleanExtra("bdj", false)) {
                  Os.setenv("BD_DEBUG_MASK", "0xffffffff", true);
                  Os.setenv("BD_DEBUG_FILE", new File(root, "libbluray-debug.txt").getPath(), true);
                  File classpath = new File(root, "bdj-jars");
                  if (!classpath.isDirectory() && !classpath.mkdirs()) {
                    throw new IllegalStateException("Cannot create BD-J classpath");
                  }
                  for (String name :
                      new String[] {"libbluray-j2se-1.4.1.jar", "libbluray-awt-j2se-1.4.1.jar"}) {
                    try (InputStream input = getAssets().open(name);
                        FileOutputStream file = new FileOutputStream(new File(classpath, name))) {
                      copy(input, file);
                    }
                  }
                  Os.setenv("JAVA_HOME", home.getPath(), true);
                  Os.setenv("JDK_HOME", home.getPath(), true);
                  Os.setenv("LIBBLURAY_CP", classpath.getPath() + File.separator, true);
                  Os.setenv("BDJ_JVM_DISABLE_JIT", "1", true);
                  result =
                      androidx.media3.exoplayer.iso.IsoNavigationSession.run(
                          getIntent().getStringExtra("fixture"),
                          new File(root, "bdj-frames").getPath());
                } else {
                  result = runProbe(home.getPath(), jar.getPath());
                }
              } catch (Throwable error) {
                Log.e("BdjZero", "Probe failed", error);
                result = "FAIL " + error;
              }
              result += "; processAbi=" + abi + "; runtimeSha256=" + runtimeHash
                  + "; elapsedMs=" + (SystemClock.elapsedRealtime() - started);
              Log.i("BdjZero", result);
              try (FileOutputStream file =
                  new FileOutputStream(new File(getFilesDir(), "result.txt"))) {
                file.write(result.getBytes(StandardCharsets.UTF_8));
              } catch (Exception error) {
                Log.e("BdjZero", "Could not save result", error);
              }
              String completed = result;
              runOnUiThread(() -> output.setText(completed));
            },
            "bdj-zero-probe")
        .start();
  }

  private void extract(File root) throws Exception {
    if (root.exists()) {
      removeCandidate(root);
    }
    String prefix = root.getCanonicalPath() + File.separator;
    try (ZipInputStream zip = new ZipInputStream(getAssets().open("j2re-zero.zip"))) {
      ZipEntry entry;
      while ((entry = zip.getNextEntry()) != null) {
        File target = new File(root, entry.getName());
        if (!target.getCanonicalPath().startsWith(prefix)) {
          throw new IllegalArgumentException("Runtime entry escapes candidate directory");
        }
        File directory = entry.isDirectory() ? target : target.getParentFile();
        if (!directory.isDirectory() && !directory.mkdirs()) {
          throw new IllegalStateException("Cannot create " + directory);
        }
        if (!entry.isDirectory()) {
          try (FileOutputStream file = new FileOutputStream(target)) {
            copy(zip, file);
          }
          Os.chmod(target.getPath(), 0755);
        }
        zip.closeEntry();
      }
    }
  }

  private String readAssetText(String name) throws Exception {
    java.io.ByteArrayOutputStream bytes = new java.io.ByteArrayOutputStream();
    try (InputStream input = getAssets().open(name)) {
      byte[] data = new byte[256];
      int size;
      while ((size = input.read(data)) != -1) {
        bytes.write(data, 0, size);
      }
    }
    return new String(bytes.toByteArray(), StandardCharsets.US_ASCII).trim();
  }

  private String verifyRuntimeArchive() throws Exception {
    MessageDigest digest = MessageDigest.getInstance("SHA-256");
    try (InputStream input = getAssets().open("j2re-zero.zip")) {
      byte[] data = new byte[32768];
      int size;
      while ((size = input.read(data)) != -1) {
        digest.update(data, 0, size);
      }
    }
    StringBuilder hex = new StringBuilder();
    for (byte value : digest.digest()) {
      hex.append(String.format(java.util.Locale.US, "%02x", value & 0xff));
    }
    String actual = hex.toString();
    if (!actual.equals(readAssetText("runtime.sha256"))) {
      throw new AssertionError("Runtime asset SHA-256 mismatch");
    }
    return actual;
  }

  private static void removeCandidate(File file) throws Exception {
    if (file.isDirectory() && file.getCanonicalFile().equals(file.getAbsoluteFile())) {
      File[] files = file.listFiles();
      if (files == null) {
        throw new IllegalStateException("Cannot read candidate directory");
      }
      for (File child : files) {
        removeCandidate(child);
      }
    }
    if (!file.delete()) {
      throw new IllegalStateException("Cannot remove stale candidate file " + file);
    }
  }

  private static void verifyJvm(File home, String abi) throws Exception {
    String arch = abi.equals("arm64-v8a") ? "aarch64" : "arm";
    File jvm = new File(home, "lib/" + arch + "/server/libjvm.so");
    try (InputStream input = new java.io.FileInputStream(jvm)) {
      byte[] header = new byte[20];
      int offset = 0;
      while (offset < header.length) {
        int size = input.read(header, offset, header.length - offset);
        if (size < 0) {
          throw new AssertionError("Truncated JVM ELF header");
        }
        offset += size;
      }
      int elfClass = abi.equals("arm64-v8a") ? 2 : 1;
      int machine = abi.equals("arm64-v8a") ? 183 : 40;
      if (header[0] != 0x7f || header[1] != 'E' || header[2] != 'L' || header[3] != 'F'
          || header[4] != elfClass || header[5] != 1
          || (header[18] & 0xff) != machine || header[19] != 0) {
        throw new AssertionError("JVM ELF differs from process ABI " + abi);
      }
    }
  }

  private static void copy(InputStream input, FileOutputStream output) throws Exception {
    byte[] buffer = new byte[32768];
    int count;
    while ((count = input.read(buffer)) != -1) {
      output.write(buffer, 0, count);
    }
  }
}
