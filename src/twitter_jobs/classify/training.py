"""Manual training-example upload + OCR helpers.

The user drops a screenshot of a tweet they consider a strong positive or
negative example. We:
  1. Save the image to disk under data/training/.
  2. OCR via Claude vision (Haiku) to extract the tweet text and author.
  3. Persist a row in training_examples with the user's reasoning and
     classification hints.

The classifier reads these rows on every call (alongside the user's dashboard
accept/dismiss decisions) and folds them into the few-shot block.
"""

from __future__ import annotations

import base64
import logging
import re
import uuid
from pathlib import Path

from anthropic import AsyncAnthropic

from twitter_jobs.config import get_settings

logger = logging.getLogger(__name__)

OCR_MODEL = "claude-haiku-4-5"
OCR_MAX_TOKENS = 1024

OCR_PROMPT = """\
This image is a screenshot of an X (Twitter) post. Extract:
1. The full tweet text, including hashtags and URLs visible.
2. The author's @handle if visible.

Reply in exactly this format and nothing else:

HANDLE: @somehandle
TEXT: <the full tweet text>

If the handle isn't visible, write 'HANDLE: unknown'.
"""


def training_dir() -> Path:
    """Filesystem location for uploaded training screenshots."""
    settings = get_settings()
    d = settings.project_root / "data" / "training"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_image(content: bytes, original_filename: str | None) -> tuple[Path, str]:
    """Save an uploaded image to data/training/ and return (path, media_type)."""
    suffix = ""
    if original_filename:
        suffix = Path(original_filename).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        suffix = ".png"
    media_type = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }[suffix]
    name = f"{uuid.uuid4().hex}{suffix}"
    path = training_dir() / name
    path.write_bytes(content)
    return path, media_type


async def ocr_screenshot(image_bytes: bytes, media_type: str) -> tuple[str, str | None]:
    """Use Claude vision to extract (tweet_text, author_handle) from the screenshot.

    Returns ('', None) on any failure — caller should let the user paste the text
    manually in that case.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        logger.warning("ANTHROPIC_API_KEY not set — skipping OCR")
        return "", None

    anthro = AsyncAnthropic(api_key=settings.anthropic_api_key)
    b64 = base64.standard_b64encode(image_bytes).decode("ascii")

    try:
        msg = await anthro.messages.create(
            model=OCR_MODEL,
            max_tokens=OCR_MAX_TOKENS,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": OCR_PROMPT},
                    ],
                }
            ],
        )
    except Exception:
        logger.exception("OCR call failed")
        return "", None

    raw = "\n".join(
        block.text for block in msg.content if getattr(block, "type", None) == "text"
    ).strip()
    return _parse_ocr_output(raw)


def _parse_ocr_output(raw: str) -> tuple[str, str | None]:
    handle_match = re.search(r"HANDLE:\s*(@?[A-Za-z0-9_]+|unknown)", raw, re.IGNORECASE)
    handle: str | None = None
    if handle_match:
        h = handle_match.group(1)
        if h.lower() != "unknown":
            handle = h.lstrip("@")

    text_match = re.search(r"TEXT:\s*(.+)", raw, re.IGNORECASE | re.DOTALL)
    text = text_match.group(1).strip() if text_match else raw.strip()
    return text, handle
