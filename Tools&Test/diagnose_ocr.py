#!/usr/bin/env python3
"""
OCR Diagnostic Tool

This script takes a screenshot of your game and:
1. Extracts the ROI regions the bot checks
2. Saves debug images so you can see what the bot "sees"
3. Tests OCR on each region
4. Identifies why detection is failing

Usage:
    python diagnose_ocr.py screenshot.png
"""

import sys
import os
import cv2
import numpy as np
from pathlib import Path

try:
    import pytesseract
    HAS_TESSERACT = True
    # Set Tesseract path on Windows
    pytesseract.pytesseract.pytesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
except ImportError:
    HAS_TESSERACT = False
    print("WARNING: pytesseract not installed!")

def diagnose_image(image_path):
    """Diagnose OCR on a single image"""
    
    if not os.path.exists(image_path):
        print(f"ERROR: Image not found: {image_path}")
        return False
    
    print(f"\n{'='*70}")
    print(f"DIAGNOSTIC REPORT: {image_path}")
    print(f"{'='*70}\n")
    
    # Load image
    frame = cv2.imread(image_path)
    if frame is None:
        print(f"ERROR: Could not load image")
        return False
    
    h, w = frame.shape[:2]
    print(f"✓ Image loaded: {w}x{h} pixels")
    
    # Create debug output directory
    debug_dir = Path("ocr_debug")
    debug_dir.mkdir(exist_ok=True)
    
    # ==================================
    # 1. EXTRACT AND SAVE ROI REGIONS
    # ==================================
    print(f"\n{'='*70}")
    print("1. EXTRACTING ROI REGIONS")
    print(f"{'='*70}\n")
    
    roi_regions = [
        ("top-center", (int(h * 0.15), int(h * 0.50), int(w * 0.15), int(w * 0.85))),
        ("middle-center", (int(h * 0.25), int(h * 0.60), int(w * 0.2), int(w * 0.8))),
        ("lower-center", (int(h * 0.60), int(h * 0.95), int(w * 0.05), int(w * 0.95))),
    ]
    
    for name, (y1, y2, x1, x2) in roi_regions:
        roi = frame[y1:y2, x1:x2]
        size = (x2 - x1, y2 - y1)
        saved = f"ocr_debug/00_ROI_{name}.png"
        cv2.imwrite(saved, roi)
        print(f"✓ {name:15} {size[0]:4}x{size[1]:3} pixels → {saved}")
    
    # ==================================
    # 2. TEST FATIGUE BAR DETECTION
    # ==================================
    print(f"\n{'='*70}")
    print("2. FATIGUE BAR DETECTION (TOP-LEFT)")
    print(f"{'='*70}\n")
    
    roi_topleft = frame[0:int(h * 0.25), 0:int(w * 0.20)]
    cv2.imwrite("ocr_debug/01_fatigue_bar_roi.png", roi_topleft)
    print(f"✓ Saved fatigue bar ROI: ocr_debug/01_fatigue_bar_roi.png")
    
    if roi_topleft.size > 0:
        b, g, r = cv2.split(roi_topleft)
        red_mask = (r > 180) & (g < 120) & (b < 120)
        red_percentage = np.count_nonzero(red_mask) / roi_topleft.size * 100
        
        print(f"\n  Red pixel analysis:")
        print(f"    - Red pixels (R>180, G<120, B<120): {np.count_nonzero(red_mask)}")
        print(f"    - Total pixels: {roi_topleft.size}")
        print(f"    - Red percentage: {red_percentage:.2f}%")
        print(f"    - Threshold: 5%")
        
        if red_percentage > 5:
            print(f"    ✓ WOULD TRIGGER: High fatigue detected!")
        else:
            print(f"    ✗ Would not trigger (red < 5%)")
        
        # Save red mask for visualization
        red_mask_img = (red_mask * 255).astype(np.uint8)
        cv2.imwrite("ocr_debug/02_red_mask.png", red_mask_img)
        print(f"    Saved red mask: ocr_debug/02_red_mask.png")
    
    # ==================================
    # 3. TEST OCR ON EACH REGION
    # ==================================
    print(f"\n{'='*70}")
    print("3. OCR TEXT DETECTION")
    print(f"{'='*70}\n")
    
    if not HAS_TESSERACT:
        print("⚠️  ERROR: Tesseract not available!")
        print("   Install: https://github.com/UB-Mannheim/tesseract/wiki")
        return False
    
    print("Testing preprocessing variants...\n")
    
    fatigue_keywords = [
        "too tired to mine",
        "you are too tired",
        "feel tired",
        "should get some rest",
        "tired"
    ]
    
    roi_idx = 0
    for roi_name, (y1, y2, x1, x2) in roi_regions[:1]:  # Test just first ROI for speed
        print(f"Region: {roi_name}\n")
        
        roi = frame[y1:y2, x1:x2]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        
        # Preprocessing variants
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        cleaned = cv2.morphologyEx(enhanced, cv2.MORPH_CLOSE, kernel, iterations=1)
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel, iterations=1)
        
        variants = [
            ("OTSU auto", cv2.threshold(cleaned, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]),
            ("Bright (>150)", cv2.threshold(cleaned, 150, 255, cv2.THRESH_BINARY)[1]),
            ("Inverted", 255 - cv2.threshold(cleaned, 150, 255, cv2.THRESH_BINARY)[1]),
            ("Adaptive", cv2.adaptiveThreshold(cleaned, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)),
            ("Original OTSU", cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]),
        ]
        
        found_any_text = False
        
        for var_idx, (var_name, var_img) in enumerate(variants):
            # Save variant for visual inspection
            saved_variant = f"ocr_debug/03_variant_{var_idx:02d}_{var_name.replace('/', '_').replace(' ', '_')}.png"
            cv2.imwrite(saved_variant, var_img)
            
            # Try OCR
            try:
                text = pytesseract.image_to_string(var_img).strip().lower()
                
                if text:
                    found_any_text = True
                    has_fatigue = any(kw in text for kw in fatigue_keywords)
                    
                    status = "✓ FATIGUE" if has_fatigue else "  (no fatigue keyword)"
                    print(f"{status} {var_name:15}: '{text[:60]}'")
                
                # Also try 2x scaled
                scaled = cv2.resize(var_img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                text_scaled = pytesseract.image_to_string(scaled).strip().lower()
                
                if text_scaled:
                    has_fatigue = any(kw in text_scaled for kw in fatigue_keywords)
                    status = "✓ FATIGUE" if has_fatigue else "  (no fatigue keyword)"
                    print(f"{status} {var_name:15} [2x]: '{text_scaled[:55]}'")
                    if not text:  # Only count if 1x didn't work
                        found_any_text = True
            
            except Exception as e:
                print(f"  ✗ {var_name:15}: ERROR - {str(e)[:40]}")
        
        if not found_any_text:
            print(f"\n  ⚠️  NO TEXT DETECTED in any variant!")
            print(f"  This means Tesseract found nothing readable.")
            print(f"  The image preprocessing may be destroying the text.")
        
        print()
    
    # ==================================
    # 4. DIAGNOSTIC SUMMARY
    # ==================================
    print(f"\n{'='*70}")
    print("4. DIAGNOSTIC SUMMARY")
    print(f"{'='*70}\n")
    
    checks = {
        "✓ Image loaded": True,
        "✓ Tesseract available": HAS_TESSERACT,
    }
    
    print("Debug files saved to: ocr_debug/")
    print("\nFiles generated:")
    print("  00_ROI_*.png          - The 3 message regions being checked")
    print("  01_fatigue_bar_roi.png - Top-left fatigue bar region")
    print("  02_red_mask.png        - Red pixels detected in fatigue bar")
    print("  03_variant_*.png       - Preprocessing variants applied")
    
    print("\n" + "="*70)
    print("NEXT STEPS:")
    print("="*70)
    print("""
1. Open ocr_debug/ folder and view the images:
   - 00_ROI_top-center.png - Does this look like the message area?
   - 03_variant_*.png - Can you see text clearly in any of these?

2. If you can't see text in the variants:
   - The ROI regions might be wrong for your game layout
   - Adjust percentages in bot.py check_fatigue_message()
   
3. If text IS visible in variants:
   - Run: python test_ocr.py ocr_debug/03_variant_00_OTSU_auto.png
   - This tests Tesseract on that specific image

4. Common issues:
   - Game resolution different from expected
   - Game messages appear in different locations
   - Tesseract config wrong for your font
""")
    
    return True

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    image_path = sys.argv[1]
    diagnose_image(image_path)

if __name__ == "__main__":
    main()
