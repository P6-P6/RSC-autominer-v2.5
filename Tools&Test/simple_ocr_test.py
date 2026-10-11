#!/usr/bin/env python3
"""
SIMPLE OCR TEST - No sophisticated preprocessing

If this works, your Tesseract is OK but preprocessing might be the issue.
If this FAILS, the problem is Tesseract/pytesseract installation.

Usage:
    python simple_ocr_test.py screenshot.png
"""

import sys
import os

print("""
╔════════════════════════════════════════════════════════════════════╗
║           SIMPLE OCR TEST - DIAGNOSING THE PROBLEM                 ║
╚════════════════════════════════════════════════════════════════════╝
""")

# Quick prerequisites check
print("Checking prerequisites...")
try:
    import cv2
    import numpy as np
    import pytesseract
    # Set Tesseract path on Windows
    pytesseract.pytesseract.pytesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    print("✓ All libraries imported")
except ImportError as e:
    print(f"✗ Missing library: {e}")
    print("\nFix with:")
    print("  pip install pytesseract opencv-python numpy")
    sys.exit(1)

if len(sys.argv) < 2:
    print("\nUsage: python simple_ocr_test.py <screenshot.png>")
    print("\nExample:")
    print("  python simple_ocr_test.py game_screenshot.png")
    sys.exit(1)

image_path = sys.argv[1]

if not os.path.exists(image_path):
    print(f"✗ File not found: {image_path}")
    sys.exit(1)

print(f"\nLoading: {image_path}")
frame = cv2.imread(image_path)

if frame is None:
    print(f"✗ Could not read image")
    sys.exit(1)

h, w = frame.shape[:2]
print(f"✓ Image loaded: {w}x{h}")

# ========================================
# TEST 1: SIMPLE RAW OCR (NO PROCESSING)
# ========================================
print("\n" + "="*70)
print("TEST 1: RAW OCR (entire image, no preprocessing)")
print("="*70)

try:
    text = pytesseract.image_to_string(frame).lower()
    if text.strip():
        print(f"✓ OCR returned text:")
        for line in text.split('\n')[:5]:  # Show first 5 lines
            if line.strip():
                print(f"    {line}")
        
        # Check for fatigue keywords
        keywords = ["too tired", "tired to mine", "feel tired"]
        found = [k for k in keywords if k in text]
        if found:
            print(f"\n✓ FOUND FATIGUE KEYWORD: {found}")
        else:
            print(f"\n✗ No fatigue keywords found")
    else:
        print("✗ OCR returned empty result (no text detected)")
        
except Exception as e:
    print(f"✗ OCR failed: {e}")

# ========================================
# TEST 2: SIMPLE GRAY + THRESHOLD
# ========================================
print("\n" + "="*70)
print("TEST 2: Simple Grayscale + BINARY_OTSU (basic preprocessing)")
print("="*70)

try:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    
    text = pytesseract.image_to_string(binary).lower()
    if text.strip():
        print(f"✓ OCR returned text:")
        for line in text.split('\n')[:5]:
            if line.strip():
                print(f"    {line}")
        
        keywords = ["too tired", "tired to mine", "feel tired"]
        found = [k for k in keywords if k in text]
        if found:
            print(f"\n✓ FOUND FATIGUE KEYWORD: {found}")
        
        # Save the binary image for visual inspection
        cv2.imwrite("simple_test_binary.png", binary)
        print(f"\n✓ Saved: simple_test_binary.png (open this image)")
        
    else:
        print("✗ OCR returned empty result")
        cv2.imwrite("simple_test_binary.png", binary)
        print(f"Saved: simple_test_binary.png (check if text is visible)")
        
except Exception as e:
    print(f"✗ Error: {e}")

# ========================================
# TEST 3: CHECK TOP-LEFT REGION
# ========================================
print("\n" + "="*70)
print("TEST 3: Top-Left Region (Fatigue Bar Area)")
print("="*70)

roi_topleft = frame[0:int(h * 0.25), 0:int(w * 0.20)]
print(f"Region size: {roi_topleft.shape}")

# Check for red
b, g, r = cv2.split(roi_topleft)
red_mask = (r > 180) & (g < 120) & (b < 120)
red_pct = np.count_nonzero(red_mask) / roi_topleft.size * 100

print(f"Red pixels: {red_pct:.2f}%")
if red_pct > 5:
    print(f"✓ FATIGUE BAR DETECTED (> 5% red)")
else:
    print(f"✗ No high fatigue bar (< 5% red)")

# Save for inspection
cv2.imwrite("simple_test_topleft.png", roi_topleft)
print(f"Saved: simple_test_topleft.png")

# ========================================
# TEST 4: CHECK MESSAGE AREAS
# ========================================
print("\n" + "="*70)
print("TEST 4: Message Regions")
print("="*70)

regions = [
    ("top", (int(h * 0.15), int(h * 0.50), int(w * 0.15), int(w * 0.85))),
    ("middle", (int(h * 0.25), int(h * 0.60), int(w * 0.2), int(w * 0.8))),
    ("bottom", (int(h * 0.60), int(h * 0.95), int(w * 0.05), int(w * 0.95))),
]

keywords = ["too tired", "tired to mine", "feel tired", "should get some rest"]

for name, (y1, y2, x1, x2) in regions:
    roi = frame[y1:y2, x1:x2]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    
    text = pytesseract.image_to_string(binary).lower()
    
    print(f"\n{name.upper()} region:")
    if text.strip():
        preview = text[:80].replace('\n', ' ')
        print(f"  Text: '{preview}...'")
        
        found = [k for k in keywords if k in text]
        if found:
            print(f"  ✓ MATCH: {found}")
        else:
            print(f"  (no fatigue keywords)")
    else:
        print(f"  (empty)")
    
    # Save region
    cv2.imwrite(f"simple_test_region_{name}.png", roi)

print("\n" + "="*70)
print("ANALYSIS COMPLETE")
print("="*70)
print("""
Check the generated files:
  - simple_test_binary.png       (whole image, binary threshold)
  - simple_test_topleft.png      (fatigue bar area)
  - simple_test_region_*.png     (message areas)

If you see TEXT in these images, but OCR didn't detect it:
  → Problem: Tesseract can't read your game font
  → Solution: May need to use different threshold or PSM modes

If you DON'T see text in the images:
  → Problem: Preprocessing destroyed the text
  → Solution: Use simpler preprocessing or adjust ROI locations

If NO text at all and files are mostly black/blank:
  → Problem: ROI regions are wrong for your layout
  → Solution: Adjust Y/X percentages in bot.py
""")
