"""
backend/vision_color_detector.py
Autonomous visual garment colour classifier for Google Merchant Center feeds.

Analyzes real studio product photographs (e.g. from cdn.shopify.com) using center-crop
foreground median RGB -> HSV classification so small embroidered logos or white/grey
studio backdrops never fool the colour detector. Works 100% locally with zero API cost.
"""

import io
import colorsys
from urllib.parse import urlparse
from typing import Optional

import httpx

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:  # pragma: no cover
    Image = None
    HAS_PIL = False

ALLOWED_IMAGE_HOST_SUFFIXES = (
    "cdn.shopify.com",
    "shopify.com",
    "maisongrozavu.com",
    ".myshopify.com",
)


def is_trusted_product_image_url(url: str) -> bool:
    """Allow only HTTPS Shopify/store CDN URLs to prevent SSRF."""
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return any(host == s.lstrip(".") or host.endswith(s) for s in ALLOWED_IMAGE_HOST_SUFFIXES)


def _hsv_to_merchant_color(h_deg: float, s: float, v: float) -> str:
    """Map median foreground HSV (h: 0..360, s: 0..1, v: 0..1) to a clean Google Merchant colour."""
    if v < 0.25:
        return "Black"
    if v < 0.42 and s < 0.22:
        return "Charcoal"
    if v > 0.94 and s < 0.04:
        return "White"
    if v > 0.84 and s < 0.09:
        return "Off-White"
    if v > 0.70 and s < 0.28 and 18 <= h_deg <= 55:
        return "Beige"
    if s < 0.14:
        return "Grey" if v >= 0.42 else "Charcoal"

    # Chromatic garment colours
    if h_deg < 12 or h_deg >= 345:
        if v < 0.50:
            return "Bordeaux"
        if s < 0.45 and v > 0.72:
            return "Blush Pink"
        return "Red"
    if 12 <= h_deg < 42:
        if v < 0.52:
            return "Brown"
        if s < 0.40 and v > 0.68:
            return "Beige"
        return "Orange"
    if 42 <= h_deg < 68:
        return "Sand" if s < 0.35 else "Yellow"
    if 68 <= h_deg < 165:
        if v < 0.45:
            return "Forest Green"
        if h_deg < 100 and s < 0.50:
            return "Olive"
        return "Green"
    if 165 <= h_deg < 255:
        return "Navy" if v < 0.45 else "Blue"
    if 255 <= h_deg < 305:
        return "Purple"
    if 305 <= h_deg < 345:
        return "Blush Pink" if (s < 0.45 and v > 0.70) else "Pink"
    return "Black"


def classify_image_bytes(raw_bytes: bytes) -> str:
    """
    Classify the primary garment/accessory colour from raw image bytes.
    Returns an empty string if the image cannot be decoded.
    """
    if not HAS_PIL or not raw_bytes:
        return ""
    try:
        im = Image.open(io.BytesIO(raw_bytes)).convert("RGB").resize((120, 120))
    except Exception:
        return ""

    # Sample the 4 corners to detect uniform studio backdrop (white or light studio grey)
    corners = [im.getpixel((4, 4)), im.getpixel((115, 4)), im.getpixel((4, 115)), im.getpixel((115, 115))]
    bg_r = sum(c[0] for c in corners) // 4
    bg_g = sum(c[1] for c in corners) // 4
    bg_b = sum(c[2] for c in corners) // 4
    corners_uniform = all(
        abs(c[0] - bg_r) < 15 and abs(c[1] - bg_g) < 15 and abs(c[2] - bg_b) < 15
        for c in corners
    )

    fg = []
    for y in range(18, 102):
        for x in range(18, 102):
            r, g, b = im.getpixel((x, y))
            # Skip pure white studio background
            if r > 246 and g > 246 and b > 246:
                continue
            # Skip uniform corner backdrop colour (within tight tolerance)
            if corners_uniform and bg_r > 180 and abs(r - bg_r) < 10 and abs(g - bg_g) < 10 and abs(b - bg_b) < 10:
                continue
            fg.append((r, g, b))

    if not fg:
        # Almost the entire center was pure white -> White garment
        return "White"

    rs = sorted(p[0] for p in fg)
    gs = sorted(p[1] for p in fg)
    bs = sorted(p[2] for p in fg)
    mid = len(fg) // 2
    mr, mg, mb = rs[mid], gs[mid], bs[mid]
    h, s, v = colorsys.rgb_to_hsv(mr / 255.0, mg / 255.0, mb / 255.0)
    return _hsv_to_merchant_color(h * 360.0, s, v)


async def detect_color_from_image_url(url: str, timeout: float = 8.0) -> str:
    """Download a trusted Shopify product photo and return its detected garment colour."""
    if not HAS_PIL or not is_trusted_product_image_url(url):
        return ""
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200 or not resp.content:
                return ""
            return classify_image_bytes(resp.content)
    except Exception:
        return ""
