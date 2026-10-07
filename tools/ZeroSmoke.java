import java.awt.Color;
import java.awt.Font;
import java.awt.Graphics2D;
import java.awt.GraphicsEnvironment;
import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import javax.imageio.ImageIO;

/** Runs inside the candidate JRE, never inside Android ART. */
public final class ZeroSmoke {
  private static native long echo(long value);

  public static String run() throws Exception {
    String name = System.getProperty("java.vm.name");
    if (!name.contains("Zero")) {
      throw new AssertionError("Expected Zero VM: " + name);
    }
    long taggedValue = 0xb400007b278701b0L;
    if (echo(taggedValue) != taggedValue) {
      throw new AssertionError("JNI callback truncated the 64-bit value");
    }
    ArrayList<byte[]> retained = new ArrayList<byte[]>();
    for (int round = 0; round < 30; round++) {
      retained.clear();
      for (int item = 0; item < 128; item++) {
        retained.add(new byte[32768]);
      }
      System.gc();
    }
    BufferedImage image = new BufferedImage(16, 16, BufferedImage.TYPE_INT_ARGB);
    Graphics2D graphics = image.createGraphics();
    graphics.setColor(Color.RED);
    graphics.fillRect(0, 0, 16, 16);
    graphics.dispose();
    if (image.getRGB(4, 4) != Color.RED.getRGB()) {
      throw new AssertionError("Java2D did not render the expected pixel");
    }
    List<String> availableFamilies = Arrays.asList(
        GraphicsEnvironment.getLocalGraphicsEnvironment().getAvailableFontFamilyNames(Locale.ROOT));
    for (String family : new String[] {"DejaVu Sans", "DejaVu Serif", "DejaVu Sans Mono"}) {
      if (!availableFamilies.contains(family)) {
        throw new AssertionError("Bundled font family is not registered: " + family);
      }
    }
    int renderedFontCount = 0;
    String[] logicalFamilies = {"Dialog", "DialogInput", "SansSerif", "Serif", "Monospaced"};
    int[] styles = {Font.PLAIN, Font.BOLD, Font.ITALIC, Font.BOLD | Font.ITALIC};
    for (String family : logicalFamilies) {
      for (int style : styles) {
        Font font = new Font(family, style, 16);
        for (char character = ' '; character <= '~'; character++) {
          if (!font.canDisplay(character)) {
            throw new AssertionError("Missing ASCII glyph: " + family + "/" + style);
          }
        }
        BufferedImage text = new BufferedImage(256, 48, BufferedImage.TYPE_INT_ARGB);
        graphics = text.createGraphics();
        try {
          graphics.setFont(font);
          graphics.setColor(Color.WHITE);
          graphics.drawString("BD-J Zero Aa09", 4, 32);
        } finally {
          graphics.dispose();
        }
        int visible = 0;
        for (int y = 0; y < text.getHeight(); y++) {
          for (int x = 0; x < text.getWidth(); x++) {
            if ((text.getRGB(x, y) >>> 24) != 0) {
              visible++;
            }
          }
        }
        if (visible == 0) {
          throw new AssertionError("Font engine rendered no glyph pixels: " + family + "/" + style);
        }
        renderedFontCount++;
      }
    }
    ByteArrayOutputStream png = new ByteArrayOutputStream();
    if (!ImageIO.write(image, "png", png)) {
      throw new AssertionError("PNG writer is missing");
    }
    BufferedImage decoded = ImageIO.read(new ByteArrayInputStream(png.toByteArray()));
    if (decoded == null || decoded.getRGB(4, 4) != Color.RED.getRGB()) {
      throw new AssertionError("PNG image round trip failed");
    }
    return name + "; logical font styles " + renderedFontCount
        + "; JNI callback, class loading, GC, Java2D, fonts, PNG PASS";
  }

  public static int attached() {
    return 42;
  }
}
