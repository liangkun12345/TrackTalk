# TrackTalk

基于 **MiMo-V2.5**（视频理解 + TTS 语音合成）和 **DeepSeek-V4-Flash**（对话生成）的赛车游戏 AI 解说系统。自动录制游戏画面，两位虚拟解说员以 F1 / WRC 风格进行实时解说（**支持中文/English 双语言**），语音从扬声器播放，屏幕底部叠加圆角字幕。

> 英文版文档 [README_EN.md](README_EN.md)

---

## 目录

1. [功能特性](#功能特性)
2. [项目结构](#项目结构)
3. [环境要求](#环境要求)
4. [快速开始](#快速开始)
5. [架构详解](#架构详解)
6. [配置项](#配置项)
7. [代码索引](#代码索引)
8. [Prompt 设计](#prompt-设计)
9. [GUI 界面](#gui-界面)
10. [常见问题](#常见问题)
11. [许可证](#许可证)

---

## 功能特性

| 功能 | 实现方式 |
|------|----------|
| **屏幕录制** | `mss` 捕获 + `cv2` 编码 MP4，分辨率可调 |
| **视频压缩** | `ffmpeg` H.264 CRF 逐级压缩（28→32→35→38→40） |
| **场景描述** | MiMo-V2.5 视频理解 → 2-4 句中文客观描述 |
| **解说生成** | DeepSeek-V4-Flash (no think) → JSON 格式双人对话 |
| **语音合成** | MiMo-V2.5-TTS：男声"苏打" + 女声"冰糖" |
| **音频播放** | `sounddevice` 非阻塞播放 |
| **圆角字幕** | tkinter Canvas 自适应宽度，arc + rect 真圆角，Win32 强制置顶 |
| **录制播放并行** | 后台线程录制下一轮时，主线程播放上一轮 |
| **时长自适应** | 根据上一轮 TTS 实际时长动态调整下次录制（6-15 秒） |
| **随机间隔** | 每轮录制前随机等待 5-15 秒 |
| **即兴唱歌** | AI 自动在 `(唱歌)` 标签中哼唱，已唱过的歌词禁止重复（列表 10 首） |
| **静默观赏** | AI 指定 `pause` 秒数，暂停录制让观众享受画面 |
| **批评车手** | AI 敢于直言，烂操作直接批评，精彩操作由衷赞叹 |
| **赛车梗** | 支持加入赛车电影/动漫经典梗 |
| **跨轮次上下文** | 最近 5 轮摘要 + 已唱歌词列表注入 prompt |
| **API Key 持久化** | 验证通过后自动写入 `.env` |
| **GUI** | tkinter 界面：双 Key 配置、显示器选择、实时日志 |
| **CLI** | `--loop` 自动循环、`--file` 指定视频 |

---

## 项目结构

```
fh-xiabbde/
├── main.py             # 核心引擎 (993 行)
│   ├── 屏幕录制         record_screen()
│   ├── 视频压缩         ensure_video_fits() + ffmpeg
│   ├── 场景描述         _mimo_describe_scene()
│   ├── 对话生成         _deepseek_generate_dialogue()
│   ├── 语音合成         generate_tts() + generate_all_tts()
│   ├── 字幕叠加         SubtitleOverlay 类
│   ├── 上下文管理       CommentaryContext 类
│   └── 命令行入口       main()
├── gui.py              # GUI 界面 (497 行)
│   ├── 配置标签页       API Key ×2、录制时长、分辨率
│   ├── 字幕&窗口标签页   位置、偏移、显示器、颜色预览
│   ├── 日志标签页       实时滚动日志
│   └── 后台线程         录制/分析/TTS 循环
├── requirements.txt    # Python 依赖
├── .env.example        # 环境变量模板
└── README.md           # 本文档
```

---

## 环境要求

| 项目 | 要求 | 备注 |
|------|------|------|
| 操作系统 | Windows 10/11 | 字幕置顶依赖 Win32 API |
| Python | 3.9+ | 推荐 3.11+ |
| ffmpeg | 用于视频压缩 | 通过 `imageio-ffmpeg` 自动获取 |
| MiMo API Key | [platform.xiaomimimo.com](https://platform.xiaomimimo.com/console/balance) | 视频理解 + TTS |
| DeepSeek API Key | [platform.deepseek.com](https://platform.deepseek.com/api_keys) | 对话生成 |

---

## 安装指南

### 前置条件

| 项目 | 要求 | 检查命令 |
|------|------|----------|
| Windows | 10/11 | `winver` |
| Python | 3.11+ | `python --version` |

### Step 1: 克隆项目

```powershell
git clone <repo-url> fh-xiabbde
cd fh-xiabbde
```

### Step 2: 安装 Python 依赖

```powershell
pip install -r requirements.txt

# 安装 ffmpeg（视频压缩，清华源秒装）
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple imageio-ffmpeg 或 pip install imageio-ffmpeg
```

### Step 3: 修复 Windows Python 路径（重要）

Windows 自带 Microsoft Store Python 占位程序，会拦截 `python` 命令导致 GUI 无法弹出。

```powershell
# 检查当前 python 指向
Get-Command python | Select-Object Source

# 如果显示 WindowsApps\python.exe，执行修复：
$real = (Get-ChildItem "$env:LOCALAPPDATA\Python\pythoncore-*" -Directory | Select-Object -Last 1).FullName
[Environment]::SetEnvironmentVariable("PATH", "$real;$real\Scripts;" + [Environment]::GetEnvironmentVariable("PATH", "User"), "User")
```

关闭并重新打开 PowerShell，`python --version` 确认修复。

### Step 4: 配置 API Key

创建 `.env` 文件（复制 `.env.example`）：

```env
MIMO_API_KEY=sk-your-mimo-key       # https://platform.xiaomimimo.com/console/balance
DEEPSEEK_API_KEY=sk-your-deepseek-key  # https://platform.deepseek.com/api_keys
```

也可在 GUI 启动后输入并点击"验证并保存"。

### Step 5: 运行

```powershell
python gui.py
```

打开赛车游戏（推荐无边框窗口模式），点击"开始录制解说"即可。

CLI 模式：

```powershell
python main.py --loop       # 自动循环
python main.py --loop -c 5  # 指定循环次数
python main.py --file video.mp4  # 使用已有视频
```

---
## 架构详解

### 数据流

```
  屏幕录制 (mss+cv2, 10s MP4)
      │
      ▼
  ffmpeg 压缩 (CRF 28→40, ≤45MB base64)
      │
      ▼
┌─────────────────────────────────────────────────────┐
│                 MiMo-V2.5 (thinking=off)             │
│                 视频理解 → 场景中文描述                 │
│    输出: "一辆红色跑车在城市街道高速过弯，走线精准..."   │
└───────────────────────┬─────────────────────────────┘
                        │  纯文本
                        ▼
┌─────────────────────────────────────────────────────┐
│              DeepSeek-V4-Flash (no-think)            │
│       文字生成 → 解说对话 JSON (大刘+小鹿一人一句)      │
│    输出: {"segments":[{...}], "pause":0}             │
└────────────┬──────────────────────────────┬─────────┘
             │                              │
             ▼                              ▼
┌─────────────────────┐      ┌─────────────────────────┐
│  MiMo-V2.5-TTS       │      │  字幕叠加 (tk Canvas)     │
│  男声苏打 + 女声冰糖   │      │  圆角窗口, Win32 强制置顶   │
│  → WAV 24kHz float32 │      │  男女不同颜色, 自适应宽度    │
└──────────┬──────────┘      └──────────────────────────┘
           │
           ▼
  音频播放 (sounddevice)
```

**管线**：MiMo 识别画面 → DeepSeek 生成对话 → MiMo TTS 输出语音。三个模型各司其职。

### 两阶段生成流程

```
generate_commentary(video_path, context)
  │
  ├─ Step 1: _mimo_describe_scene(video_path)
  │     ├─ 模型: mimo-v2.5
  │     ├─ prompt: SYSTEM_PROMPT_DESCRIBE
  │     ├─ 输出: "一辆红色跑车正在城市街道上高速行驶，前方是一个90度弯..."
  │     └─ Token: ~200-500 tokens
  │
  └─ Step 2: _deepseek_generate_dialogue(description, context)
        ├─ 模型: deepseek-v4-flash
        ├─ prompt: SYSTEM_PROMPT_BASE + 上下文 + 画面描述
        ├─ 输出: {"segments": [...], "pause": 0}
        └─ Token: ~500-2000 tokens
```

### GUI 并行架构

```
主线程 (Main Thread)
  │
  ├─ tkinter 事件循环 (mainloop)
  │     ├─ 每 100ms 检查 msg_queue
  │     ├─ 处理日志、状态更新
  │     ├─ 收到 "play" 消息 → 启动音频 + 字幕
  │     └─ 每 50ms 驱动字幕 overlay.tick()
  │
  └─ 后台线程 (_cycle_thread)
        ├─ 循环: 录制 → analyze → TTS → 等待播放槽位
        ├─ 录制与主线程播放并行
        └─ 通过 msg_queue 通信
```

### 动态时长序列

```
第1轮: 录制 10s → TTS 3.2s → 下次录制 = min(8, max(3.2+5, 6)) = 8s
第2轮: 录制 8s  → TTS 2.8s → 下次录制 = 7s
第3轮: 录制 7s  → TTS 3.5s → 下次录制 = 8s
... 在 6-15s 范围内自适应
```

### 循环节奏

```
┌──────┐   ┌────────┐   ┌─────┐   ┌────────────┐
│随机等 │──▶│ 录制10s │──▶│分析 │──▶│ 等待播放槽位 │──▶ 下一轮
│5-15s │   │(与播放并行)│  │+TTS │   │(上一轮播完即提交)│
└──────┘   └────────┘   └─────┘   └────────────┘
```

---

## 配置项

### 环境变量 (.env)

| 变量 | 说明 | 示例 |
|------|------|------|
| `MIMO_API_KEY` | 小米 MiMo API Key | `sk-mimo-xxxx` |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | `sk-deepseek-xxxx` |

### 代码常量 (main.py)

| 常量 | 位置 | 默认值 | 说明 |
|------|------|--------|------|
| `RECORD_DURATION` | 51 | 10s | 初始录制时长（之后自适应） |
| `RECORD_FPS` | 52 | 15 | 录制帧率 |
| `TARGET_WIDTH` | 53 | 960 | 输出分辨率宽度 |
| `TARGET_HEIGHT` | 54 | 540 | 输出分辨率高度 |
| `MAX_BASE64_MB` | 55 | 45 | base64 大小阈值 |
| `MODEL_VISION` | 57 | `mimo-v2.5` | MiMo 视频理解模型 |
| `MODEL_TTS` | 58 | `mimo-v2.5-tts` | MiMo TTS 模型 |
| `MALE_VOICE` | 45 | `苏打` | 男声预置音色 |
| `FEMALE_VOICE` | 46 | `冰糖` | 女声预置音色 |
| `MALE_COLOR` | 47 | `#00BFFF` | 男解说字幕颜色 |
| `FEMALE_COLOR` | 48 | `#FF69B4` | 女解说字幕颜色 |
| `SUBTITLE_BG` | 49 | `#111111` | 字幕背景色 |

### SubtitleOverlay 常量 (main.py)

| 常量 | 位置 | 默认值 | 说明 |
|------|------|--------|------|
| `RADIUS` | 507 | 18px | 圆角半径 |
| `PAD_X` | 508 | 60px | 左右留白 |
| `PAD_Y` | 509 | 30px | 上下留白 |
| `FONT_SIZE` | 510 | 20 | 解说文字大小 |
| `NAME_SIZE` | 511 | 10 | 说话人名字大小 |

---

## 代码索引

### main.py 核心函数

| 函数 | 行号 | 功能 |
|------|------|------|
| `record_screen()` | 61 | 屏幕录制为 MP4 |
| `CommentaryContext` | 138 | 跨轮次上下文（摘要、唱歌记录、暂停控制） |
| `SYSTEM_PROMPT_DESCRIBE` | 187 | MiMo 场景描述 prompt |
| `SYSTEM_PROMPT_BASE` | 198 | DeepSeek 解说对话 prompt |
| `_find_ffmpeg()` | 260 | 查找 ffmpeg 二进制 |
| `compress_video()` | 273 | ffmpeg CRF 压缩 |
| `ensure_video_fits()` | 286 | 保证 base64 ≤ 45MB |
| `generate_commentary()` | 342 | 编排两阶段流水线 |
| `_mimo_describe_scene()` | 355 | 调用 MiMo 描述画面 |
| `_deepseek_generate_dialogue()` | 382 | 调用 DeepSeek 生成解说 |
| `generate_tts()` | 436 | 调用 MiMo TTS 合成语音 |
| `generate_all_tts()` | 450 | 并行 TTS 多段解说 |
| `SubtitleOverlay` | 503 | 圆角字幕窗口类 |
| `SubtitleOverlay._draw_round_rect()` | 577 | 真圆角绘制（arc+rect） |
| `SubtitleOverlay.tick()` | 616 | 驱动字幕刷新 |
| `play_commentary()` | 663 | 音频播放 + 字幕调度 |
| `save_api_key()` | 782 | 保存 Key 到 .env |
| `delete_api_key()` | 793 | 删除 .env |
| `_validate_api_key()` | 808 | 验证 MiMo Key |
| `_run_single_cycle()` | 828 | 单轮录制→分析→TTS→播放 |
| `_run_loop_mode()` | 879 | CLI 循环模式 |
| `_run_single_mode()` | 920 | CLI 单次模式 |

### gui.py 核心函数

| 函数 | 行号 | 功能 |
|------|------|------|
| `RacingCommentatorGUI.__init__()` | 25 | GUI 初始化 |
| `_build_config_tab()` | 100 | 配置标签页 UI |
| `_build_display_tab()` | 150 | 字幕&窗口标签页 UI |
| `_build_log_tab()` | 190 | 日志标签页 UI |
| `_verify_key()` | 210 | 验证并保存 MiMo Key |
| `_verify_deepseek_key()` | 237 | 验证并保存 DeepSeek Key |
| `_delete_key()` | 252 | 删除 MiMo Key |
| `_delete_deepseek_key()` | 260 | 删除 DeepSeek Key |
| `_start()` | 270 | 开始解说循环 |
| `_cycle_thread()` | 295 | 后台录制/分析/TTS 循环 |
| `_process_queue()` | 380 | 消息队列处理 |
| `_start_playback()` | 408 | 启动音频播放 + 字幕 |

---

## Prompt 设计

> 提示词保存在 `prompts.toml` 中，修改提示词直接编辑该文件即可，无需改动 `main.py`。
> `main.py:187-202` 自动加载，结构为 `[describe].prompt` 和 `[dialogue].prompt`，格式与 Python `"""..."""` 完全一致。


### 1. SYSTEM_PROMPT_DESCRIBE（MiMo 场景描述）— main.py:187

**英文 prompt（保存 token，但保留原文全部细节，输出仍用中文）**：

```
You are a racing video analyst. Carefully observe this racing game footage
and objectively describe everything you see in Chinese:
- Car names and liveries (omit if not visible)
- Track type and environment (city streets / mountain roads / circuit / snow / desert, etc.)
- Car positions, count, and relative distances between them
- Actions taking place (accelerating, braking, cornering, overtaking, collisions, etc.)
- Racing events (overtakes, being overtaken)
- Rankings
- Professional racing terms (understeer, oversteer, early braking, late braking, braking force, etc.)
- Scenery description
- Sense of speed, weather, lighting, and other atmosphere info
- Professionalism of the racing line
- Corner entry and exit speeds
- Any noteworthy details

Write 2-7 sentences. Describe only observed facts. Do not expand into commentary.
Do not evaluate. Keep it as brief as possible.
```

### 2. SYSTEM_PROMPT_BASE（DeepSeek 对话生成）— 198行

完整 prompt 包含以下模块：

#### 【人物设定】
- **大刘**：42岁，前房车赛退役车手，豪爽接地气，对技术有职业病般执着
- **小鹿**：28岁，赛车记者出身，机灵俏皮，擅长比喻

#### 【人物关系与互动】
- 老搭档五年，大刘爱显摆经验，小鹿敢怼回去

#### 【解说风格】
- 50%专业分析 + 30%气氛描述 + 20%闲聊互动

#### 【批评与赞美】
- 烂操作直接批评："这刹车点选得太离谱了"
- 精彩操作由衷赞叹："教科书级别的弯心切入"

#### 【静默观赏模式】
- 只有在完全无解说内容时才启动
- 必须有前摇引导语，pause 设秒数

#### 【即兴唱歌】
- 情绪到位就唱，格式：`(唱歌)歌词内容`

#### 【赛车梗】
- 马自达塞车梗、AE86 漂移梗等经典名场面

#### 上下文注入
每轮注入：前情提要（最近5轮摘要）+ 已唱过的歌词列表（禁止重复）+ DeepSeek 收到的当前画面文本描述。

---

## GUI 界面

```
┌──────────────────────────────────────────────────────┐
│              TrackTalk                         │
├──────────────────┬────────────────────────────────────┤
│ [配置] [字幕&窗口] │ [日志]                              │
├──────────────────┤                                    │
│ MiMo API Key:    │  --- 第 1 轮 (录制8秒) ---          │
│ [********] [验证] │  [MiMo] 画面描述: 一辆红色赛车...    │
│ DeepSeek Key:    │  [DeepSeek] 成功生成 2 段解说词       │
│ [********] [验证] │  [TTS] 生成 2 段语音...              │
│ 录制时长: [10s ▼]│  🎶 唱歌: 原谅我这一生不羁放纵...    │
│ 分辨率: [960x540]│  [播放] 第1轮开始播放                │
│ 男解说音色: 苏打  │                                    │
│ 女解说音色: 冰糖  │                                    │
├──────────────────┤                                    │
│ 字幕位置: ◉底部  │                                    │
│ 屏幕边距: [40px] │                                    │
│ 录制显示器: [...] │                                    │
├──────────────────┴────────────────────────────────────┤
│  [▶ 开始录制解说]  [⏹ 停止]   状态: 运行中...          │
└──────────────────────────────────────────────────────┘
```

### 操作步骤

1. 打开赛车游戏（推荐 **无边框窗口模式**，否则字幕可能被遮挡）
2. 启动 GUI：`python gui.py`
3. 在"配置"标签页分别填入 MiMo 和 DeepSeek 的 API Key，点击"验证并保存"
4. 在"字幕&窗口"标签页选择录制显示器
5. 切回游戏
6. 切回 GUI 点击 "▶ 开始录制解说"
7. 系统自动无限循环，日志实时滚动
8. 点击"⏹ 停止"或关闭窗口退出

---

## 常见问题

### Q: 视频上传提示 "exceeded maximum size limit"
自动压缩不达标时会跳过本轮。可进一步降低分辨率（如 854×480）或缩短录制时长。

### Q: 字幕窗口被游戏完全遮挡
将游戏设为**无边框窗口模式**（Borderless Window），而非独占全屏。系统每 0.5 秒通过 Win32 `SetWindowPos(HWND_TOPMOST)` 强制置顶。

### Q: 如何确认用了 DeepSeek？
日志中出现 `[DeepSeek]` 前缀的行即为 DeepSeek 调用，`[MiMo]` 为 MiMo 调用。

### Q: 解说太频繁 / 太少
调整 `RECORD_DURATION`（初始录制秒数）和随机间隔范围（gui.py 第 308 行 `random.randint(5, 15)`）。

### Q: 想更换 TTS 音色
修改 `MALE_VOICE` / `FEMALE_VOICE`（第 45-46 行），可选：`茉莉`、`白桦`、`Mia`、`Chloe` 等。

### Q: 字幕窗口太大 / 太小
修改 `SubtitleOverlay` 类的 `FONT_SIZE`（510行）、`PAD_X`（508行）、`PAD_Y`（509行）。

### Q: 如何只录制指定显示器？
GUI "字幕&窗口"标签页选择目标显示器。CLI 模式默认录制主显示器。

---

## 使用OpenCode + DeepSeek 辅助生成

## 许可证

仅供学习和研究使用。MiMo API 调用遵循[小米 MiMo 服务协议](https://mimo.mi.com/docs/quick-start/terms/user-agreement)。DeepSeek API 调用遵循 [DeepSeek 服务协议](https://platform.deepseek.com/terms)。

## 免责声明
本工具仅供学习研究，使用风险自负。请勿用于违反游戏服务条款的场景。