import logging
from pathlib import Path

import pandas as pd
import streamlit as st

from ydl_app_monitor.config import load_settings
from ydl_app_monitor.experiment import is_experiment_mode
from ydl_app_monitor.monitor import YdlMonitorService


Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/ydl_app_monitor_dashboard.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)


@st.cache_resource
def get_service() -> YdlMonitorService:
    return YdlMonitorService(load_settings())


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except Exception as exc:
        st.warning(f"读取失败: {path} ({exc})")
        return pd.DataFrame()


def main() -> None:
    st.set_page_config(page_title="壹点灵 App AI 回复控制台", layout="wide")
    service = get_service()
    settings = service.settings
    runtime = service.runtime

    st.title("壹点灵 App AI 回复控制台")

    with st.sidebar:
        st.header("运行控制")
        col_a, col_b = st.columns(2)
        if col_a.button("启动监控", use_container_width=True):
            service.start()
        if col_b.button("停止", use_container_width=True):
            service.stop()

        if st.button("立即执行一轮", use_container_width=True):
            if service.running:
                service.trigger_cycle()
            else:
                with st.spinner("执行单轮监控中"):
                    service.run_once()

        if st.button("页面校准 Dump", use_container_width=True):
            with st.spinner("正在连接 Appium 并保存页面"):
                try:
                    dump = service.dump_current_page()
                    st.success(f"XML: {dump['xml']}")
                    st.success(f"Screenshot: {dump['screenshot']}")
                except Exception as exc:
                    st.error(str(exc))

        st.divider()
        st.header("开关")
        mode_labels = {
            "single_ai": "单条 AI 回复",
            "identity_experiment": "AI 身份披露对照实验",
        }
        mode_values = list(mode_labels.keys())
        current_mode = runtime.reply_mode if runtime.reply_mode in mode_values else "single_ai"
        selected_mode = st.selectbox(
            "回复模式",
            mode_values,
            index=mode_values.index(current_mode),
            format_func=lambda value: mode_labels[value],
        )
        runtime.reply_mode = selected_mode

        runtime.monitor_enabled = st.toggle("监控新帖", value=runtime.monitor_enabled)
        runtime.ai_reply_enabled = st.toggle("生成 AI 回复", value=runtime.ai_reply_enabled)
        runtime.followup_enabled = st.toggle(
            "监控并回复用户追评",
            value=runtime.followup_enabled,
            disabled=is_experiment_mode(runtime.reply_mode),
            help="实验模式固定为每个问题一条策略回复，不自动处理追评。",
        )

        real_enabled = st.toggle(
            "真实点击发布",
            value=runtime.real_post_enabled,
            disabled=not settings.real_posting_allowed,
            help="需要 DRY_RUN=false、ENABLE_REAL_POST=true、REAL_POST_CONFIRMATION=I_UNDERSTAND_REAL_POSTING",
        )
        runtime.real_post_enabled = bool(real_enabled and settings.real_posting_allowed)

        runtime.kill_switch = st.toggle("急停", value=runtime.kill_switch)

        st.divider()
        st.header("当前配置")
        st.write(f"Dry run: `{settings.dry_run}`")
        st.write(f"Real posting allowed: `{settings.real_posting_allowed}`")
        st.write(f"Package: `{settings.app_package}`")
        st.write(f"Reply mode: `{runtime.reply_mode}`")
        st.write(f"Interval: `{settings.check_interval_seconds}s`")
        st.write(f"Max posts/hour: `{settings.max_posts_per_hour}`")
        if is_experiment_mode(runtime.reply_mode):
            st.write(f"Active account id: `{settings.experiment_active_account_id or '未设置'}`")
            st.write(f"Account 1: `{settings.experiment_account1_nickname}`")
            st.write(f"Account 2: `{settings.experiment_account2_nickname}`")
            st.write(f"Account 3: `{settings.experiment_account3_nickname}`")
            st.write("Strategy rotation: `question_id % 4 -> strategy 0/1/2/3`")
            st.write(f"Timing respected: `{settings.experiment_respect_reply_timing}`")

    stats = service.get_last_stats()
    status_cols = st.columns(6)
    status_cols[0].metric("线程", "运行中" if service.running else "未运行")
    status_cols[1].metric("状态", runtime.current_status)
    status_cols[2].metric("本轮捕获", stats.captured)
    status_cols[3].metric("新帖", stats.new_posts)
    status_cols[4].metric("已生成", stats.generated)
    status_cols[5].metric("已发布/干运行", stats.posted)

    if runtime.last_error:
        st.error(runtime.last_error)
    if not settings.real_posting_allowed:
        st.info("真实发布未启用。需要在 .env 中设置 DRY_RUN=false、ENABLE_REAL_POST=true、REAL_POST_CONFIRMATION=I_UNDERSTAND_REAL_POSTING。")
    if is_experiment_mode(runtime.reply_mode):
        st.info("实验模式会按 question_id % 4 将新问题分到策略0/1/2/3，每个问题只生成一条计划回复，并记录账号、策略与计划时间；计划时间默认落在发现问题后的12小时内。")
        if settings.real_posting_allowed and not settings.experiment_active_account_id:
            st.warning("真实发布实验回复前，请在 .env 设置 EXPERIMENT_ACTIVE_ACCOUNT_ID=account1、account2 或 account3，确保当前手机登录账号与计划账号一致。")

    tabs = st.tabs(["帖子", "回复", "对话", "运行记录", "配置校准"])

    with tabs[0]:
        posts = read_csv(settings.posts_csv)
        if posts.empty:
            st.write("暂无帖子数据。")
        else:
            risk_filter = st.multiselect(
                "风险等级",
                sorted(posts["risk_level"].dropna().unique().tolist()) if "risk_level" in posts else [],
                default=[],
            )
            view = posts
            if risk_filter:
                view = view[view["risk_level"].isin(risk_filter)]
            st.dataframe(view.sort_values("crawl_time", ascending=False), use_container_width=True, height=520)

    with tabs[1]:
        replies = read_csv(settings.replies_csv)
        if replies.empty:
            st.write("暂无回复数据。")
        else:
            st.dataframe(replies.sort_values("created_at", ascending=False), use_container_width=True, height=520)

    with tabs[2]:
        dialogues = read_csv(settings.dialogues_csv)
        if dialogues.empty:
            st.write("暂无对话数据。")
        else:
            st.dataframe(dialogues.sort_values("event_time", ascending=False), use_container_width=True, height=520)

    with tabs[3]:
        runs = read_csv(settings.runs_csv)
        if runs.empty:
            st.write("暂无运行记录。")
        else:
            st.dataframe(runs.sort_values("run_time", ascending=False), use_container_width=True, height=420)

    with tabs[4]:
        st.subheader("选择器")
        st.write("如果无法进入板块、找不到评论框或发送按钮，先点击侧边栏的“页面校准 Dump”，再根据 XML 中的文字调整 `.env`。")
        st.code(
            "\n".join([
                f"TARGET_TAB_TEXTS={','.join(settings.target_tab_texts)}",
                f"SEARCH_TRIGGER_TEXTS={','.join(settings.search_trigger_texts)}",
                f"COMMENT_ENTRY_TEXTS={','.join(settings.comment_entry_texts)}",
                f"COMMENT_INPUT_HINTS={','.join(settings.comment_input_hints)}",
                f"SEND_BUTTON_TEXTS={','.join(settings.send_button_texts)}",
            ]),
            language="text",
        )
        st.subheader("可见文本预览")
        if service.app.started and st.button("刷新可见文本"):
            try:
                texts = service.app.visible_texts(min_len=1)
                st.text("\n".join(texts[:250]))
            except Exception as exc:
                st.error(str(exc))


if __name__ == "__main__":
    main()
