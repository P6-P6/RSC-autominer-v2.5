#!/usr/bin/env python3
"""
Fatigue Detection OCR Test Utility

This script helps test and debug the OCR fatigue detection.
You can run it with a screenshot to verify the detection works.

Usage:
    python test_ocr.py <path_to_screenshot.png>
    
    # Or load from clipboard (if you have PIL/Pillow)
    python test_ocr.py --clipboard
    
    # Run with verbose mode
    python test_ocr.py <screenshot.png> --verbose
"""

import sys
import os
import cv2
import numpy as np

try:
    import pytesseract
    HAS_TESSERACT = True
    # Set Tesseract path on Windows
    pytesseract.pytesseract.pytesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
except ImportError:
    HAS_TESSERACT = False
    print("WARNING: pytesseract not installed. Install with: pip install pytesseract")

def test_fatigue_detection(image_path, verbose=False):
    """Test the fatigue detection on a single image"""
    
    if not os.path.exists(image_path):
        print(f"ERROR: Image not found: {image_path}")
        return False
    
    print(f"Loading image: {image_path}")
    frame = cv2.imread(image_path)
    
    if frame is None:
        print(f"ERROR: Could not load image")
        return False
    
    h, w = frame.shape[:2]
    print(f"Image size: {w}x{h}")
    
    if not HAS_TESSERACT:
        print("ERROR: Tesseract not available. Skipping OCR test.")
        return False
    
    # Define fatigue keywords
    fatigue_keywords = [
        "too tired to mine",
        "you are too tired",
        "you manage to obtain",
        "feel tired",
        "should get some rest",
        "tired"
    ]
    
    # Check multiple ROI regions
    roi_regions = [
        ("Top-center", frame[int(h * 0.15):int(h * 0.50), int(w * 0.15):int(w * 0.85)]),
        ("Middle-center", frame[int(h * 0.25):int(h * 0.60), int(w * 0.2):int(w * 0.8)]),
        ("Lower-center", frame[int(h * 0.60):int(h * 0.95), int(w * 0.05):int(w * 0.95)]),
    ]
    
    found_fatigue = False
    
    for roi_name, roi in roi_regions:
        if roi.size == 0:
            print(f"  {roi_name}: (empty ROI)")
            continue
        
        print(f"\n{'='*60}")
        print(f"Testing ROI: {roi_name}")
        print(f"{'='*60}")
        
        # Convert to grayscale
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        
        # Apply CLAHE
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        
        # Morphological operations
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        cleaned = cv2.morphologyEx(enhanced, cv2.MORPH_CLOSE, kernel, iterations=1)
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel, iterations=1)
        
        # Test variants
        variants = [
            ("OTSU auto", cv2.threshold(cleaned, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]),
            ("Bright text (>150)", cv2.threshold(cleaned, 150, 255, cv2.THRESH_BINARY)[1]),
            ("Inverted", 255 - cv2.threshold(cleaned, 150, 255, cv2.THRESH_BINARY)[1]),
            ("Adaptive", cv2.adaptiveThreshold(cleaned, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)),
            ("OTSU original", cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]),
        ]
        
        tess_configs = [
            ('Default', '--psm 6 -c tessedit_char_whitelist=abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 '),
            ('PSM 3', '--psm 3'),
            ('PSM 6', '--psm 6'),
            ('PSM 7', '--psm 7'),
            ('PSM 11', '--psm 11'),
            ('PSM 13', '--psm 13'),
        ]
        
        for var_name, var_img in variants:
            if verbose:
                print(f"\n  Variant: {var_name}")
            
            # Test original and 2x scaled
            test_imgs = [
                ("1x", var_img),
                ("2x scaled", cv2.resize(var_img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC))
            ]
            
            for scale_name, test_img in test_imgs:
                for tess_name, tcfg in tess_configs:
                    try:
                        text = pytesseract.image_to_string(test_img, config=tcfg).strip().lower()
                        
                        if text:
                            # Check for keywords
                            found_keyword = False
                            for keyword in fatigue_keywords:
                                if keyword in text:
                                    print(f"✓ FOUND: '{text}'")
                                    print(f"  Variant: {var_name} | Scale: {scale_name} | PSM: {tess_name}")
                                    found_fatigue = True
                                    found_keyword = True
                                    break
                            
                            if not found_keyword and verbose:
                                print(f"  {var_name} / {tess_name} ({scale_name}): '{text}'")
                    except Exception as e:
                        if verbose:
                            print(f"  Error: {e}")
    
    # Also test fatigue bar detection
    print(f"\n{'='*60}")
    print(f"Testing Fatigue Bar (top-left red detection)")
    print(f"{'='*60}")
    
    roi_topleft = frame[0:int(h * 0.25), 0:int(w * 0.20)]
    if roi_topleft.size > 0:
        b, g, r = cv2.split(roi_topleft)
        red_mask = (r > 180) & (g < 120) & (b < 120)
        red_percentage = np.count_nonzero(red_mask) / roi_topleft.size * 100
        print(f"Red pixels in top-left: {red_percentage:.1f}%")
        
        if red_percentage > 5:
            print(f"✓ HIGH FATIGUE DETECTED (red > 5%)")
            found_fatigue = True
        else:
            print(f"Low red percentage (< 5% threshold)")
    
    print(f"\n{'='*60}")
    if found_fatigue:
        print("✓ FATIGUE DETECTED - OCR Working!")
        return True
    else:
        print("✗ NO FATIGUE DETECTED - Check screenshot or thresholds")
        return False

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nExample:")
        print(f"  python {sys.argv[0]} screenshot.png")
        print(f"  python {sys.argv[0]} screenshot.png --verbose")
        sys.exit(1)
    
    image_path = sys.argv[1]
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    
    success = test_fatigue_detection(image_path, verbose=verbose)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
