import re
import time
from collections import deque
from dataclasses import dataclass
from typing import Iterable, List, Tuple

from .config import Settings


HIGH_RISK_KEYWORDS = (
    "自杀",
    "自残",
    "自伤",
    "不想活",
    "想死",
    "去死",
    "结束生命",
    "轻生",
    "割腕",
    "跳楼",
    "上吊",
    "服药自杀",
)

MEDIUM_RISK_KEYWORDS = (
    "抑郁",
    "抑郁症",
    "崩溃",
    "绝望",
    "活着没意思",
    "情绪低落",
    "失眠",
    "焦虑",
)

BLOCKED_REPLY_PATTERNS = (
    r"你就是抑郁症",
    r"你患有",
    r"停药",
    r"换药",
    r"吃.*药",
    r"我能治好",
    r"保证.*好",
)

PII_PATTERNS = (
    (re.compile(r"1[3-9]\d{9}"), "[手机号]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[邮箱]"),
    (re.compile(r"(微信|vx|v信|QQ|qq)[:：]?\s*[A-Za-z0-9_-]{5,}"), "[联系方式]"),
)


@dataclass
class RiskResult:
    level: str
    reason: str
    keyword_hits: List[str]


class SafetyGate:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._send_times = deque()
        self._last_send_at = 0.0

    def scrub_pii(self, text: str) -> str:
        result = text or ""
        for pattern, replacement in PII_PATTERNS:
            result = pattern.sub(replacement, result)
        return result

    def classify(self, text: str) -> RiskResult:
        content = text or ""
        high_hits = [word for word in HIGH_RISK_KEYWORDS if word in content]
        if high_hits:
            return RiskResult("high", "self-harm or suicide keyword", high_hits)

        medium_hits = [word for word in MEDIUM_RISK_KEYWORDS if word in content]
        topic_hits = [word for word in self.settings.topic_keywords if word and word in content]
        hits = sorted(set(medium_hits + topic_hits))
        if hits:
            return RiskResult("medium", "mental health keyword", hits)

        return RiskResult("low", "no elevated keyword", [])

    def validate_reply(
        self,
        reply: str,
        require_ai_disclosure: bool = True,
        disclosure_text: str = "",
    ) -> Tuple[bool, str]:
        text = reply or ""
        if not text.strip():
            return False, "empty reply"
        marker = disclosure_text or self.settings.ai_disclosure_prefix
        if require_ai_disclosure and marker and marker not in text:
            return False, "missing AI disclosure"
        for pattern in BLOCKED_REPLY_PATTERNS:
            if re.search(pattern, text):
                return False, f"blocked unsafe wording: {pattern}"
        if len(text) > 260:
            return False, "reply too long"
        return True, ""

    def can_auto_post(self, risk_level: str) -> Tuple[bool, str]:
        if risk_level == "high":
            return False, "high-risk content requires manual handling"
        if not self.settings.real_posting_allowed:
            return False, "real posting is not enabled"

        now = time.time()
        while self._send_times and now - self._send_times[0] > 3600:
            self._send_times.popleft()
        if len(self._send_times) >= self.settings.max_posts_per_hour:
            return False, "hourly posting limit reached"
        if now - self._last_send_at < self.settings.min_post_interval_seconds:
            return False, "minimum posting interval has not elapsed"
        return True, ""

    def mark_posted(self) -> None:
        now = time.time()
        self._send_times.append(now)
        self._last_send_at = now

    def should_keep_text(self, text: str) -> bool:
        cleaned = (text or "").strip()
        if len(cleaned) < self.settings.post_min_chars:
            return False
        blocked_labels = {
            "首页", "我的", "消息", "咨询", "课程", "搜索", "发布", "评论", "赞", "分享",
            "最新", "关注", "推荐", "暖暖", "倾诉热线", "心事信箱", "心球说说",
        }
        if cleaned in blocked_labels:
            return False
        blocked_patterns = (
            r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s+发布了",
            r"^[\d,]+\s*个问题在这里收获了答案$",
            r"^\d+\s*个回答$",
            r"^\d+\s*看见",
            r".*看见\s*[·\s].*(赞同|评论|分享|赞)",
        )
        return not any(re.match(pattern, cleaned) for pattern in blocked_patterns)
