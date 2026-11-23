import android.graphics.PixelFormat;
import android.graphics.Rect;
import android.media.Image;
import android.media.ImageReader;
import android.os.IBinder;
import android.view.Surface;
import java.io.BufferedOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.lang.reflect.Method;
import java.nio.ByteBuffer;

/**
 * Persistent screen capture, run as the shell user via app_process (like scrcpy): mirrors the
 * display into a virtual display backed by an ImageReader, so frames arrive as the screen
 * renders them, and hands out the latest one on request. Much faster than `screencap`
 * (~70 ms per call on Waydroid, plus adb).
 *
 * Usage: app_process -Djava.class.path=/data/local/tmp/inject.dex / Capture <w> <h> <x0> <y0> <x1> <y1>
 * Protocol (stdin/stdout, binary): each byte read from stdin requests a frame; the reply is
 *   int64 frame timestamp (ns, System.nanoTime clock (CLOCK_MONOTONIC, as Image timestamps)), int64 now (same clock),
 *   then (y1-y0) rows of (x1-x0) RGBA pixels: the crop x0..x1, y0..y1 of the screen.
 * Hidden APIs (SurfaceControl display mirroring) as on Android 10-13 (API 29-33).
 */
public class Capture {
    public static void main(String[] a) throws Exception {
        int w = Integer.parseInt(a[0]), h = Integer.parseInt(a[1]);
        int x0 = Integer.parseInt(a[2]), y0 = Integer.parseInt(a[3]);
        int x1 = Integer.parseInt(a[4]), y1 = Integer.parseInt(a[5]);

        ImageReader reader = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 3);
        Surface surface = reader.getSurface();

        Class<?> sc = Class.forName("android.view.SurfaceControl");
        IBinder display = (IBinder) sc.getMethod("createDisplay", String.class, boolean.class)
                .invoke(null, "aamuttaja-capture", false);
        Class<?> dmg = Class.forName("android.hardware.display.DisplayManagerGlobal");
        Object dm = dmg.getMethod("getInstance").invoke(null);
        Object info = dmg.getMethod("getDisplayInfo", int.class).invoke(dm, 0);
        int layerStack = info.getClass().getField("layerStack").getInt(info);
        int lw = info.getClass().getField("logicalWidth").getInt(info);
        int lh = info.getClass().getField("logicalHeight").getInt(info);

        sc.getMethod("openTransaction").invoke(null);
        try {
            sc.getMethod("setDisplaySurface", IBinder.class, Surface.class).invoke(null, display, surface);
            sc.getMethod("setDisplayProjection", IBinder.class, int.class, Rect.class, Rect.class)
                    .invoke(null, display, 0, new Rect(0, 0, lw, lh), new Rect(0, 0, w, h));
            sc.getMethod("setDisplayLayerStack", IBinder.class, int.class).invoke(null, display, layerStack);
        } finally {
            sc.getMethod("closeTransaction").invoke(null);
        }

        DataInputStream in = new DataInputStream(System.in);
        DataOutputStream out = new DataOutputStream(new BufferedOutputStream(System.out, 1 << 20));
        int cw = x1 - x0, ch = y1 - y0;
        byte[] row = new byte[cw * 4];
        byte[] blank = new byte[cw * 4];
        Image last = null;
        while (in.read() >= 0) {
            Image img = reader.acquireLatestImage();
            if (img != null) {
                if (last != null) last.close();
                last = img;
            }
            out.writeLong(last != null ? last.getTimestamp() : 0);
            out.writeLong(System.nanoTime());
            if (last == null) {
                for (int y = 0; y < ch; y++) out.write(blank);
            } else {
                Image.Plane p = last.getPlanes()[0];
                ByteBuffer buf = p.getBuffer();
                int stride = p.getRowStride();
                for (int y = y0; y < y1; y++) {
                    buf.position(y * stride + x0 * 4);
                    buf.get(row);
                    out.write(row);
                }
            }
            out.flush();
        }
    }
}
