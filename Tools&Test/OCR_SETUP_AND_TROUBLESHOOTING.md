# Fatigue OCR Setup & Troubleshooting Guide

## Quick Setup

### Prerequisites
The improved fatigue detection requires:
1. **Tesseract-OCR** - The OCR engine
2. **pytesseract** - Python wrapper for Tesseract
3. **OpenCV** - For image processing (already required by bot)
4. **NumPy** - For array operations (already required)

### Installation

#### Windows

##### 1. Install Tesseract-OCR Executable

Download and install from: https://github.com/UB-Mannheim/tesseract/wiki

**Recommended**: Use the installer from this link (supports Windows 7-11)

After installation, verify with:
```bash
tesseract --version
```

##### 2. Install Python Package

```bash
pip install pytesseract
```

Or in your virtual environment:
```bash
# If using the my_bot_env environment
my_bot_env\Scripts\pip install pytesseract
```

##### 3. Update Tesseract Path (if needed)

If pytesseract can't find Tesseract, add this code near the top of `bot.py` before importing pytesseract:

```python
import pytesseract
pytesseract.pytesseract.pytesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
```

Adjust the path if you installed Tesseract to a different location.

#### Linux/Mac

```bash
# Ubuntu/Debian
sudo apt-get install tesseract-ocr
pip install pytesseract

# macOS
brew install tesseract
pip install pytesseract
```

## Configuration

### Enable/Disable Fatigue Detection

Edit `config.json`:
```json
{
    "fatigue_detection_enabled": true
}
```

- `true`: Bot will check for fatigue and stop when detected
- `false`: Bot will ignore fatigue detection

## Troubleshooting

### Issue 1: "pytesseract.TesseractNotFoundError"

**Symptom**: Bot crashes with error about Tesseract not found

**Solution**:
1. Verify Tesseract is installed:
   ```bash
   tesseract --version
   ```

2. If not found, install from: https://github.com/UB-Mannheim/tesseract/wiki

3. If installed but still not found, set the path in bot.py:
   ```python
   import pytesseract
   pytesseract.pytesseract.pytesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
   ```

### Issue 2: "ImportError: No module named 'pytesseract'"

**Symptom**: Bot can't import pytesseract library

**Solution**:
```bash
pip install pytesseract
```

Or if using the virtual environment:
```bash
my_bot_env\Scripts\pip install pytesseract
```

### Issue 3: OCR Not Detecting Fatigue Message

**Symptom**: 
- Bot doesn't stop when you get the "You are too tired to mine this rock" message
- No "[FATIGUE]" lines in console output

**Debug Steps**:

1. **Verify pytesseract is working**:
   ```bash
   python -c "import pytesseract; print(pytesseract.get_languages())"
   ```
   Should show: `['eng']` or similar

2. **Test OCR with the test script**:
   ```bash
   # Take a screenshot of the fatigue message
   # Save it as "fatigue_test.png"
   python test_ocr.py fatigue_test.png --verbose
   ```

3. **Check debug output**:
   - Run the bot and watch the console/debug logs
   - Look for lines like: `[FATIGUE] ROI 0 - Variant 'OTSU auto' - Detected: ...`
   - If you see these, OCR is working

4. **Verify config.json**:
   ```json
   "fatigue_detection_enabled": true
   ```

5. **Check screenshot quality**:
   - The larger/clearer the game window, the better OCR works
   - Minimum recommended: 1024x768 game window resolution
   - Better: 1280x960 or higher

### Issue 4: False Positives (Bot Stops When Not Fatigued)

**Symptom**: Bot stops with "[FATIGUE] Detected" even when you're not tired

**Cause**: Either:
- OCR is misreading other game messages as fatigue
- Fatigue bar color detection threshold is too sensitive

**Solution**:

1. **Check what's being detected**:
   - Look at console output showing what text was detected
   - Verify it actually says "tired" or "mine this rock"

2. **If it's the fatigue bar detection wrongly triggering**:
   - The red bar detection might be too sensitive
   - You can temporarily disable it by modifying `check_fatigue_bar_topleft()`:
     ```python
     # Add at the start:
     return False  # Temporarily disable
     ```

3. **Game messages sometimes contain these words**:
   - The keywords like "tired" might appear in other messages
   - Check the full text output to verify

### Issue 5: Fatigue Bar Detection (Red Pixels) Not Working

**Symptom**:
- Message detection works, but red bar detection doesn't
- Or vice versa

**Why**: The fatigue bar color and position vary by:
- Game brightness settings
- Resolution
- Game client version

**Solution**:

1. **Verify bar is actually red**: Take a screenshot and check the top-left corner
   - If it's a different color, adjust RGB thresholds in `check_fatigue_bar_topleft()`
   - Current check: `(r > 180) & (g < 120) & (b < 120)`

2. **Adjust detection**:
   ```python
   # In check_fatigue_bar_topleft(), modify:
   red_mask = (r > 200) & (g < 100) & (b < 100)  # More strict
   # or
   red_mask = (r > 150) & (g < 150) & (b < 150)  # More lenient
   ```

3. **Test with test utility**:
   ```bash
   python test_ocr.py screenshot.png
   # Check "Fatigue Bar" section output
   ```

## Verification Checklist

Before running the bot, verify:

- [ ] Tesseract installed: `tesseract --version`
- [ ] pytesseract installed: `pip show pytesseract`
- [ ] pytesseract can find Tesseract: `python -c "import pytesseract; pytesseract.get_languages()"`
- [ ] `config.json` has `"fatigue_detection_enabled": true`
- [ ] Test script works: `python test_ocr.py screenshot.png`

## Performance Impact

The improved OCR has minimal performance impact:
- Only runs **after mining** (not constantly)
- Checks multiple regions but very fast
- ~50-100ms per check (negligible in context of 3-6 second mining cycle)

## Advanced Tuning

### Fine-Tuning Tesseract Configs

If detection is still not working, you can add more PSM configurations in `bot.py`:

```python
tess_configs = [
    '--psm 6 -c tessedit_char_whitelist=...',  # Current
    '--psm 4',  # Assume single text column
    '--psm 5',  # Assume single text block
    '--psm 8',  # Treat as single word
    # Add more as needed...
]
```

See [Tesseract documentation](https://github.com/UB-Mannheim/tesseract/wiki) for PSM descriptions.

### Adjusting ROI Regions

If fatigue messages appear in different places for your screen resolution:

```python
roi_regions = [
    frame[int(h * 0.10):int(h * 0.55), int(w * 0.10):int(w * 0.90)],  # Larger area
    # etc...
]
```

Adjust the percentages to match your game layout.

## Support

If issues persist:

1. Collect this information:
   - Screenshot of the fatigue message
   - Output from: `tesseract --version`
   - Output from: `pip show pytesseract opencv-python numpy`
   - Console output when running bot with fatigue_detection_enabled=true

2. Run test script with verbose:
   ```bash
   python test_ocr.py fatigue_screenshot.png --verbose
   ```

3. Check the [Tesseract GitHub issues](https://github.com/UB-Mannheim/tesseract) for common problems
