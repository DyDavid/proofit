"""OCR pipeline for image and screenshot job descriptions using pytesseract.

Applies grayscale conversion and thresholding before extracting text.
"""

from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)


def extract_text_from_image(image_bytes: bytes) -> str:
    """Extract plain text from image bytes (PNG, JPEG) with grayscale/threshold preprocessing."""
    if not image_bytes:
        raise ValueError("Image bytes are empty")

    try:
        import pytesseract
        from PIL import Image, ImageOps

        img = Image.open(io.BytesIO(image_bytes))

        # Convert to grayscale
        gray = ImageOps.grayscale(img)

        # Simple thresholding for contrast improvement
        threshold = 150
        binary = gray.point(lambda p: 255 if p > threshold else 0)

        # Run OCR
        text = pytesseract.image_to_string(binary)
        if text and text.strip():
            return text.strip()

        # Fallback to un-thresholded grayscale OCR
        raw_ocr = pytesseract.image_to_string(gray)
        return raw_ocr.strip() if raw_ocr else ""

    except Exception as err:
        logger.warning("Pytesseract OCR processing failed: %s", err)
        raise ValueError(f"OCR processing failed for image: {err}") from err
