import logging
import time
from typing import Dict, List, Tuple

from .app_crawler import YdlAppCrawler
from .app_driver import YdlAppDriver, center_of, stable_hash
from .config import Settings
from .models import PostRecord
from .safety import SafetyGate


log = logging.getLogger(__name__)


LOGIN_OR_RATE_LIMIT_MARKERS = ("登录", "验证码", "频繁", "稍后", "异常", "风险")


class YdlAppPoster:
    def __init__(self, settings: Settings, app: YdlAppDriver, crawler: YdlAppCrawler, safety: SafetyGate) -> None:
        self.settings = settings
        self.app = app
        self.crawler = crawler
        self.safety = safety

    def post_reply(
        self,
        post: PostRecord,
        reply_content: str,
        reply_kind: str = "post_reply",
        require_ai_disclosure: bool = True,
        disclosure_text: str = "",
    ) -> Dict[str, str]:
        result = {
            "post_id": post.post_id,
            "reply_kind": reply_kind,
            "reply_content": reply_content,
            "status": "dry_run" if self.settings.dry_run else "sent",
            "error": "",
            "reply_id": stable_hash(f"{post.post_id}:{reply_kind}:{reply_content}"),
        }

        ok, reason = self.safety.validate_reply(
            reply_content,
            require_ai_disclosure=require_ai_disclosure,
            disclosure_text=disclosure_text,
        )
        if not ok:
            result["status"] = "blocked"
            result["error"] = reason
            return result

        can_post, reason = self.safety.can_auto_post(post.risk_level)
        if not can_post:
            if self.settings.dry_run:
                result["status"] = "dry_run"
                return result
            result["status"] = "blocked"
            result["error"] = reason
            return result

        if not self.crawler.open_post(post):
            result["status"] = "failed"
            result["error"] = "could not open post from current feed"
            return result

        try:
            self._send_on_current_post(reply_content, disclosure_text=disclosure_text)
            if self._looks_blocked_or_login_required():
                result["status"] = "failed"
                result["error"] = "login, captcha, or rate-limit marker detected after sending"
            else:
                self.safety.mark_posted()
        except Exception as exc:
            log.exception("Post reply failed")
            result["status"] = "failed"
            result["error"] = str(exc)
        finally:
            self.app.back()

        return result

    def extract_visible_comment_events(self, post: PostRecord, known_texts: List[str]) -> List[Dict[str, str]]:
        if not self.crawler.open_post(post):
            return []
        try:
            known = set(known_texts)
            events = []
            comment_top = 0
            for node in self.app.nodes():
                if not node.bounds:
                    continue
                if node.resource_id.endswith("id/tv_comment_count") or node.label.startswith("评论 "):
                    point = center_of(node.bounds)
                    if point is not None:
                        comment_top = max(comment_top, point[1])

            for node in self.app.nodes():
                text = node.label.strip()
                if not text or len(text) < 8 or not node.bounds:
                    continue
                if "content" not in node.resource_id:
                    continue
                point = center_of(node.bounds)
                if point is None or point[1] <= comment_top:
                    continue
                if text in known:
                    continue
                if self.settings.ai_disclosure_prefix in text:
                    continue
                if self.settings.self_display_name and self.settings.self_display_name in text:
                    continue
                if text == post.content:
                    continue
                event_id = stable_hash(f"{post.post_id}:{text}")
                events.append({
                    "event_id": event_id,
                    "post_id": post.post_id,
                    "user_name": "",
                    "content": text[:1000],
                })
            return events
        finally:
            self.app.back()

    def _send_on_current_post(self, reply_content: str, disclosure_text: str = "") -> None:
        if not self.app.click_first_text(self.settings.comment_entry_texts, partial=True):
            log.info("Comment entry text not found; trying direct input search")

        input_box = None
        for _ in range(5):
            input_box = self.app.find_input(self.settings.comment_input_hints)
            if input_box is not None:
                break
            time.sleep(0.8)
        if input_box is None:
            raise RuntimeError("comment input was not found")

        self.app.set_text(input_box, reply_content)
        time.sleep(0.8)
        visible_text = "\n".join(self.app.visible_texts(min_len=1))
        expected = disclosure_text if disclosure_text and disclosure_text in reply_content else reply_content[:8]
        if expected and expected not in visible_text:
            raise RuntimeError("reply text was not visible as decoded Chinese after input")
        if not self.app.click_first_text(self.settings.send_button_texts, partial=True):
            raise RuntimeError("send button was not found")
        time.sleep(2.5)

    def _looks_blocked_or_login_required(self) -> bool:
        text = "\n".join(self.app.visible_texts(min_len=2))
        return any(marker in text for marker in LOGIN_OR_RATE_LIMIT_MARKERS)
