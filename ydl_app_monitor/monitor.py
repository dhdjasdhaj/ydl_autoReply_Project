import logging
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional

from .app_crawler import YdlAppCrawler
from .app_driver import YdlAppDriver, stable_hash
from .app_poster import YdlAppPoster
from .config import Settings
from .experiment import build_reply_plans, is_experiment_mode, strategy_for_id
from .llm_reply import LlmReplyGenerator
from .models import CycleStats, DialogueEvent, PostRecord, ReplyRecord, now_text
from .safety import SafetyGate
from .store import AppStore


log = logging.getLogger(__name__)


class MonitorRuntime:
    def __init__(self, settings: Settings) -> None:
        self.monitor_enabled = True
        self.ai_reply_enabled = settings.enable_ai_reply
        self.followup_enabled = settings.enable_followup_reply
        self.real_post_enabled = settings.real_posting_allowed
        self.reply_mode = settings.reply_mode
        self.kill_switch = False
        self.last_cycle_at = ""
        self.next_cycle_at = ""
        self.last_error = ""
        self.current_status = "idle"


class YdlMonitorService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.runtime = MonitorRuntime(settings)
        self.safety = SafetyGate(settings)
        self.app = YdlAppDriver(settings)
        self.crawler = YdlAppCrawler(settings, self.app, self.safety)
        self.poster = YdlAppPoster(settings, self.app, self.crawler, self.safety)
        self.generator = LlmReplyGenerator(settings, self.safety)
        self.store = AppStore(settings.posts_csv, settings.replies_csv, settings.dialogues_csv, settings.runs_csv)

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._trigger_event = threading.Event()
        self._lock = threading.Lock()
        self._last_stats = CycleStats()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._trigger_event.set()
        if self._thread is not None:
            self._thread.join(timeout=8)
        self.app.stop()

    def trigger_cycle(self) -> None:
        self._trigger_event.set()

    def dump_current_page(self) -> Dict[str, str]:
        self.app.start()
        xml_path, png_path = self.app.dump(self.settings.dumps_dir, "calibration")
        return {"xml": str(xml_path), "screenshot": str(png_path)}

    def get_last_stats(self) -> CycleStats:
        with self._lock:
            return self._last_stats

    def _run_forever(self) -> None:
        self.runtime.current_status = "running"
        try:
            self.app.start()
            while not self._stop_event.is_set():
                if self.runtime.kill_switch:
                    self.runtime.current_status = "kill_switch_active"
                    time.sleep(1)
                    continue
                if self.runtime.monitor_enabled:
                    self.run_once()
                sleep_until = time.time() + self.settings.check_interval_seconds
                self.runtime.next_cycle_at = now_text()
                while time.time() < sleep_until and not self._stop_event.is_set():
                    if self._trigger_event.wait(timeout=1):
                        self._trigger_event.clear()
                        break
        except Exception as exc:
            self.runtime.last_error = str(exc)
            self.runtime.current_status = "failed"
            log.exception("Monitor loop failed")
        finally:
            self.runtime.current_status = "stopped"

    def run_once(self) -> CycleStats:
        stats = CycleStats()
        self.runtime.current_status = "polling"
        self.runtime.last_cycle_at = now_text()
        try:
            posted_ids = self.store.handled_post_ids() if is_experiment_mode(self.runtime.reply_mode) else self.store.posted_post_ids()
            processed_ids = set()

            def process_visible_post(post: PostRecord) -> None:
                if not post.question_id and not self.crawler.enrich_post_question_id(post):
                    stats.failed += 1
                    stats.notes.append(f"missing real question_id for post candidate: {post.title[:24]}")
                    return
                status = self.store.upsert_post(post)
                if status == "new":
                    stats.new_posts += 1
                if status != "new" or post.post_id in posted_ids or post.post_id in processed_ids:
                    return
                processed_ids.add(post.post_id)
                self._process_post(post, stats)

            posts = self.crawler.poll(on_post=process_visible_post)
            stats.captured = len(posts)

            if self.runtime.ai_reply_enabled and is_experiment_mode(self.runtime.reply_mode):
                self._process_due_experiment_replies(stats)

            if self.runtime.followup_enabled and not is_experiment_mode(self.runtime.reply_mode):
                self._process_followups(stats)

        except Exception as exc:
            stats.failed += 1
            stats.notes.append(str(exc))
            self.runtime.last_error = str(exc)
            log.exception("Polling cycle failed")
            try:
                self.app.dump(self.settings.dumps_dir, "cycle_error")
            except Exception:
                pass

        self.store.append_run(stats.to_row())
        with self._lock:
            self._last_stats = stats
        self.runtime.current_status = "sleeping"
        return stats

    def _process_post(self, post: PostRecord, stats: CycleStats) -> None:
        if post.risk_level == "high":
            stats.blocked += 1
            self.store.update_post_status(post.post_id, "blocked_high_risk")
            return
        if not self.runtime.ai_reply_enabled:
            self.store.update_post_status(post.post_id, "captured_no_ai")
            return
        if is_experiment_mode(self.runtime.reply_mode):
            self._schedule_experiment_replies(post, stats)
            return

        try:
            reply_text = self.generator.generate_post_reply(post)
            stats.generated += 1
        except Exception as exc:
            stats.failed += 1
            self.store.append_reply(ReplyRecord(
                reply_id=stable_hash(f"{post.post_id}:llm_failed:{time.time()}"),
                post_id=post.post_id,
                reply_kind="post_reply",
                reply_content="",
                status="llm_failed",
                error=str(exc),
            ))
            return

        if self.runtime.kill_switch:
            self.store.update_post_status(post.post_id, "generated_stopped")
            return

        original_real_flag = self.settings.enable_real_post
        if not self.runtime.real_post_enabled:
            self.settings.enable_real_post = False
        try:
            result = self.poster.post_reply(post, reply_text, reply_kind="post_reply")
        finally:
            self.settings.enable_real_post = original_real_flag

        self.store.append_reply(ReplyRecord(
            reply_id=result["reply_id"],
            post_id=post.post_id,
            reply_kind="post_reply",
            reply_content=reply_text,
            status=result["status"],
            error=result.get("error", ""),
        ))
        self.store.append_dialogue(DialogueEvent(
            conversation_id=post.post_id,
            post_id=post.post_id,
            role="assistant",
            content=reply_text,
            parent_reply_id=result["reply_id"],
        ))

        if result["status"] in {"sent", "dry_run"}:
            stats.posted += 1
            self.store.update_post_status(post.post_id, result["status"])
        elif result["status"] == "blocked":
            stats.blocked += 1
            self.store.update_post_status(post.post_id, "blocked")
        else:
            stats.failed += 1
            self.store.update_post_status(post.post_id, "posting_failed")

    def _schedule_experiment_replies(self, post: PostRecord, stats: CycleStats) -> None:
        if self.store.has_experiment_replies(post.post_id):
            return

        question_id = self.store.question_id_for_post(post.post_id)
        plans = build_reply_plans(self.settings, post.post_id, question_id)
        generated = 0

        for plan in plans:
            strategy = plan.strategy
            try:
                reply_text = self.generator.generate_strategy_reply(post, strategy)
                status = "scheduled"
                error = ""
                generated += 1
            except Exception as exc:
                reply_text = ""
                status = "llm_failed"
                error = str(exc)
                stats.failed += 1

            self.store.append_reply(ReplyRecord(
                reply_id=stable_hash(f"{post.post_id}:experiment:{strategy.strategy_id}:{plan.reply_order}"),
                post_id=post.post_id,
                reply_kind="experiment_reply",
                account_id=strategy.account_id,
                account_nickname=strategy.account_nickname,
                strategy_id=str(strategy.strategy_id),
                strategy_name=strategy.strategy_name,
                experiment_group=strategy.experiment_group,
                reply_order=str(plan.reply_order),
                planned_send_at=plan.planned_send_at,
                reply_content=reply_text,
                status=status,
                error=error,
            ))

        stats.generated += generated
        self.store.update_post_status(post.post_id, "experiment_scheduled")

    def _process_due_experiment_replies(self, stats: CycleStats) -> None:
        for row in self.store.due_experiment_replies(datetime.now()):
            if self.runtime.kill_switch:
                return
            active_account_id = self.settings.experiment_active_account_id
            if self.runtime.real_post_enabled and not active_account_id:
                stats.notes.append("EXPERIMENT_ACTIVE_ACCOUNT_ID is required for real experiment posting")
                return
            if self.runtime.real_post_enabled and row.get("account_id") != active_account_id:
                continue

            post_row = self.store.post_row(row.get("post_id", ""))
            if not post_row:
                self.store.update_reply_status(row.get("reply_id", ""), "failed", "post row not found")
                stats.failed += 1
                continue

            post = PostRecord(
                question_id=post_row.get("question_id", ""),
                post_id=post_row.get("post_id", ""),
                title=post_row.get("title", ""),
                content=post_row.get("content", ""),
                source=post_row.get("source", "app"),
                risk_level=post_row.get("risk_level", "unknown"),
                risk_reason=post_row.get("risk_reason", ""),
                keyword_hits=post_row.get("keyword_hits", ""),
                tap_text=post_row.get("tap_text", ""),
            )

            try:
                strategy = strategy_for_id(self.settings, int(row.get("strategy_id") or 0))
            except ValueError as exc:
                self.store.update_reply_status(row.get("reply_id", ""), "failed", str(exc))
                stats.failed += 1
                continue

            original_real_flag = self.settings.enable_real_post
            if not self.runtime.real_post_enabled:
                self.settings.enable_real_post = False
            try:
                result = self.poster.post_reply(
                    post,
                    row.get("reply_content", ""),
                    reply_kind="experiment_reply",
                    require_ai_disclosure=strategy.text_ai_disclosure,
                    disclosure_text=self.settings.ai_disclosure_suffix,
                )
            finally:
                self.settings.enable_real_post = original_real_flag

            self.store.update_reply_status(
                row.get("reply_id", ""),
                result["status"],
                result.get("error", ""),
            )
            self.store.append_dialogue(DialogueEvent(
                conversation_id=post.post_id,
                post_id=post.post_id,
                role=row.get("account_id", "assistant"),
                content=row.get("reply_content", ""),
                parent_reply_id=row.get("reply_id", ""),
            ))

            if result["status"] in {"sent", "dry_run"}:
                stats.posted += 1
            elif result["status"] == "blocked":
                stats.blocked += 1
            else:
                stats.failed += 1

            if self.store.experiment_replies_complete(post.post_id):
                self.store.update_post_status(post.post_id, "experiment_complete")

    def _process_followups(self, stats: CycleStats) -> None:
        replied_targets = self.store.replied_target_ids()
        reply_rows = self.store.replies.read_rows()
        post_rows = {row.get("post_id"): row for row in self.store.posts.read_rows()}

        for reply_row in reply_rows:
            if reply_row.get("reply_kind") != "post_reply":
                continue
            if reply_row.get("status") not in {"sent", "dry_run"}:
                continue

            post_id = reply_row.get("post_id", "")
            post_row = post_rows.get(post_id)
            if not post_row:
                continue

            followup_count = sum(
                1 for row in reply_rows
                if row.get("reply_kind") == "followup_reply" and row.get("post_id") == post_id
            )
            if followup_count >= self.settings.max_followups_per_thread:
                continue

            post = PostRecord(
                post_id=post_id,
                title=post_row.get("title", ""),
                content=post_row.get("content", ""),
                source=post_row.get("source", "app"),
                risk_level=post_row.get("risk_level", "unknown"),
                risk_reason=post_row.get("risk_reason", ""),
                keyword_hits=post_row.get("keyword_hits", ""),
                tap_text=post_row.get("tap_text", ""),
            )

            known_texts = [row.get("reply_content", "") for row in reply_rows if row.get("post_id") == post_id]
            events = self.poster.extract_visible_comment_events(post, known_texts)
            for event in events:
                event_id = event["event_id"]
                if event_id in replied_targets:
                    continue
                stats.followups_seen += 1
                risk = self.safety.classify(event["content"])
                if risk.level == "high":
                    stats.blocked += 1
                    self.store.append_dialogue(DialogueEvent(
                        conversation_id=post_id,
                        post_id=post_id,
                        role="user_high_risk",
                        content=event["content"],
                        parent_reply_id=event_id,
                    ))
                    continue
                try:
                    reply_text = self.generator.generate_followup_reply(post, event)
                    result = self.poster.post_reply(post, reply_text, reply_kind="followup_reply")
                except Exception as exc:
                    stats.failed += 1
                    self.store.append_reply(ReplyRecord(
                        reply_id=stable_hash(f"{post_id}:followup_failed:{event_id}"),
                        post_id=post_id,
                        reply_kind="followup_reply",
                        reply_content="",
                        status="failed",
                        error=str(exc),
                        parent_reply_id=event_id,
                        target_content=event["content"],
                    ))
                    continue

                self.store.append_reply(ReplyRecord(
                    reply_id=result["reply_id"],
                    post_id=post_id,
                    reply_kind="followup_reply",
                    reply_content=reply_text,
                    status=result["status"],
                    error=result.get("error", ""),
                    parent_reply_id=event_id,
                    target_content=event["content"],
                ))
                self.store.append_dialogue(DialogueEvent(
                    conversation_id=post_id,
                    post_id=post_id,
                    role="user",
                    content=event["content"],
                    parent_reply_id=event_id,
                ))
                self.store.append_dialogue(DialogueEvent(
                    conversation_id=post_id,
                    post_id=post_id,
                    role="assistant",
                    content=reply_text,
                    parent_reply_id=result["reply_id"],
                ))
                if result["status"] in {"sent", "dry_run"}:
                    stats.followups_posted += 1
