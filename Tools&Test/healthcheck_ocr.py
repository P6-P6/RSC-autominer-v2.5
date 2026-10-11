#!/usr/bin/env python3
"""
Quick Health Check for OCR Setup

This script checks if all OCR components are properly installed and working.
Run this FIRST to diagnose the issue.

Usage:
    python healthcheck_ocr.py
"""

import sys
import os

print("="*70)
print("OCR HEALTH CHECK")
print("="*70 + "\n")

# ==========================================
# 1. Check Tesseract Installation
# ==========================================
print("1. CHECKING TESSERACT INSTALLATION")
print("-" * 70)

import subprocess
tesseract_path = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
try:
    result = subprocess.run([tesseract_path, "--version"], capture_output=True, text=True, timeout=5)
    if result.returncode == 0:
        version_line = result.stdout.split('\n')[0]
        print(f"✓ Tesseract found: {version_line}")
        tesseract_ok = True
    else:
        print(f"✗ Tesseract command failed:")
        print(f"  {result.stderr}")
        tesseract_ok = False
except FileNotFoundError:
    print(f"✗ Tesseract NOT found at: {tesseract_path}")
    print("  Check installation path or reinstall from:")
    print("  https://github.com/UB-Mannheim/tesseract/wiki")
    tesseract_ok = False
except Exception as e:
    print(f"✗ Error checking Tesseract: {e}")
    tesseract_ok = False

# ==========================================
# 2. Check pytesseract Installation
# ==========================================
print("\n2. CHECKING PYTESSERACT INSTALLATION")
print("-" * 70)

try:
    import pytesseract
    print(f"✓ pytesseract imported successfully")
    
    # Set Tesseract path on Windows
    pytesseract.pytesseract.pytesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    
    # Try to get languages
    try:
        langs = pytesseract.get_languages()
        print(f"✓ Available languages: {langs}")
        pytesseract_ok = True
    except Exception as e:
        print(f"⚠️  pytesseract found but can't get languages:")
        print(f"  {e}")
        pytesseract_ok = False

except ImportError:
    print("✗ pytesseract NOT installed")
    print("  Install with: pip install pytesseract")
    pytesseract_ok = False
except Exception as e:
    print(f"✗ Error importing pytesseract: {e}")
    pytesseract_ok = False

# ==========================================
# 3. Check OpenCV
# ==========================================
print("\n3. CHECKING OPENCV")
print("-" * 70)

try:
    import cv2
    print(f"✓ OpenCV {cv2.__version__} imported successfully")
    opencv_ok = True
except ImportError:
    print("✗ OpenCV NOT installed")
    print("  Install with: pip install opencv-python")
    opencv_ok = False

# ==========================================
# 4. Check NumPy
# ==========================================
print("\n4. CHECKING NUMPY")
print("-" * 70)

try:
    import numpy as np
    print(f"✓ NumPy {np.__version__} imported successfully")
    numpy_ok = True
except ImportError:
    print("✗ NumPy NOT installed")
    numpy_ok = False

# ==========================================
# 5. Try Simple OCR Test
# ==========================================
print("\n5. TESTING SIMPLE OCR")
print("-" * 70)

if tesseract_ok and pytesseract_ok and opencv_ok:
    try:
        # Create a simple test image with text
        import numpy as np
        import cv2
        import pytesseract
        
        # White image with black text "TEST"
        test_img = np.ones((100, 300), dtype=np.uint8) * 255
        cv2.putText(test_img, "TEST", (50, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.5, 0, 2)
        
        text = pytesseract.image_to_string(test_img).strip()
        
        if "TEST" in text:
            print(f"✓ OCR TEST PASSED: Detected '{text}'")
            ocr_works = True
        else:
            print(f"⚠️  OCR returned unexpected result: '{text}'")
            ocr_works = False
    
    except Exception as e:
        print(f"✗ OCR test failed: {e}")
        ocr_works = False
else:
    print("⊘ Skipping OCR test (missing dependencies)")
    ocr_works = False

# ==========================================
# 6. SUMMARY
# ==========================================
print("\n" + "="*70)
print("SUMMARY")
print("="*70 + "\n")

status = {
    "Tesseract executable": "✓" if tesseract_ok else "✗",
    "pytesseract Python": "✓" if pytesseract_ok else "✗",
    "OpenCV": "✓" if opencv_ok else "✗",
    "NumPy": "✓" if numpy_ok else "✗",
    "OCR functional": "✓" if ocr_works else "✗",
}

all_ok = all([tesseract_ok, pytesseract_ok, opencv_ok, numpy_ok, ocr_works])

print("Component Status:")
for component, result in status.items():
    print(f"  {result} {component}")

print("\n" + "-"*70)

if all_ok:
    print("✓ ALL CHECKS PASSED - OCR is ready!")
    print("\nYour bot should be able to detect fatigue messages.")
    print("If it still doesn't work:")
    print("  1. Run: python diagnose_ocr.py screenshot.png")
    print("  2. Check ocr_debug/ folder to see what bot 'sees'")
    print("  3. Verify message location matches ROI regions")
else:
    print("✗ ISSUES FOUND - See above for details")
    
    if not tesseract_ok:
        print("\nTo fix Tesseract:")
        print("  1. Download installer: https://github.com/UB-Mannheim/tesseract/wiki")
        print("  2. Install with default settings")
        print("  3. Restart command prompt")
        print("  4. Run this script again")
    
    if not pytesseract_ok:
        print("\nTo fix pytesseract:")
        print("  Run: pip install pytesseract")
    
    if not opencv_ok:
        print("\nTo fix OpenCV:")
        print("  Run: pip install opencv-python")

print("\n" + "="*70 + "\n")

sys.exit(0 if all_ok else 1)
