import logging
import time
from typing import Callable, Dict, Iterable, List, Optional, Set

from .app_driver import YdlAppDriver, stable_hash
from .config import Settings
from .models import PostRecord, UiNode
from .question_id import parse_question_id_from_share_text
from .safety import SafetyGate


log = logging.getLogger(__name__)


PostCallback = Callable[[PostRecord], None]


class YdlAppCrawler:
    def __init__(self, settings: Settings, app: YdlAppDriver, safety: SafetyGate) -> None:
        self.settings = settings
        self.app = app
        self.safety = safety
        self._seen_this_cycle: Set[str] = set()
        self._current_source = "app"

    def poll(self, on_post: Optional[PostCallback] = None) -> List[PostRecord]:
        self.app.start()
        self._seen_this_cycle = set()

        posts: List[PostRecord] = []
        target_tabs = self.settings.target_tab_texts or [""]
        for tab_text in target_tabs:
            self.app.activate_app()
            if not self._enter_home_qa_section():
                continue
            if tab_text:
                if not self._enter_target_tab(tab_text):
                    continue
                self._current_source = tab_text
            posts.extend(self._collect_current_page(on_post))

        return posts

    def _collect_current_page(self, on_post: Optional[PostCallback] = None) -> List[PostRecord]:
        posts: List[PostRecord] = []
        for _ in range(max(self.settings.scroll_rounds, 1)):
            for candidate in self._candidate_nodes():
                post = self._build_post(candidate)
                if post.post_id in self._seen_this_cycle:
                    continue
                self._seen_this_cycle.add(post.post_id)
                posts.append(post)
                if on_post:
                    on_post(post)
            self.app.scroll_down()
        return posts

    def _enter_home_qa_section(self) -> bool:
        for attempt in range(2):
            self.app.click_first_text(self.settings.home_tab_texts, partial=False)
            if self._click_home_qa_more():
                return True

            for _ in range(3):
                self.app.scroll_down(amount=0.7)
                if self._click_home_qa_more():
                    return True

            if attempt == 0:
                self.app.back()

        log.warning("Could not find the home 心声·问答 更多 entry")
        return False

    def _click_home_qa_more(self) -> bool:
        if self.app.click_text_near_text(
            self.settings.home_section_title_texts,
            self.settings.home_section_more_texts,
            vertical_tolerance=180,
            partial=True,
        ):
            log.info("Clicked home 心声·问答 更多 entry")
            return True

        visible = "\n".join(self.app.visible_texts(1))
        if any(text in visible for text in self.settings.home_section_title_texts):
            if self.app.click_first_text(self.settings.home_section_more_texts, partial=True):
                log.info("Clicked fallback 更多 entry while 心声·问答 was visible")
                return True
        return False

    def _enter_target_tab(self, tab_text: str) -> bool:
        if self.app.click_first_text([tab_text], partial=False):
            log.info("Clicked target tab: %s", tab_text)
            return True
        if self.app.click_first_text([tab_text], partial=True):
            log.info("Clicked target tab candidate: %s", tab_text)
            return True
        return False

    def _candidate_nodes(self) -> Iterable[UiNode]:
        visible_context = " ".join(self.app.visible_texts(1)[:50])
        targeted_search_page = bool(
            self.settings.search_keyword and self.settings.search_keyword in visible_context
        )
        for node in self.app.nodes():
            label = node.label.strip()
            if not self.safety.should_keep_text(label):
                continue
            if len(label) > self.settings.post_max_chars:
                label = label[: self.settings.post_max_chars]
            if self.settings.topic_keywords and not any(keyword in label for keyword in self.settings.topic_keywords):
                # Keep a small amount of non-keyword candidates only when the page is already a targeted search result.
                if not targeted_search_page:
                    continue
            yield UiNode(
                text=label,
                content_desc=node.content_desc,
                hint=node.hint,
                resource_id=node.resource_id,
                class_name=node.class_name,
                clickable=node.clickable,
                enabled=node.enabled,
                bounds=node.bounds,
            )

    def _build_post(self, node: UiNode) -> PostRecord:
        text = self.safety.scrub_pii(node.label)
        title = text[:60]
        risk = self.safety.classify(text)
        return PostRecord(
            post_id=stable_hash(text),
            title=title,
            content=text,
            source=self._current_source,
            risk_level=risk.level,
            risk_reason=risk.reason,
            keyword_hits=",".join(risk.keyword_hits),
            status="captured",
            tap_text=node.label[:80],
        )

    def enrich_post_question_id(self, post: PostRecord) -> bool:
        if post.question_id:
            return True
        if not self.open_post(post):
            return False

        try:
            question_id = self._question_id_from_current_post_share()
            if not question_id:
                return False
            post.question_id = question_id
            post.post_id = f"ask:{question_id}"
            return True
        finally:
            self.app.back()

    def _question_id_from_current_post_share(self) -> str:
        visible_text = "\n".join(self.app.visible_texts(min_len=1))
        question_id = parse_question_id_from_share_text(visible_text)
        if question_id:
            return question_id

        if not self.app.click_first_text(["分享"], partial=True):
            return ""
        time.sleep(1.0)

        for copy_text in ("复制链接", "复制", "链接"):
            if self.app.click_first_text([copy_text], partial=True):
                time.sleep(1.0)
                clipboard = self.app.clipboard_text()
                question_id = parse_question_id_from_share_text(clipboard)
                if question_id:
                    return question_id
                break

        visible_text = "\n".join(self.app.visible_texts(min_len=1))
        return parse_question_id_from_share_text(visible_text) or ""

    def open_post(self, post: PostRecord) -> bool:
        if self._click_post_from_current_page(post):
            return True

        if post.source in self.settings.target_tab_texts:
            self.app.activate_app()
            if self._enter_home_qa_section():
                self._enter_target_tab(post.source)
                for _ in range(max(self.settings.scroll_rounds, 1)):
                    if self._click_post_from_current_page(post):
                        return True
                    self.app.scroll_down()
        return False

    def _click_post_from_current_page(self, post: PostRecord) -> bool:
        if post.tap_text:
            if self.app.click_first_text([post.tap_text], partial=False):
                return True
            if self.app.click_first_text([post.tap_text[:24]], partial=True):
                return True
        return self.app.click_first_text([post.title[:24]], partial=True)
