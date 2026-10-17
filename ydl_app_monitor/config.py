from dataclasses import dataclass
import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv


load_dotenv()


def _csv_env(name: str, default: str) -> List[str]:
    raw = os.getenv(name, default)
    return [part.strip() for part in raw.split(",") if part.strip()]


def _bool_env(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: str) -> int:
    return int(os.getenv(name, default).strip())


@dataclass
class Settings:
    appium_server_url: str = os.getenv("APPIUM_SERVER_URL", "http://127.0.0.1:4723")
    device_name: str = os.getenv("ANDROID_DEVICE_NAME", "Android")
    device_udid: str = os.getenv("ANDROID_UDID", "")
    adb_path: str = os.getenv("ADB_PATH", "adb")
    control_backend: str = os.getenv("CONTROL_BACKEND", "appium")
    page_source_backend: str = os.getenv("PAGE_SOURCE_BACKEND", "appium")
    app_package: str = os.getenv("YDL_APP_PACKAGE", "com.hzdh.ydl")
    app_activity: str = os.getenv("YDL_APP_ACTIVITY", "")
    app_startup_seconds: int = int(os.getenv("APP_STARTUP_SECONDS", "8"))
    command_timeout_seconds: int = int(os.getenv("COMMAND_TIMEOUT_SECONDS", "180"))

    check_interval_seconds: int = int(os.getenv("CHECK_INTERVAL_SECONDS", "60"))
    scroll_rounds: int = int(os.getenv("SCROLL_ROUNDS", "4"))
    post_min_chars: int = int(os.getenv("POST_MIN_CHARS", "18"))
    post_max_chars: int = int(os.getenv("POST_MAX_CHARS", "1200"))
    topic_keywords: List[str] = None
    target_tab_texts: List[str] = None
    home_tab_texts: List[str] = None
    home_section_title_texts: List[str] = None
    home_section_more_texts: List[str] = None
    search_trigger_texts: List[str] = None
    search_keyword: str = os.getenv("SEARCH_KEYWORD", "抑郁症")

    dry_run: bool = _bool_env("DRY_RUN", "true")
    enable_ai_reply: bool = _bool_env("ENABLE_AI_REPLY", "true")
    enable_real_post: bool = _bool_env("ENABLE_REAL_POST", "false")
    real_post_confirmation: str = os.getenv("REAL_POST_CONFIRMATION", "")
    enable_followup_reply: bool = _bool_env("ENABLE_FOLLOWUP_REPLY", "true")
    reply_mode: str = os.getenv("REPLY_MODE", "single_ai").strip().lower()
    max_posts_per_hour: int = _int_env("MAX_POSTS_PER_HOUR", "3")
    min_post_interval_seconds: int = _int_env("MIN_POST_INTERVAL_SECONDS", "120")
    max_followups_per_thread: int = _int_env("MAX_FOLLOWUPS_PER_THREAD", "3")
    self_display_name: str = os.getenv("SELF_DISPLAY_NAME", "")
    ai_disclosure_prefix: str = os.getenv("AI_DISCLOSURE_PREFIX", "[AI辅助回复]")
    ai_disclosure_suffix: str = os.getenv("AI_DISCLOSURE_SUFFIX", "[AI辅助回复]")

    experiment_account1_nickname: str = os.getenv("EXPERIMENT_ACCOUNT1_NICKNAME", "豆包陪伴AI小助手")
    experiment_account2_nickname: str = os.getenv("EXPERIMENT_ACCOUNT2_NICKNAME", "豆包")
    experiment_account3_nickname: str = os.getenv("EXPERIMENT_ACCOUNT3_NICKNAME", "暖心同行者")
    experiment_active_account_id: str = os.getenv("EXPERIMENT_ACTIVE_ACCOUNT_ID", "").strip()
    experiment_random_seed: str = os.getenv("EXPERIMENT_RANDOM_SEED", "ydl_identity_experiment")
    experiment_respect_reply_timing: bool = _bool_env("EXPERIMENT_RESPECT_REPLY_TIMING", "true")
    experiment_reply_window_seconds: int = _int_env("EXPERIMENT_REPLY_WINDOW_SECONDS", "43200")
    experiment_first_reply_min_seconds: int = _int_env("EXPERIMENT_FIRST_REPLY_MIN_SECONDS", "0")
    experiment_first_reply_max_seconds: int = _int_env("EXPERIMENT_FIRST_REPLY_MAX_SECONDS", "43200")
    experiment_second_reply_gap_min_seconds: int = _int_env("EXPERIMENT_SECOND_REPLY_GAP_MIN_SECONDS", "600")
    experiment_second_reply_gap_max_seconds: int = _int_env("EXPERIMENT_SECOND_REPLY_GAP_MAX_SECONDS", "21600")

    comment_entry_texts: List[str] = None
    comment_input_hints: List[str] = None
    send_button_texts: List[str] = None

    data_dir: Path = Path(os.getenv("DATA_DIR", "data"))
    posts_csv: Path = Path(os.getenv("POSTS_CSV", "data/ydl_posts.csv"))
    replies_csv: Path = Path(os.getenv("REPLIES_CSV", "data/ydl_replies.csv"))
    dialogues_csv: Path = Path(os.getenv("DIALOGUES_CSV", "data/ydl_dialogues.csv"))
    runs_csv: Path = Path(os.getenv("RUNS_CSV", "data/ydl_runs.csv"))
    dumps_dir: Path = Path(os.getenv("DUMPS_DIR", "data/dumps"))

    llm_api_base: str = os.getenv("LLM_API_BASE", "https://api.openai.com/v1")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    llm_timeout_seconds: int = _int_env("LLM_TIMEOUT_SECONDS", "60")
    llm_temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.4"))
    llm_max_tokens: int = _int_env("LLM_MAX_TOKENS", "180")

    def __post_init__(self) -> None:
        self.topic_keywords = _csv_env("TOPIC_KEYWORDS", "抑郁症,抑郁,情绪低落,不想活,自伤,自杀")
        self.target_tab_texts = _csv_env("TARGET_TAB_TEXTS", "心声,问答,树洞,社区,话题")
        self.home_tab_texts = _csv_env("HOME_TAB_TEXTS", "首页")
        self.home_section_title_texts = _csv_env("HOME_SECTION_TITLE_TEXTS", "心声·问答")
        self.home_section_more_texts = _csv_env("HOME_SECTION_MORE_TEXTS", "更多")
        self.search_trigger_texts = _csv_env("SEARCH_TRIGGER_TEXTS", "搜索,查找")
        self.comment_entry_texts = _csv_env("COMMENT_ENTRY_TEXTS", "评论,写评论,说点什么,我来说两句,回复")
        self.comment_input_hints = _csv_env("COMMENT_INPUT_HINTS", "评论,回复,说点什么,输入")
        self.send_button_texts = _csv_env("SEND_BUTTON_TEXTS", "发送,发布,评论,提交")

    @property
    def real_posting_allowed(self) -> bool:
        return (
            self.enable_real_post
            and not self.dry_run
            and self.real_post_confirmation == "I_UNDERSTAND_REAL_POSTING"
        )


def load_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.dumps_dir.mkdir(parents=True, exist_ok=True)
    return settings
