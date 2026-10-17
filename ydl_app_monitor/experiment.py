import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List

from .config import Settings


EXPERIMENT_REPLY_KIND = "experiment_reply"
EXPERIMENT_MODES = {"identity_experiment", "experiment"}


@dataclass(frozen=True)
class ReplyStrategy:
    strategy_id: int
    strategy_name: str
    account_id: str
    account_nickname: str
    experiment_group: str
    prompt_profile: str
    is_human_baseline: bool = False
    text_ai_disclosure: bool = False


@dataclass(frozen=True)
class ReplyPlan:
    strategy: ReplyStrategy
    reply_order: int
    planned_send_at: str


def is_experiment_mode(mode: str) -> bool:
    return (mode or "").strip().lower() in EXPERIMENT_MODES


def strategy_for_id(settings: Settings, strategy_id: int) -> ReplyStrategy:
    if strategy_id == 0:
        return ReplyStrategy(
            strategy_id=0,
            strategy_name="策略0-账号1-结尾AI辅助回复标签",
            account_id="account1",
            account_nickname=settings.experiment_account1_nickname,
            experiment_group="账号1/豆包陪伴AI小助手/文本结尾AI标签",
            prompt_profile="生成一条陪伴式评论，正文不要自称AI，末尾会由程序统一追加AI辅助回复标签。",
            text_ai_disclosure=True,
        )
    if strategy_id == 1:
        return ReplyStrategy(
            strategy_id=1,
            strategy_name="策略1-账号1-仅昵称含AI",
            account_id="account1",
            account_nickname=settings.experiment_account1_nickname,
            experiment_group="账号1/豆包陪伴AI小助手/文本无AI提示",
            prompt_profile="生成一条陪伴式评论，正文和结尾都不要出现任何AI、机器人、生成、辅助回复等身份提示。",
        )
    if strategy_id == 2:
        return ReplyStrategy(
            strategy_id=2,
            strategy_name="策略2-账号2-普通豆包昵称",
            account_id="account2",
            account_nickname=settings.experiment_account2_nickname,
            experiment_group="账号2/豆包/文本无AI提示",
            prompt_profile="生成一条陪伴式评论，正文和结尾都不要出现任何AI、助手、机器人、生成、辅助回复等提示。",
        )
    if strategy_id == 3:
        return ReplyStrategy(
            strategy_id=3,
            strategy_name="策略3-模拟真人回复",
            account_id="account3",
            account_nickname=settings.experiment_account3_nickname,
            experiment_group="真人回复基准",
            prompt_profile="模拟普通真人用户的自然评论，文本和账号昵称都不使用任何AI相关提示。",
            is_human_baseline=True,
        )
    raise ValueError(f"unsupported reply strategy: {strategy_id}")


def strategy_id_for_question(question_id: int) -> int:
    return question_id % 4


def aigc_strategy_id_for_question(question_id: int) -> int:
    return strategy_id_for_question(question_id)


def build_reply_plans(settings: Settings, post_id: str, question_id: int) -> List[ReplyPlan]:
    strategy = strategy_for_id(settings, strategy_id_for_question(question_id))

    seed = f"{settings.experiment_random_seed}:{post_id}:{question_id}"
    rng = random.Random(seed)

    now = datetime.now()
    send_offset = rng.randint(
        settings.experiment_first_reply_min_seconds,
        settings.experiment_first_reply_max_seconds,
    )
    send_offset = min(send_offset, settings.experiment_reply_window_seconds)

    if settings.experiment_respect_reply_timing:
        planned_time = now + timedelta(seconds=send_offset)
    else:
        planned_time = now

    return [
        ReplyPlan(
            strategy=strategy,
            reply_order=0,
            planned_send_at=planned_time.strftime("%Y-%m-%d %H:%M:%S"),
        )
    ]
