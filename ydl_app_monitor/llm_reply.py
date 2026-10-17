import json
import urllib.error
import urllib.request
from typing import Dict

from .config import Settings
from .experiment import ReplyStrategy
from .models import PostRecord
from .safety import SafetyGate


AI_DISCLOSURE_MARKERS = (
    "[AI辅助回复]",
    "由AI生成",
    "由 AI 生成",
    "作为AI助手",
    "作为 AI 助手",
    "AI辅助回复",
    "AI 辅助回复",
    "AI助手",
    "AI 助手",
    "生成的回复",
    "我是AI",
    "我是 AI",
    "我是",
    "作为AI",
    "作为 AI",
    "人工智能",
    "大模型",
    "机器人",
    "AIGC",
    "生成",
    "助手",
    "AI",
)


class LlmReplyGenerator:
    def __init__(self, settings: Settings, safety: SafetyGate) -> None:
        self.settings = settings
        self.safety = safety

    def generate_post_reply(self, post: PostRecord) -> str:
        content = self.safety.scrub_pii(post.content)
        prompt = (
            "请为下面这条壹点灵心理问答/心声帖子生成一条可以发到评论区的中文回复。\n"
            "要求：\n"
            "1. 开头必须包含给定 AI 披露前缀。\n"
            "2. 共情、简短、边界清楚，不冒充医生、咨询师或平台专家。\n"
            "3. 不诊断，不建议用药/停药/换药，不承诺疗效。\n"
            "4. 如对方痛苦明显，建议联系专业人士或可信任的人。\n"
            "5. 80 到 180 字。\n"
            "6. 只输出评论正文，不要输出解释、标题或引号。\n\n"
            f"AI 披露前缀: {self.settings.ai_disclosure_prefix}\n"
            f"帖子标题: {post.title}\n"
            f"帖子内容: {content}\n"
        )
        return self._complete(prompt)

    def generate_strategy_reply(self, post: PostRecord, strategy: ReplyStrategy) -> str:
        content = self.safety.scrub_pii(post.content)
        if strategy.is_human_baseline:
            prompt = (
                "请为下面这条心理问答/心声帖子生成一条普通真人用户风格的中文评论。\n"
                "要求：\n"
                "1. 语言自然、口语化、温和，像真实社区用户看到帖子后的回应。\n"
                "2. 不出现任何 AI、机器人、助手、生成、辅助回复等身份提示，也不要提账号是实验账号。\n"
                "3. 不冒充医生、咨询师或平台专家；不诊断，不给药物建议，不承诺疗效。\n"
                "4. 如对方痛苦明显，建议联系专业人士或身边可信任的人。\n"
                "5. 80 到 180 字，不故意加入大量错别字或夸张情绪。\n"
                "6. 只输出评论正文，不要输出解释、标题或引号。\n\n"
                f"策略说明: {strategy.prompt_profile}\n"
                f"账号昵称: {strategy.account_nickname}\n"
                f"帖子标题: {post.title}\n"
                f"帖子内容: {content}\n"
            )
            return self._complete_for_strategy(prompt, strategy)

        disclosure_rule = (
            f"回复正文内部不出现任何 AI 身份表述，末尾标签由程序统一追加为"
            f"{self.settings.ai_disclosure_suffix}。"
            if strategy.text_ai_disclosure
            else "回复正文和结尾都不出现任何 AI、AI助手、机器人、生成、辅助回复等提示。"
        )
        prompt = (
            "请为下面这条心理问答/心声帖子生成一条陪伴式中文评论。\n"
            "要求：\n"
            f"1. {disclosure_rule}\n"
            "2. 共情、简短、边界清楚，不冒充医生、咨询师或平台专家。\n"
            "3. 不诊断，不建议用药/停药/换药，不承诺疗效。\n"
            "4. 如对方痛苦明显，建议联系专业人士或可信任的人。\n"
            "5. 80 到 180 字。\n"
            "6. 只输出评论正文，不要输出解释、标题或引号。\n\n"
            f"实验策略: {strategy.strategy_name}\n"
            f"策略说明: {strategy.prompt_profile}\n"
            f"账号昵称: {strategy.account_nickname}\n"
            f"帖子标题: {post.title}\n"
            f"帖子内容: {content}\n"
        )
        return self._complete_for_strategy(prompt, strategy)

    def generate_followup_reply(self, post: PostRecord, user_reply: Dict[str, str], history: str = "") -> str:
        content = self.safety.scrub_pii(user_reply.get("content", ""))
        prompt = (
            "用户回复了我之前的 AI 辅助评论。请继续生成一条中文回复。\n"
            "要求：\n"
            "1. 开头必须包含给定 AI 披露前缀。\n"
            "2. 只回应用户刚刚说的话，避免追问隐私。\n"
            "3. 不诊断，不给药物建议，不承诺治疗效果。\n"
            "4. 如果出现危机、自伤、自杀含义，应建议立刻联系身边可信任的人、当地急救或专业危机支持。\n"
            "5. 80 到 180 字。\n"
            "6. 只输出评论正文，不要输出解释、标题或引号。\n\n"
            f"AI 披露前缀: {self.settings.ai_disclosure_prefix}\n"
            f"原帖: {post.content[:700]}\n"
            f"对话历史摘要: {history[:700]}\n"
            f"用户回复: {content}\n"
        )
        return self._complete(prompt)

    def _complete(self, prompt: str, system_content: str = "", apply_legacy_clean: bool = True) -> str:
        if not self.settings.llm_api_key:
            raise RuntimeError("LLM_API_KEY is not configured")

        if not system_content:
            system_content = (
                "你是心理健康社区的 AI 辅助回复草稿生成器。"
                "回复必须谨慎、非诊断、非治疗承诺，并清晰披露 AI 辅助身份。"
            )

        payload = {
            "model": self.settings.llm_model,
            "messages": [
                {
                    "role": "system",
                    "content": system_content,
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": self.settings.llm_temperature,
            "max_tokens": self.settings.llm_max_tokens,
        }

        request = urllib.request.Request(
            f"{self.settings.llm_api_base.rstrip('/')}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.settings.llm_timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM API HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM API request failed: {exc}") from exc
        except TimeoutError as exc:
            raise RuntimeError(f"LLM API request timed out after {self.settings.llm_timeout_seconds}s") from exc

        text = data["choices"][0]["message"]["content"]
        return self._clean(text) if apply_legacy_clean else text

    def _complete_for_strategy(self, prompt: str, strategy: ReplyStrategy) -> str:
        system_content = (
            "你是心理健康社区评论草稿生成器。回复必须谨慎、非诊断、非治疗承诺，"
            "风格要自然、有温度、少模板化。严格遵守用户指定的身份披露方式。"
        )
        text = self._complete(prompt, system_content=system_content, apply_legacy_clean=False)
        return self._clean_for_strategy(text, strategy)

    def _clean(self, text: str) -> str:
        cleaned = " ".join((text or "").strip().strip('"').strip("'").split())
        if self.settings.ai_disclosure_prefix and self.settings.ai_disclosure_prefix not in cleaned:
            cleaned = f"{self.settings.ai_disclosure_prefix}{cleaned}"
        return cleaned[:260]

    def _clean_for_strategy(self, text: str, strategy: ReplyStrategy) -> str:
        cleaned = " ".join((text or "").strip().strip('"').strip("'").split())
        dynamic_markers = (
            self.settings.ai_disclosure_prefix,
            self.settings.ai_disclosure_suffix,
        )
        for marker in tuple(AI_DISCLOSURE_MARKERS) + dynamic_markers:
            if not marker:
                continue
            cleaned = cleaned.replace(marker, "")
        cleaned = " ".join(cleaned.split()).strip(" ，。,.；;：:")

        if strategy.text_ai_disclosure:
            suffix = self.settings.ai_disclosure_suffix
            if suffix:
                max_body_len = max(260 - len(suffix), 0)
                cleaned = cleaned[:max_body_len].rstrip()
                if not cleaned.endswith(suffix):
                    cleaned = f"{cleaned}{suffix}"
                return cleaned[:260]

        return cleaned[:260]
