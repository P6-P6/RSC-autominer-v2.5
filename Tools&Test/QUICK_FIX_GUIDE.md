# OCR Not Detecting - Quick Diagnosis & Fix

## STEP 1: Verify Tesseract Works (2 min)

Run this health check:
```bash
python healthcheck_ocr.py
```

**Expected output**: All ✓ marks

### If you see ✗ errors:

**"Tesseract NOT FOUND on PATH"**:
- Download: https://github.com/UB-Mannheim/tesseract/wiki
- Install with default settings
- Restart PowerShell/command prompt
- Run healthcheck again

**"pytesseract NOT installed"**:
```bash
pip install pytesseract
```

---

## STEP 2: Diagnose Where Text Is (5 min)

Take a screenshot when fatigue message appears, save as `fatigue.png`, then run:

```bash
python simple_ocr_test.py fatigue.png
```

This will:
- Test raw OCR on your screenshot
- Test basic grayscale + threshold
- Check fatigue bar area
- Check message regions
- Create images: `simple_test_*.png`

### What to look for:

1. **Check `simple_test_region_top.png`**
   - Can you see the "You are too tired..." text in this image?
   - If NO → message is in different location, need to adjust ROI
   - If YES → OCR should detect it, but might be font issue

2. **Check `simple_test_binary.png`**  
   - Can you clearly see text?
   - If NO → preprocessing needs tuning
   - If YES → Tesseract should read it

3. **Console output**:
   - Does it show `✓ FOUND FATIGUE KEYWORD`?
   - If YES → OCR works, integration issue
   - If NO → Tesseract can't read the font

---

## STEP 3: Understand the Problem

Based on `simple_ocr_test.py` output:

| Symptom | Cause | Fix |
|---------|-------|-----|
| Console shows text but no "FATIGUE" keyword | Message is there but keyword doesn't match | Check exact text, update keywords |
| Console shows nothing (empty) | OCR sees no text | Check binary image, adjust threshold, or check ROI location |
| Binary image is mostly black, no visible text | Preprocessing destroying text | Use simpler threshold, reduce preprocessing |
| Fatigue bar % is 0% | You're not at 100% fatigue yet | Wait until you're fully tired, retake screenshot |

---

## STEP 4: Testing Images Generated

After running `simple_ocr_test.py`, check these files:

```
simple_test_binary.png         ← Whole image with OTSU threshold
simple_test_topleft.png        ← Top-left (fatigue bar area)
simple_test_region_top.png     ← Top message area (20% x 30-50% height)
simple_test_region_middle.png  ← Middle dialog area
simple_test_region_bottom.png  ← Bottom chat area
```

**If you see clear text in any `simple_test_region_*.png`:**
- Open it in Paint/Viewer
- Verify it shows the fatigue message
- If yes, copy the ROI name and we'll verify OCR on that specific region

---

## STEP 5: Quick Fixes

### Fix #1: ROI Regions Are Wrong

If `simple_test_region_top.png` is blank/black:

The message appears in a different area. Need to adjust in `bot.py`:

```python
roi_regions = [
    # OLD: ("Top-center", frame[int(h * 0.15):int(h * 0.50), int(w * 0.15):int(w * 0.85)]),
    # TRY: Adjust the percentages based on where message appears
    ("Top-center", frame[int(h * 0.10):int(h * 0.55), int(w * 0.10):int(w * 0.90)]),
]
```

### Fix #2: Text Is Destroyed by Preprocessing

If the binary image shows no text:

**Simplify the preprocessing** - Edit `check_fatigue_message()` in bot.py:

```python
# Comment out advanced preprocessing, just use basic OTSU:
for roi in roi_regions:
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    
    # Skip CLAHE and morphology - just use OTSU threshold
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    
    # Try OCR
    text = pytesseract.image_to_string(binary).lower()
```

### Fix #3: Exact Text Check

The message might have exact wording. In `simple_ocr_test.py` output, if you see the actual text (e.g., "You are too tired to mine this rock"), add it to keywords in `bot.py`:

```python
fatigue_keywords = [
    "too tired to mine",  # Exact phrase
    "you are too tired",
    "tired",
]
```

---

## STEP 6: Minimal Test Case

If nothing above works, use the **absolute minimum** code:

Replace the `check_fatigue_message()` function in bot.py with:

```python
def check_fatigue_message(self, frame, window_region):
    """Minimal OCR - just check top-center"""
    if not _HAVE_PYTESSACT:
        return False
    
    try:
        h, w = frame.shape[:2]
        
        # Just check top-center area
        roi = frame[int(h * 0.2):int(h * 0.5), int(w * 0.2):int(w * 0.8)]
        
        # Minimal preprocessing - just grayscale + basic threshold
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        
        # Raw OCR - no fancy PSM configs
        text = pytesseract.image_to_string(binary).lower()
        
        # Simple keyword check
        if "tired" in text or "mine" in text:
            print(f"[FATIGUE] Detected: {text}")
            return True
    
    except Exception as e:
        print(f"[FATIGUE] Error: {e}")
    
    return False
```

This removes ALL the complex preprocessing. If this works, the issue was in the preprocessing. If this still doesn't work, it's either:
- Tesseract not installed properly
- ROI location wrong
- Game font Tesseract can't read

---

## HELP - Still Not Working?

Provide me with:

1. **Screenshot** showing the "You are too tired" message
2. **Output** from running:
   ```bash
   python healthcheck_ocr.py
   python simple_ocr_test.py screenshot.png
   ```
3. **Files** from ocr_debug/ or simple_test_*.png files (showing what you see)

Then I can give you exact fixes!

---

## Commands Cheat Sheet

```bash
# Check if Tesseract installed
python healthcheck_ocr.py

# Diagnose OCR on screenshot
python simple_ocr_test.py screenshot.png

# Full diagnostic with debug images
python diagnose_ocr.py screenshot.png

# Test a specific region image
python test_ocr.py simple_test_region_top.png --verbose
```

---

**TL;DR**: 
1. Run `python healthcheck_ocr.py` - see if everything is installed
2. Take fatigue screenshot, run `python simple_ocr_test.py screenshot.png`
3. Check the generated `simple_test_*.png` files to see what's visible
4. Report back with what you find!
