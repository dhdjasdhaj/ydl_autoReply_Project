import re
from typing import Optional


ASK_URL_RE = re.compile(r"(?:https?://)?(?:m\.)?ydl\.com/ask/(\d+)\b")
ASK_PATH_RE = re.compile(r"/ask/(\d+)\b")


def parse_question_id_from_share_text(text: str) -> Optional[str]:
    if not text:
        return None

    match = ASK_URL_RE.search(text)
    if match:
        return match.group(1)

    match = ASK_PATH_RE.search(text)
    if match:
        return match.group(1)

    return None

