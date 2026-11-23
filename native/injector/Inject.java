import android.os.SystemClock;
import android.view.InputDevice;
import android.view.InputEvent;
import android.view.KeyCharacterMap;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.MotionEvent.PointerCoords;
import android.view.MotionEvent.PointerProperties;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.lang.reflect.Method;

/**
 * Persistent touch injector, run as the shell user via app_process (no root needed: shell holds
 * INJECT_EVENTS). Reads one command per line on stdin, coordinates as screen fractions 0..1:
 *   d x y            finger 0 down          m x y      move finger 0       u    finger 0 up
 *   D x1 y1 x2 y2..  press several fingers  U          lift all fingers
 *   a x y            add one more finger (while others are down)   r   lift the last finger
 *   t text           type text (rest of the line)                   k code     press a key code
 *   p                print "ok" (sync point)
 * Usage: app_process -Djava.class.path=/data/local/tmp/inject.dex / Inject <width> <height>
 */
public class Inject {
    static Object im;
    static Method inject;
    static float W, H;
    static long downTime;
    static int n;                     // fingers currently down
    static final PointerProperties[] props = new PointerProperties[10];
    static final PointerCoords[] coords = new PointerCoords[10];

    public static void main(String[] a) throws Exception {
        W = Float.parseFloat(a[0]);
        H = Float.parseFloat(a[1]);
        Class<?> c = Class.forName("android.hardware.input.InputManager");
        im = c.getMethod("getInstance").invoke(null);
        inject = c.getMethod("injectInputEvent", InputEvent.class, int.class);
        for (int i = 0; i < 10; i++) {
            props[i] = new PointerProperties();
            props[i].id = i;
            props[i].toolType = MotionEvent.TOOL_TYPE_FINGER;
            coords[i] = new PointerCoords();
            coords[i].pressure = 1f;
            coords[i].size = 1f;
        }
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in));
        String line;
        while ((line = in.readLine()) != null) {
            String[] t = line.trim().split("\\s+");
            if (t[0].isEmpty()) continue;
            switch (t[0]) {
                case "d":
                    set(0, t[1], t[2]);
                    downTime = SystemClock.uptimeMillis();
                    n = 1;
                    send(MotionEvent.ACTION_DOWN);
                    break;
                case "m":
                    set(0, t[1], t[2]);
                    send(MotionEvent.ACTION_MOVE);
                    break;
                case "u":
                    send(MotionEvent.ACTION_UP);
                    n = 0;
                    break;
                case "D": {
                    int k = (t.length - 1) / 2;
                    downTime = SystemClock.uptimeMillis();
                    for (int i = 0; i < k; i++) {
                        set(i, t[1 + 2 * i], t[2 + 2 * i]);
                        n = i + 1;
                        send(i == 0 ? MotionEvent.ACTION_DOWN
                                : MotionEvent.ACTION_POINTER_DOWN | (i << MotionEvent.ACTION_POINTER_INDEX_SHIFT));
                    }
                    break;
                }
                case "U":
                    while (n > 1) {
                        send(MotionEvent.ACTION_POINTER_UP | ((n - 1) << MotionEvent.ACTION_POINTER_INDEX_SHIFT));
                        n--;
                    }
                    if (n == 1) send(MotionEvent.ACTION_UP);
                    n = 0;
                    break;
                case "a":
                    set(n, t[1], t[2]);
                    n++;
                    send(MotionEvent.ACTION_POINTER_DOWN | ((n - 1) << MotionEvent.ACTION_POINTER_INDEX_SHIFT));
                    break;
                case "r":
                    if (n > 1) {
                        send(MotionEvent.ACTION_POINTER_UP | ((n - 1) << MotionEvent.ACTION_POINTER_INDEX_SHIFT));
                        n--;
                    }
                    break;
                case "t":
                    type(line.trim().substring(1).trim());
                    break;
                case "k": {
                    int code = Integer.parseInt(t[1]);
                    long now = SystemClock.uptimeMillis();
                    inject.invoke(im, new KeyEvent(now, now, KeyEvent.ACTION_DOWN, code, 0), 0);
                    inject.invoke(im, new KeyEvent(now, now, KeyEvent.ACTION_UP, code, 0), 0);
                    break;
                }
                case "p":
                    System.out.println("ok");
                    System.out.flush();
                    break;
            }
        }
    }

    static void type(String text) throws Exception {
        KeyCharacterMap map = KeyCharacterMap.load(KeyCharacterMap.VIRTUAL_KEYBOARD);
        for (char ch : text.toCharArray()) {
            KeyEvent[] evs = map.getEvents(new char[] {ch});
            if (evs != null) {
                for (KeyEvent e : evs) inject.invoke(im, e, 0);
            } else {  // no key for it (e.g. Ä): send the character itself
                inject.invoke(im, new KeyEvent(SystemClock.uptimeMillis(), String.valueOf(ch), 0, 0), 0);
            }
        }
    }

    static void set(int i, String x, String y) {
        coords[i].x = Float.parseFloat(x) * W;
        coords[i].y = Float.parseFloat(y) * H;
    }

    static void send(int action) throws Exception {
        MotionEvent e = MotionEvent.obtain(downTime, SystemClock.uptimeMillis(), action, n, props, coords,
                0, 0, 1f, 1f, 0, 0, InputDevice.SOURCE_TOUCHSCREEN, 0);
        inject.invoke(im, e, 0);   // 0 = INJECT_INPUT_EVENT_MODE_ASYNC
        e.recycle();
    }
}
