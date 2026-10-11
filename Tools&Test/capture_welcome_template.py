"""
One-shot tool: capture the 'Welcome to RSCRevolution2!' banner from a live
game window and save it as templates/welcome_rscrevolution.png.

HOW TO USE:
  1. Log into RSCRevolution so the welcome banner is visible on screen.
  2. Run this script: python "Tools&Test/capture_welcome_template.py"
  3. A preview window opens.  Drag the two horizontal sliders to crop the
     banner tightly, then press S to save and Q to quit.

The saved template replaces the auto-generated one — template matching will
then be pixel-perfect for your monitor resolution.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import cv2
import numpy as np
import win32gui
import win32con
from mss import mss

OUT_PATH = os.path.join(os.path.dirname(__file__), '..', 'templates', 'welcome_rscrevolution.png')

def list_java_windows():
    results = []
    def _cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title:
                results.append((hwnd, title))
    win32gui.EnumWindows(_cb, None)
    return results

def pick_window():
    wins = list_java_windows()
    print('\nVisible windows:')
    for i, (hwnd, title) in enumerate(wins):
        print(f'  [{i}] {title}  (hwnd={hwnd})')
    idx = int(input('\nEnter index of your RSC game window: '))
    return wins[idx]

def main():
    hwnd, title = pick_window()
    print(f'Using: {title}')

    rect = win32gui.GetClientRect(hwnd)
    pt   = win32gui.ClientToScreen(hwnd, (0, 0))
    region = {'left': pt[0], 'top': pt[1],
              'width': rect[2], 'height': rect[3]}

    with mss() as sct:
        shot  = sct.grab(region)
        frame = np.ascontiguousarray(
            np.frombuffer(shot.raw, dtype=np.uint8)
            .reshape((shot.height, shot.width, 4))[:, :, :3])

    h, w = frame.shape[:2]
    # Show top-third only — banner is always near the top
    preview_h = max(1, h // 3)
    preview   = frame[:preview_h].copy()

    cv2.namedWindow('Crop banner — drag sliders, S=save Q=quit', cv2.WINDOW_NORMAL)
    cv2.resizeWindow('Crop banner — drag sliders, S=save Q=quit', min(w, 900), 220)

    top_pct    = [0]
    bottom_pct = [30]

    cv2.createTrackbar('Top %',    'Crop banner — drag sliders, S=save Q=quit', 0,  100, lambda v: top_pct.__setitem__(0, v))
    cv2.createTrackbar('Bottom %', 'Crop banner — drag sliders, S=save Q=quit', 30, 100, lambda v: bottom_pct.__setitem__(0, v))

    print('\nDrag sliders to crop tightly around the banner, then:')
    print('  S — save to templates/welcome_rscrevolution.png')
    print('  Q — quit without saving')

    while True:
        y1 = int(h * top_pct[0]    / 100)
        y2 = int(h * bottom_pct[0] / 100)
        y2 = max(y1 + 1, y2)

        disp = preview.copy()
        scale = preview_h / h
        dy1 = int(y1 * scale)
        dy2 = int(y2 * scale)
        cv2.rectangle(disp, (0, dy1), (w - 1, dy2), (0, 255, 0), 1)
        cv2.imshow('Crop banner — drag sliders, S=save Q=quit', disp)

        key = cv2.waitKey(30) & 0xFF
        if key == ord('q'):
            print('Quit — nothing saved.')
            break
        if key == ord('s'):
            crop = frame[y1:y2, :]
            os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
            cv2.imwrite(OUT_PATH, crop)
            print(f'Saved: {os.path.abspath(OUT_PATH)}  size={crop.shape[1]}x{crop.shape[0]}')
            break

    cv2.destroyAllWindows()

if __name__ == '__main__':
    main()
