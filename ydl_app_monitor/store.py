import csv
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Set

from .models import DialogueEvent, PostRecord, ReplyRecord


class CsvTable:
    def __init__(self, path: Path, fieldnames: List[str]) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fieldnames = fieldnames
        self._lock = threading.Lock()
        if not self.path.exists():
            self._write_rows([])

    def read_rows(self) -> List[Dict[str, str]]:
        with self._lock:
            if not self.path.exists() or self.path.stat().st_size == 0:
                return []
            with self.path.open("r", newline="", encoding="utf-8-sig") as f:
                return list(csv.DictReader(f))

    def append_row(self, row: Dict[str, str]) -> None:
        with self._lock:
            self._ensure_header()
            with self.path.open("a", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=self.fieldnames, extrasaction="ignore")
                writer.writerow(row)

    def rewrite_rows(self, rows: List[Dict[str, str]]) -> None:
        with self._lock:
            self._write_rows(rows)

    def _ensure_header(self) -> None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            self._write_rows([])
            return
        with self.path.open("r", newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            header = next(reader, [])
        if header == self.fieldnames:
            return
        rows = []
        with self.path.open("r", newline="", encoding="utf-8-sig") as f:
            for old_row in csv.DictReader(f):
                rows.append({field: old_row.get(field, "") for field in self.fieldnames})
        self._write_rows(rows)

    def _write_rows(self, rows: List[Dict[str, str]]) -> None:
        with self.path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=self.fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)


class AppStore:
    def __init__(self, posts_csv: Path, replies_csv: Path, dialogues_csv: Path, runs_csv: Path) -> None:
        self.posts = CsvTable(posts_csv, [
            "question_id", "post_id", "title", "content", "source", "risk_level", "risk_reason",
            "keyword_hits", "crawl_time", "status", "tap_text",
        ])
        self.replies = CsvTable(replies_csv, [
            "reply_id", "post_id", "reply_kind", "account_id", "account_nickname",
            "strategy_id", "strategy_name", "experiment_group", "reply_order",
            "planned_send_at", "reply_content", "status", "error",
            "parent_reply_id", "target_user", "target_content", "created_at",
        ])
        self.dialogues = CsvTable(dialogues_csv, [
            "conversation_id", "post_id", "role", "content", "event_time", "parent_reply_id",
        ])
        self.runs = CsvTable(runs_csv, [
            "run_time", "captured", "new_posts", "generated", "posted", "blocked",
            "failed", "followups_seen", "followups_posted", "notes",
        ])

    def upsert_post(self, post: PostRecord) -> str:
        rows = self.posts.read_rows()
        for index, row in enumerate(rows):
            if row.get("post_id") != post.post_id:
                continue
            if row.get("content") != post.content or row.get("status") != post.status:
                question_id = post.question_id or row.get("question_id") or str(index)
                merged = row.copy()
                merged.update(post.to_row())
                merged["question_id"] = question_id
                rows[index] = merged
                self.posts.rewrite_rows(rows)
                return "updated"
            return "unchanged"
        row = post.to_row()
        row["question_id"] = post.question_id or str(len(rows))
        rows.append(row)
        self.posts.rewrite_rows(rows)
        return "new"

    def question_id_for_post(self, post_id: str) -> int:
        rows = self.posts.read_rows()
        changed = False
        for index, row in enumerate(rows):
            if not row.get("question_id"):
                row["question_id"] = str(index)
                changed = True
            if row.get("post_id") == post_id:
                if changed:
                    self.posts.rewrite_rows(rows)
                return int(row.get("question_id") or index)
        return len(rows)

    def update_post_status(self, post_id: str, status: str) -> None:
        rows = self.posts.read_rows()
        changed = False
        for row in rows:
            if row.get("post_id") == post_id:
                row["status"] = status
                changed = True
        if changed:
            self.posts.rewrite_rows(rows)

    def append_reply(self, reply: ReplyRecord) -> None:
        self.replies.append_row(reply.to_row())

    def update_reply_status(self, reply_id: str, status: str, error: str = "") -> None:
        rows = self.replies.read_rows()
        changed = False
        for row in rows:
            if row.get("reply_id") != reply_id:
                continue
            row["status"] = status
            row["error"] = error
            changed = True
        if changed:
            self.replies.rewrite_rows(rows)

    def append_dialogue(self, event: DialogueEvent) -> None:
        self.dialogues.append_row(event.to_row())

    def append_run(self, row: Dict[str, str]) -> None:
        self.runs.append_row(row)

    def posted_post_ids(self) -> Set[str]:
        result = set()
        for row in self.replies.read_rows():
            if row.get("reply_kind") == "post_reply" and row.get("status") in {"sent", "dry_run"}:
                result.add(row.get("post_id", ""))
        return {item for item in result if item}

    def handled_post_ids(self) -> Set[str]:
        result = self.posted_post_ids()
        for row in self.replies.read_rows():
            if row.get("reply_kind") == "experiment_reply" and row.get("status") in {
                "scheduled", "sent", "dry_run", "blocked", "failed", "llm_failed",
            }:
                result.add(row.get("post_id", ""))
        return {item for item in result if item}

    def has_experiment_replies(self, post_id: str) -> bool:
        return any(
            row.get("post_id") == post_id and row.get("reply_kind") == "experiment_reply"
            for row in self.replies.read_rows()
        )

    def due_experiment_replies(self, now: datetime) -> List[Dict[str, str]]:
        due = []
        for row in self.replies.read_rows():
            if row.get("reply_kind") != "experiment_reply" or row.get("status") != "scheduled":
                continue
            planned = row.get("planned_send_at", "")
            try:
                planned_at = datetime.strptime(planned, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                planned_at = now
            if planned_at <= now:
                due.append(row)
        due.sort(key=lambda item: (item.get("planned_send_at", ""), item.get("reply_order", "")))
        return due

    def post_row(self, post_id: str) -> Dict[str, str]:
        for row in self.posts.read_rows():
            if row.get("post_id") == post_id:
                return row
        return {}

    def experiment_replies_complete(self, post_id: str) -> bool:
        rows = [
            row for row in self.replies.read_rows()
            if row.get("post_id") == post_id and row.get("reply_kind") == "experiment_reply"
        ]
        if not rows:
            return False
        return all(row.get("status") in {"sent", "dry_run", "blocked", "failed", "llm_failed"} for row in rows)

    def replied_target_ids(self) -> Set[str]:
        result = set()
        for row in self.replies.read_rows():
            if row.get("reply_kind") == "followup_reply" and row.get("parent_reply_id"):
                result.add(row["parent_reply_id"])
        return result
