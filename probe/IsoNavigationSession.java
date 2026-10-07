package androidx.media3.exoplayer.iso;

import android.graphics.Bitmap;
import android.os.SystemClock;
import android.util.Log;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.util.Arrays;

/** Test facade for the shipped ISO JNI contract; contains no player implementation. */
public final class IsoNavigationSession {
  private boolean menuActive;
  private boolean infiniteStill;
  private boolean bdjIdle;
  private boolean timeSeekAllowed;
  private int discontinuityId;
  private boolean waitingForDrain;
  private long finiteStillId;
  private long finiteStillDurationMs;
  private boolean titleEnded;
  private int menuDomain;
  private long stateVersion;
  private long action;

  private long pollAction() {
    long result = action;
    action = 0;
    return result;
  }

  public static final class Reader implements AutoCloseable {
    private final RandomAccessFile file;

    Reader(String path) throws IOException {
      file = new RandomAccessFile(path, "r");
    }

    public synchronized int read(long position, byte[] data, int offset, int length)
        throws IOException {
      file.seek(position);
      return file.read(data, offset, length);
    }

    @Override
    public void close() throws IOException {
      file.close();
    }
  }

  private static final class Frame {
    final int version;
    final int width;
    final int height;
    final int[] pixels;

    Frame(int version, int width, int height, int[] pixels) {
      this.version = version;
      this.width = width;
      this.height = height;
      this.pixels = pixels;
    }
  }

  public static String run(String fixture, String outputDirectory) throws Exception {
    if (fixture == null || fixture.isEmpty()) {
      throw new IllegalArgumentException("An explicit BD-J fixture path is required");
    }
    System.loadLibrary("isoJNI");
    File output = new File(outputDirectory);
    if (!output.isDirectory() && !output.mkdirs()) {
      throw new IllegalStateException("Cannot create frame output");
    }
    int frames = 0;
    int visiblePixelsMin = Integer.MAX_VALUE;
    for (int cycle = 0; cycle < 2; cycle++) {
      IsoNavigationSession owner = new IsoNavigationSession();
      try (Reader reader = new Reader(fixture)) {
        Log.i("BdjZero", "Opening BD-J cycle=" + cycle);
        long handle = nativeOpen(reader, owner, 2);
        if (handle == 0) {
          throw new AssertionError("Could not open native BD-J session");
        }
        try {
          if (!nativeIsBdj(handle) || !nativeHasMenu(handle)) {
            throw new AssertionError("Disc lacks an active BD-J menu");
          }
          Log.i("BdjZero", "BD-J opened, waiting for initial pixels cycle=" + cycle);
          Frame initial = awaitFrame(handle, null);
          saveFrame(initial, new File(output, "cycle" + cycle + "-initial.png"));
          frames++;
          visiblePixelsMin = Math.min(visiblePixelsMin, visiblePixels(initial));
          Frame current = initial;
          for (int key : new int[] {2, 4, 5}) {
            Log.i("BdjZero", "BD-J key=" + key + " cycle=" + cycle);
            owner.action = key;
            nativePump(handle);
            current = awaitFrame(handle, current);
            saveFrame(current, new File(output, "cycle" + cycle + "-key" + key + ".png"));
            frames++;
            visiblePixelsMin = Math.min(visiblePixelsMin, visiblePixels(current));
          }
          Log.i(
              "BdjZero",
              "BD-J cycle=" + cycle + " graphics=" + initial.version + "->" + current.version);
        } finally {
          nativeClose(handle);
        }
      }
    }
    return "PASS native BD-J menu pixels, down/right/select, close/reopen; menuFrames="
        + frames + "; changedFrames=6; visiblePixelsMin=" + visiblePixelsMin;
  }

  private static int visiblePixels(Frame frame) {
    int visible = 0;
    for (int pixel : frame.pixels) {
      if ((pixel >>> 24) != 0 && (pixel & 0x00FFFFFF) != 0) {
        visible++;
      }
    }
    return visible;
  }

  private static void saveFrame(Frame frame, File target) throws Exception {
    Bitmap bitmap =
        Bitmap.createBitmap(frame.pixels, frame.width, frame.height, Bitmap.Config.ARGB_8888);
    try (FileOutputStream file = new FileOutputStream(target)) {
      if (!bitmap.compress(Bitmap.CompressFormat.PNG, 100, file)) {
        throw new AssertionError("Could not save native BD-J pixels");
      }
    } finally {
      bitmap.recycle();
    }
  }

  private static Frame awaitFrame(long handle, Frame previous) throws Exception {
    long deadline = SystemClock.elapsedRealtime() + 150000;
    while (SystemClock.elapsedRealtime() < deadline) {
      nativePump(handle);
      int[] info = nativeGetHdmvMenuOverlayInfo(handle, previous == null ? -1 : previous.version);
      if (info != null && info[1] > 0 && info[2] > 0 && info[3] != 0) {
        int[] pixels = new int[info[1] * info[2]];
        if (nativeCopyHdmvMenuOverlay(handle, info[0], pixels)) {
          boolean content = false;
          for (int pixel : pixels) {
            if ((pixel >>> 24) != 0 && (pixel & 0x00FFFFFF) != 0) {
              content = true;
              break;
            }
          }
          if (content && (previous == null || !Arrays.equals(previous.pixels, pixels))) {
            return new Frame(info[0], info[1], info[2], pixels);
          }
        }
      }
      SystemClock.sleep(100);
    }
    throw new AssertionError("Timed out waiting for changed BD-J pixels");
  }

  private static native long nativeOpen(Object reader, Object owner, int type);

  private static native boolean nativeIsBdj(long handle);

  private static native boolean nativeHasMenu(long handle);

  private static native int nativePump(long handle);

  private static native int[] nativeGetHdmvMenuOverlayInfo(long handle, int previousVersion);

  private static native boolean nativeCopyHdmvMenuOverlay(long handle, int version, int[] pixels);

  private static native void nativeClose(long handle);
}
