# TrackTalk

An AI-powered racing game commentary system built on **MiMo-V2.5** (video understanding + TTS) and **DeepSeek-V4-Flash** (dialogue generation). Automatically captures gameplay, generates F1 / WRC / Le Mans-style commentary in Chinese or English, synthesizes speech, and overlays subtitles on screen.

---

## Features

| Feature | Implementation |
|---------|---------------|
| **Screen Recording** | `mss` capture + `cv2` MP4 encoding, adjustable resolution |
| **Video Compression** | `ffmpeg` H.264 CRF progressive (28→32→35→38→40) |
| **Scene Description** | MiMo-V2.5 video understanding → Chinese text description |
| **Dialogue Generation** | DeepSeek-V4-Flash (no-think) → JSON dual-commentator dialogue |
| **Speech Synthesis** | MiMo-V2.5-TTS: Chinese (苏打/冰糖) or English (Milo/Chloe) |
| **Audio Playback** | `sounddevice` non-blocking playback |
| **Rounded Subtitles** | tkinter Canvas auto-width, arc-based corners, Win32 topmost |
| **Parallel Recording** | Background thread records next clip while main thread plays audio |
| **Adaptive Duration** | Dynamically adjusts recording length from TTS output (6-15s) |
| **Random Intervals** | 5-15s random delay between recording rounds |
| **Impromptu Singing** | AI bursts into song lines, 10-song dedup list |
| **Silent Appreciation** | AI sets `pause` seconds, stops recording to let viewers enjoy |
| **Criticism & Praise** | Dares to call out bad driving, genuinely celebrates great moves |
| **Bilingual** | Chinese (大刘 & 小鹿) or English (Dave & Lena) with one click |
| **Cross-Round Context** | Last 5 round summaries + sung lyrics list injected into prompt |
| **API Key Persistence** | Auto-saved to `.env` after verification |
| **GUI** | tkinter interface: dual Key config, monitor selection, live log |
| **CLI** | `--loop` auto cycle, `--file` for existing videos |

## Project Structure

```
fh-xiabbde/
├── main.py             # Core engine
├── gui.py              # GUI interface
├── prompts.toml        # Prompt templates (editable without touching code)
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variable template
├── .gitignore
├── LICENSE             # MIT
├── README.md           # Chinese docs
└── README_EN.md        # This file
```

## Requirements

