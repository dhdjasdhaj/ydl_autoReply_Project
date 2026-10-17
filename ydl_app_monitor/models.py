from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class UiNode:
    text: str = ""
    content_desc: str = ""
    hint: str = ""
    resource_id: str = ""
    class_name: str = ""
    clickable: bool = False
    enabled: bool = True
    bounds: str = ""

    @property
    def label(self) -> str:
        return " ".join(part for part in [self.text, self.content_desc, self.hint] if part).strip()


@dataclass
class PostRecord:
    post_id: str
    title: str
    content: str
    question_id: str = ""
    source: str = "app"
    risk_level: str = "unknown"
    risk_reason: str = ""
    keyword_hits: str = ""
    crawl_time: str = field(default_factory=now_text)
    status: str = "captured"
    tap_text: str = ""

    def to_row(self) -> Dict[str, str]:
        return {
            "question_id": self.question_id,
            "post_id": self.post_id,
            "title": self.title,
            "content": self.content,
            "source": self.source,
            "risk_level": self.risk_level,
            "risk_reason": self.risk_reason,
            "keyword_hits": self.keyword_hits,
            "crawl_time": self.crawl_time,
            "status": self.status,
            "tap_text": self.tap_text,
        }


@dataclass
class ReplyRecord:
    reply_id: str
    post_id: str
    reply_kind: str
    reply_content: str
    status: str
    account_id: str = ""
    account_nickname: str = ""
    strategy_id: str = ""
    strategy_name: str = ""
    experiment_group: str = ""
    reply_order: str = ""
    planned_send_at: str = ""
    error: str = ""
    parent_reply_id: str = ""
    target_user: str = ""
    target_content: str = ""
    created_at: str = field(default_factory=now_text)

    def to_row(self) -> Dict[str, str]:
        return {
            "reply_id": self.reply_id,
            "post_id": self.post_id,
            "reply_kind": self.reply_kind,
            "account_id": self.account_id,
            "account_nickname": self.account_nickname,
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "experiment_group": self.experiment_group,
            "reply_order": self.reply_order,
            "planned_send_at": self.planned_send_at,
            "reply_content": self.reply_content,
            "status": self.status,
            "error": self.error,
            "parent_reply_id": self.parent_reply_id,
            "target_user": self.target_user,
            "target_content": self.target_content,
            "created_at": self.created_at,
        }


@dataclass
class DialogueEvent:
    conversation_id: str
    post_id: str
    role: str
    content: str
    event_time: str = field(default_factory=now_text)
    parent_reply_id: str = ""

    def to_row(self) -> Dict[str, str]:
        return {
            "conversation_id": self.conversation_id,
            "post_id": self.post_id,
            "role": self.role,
            "content": self.content,
            "event_time": self.event_time,
            "parent_reply_id": self.parent_reply_id,
        }


@dataclass
class CycleStats:
    captured: int = 0
    new_posts: int = 0
    generated: int = 0
    posted: int = 0
    blocked: int = 0
    failed: int = 0
    followups_seen: int = 0
    followups_posted: int = 0
    notes: List[str] = field(default_factory=list)

    def to_row(self) -> Dict[str, str]:
        return {
            "run_time": now_text(),
            "captured": str(self.captured),
            "new_posts": str(self.new_posts),
            "generated": str(self.generated),
            "posted": str(self.posted),
            "blocked": str(self.blocked),
            "failed": str(self.failed),
            "followups_seen": str(self.followups_seen),
            "followups_posted": str(self.followups_posted),
            "notes": " | ".join(self.notes),
        }
