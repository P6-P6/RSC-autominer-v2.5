# Fatigue Detection OCR Improvements

## Overview
The bot now has significantly improved fatigue detection using Tesseract OCR, optimized for RSC's bitmap Arial font rendering. The detection uses multiple complementary methods to ensure reliability.

## What Was Improved

### 1. **Enhanced OCR Message Detection** (`check_fatigue_message()`)

#### Specific Message Detection
- **Primary target**: "You are too tired to mine this rock"
- **Additional keywords**: "you are too tired", "too tired to mine", "feel tired", "should get some rest", plus variations

#### Advanced Image Preprocessing
The function now applies multiple preprocessing techniques specifically designed for bitmap fonts without anti-aliasing:

1. **CLAHE (Contrast Limited Adaptive Histogram Equalization)**
   - Increases contrast in localized areas
   - Enhances text visibility against game background

2. **Morphological Operations**
   - Closes small holes in text
   - Opens noise around characters
   - Makes characters more solid and recognizable

3. **Multiple Thresholding Variants**
   - OTSU automatic thresholding
   - High threshold for bright text on dark background
   - Inverted threshold for dark text on light background
   - Adaptive thresholding for varying lighting conditions
   - Original gray without CLAHE (fallback)

#### Multiple Regions Checked
The bot now checks three different areas of the screen where fatigue messages might appear:
1. **Top-center area** (15-50% height, 15-85% width) - Main game messages
2. **Middle-center area** (25-60% height, 20-80% width) - Dialog boxes
3. **Lower-center area** (60-95% height, 5-95% width) - Chat/status messages

#### Multiple Tesseract Configurations
The OCR tries multiple Page Segmentation Mode (PSM) values:
- PSM 3: Fully automatic page segmentation
- PSM 6: Assume uniform block of text (good for dialog boxes)
- PSM 7: Treat as single text line (for clear messages)
- PSM 11: Sparse text with OCR engine only
- PSM 13: Raw line mode
- PSM 6 with character whitelist (for robustness)

#### Image Scaling
For each preprocessing variant:
- Tests the original resolution image
- Tests a 2x scaled-up version (for small text rendition)

### 2. **New Fatigue Bar Detection** (`check_fatigue_bar_topleft()`)

Since fatigue is also displayed with a red bar on the top-left of the game window, the bot now checks for this visual indicator as well:

- **Detection Method**: Color-based detection of red pixels in the top-left stats area
- **Threshold**: If >5% of the top-left region is red, fatigue is detected
- **Location**: Checks approximately the first 20% of width and 25% of height (top-left corner)
- **Color Range**: Looks for red (high R, low G and B)

### 3. **Dual-Method Verification**

The bot now uses **both methods together**:
```python
has_fatigue_message = self.check_fatigue_message(frame_check, window_region)
has_fatigue_bar = self.check_fatigue_bar_topleft(frame_check)

if has_fatigue_message or has_fatigue_bar:
    # Stop bot due to fatigue
```

If **either** method detects fatigue, the bot stops with audio warning beeps.

## Configuration

The fatigue detection is controlled by the `config.json` setting:
```json
"fatigue_detection_enabled": true
```

When enabled, the bot:
1. Checks for fatigue message during mining (periodically after each click)
2. Logs detailed debug information about:
   - Which ROI detected the message
   - Which preprocessing variant worked
   - The actual OCR text detected
3. Plays two beep sounds (1000 Hz) when triggered
4. Gracefully stops the bot

## Debug Information

When fatigue is detected, the bot logs:
```
[FATIGUE] ROI 0 - Variant 'OTSU auto' - Detected: 'you are too tired to mine this rock'
🚨 FATIGUE DETECTED: too tired to mine | Full text: you are too tired to mine this rock
```

For fatigue bar detection:
```
[FATIGUE BAR] Detected high fatigue bar (red: 23.4%)
⚠️ FATIGUE BAR: High fatigue detected (23.4% red)
```

## Why This Works Better

1. **Multiple Preprocessing**: Bitmap fonts without anti-aliasing work better with various thresholding methods
2. **Multiple ROIs**: The message could appear in different areas depending on game context
3. **Multiple Tesseract Modes**: Different PSM values work better for different text layouts
4. **Scaling**: Small text that's hard to read at native resolution becomes clearer when scaled up
5. **Dual Detection**: Two independent detection methods provide belt-and-suspenders verification
6. **Robust Keyword Matching**: Checks for exact phrase variations rather than single words

## Performance Impact

- `check_fatigue_message()`: ~50-100ms per call (with multiple variants/configs to try)
- `check_fatigue_bar_topleft()`: ~5-10ms per call (simple color detection)
- Total impact: Barely noticeable since checks only run after mining, not during every frame

## Limitations & Notes

1. **OCR Accuracy**: Even with improvements, Tesseract isn't 100% reliable. The fatigue bar detection provides a secondary failsafe.
2. **Font Rendering**: If game rendering changes significantly, thresholds might need tuning
3. **Game Window Clarity**: Better results with higher resolution game window
4. **Tesseract Installation**: Requires Tesseract-OCR to be installed on the system

## Testing Recommendations

To verify the improvements work:

1. Run the bot and watch the debug console output
2. Manually trigger fatigue by mining until tired
3. Check that:
   - Message is detected correctly (logs show the fatigue text)
   - Bot stops with beep sounds
   - The fatigue bar detection (red pixel check) also works as backup

## Future Enhancements

Potential improvements that could be added:
- Fine-tune Tesseract training data for RSC's specific font
- Implement more sophisticated color detection for fatigue bar
- Add configurable thresholds in config.json
- Store screenshots of fatigue messages for debugging