| Item | Requirement | Notes |
|------|-------------|-------|
| OS | Windows 10/11 | Subtitle topmost uses Win32 API |
| Python | 3.11+ | `tomllib` for prompt loading |
| ffmpeg | For video compression | Auto-installed via `imageio-ffmpeg` |
| MiMo API Key | [platform.xiaomimimo.com](https://platform.xiaomimimo.com/console/balance) | Video understanding + TTS |
| DeepSeek API Key | [platform.deepseek.com](https://platform.deepseek.com/api_keys) | Dialogue generation |

## Installation Guide

### Prerequisites

| Item | Requirement | Check |
|------|-------------|-------|
| Windows | 10/11 | `winver` |
| Python | 3.11+ | `python --version` |

### Step 1: Clone

```powershell
git clone <repo-url> fh-xiabbde
cd fh-xiabbde
```

### Step 2: Install Dependencies

```powershell
pip install -r requirements.txt

# ffmpeg for video compression
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple imageio-ffmpeg or pip install imageio-ffmpeg
```

### Step 3: Fix Windows Python Path (Critical)

Windows comes with a Microsoft Store Python stub that hijacks the `python` command. Must fix or GUI won't appear.

```powershell
# Check what python points to
Get-Command python | Select-Object Source

# If it shows WindowsApps\python.exe (stub), run:
$real = (Get-ChildItem "$env:LOCALAPPDATA\Python\pythoncore-*" -Directory | Select-Object -Last 1).FullName
[Environment]::SetEnvironmentVariable("PATH", "$real;$real\Scripts;" + [Environment]::GetEnvironmentVariable("PATH", "User"), "User")
```

Close and reopen PowerShell, verify with `python --version`.

### Step 4: Configure API Keys

Create `.env` (copy `.env.example`):

```env
MIMO_API_KEY=sk-your-mimo-key       # https://platform.xiaomimimo.com/console/balance
DEEPSEEK_API_KEY=sk-your-deepseek-key  # https://platform.deepseek.com/api_keys
```

Or enter in the GUI and click "Verify & Save".

### Step 5: Run

```powershell
python gui.py
```

Open your racing game (recommended: Borderless Window mode), click "Start" to begin.

CLI mode:

```powershell
python main.py --loop       # Auto cycle
python main.py --loop -c 5  # Fixed cycles
python main.py --file video.mp4  # Existing video
```

### Troubleshooting

| Problem | Fix |
|---------|-----|
| `python` opens Microsoft Store | Run Step 3 to fix PATH |
| `import cv2` DLL error | `pip uninstall opencv-python; pip install opencv-python` |
| No window appears | Check antivirus blocking tkinter |
| `tomllib` not found | Python must be >= 3.11 |
| No audio output | Check system volume, `pip install sounddevice --force` |

---
## Language Selection

The GUI includes a language toggle on the Config tab:

| Language | Male Voice | Female Voice | Characters |
|----------|-----------|--------------|------------|
| **中文** | 苏打 | 冰糖 | 大刘 & 小鹿 |
| **English** | Milo | Chloe | Dave & Lena |

Switching language auto-switches the TTS voices and loads the corresponding prompt from `prompts.toml` (`[dialogue]` or `[dialogue_en]`).

## Architecture

### Pipeline

```
Screen Recording → ffmpeg Compression → MiMo-V2.5 Scene Description
                                              (Chinese text)
                                                  │
                                                  ▼
                              DeepSeek-V4-Flash Dialogue Generation
                              (JSON: segments + pause signal)
                                  │              │
                                  ▼              ▼
                     MiMo-V2.5-TTS          Subtitle Overlay
                     (Male + Female)        (tk Canvas, Win32)
                          │
                          ▼
                     Audio Playback
                     (sounddevice)
```

### Two-Stage Generation

1. **MiMo describe** — `_mimo_describe_scene()`: send video → get 2-7 sentence Chinese description
2. **DeepSeek dialogue** — `_deepseek_generate_dialogue()`: send description + context → get JSON commentary

### Parallel Architecture

- **Main Thread**: tkinter event loop, subtitle updates, audio playback control
- **Worker Thread**: recording → MiMo analysis → TTS → wait for playback slot → repeat
- Recording runs in parallel with audio playback

## Configuration

### Code Constants (main.py)

| Constant | Line | Default | Description |
|----------|------|---------|-------------|
| `RECORD_DURATION` | 55 | 10s | Initial recording (adapts dynamically) |
| `RECORD_FPS` | 56 | 15 | Recording FPS |
| `TARGET_WIDTH` | 57 | 960 | Output resolution width |
| `TARGET_HEIGHT` | 58 | 540 | Output resolution height |
| `LANGUAGE` | 49 | `zh` | Commentary language (`zh`/`en`) |
| `MALE_VOICE` | 45 | 苏打 | Chinese male TTS voice |
| `FEMALE_VOICE` | 46 | 冰糖 | Chinese female TTS voice |
| `MALE_VOICE_EN` | 47 | Milo | English male TTS voice |
| `FEMALE_VOICE_EN` | 48 | Chloe | English female TTS voice |

### Prompts (prompts.toml)

| Section | Usage |
|---------|-------|
| `[describe].prompt` | MiMo scene description (English prompt, Chinese output) |
| `[dialogue].prompt` | DeepSeek Chinese commentary generation |
| `[dialogue_en].prompt` | DeepSeek English commentary generation |

Edit `prompts.toml` directly to modify commentary behavior without touching Python code.

## Dialogue Prompts

The `[dialogue]` and `[dialogue_en]` prompts contain these modules:

- **Characters** — Background, personality, speaking style of both commentators
- **Interaction** — Dynamic between the duo
- **Style** — 50% analysis + 30% atmosphere + 20% banter
- **Output Format** — Strict JSON with `segments` and `pause`
- **Criticism & Praise** — Must have opinions, call out bad driving
- **Silent Appreciation** — Only when nothing to say, must have lead-in
- **Singing** — Burst into 1-2 song lines, never repeat lyrics
- **Racing Memes** — Sprinkle in racing culture references

## FAQ

### Q: Subtitle window hidden by game?
Use **Borderless Window** mode in your game. The system calls `SetWindowPos(HWND_TOPMOST)` every 0.5s via Win32 API.

### Q: How to confirm DeepSeek is being used?
Log lines prefixed with `[DeepSeek]` indicate DeepSeek calls. `[MiMo]` lines are MiMo calls.

### Q: Commentary too frequent / too sparse?
Adjust `RECORD_DURATION` (line 55) and random interval range (gui.py `random.randint(5, 15)`).

### Q: Want different TTS voices?
Change `MALE_VOICE`/`FEMALE_VOICE` for Chinese, or `MALE_VOICE_EN`/`FEMALE_VOICE_EN` for English. Available: `Mia`, `Chloe`, `Milo`, `Dean`, `茉莉`, `白桦`, etc.

### Q: How to modify commentary behavior?
Edit `prompts.toml` — no code changes needed. Restart the app to reload.

## use opencode + deepseek

## License

MIT — see [LICENSE](LICENSE). MiMo API usage follows [Xiaomi MiMo Terms](https://mimo.mi.com/docs/quick-start/terms/user-agreement). DeepSeek API usage follows [DeepSeek Terms](https://platform.deepseek.com/terms).
