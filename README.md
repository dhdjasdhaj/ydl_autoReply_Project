# 壹点灵 App 监控与实验回复控制台

这个项目使用安卓真机加 Appium/ADB 控制壹点灵 App 的真实界面，完成新帖采集、LLM 生成回复、计划发布、真实发布和 CSV 数据记录。

项目不使用 Fiddler、Frida、Magisk、APK 逆向、证书绕过或隐藏接口复用。所有发布动作都通过 App 的真实 UI 完成。

## 实验设计

实验模式通过 `REPLY_MODE=identity_experiment` 开启。系统会按 `question_id % 4` 将问题轮换分到四个策略组，每个问题只生成一条回复计划。

- 策略0：账号1，昵称“豆包陪伴AI小助手”，回复正文末尾追加 `[AI辅助回复]`。
- 策略1：账号1，昵称“豆包陪伴AI小助手”，回复文本不出现任何 AI 相关提示。
- 策略2：账号2，昵称“豆包”，回复文本不出现任何 AI 相关提示。
- 策略3：账号3，真人头像和真人昵称，模拟真人回复，账号昵称和回复文本均不出现任何 AI 提示。

默认所有实验回复会计划在发现问题后的 12 小时内完成：

```env
EXPERIMENT_REPLY_WINDOW_SECONDS=43200
EXPERIMENT_FIRST_REPLY_MIN_SECONDS=0
EXPERIMENT_FIRST_REPLY_MAX_SECONDS=43200
```

真实发布时，当前手机只能代表当前登录账号。请在运行对应账号前设置：

```env
EXPERIMENT_ACTIVE_ACCOUNT_ID=account1
```

可选值为 `account1`、`account2`、`account3`。如果真实发布已开启但未设置该值，实验回复会保留在计划状态，避免误用当前账号代发。

## 安装

```powershell
python -m pip install -r requirements.txt
npm install -g appium
appium driver install uiautomator2
```

确认手机可见：

```powershell
adb devices -l
```

## 配置

复制配置模板：

```powershell
Copy-Item .env.example .env
```

先保持干运行：

```env
DRY_RUN=true
ENABLE_REAL_POST=false
```

确认要真实发布时，必须同时设置：

```env
DRY_RUN=false
ENABLE_REAL_POST=true
REAL_POST_CONFIRMATION=I_UNDERSTAND_REAL_POSTING
```

LLM 配置示例：

```env
LLM_API_BASE=https://api.openai.com/v1
LLM_API_KEY=你的 API Key
LLM_MODEL=gpt-4o-mini
```

## 运行

启动控制台：

```powershell
.\start_dashboard.ps1
```

或运行一次页面校准：

```powershell
python calibrate.py
```

校准会保存当前 App 页面 XML 和截图到 `data/dumps`。如果找不到评论入口、评论输入框或发送按钮，请根据 XML 调整 `.env` 中的：

- `TARGET_TAB_TEXTS`
- `COMMENT_ENTRY_TEXTS`
- `COMMENT_INPUT_HINTS`
- `SEND_BUTTON_TEXTS`

## 数据记录

- 帖子记录：`data/ydl_posts.csv`
- 回复计划与发布结果：`data/ydl_replies.csv`
- 对话事件：`data/ydl_dialogues.csv`
- 每轮运行统计：`data/ydl_runs.csv`

实验结束后，可在平台删除所有由本项目发布的回复数据。
