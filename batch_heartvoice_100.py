import argparse
import logging
import sys
import time
from pathlib import Path

from ydl_app_monitor.app_crawler import YdlAppCrawler
from ydl_app_monitor.app_driver import YdlAppDriver
from ydl_app_monitor.config import load_settings
from ydl_app_monitor.safety import SafetyGate
from ydl_app_monitor.store import AppStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect heart-voice posts from the app without generating or posting replies."
    )
    parser.add_argument("--target", type=int, default=100, help="number of new posts to collect")
    parser.add_argument("--tab", default="心声", help="target tab text to crawl")
    parser.add_argument("--max-cycles", type=int, default=20, help="maximum crawl cycles")
    parser.add_argument("--sleep", type=float, default=2.0, help="seconds to wait between cycles")
    parser.add_argument(
        "--scroll-rounds",
        type=int,
        default=0,
        help="override SCROLL_ROUNDS from .env when greater than 0",
    )
    return parser.parse_args()


def configure_logging() -> None:
    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler("logs/batch_heartvoice_100.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    args = parse_args()
    configure_logging()

    settings = load_settings()
    settings.target_tab_texts = [args.tab]
    if args.scroll_rounds > 0:
        settings.scroll_rounds = args.scroll_rounds

    app = YdlAppDriver(settings)
    safety = SafetyGate(settings)
    crawler = YdlAppCrawler(settings, app, safety)
    store = AppStore(settings.posts_csv, settings.replies_csv, settings.dialogues_csv, settings.runs_csv)

    new_count = 0
    seen_this_run = set()

    try:
        for cycle in range(1, args.max_cycles + 1):
            print(f"Cycle {cycle}/{args.max_cycles}: crawling {args.tab}...")
            cycle_new = 0
            posts = crawler.poll()
            for post in posts:
                if not post.question_id and not crawler.enrich_post_question_id(post):
                    print(f"[skip] could not read real question_id: {post.title}")
                    continue
                if post.post_id in seen_this_run:
                    continue
                seen_this_run.add(post.post_id)
                status = store.upsert_post(post)
                if status == "new":
                    new_count += 1
                    cycle_new += 1
                    print(f"[{new_count}/{args.target}] {post.title}")
                    if new_count >= args.target:
                        print(f"Done. Collected {new_count} new posts into {settings.posts_csv}.")
                        return

            print(f"Cycle {cycle} finished: {len(posts)} visible candidates, {cycle_new} new posts.")
            if cycle < args.max_cycles:
                time.sleep(max(args.sleep, 0))

        print(
            f"Stopped after {args.max_cycles} cycles. "
            f"Collected {new_count} new posts into {settings.posts_csv}."
        )
    finally:
        app.stop()


if __name__ == "__main__":
    main()
