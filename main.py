"""
TrackTalk
- 录制屏幕视频 → MiMo-V2.5 视频理解生成解说词 → MiMo-V2.5-TTS 语音合成 → 播放音频 + 字幕叠加
"""

import os
import re
import sys
import json
import time
import random
import base64
import ctypes
import shutil
import subprocess
import threading
import tempfile
import io
from pathlib import Path

import cv2
import numpy as np
import soundfile as sf
import sounddevice as sd
from openai import OpenAI
import mss
import mss.tools
import tkinter as tk
from tkinter import font as tkfont

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

# ============================================================
# 配置
# ============================================================
MIMO_API_KEY = os.environ.get("MIMO_API_KEY", "")
MIMO_BASE_URL = "https://api.xiaomimimo.com/v1"
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

MALE_VOICE = "苏打"
FEMALE_VOICE = "冰糖"
MALE_VOICE_EN = "Milo"
FEMALE_VOICE_EN = "Chloe"
LANGUAGE = os.environ.get("COMMENTARY_LANG", "zh")  # zh or en
MALE_COLOR = "#00BFFF"
FEMALE_COLOR = "#FF69B4"
SUBTITLE_BG = "#111111"

RECORD_DURATION = 10
RECORD_FPS = 15
TARGET_WIDTH = 960
TARGET_HEIGHT = 540
MAX_BASE64_MB = 45  # 留 5MB 余量防止边界情况

MODEL_VISION = "mimo-v2.5"
MODEL_TTS = "mimo-v2.5-tts"

# ============================================================
# 1. 屏幕录制
# ============================================================
def record_screen(output_path: str, duration: int = RECORD_DURATION,
                  fps: int = RECORD_FPS, target_w: int = TARGET_WIDTH,
                  target_h: int = TARGET_HEIGHT) -> str:
    """录制屏幕并保存为 MP4 文件。"""
    sct = mss.mss()
    monitor = sct.monitors[1]

    native_w = monitor["width"]
    native_h = monitor["height"]

    if native_w <= target_w or native_h <= target_h:
        out_w, out_h = native_w, native_h
    else:
        scale = min(target_w / native_w, target_h / native_h)
        out_w, out_h = int(native_w * scale), int(native_h * scale)

    out_w = out_w // 2 * 2
    out_h = out_h // 2 * 2

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(output_path, fourcc, fps, (out_w, out_h))
    if not writer.isOpened():
        fourcc = cv2.VideoWriter_fourcc(*'XVID')
        avi_path = output_path.replace('.mp4', '.avi')
        writer = cv2.VideoWriter(avi_path, fourcc, fps, (out_w, out_h))
        output_path = avi_path

    frame_interval = 1.0 / fps
    frame_count = 0
    start_time = time.time()

    print(f"\n[录制] 分辨率: {out_w}x{out_h}, FPS: {fps}, 时长: {duration}秒")
    for i in range(3, 0, -1):
        print(f"[录制] {i}...")
        time.sleep(1)
    print("[录制] 开始! (按 Ctrl+C 可提前结束)\n")

    try:
        while time.time() - start_time < duration:
            loop_start = time.time()

            img = sct.grab(monitor)
            frame = np.array(img)
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

            if (out_w, out_h) != (native_w, native_h):
                frame = cv2.resize(frame, (out_w, out_h))

            writer.write(frame)
            frame_count += 1

            elapsed = time.time() - loop_start
            if elapsed < frame_interval:
                time.sleep(frame_interval - elapsed)

            remaining = max(0, duration - (time.time() - start_time))
            print(f"\r[录制] 剩余 {remaining:.0f}秒 | 已录 {frame_count} 帧", end="", flush=True)

    except KeyboardInterrupt:
        print("\n[录制] 用户中断")

    writer.release()
    actual_duration = time.time() - start_time
    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)

    print(f"\n[录制] 完成! 帧数: {frame_count}, 实际时长: {actual_duration:.1f}秒, "
          f"大小: {file_size_mb:.1f}MB")

    if file_size_mb > 45:
        print(f"[警告] 文件大小 {file_size_mb:.1f}MB 超过 45MB 限制, 但仍可尝试上传")

    return output_path

# ============================================================
# 2. 视频理解 - 生成解说词
# ============================================================
class CommentaryContext:
    """维护跨轮次的解说上下文，让两位解说员能引用之前发生的事。"""

    def __init__(self):
        self.round = 0
        self.events: list[str] = []       # 每轮的关键事件摘要
        self.last_position: str = ""       # 上一轮末的大致位置/情况
        self.pause_seconds: int = 0        # 本轮是否需要暂停录制（0=不需要）
        self.sung_songs: list[str] = []    # 已唱过的歌名，最多记10首

    def update(self, segments: list[dict]) -> str | None:
        """根据本轮解说词提取摘要，返回本轮新唱的歌词（如果有）。"""
        self.round += 1
        texts = [s['text'] for s in segments if s.get('text')]
        combined = ' '.join(texts)
        summary = combined[:200] + ('...' if len(combined) > 200 else '')
        self.last_position = combined[-120:] if len(combined) > 120 else combined
        self.events.append(f"第{self.round}轮: {summary}")
        if len(self.events) > 5:
            self.events = self.events[-5:]

        new_song = None
        for s in segments:
            t = s.get('text', '')
            if t.startswith('(唱歌)') or t.startswith('(sing)'):
                lyric = t.replace('(唱歌)', '').replace('(sing)', '').strip()
                if lyric and lyric not in self.sung_songs:
                    self.sung_songs.append(lyric)
                    new_song = lyric
                if len(self.sung_songs) > 10:
                    self.sung_songs = self.sung_songs[-10:]

        return new_song

    def get_context_text(self) -> str:
        """生成可嵌入 prompt 的上下文字符串。"""
        lines = []
        if self.events:
            lines.append("【前情提要 - 之前几轮发生了什么】")
            lines.extend(self.events[-5:])
            if self.last_position:
                lines.append(f"上轮结束时的情况: {self.last_position[:200]}")
            lines.append("请自然地在前情提要中找到可以聊的细节，穿插到本轮解说中，让听众感受到比赛的连续性。")
        if self.sung_songs:
            lines.append(f"【已唱过的歌词 - 禁止重复】以下歌词已经唱过了，本轮不要再唱相同的: {', '.join(self.sung_songs)}")
        return "\n".join(lines)


# 加载提示词配置
PROMPTS_FILE = Path(__file__).parent / "prompts.toml"
_prompts = {"describe": "", "dialogue": "", "dialogue_en": ""}
if PROMPTS_FILE.exists():
    try:
        import tomllib
        data = tomllib.loads(PROMPTS_FILE.read_text(encoding="utf-8"))
        _prompts["describe"] = data.get("describe", {}).get("prompt", "")
        _prompts["dialogue"] = data.get("dialogue", {}).get("prompt", "")
        _prompts["dialogue_en"] = data.get("dialogue_en", {}).get("prompt", _prompts["dialogue"])
        if _prompts["describe"] or _prompts["dialogue"]:
            print("[配置] 已加载 prompts.toml")
    except Exception as e:
        print(f"[警告] prompts.toml 解析失败: {e}")

SYSTEM_PROMPT_DESCRIBE = _prompts["describe"]
SYSTEM_PROMPT_BASE = _prompts["dialogue"]
SYSTEM_PROMPT_BASE_EN = _prompts["dialogue_en"]


def _find_ffmpeg() -> str | None:
    """在系统 PATH、常见路径、imageio-ffmpeg 中查找 ffmpeg。"""
    for name in ["ffmpeg.exe", "ffmpeg"]:
        path = shutil.which(name)
        if path:
            return path
    for p in [r"C:\ffmpeg\bin\ffmpeg.exe",
              r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
              Path.home() / "ffmpeg" / "bin" / "ffmpeg.exe"]:
        if Path(p).is_file():
            return str(p)
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            return exe
    except ImportError:
        pass
    return None


def compress_video(input_path: str, output_path: str, crf: int = 28) -> bool:
    """用 ffmpeg H.264 CRF 压缩视频。CRF 越大画质越低、文件越小。"""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return False
    try:
        result = subprocess.run(
            [ffmpeg, "-y", "-i", input_path,
             "-c:v", "libx264", "-preset", "fast", "-crf", str(crf),
             "-pix_fmt", "yuv420p", "-an", output_path],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            print(f"  [ffmpeg] CRF={crf} 失败: {result.stderr[-200:]}")
            return False
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception as e:
        print(f"  [ffmpeg] 异常: {e}")
        return False


def ensure_video_fits(video_path: str, tmp_dir: Path) -> str:
    """确保视频 base64 编码后不超过 50MB。不足则用 ffmpeg 逐级压缩直到达标。"""
    with open(video_path, "rb") as f:
        raw = f.read()
    b64_size_mb = len(base64.b64encode(raw)) / (1024 * 1024)

    if b64_size_mb <= MAX_BASE64_MB:
        print(f"[视频] base64 大小 {b64_size_mb:.1f}MB，无需压缩")
        return video_path

    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        print("[警告] 未找到 ffmpeg，无法压缩。请手动降低录制分辨率或时长")
        print(f"[警告] 当前 base64 大小: {b64_size_mb:.1f}MB")
        return video_path

    compressed = str(tmp_dir / f"compressed_{int(time.time())}.mp4")
    for crf in [28, 32, 35, 38, 40]:
        print(f"[压缩] 尝试 CRF={crf} ... ", end="", flush=True)
        if compress_video(video_path, compressed, crf=crf):
            with open(compressed, "rb") as f:
                new_b64_mb = len(base64.b64encode(f.read())) / (1024 * 1024)
            print(f"base64={new_b64_mb:.1f}MB")
            if new_b64_mb <= MAX_BASE64_MB:
                print(f"[压缩] 成功! {b64_size_mb:.1f}MB → {new_b64_mb:.1f}MB")
                return compressed
            if new_b64_mb < b64_size_mb * 0.6:
                print(f"  [压缩] 未达标但显著减小，使用此版本")
                return compressed
        else:
            print("失败")
    print(f"[压缩] 所有 CRF 都未达标，返回 None 跳过本轮")
    return None


def generate_commentary(video_path: str, context: CommentaryContext = None) -> list[dict]:
    """两步生成解说词：MiMo 描述场景 → DeepSeek 生成对话。"""
    video_path = ensure_video_fits(video_path, Path(video_path).parent)
    if video_path is None:
        print("[分析] 视频过大且无法压缩，跳过本轮")
        return []

    # Step 1: MiMo 描述赛场画面
    description = _mimo_describe_scene(video_path)

    # Step 2: DeepSeek 根据描述生成解说对话
    segments = _deepseek_generate_dialogue(description, context)

    return segments


def _mimo_describe_scene(video_path: str) -> str:
    """调用 MiMo-V2.5 视频理解，返回客观场景描述。"""
    client = OpenAI(api_key=MIMO_API_KEY, base_url=MIMO_BASE_URL)

    with open(video_path, "rb") as f:
        video_bytes = f.read()
    video_b64 = base64.b64encode(video_bytes).decode("utf-8")
    ext = Path(video_path).suffix.lower().lstrip('.')
    mime_map = {"mp4": "video/mp4", "avi": "video/avi", "mov": "video/quicktime", "wmv": "video/x-ms-wmv"}
    mime_type = mime_map.get(ext, "video/mp4")
    data_url = f"data:{mime_type};base64,{video_b64}"

    print(f"\n[MiMo] 正在描述视频画面... (base64: {len(video_b64)/(1024*1024):.1f}MB)")
    completion = client.chat.completions.create(
        model=MODEL_VISION,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_DESCRIBE},
            {"role": "user", "content": [
                {"type": "video_url", "video_url": {"url": data_url}, "fps": 2, "media_resolution": "default"},
                {"type": "text", "text": "请描述这段赛车游戏视频画面的内容。"}
            ]}
        ],
        max_completion_tokens=512,
        extra_body={"thinking": {"type": "disabled"}}
    )
    description = completion.choices[0].message.content.strip()
    print(f"[MiMo] 画面描述: {description}")
    return description


def _deepseek_generate_dialogue(description: str, context: CommentaryContext = None) -> list[dict]:
    """调用 DeepSeek 根据场景描述生成解说词 JSON。"""
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    system_prompt = SYSTEM_PROMPT_BASE_EN if LANGUAGE == "en" else SYSTEM_PROMPT_BASE
    if context and context.events:
        ctx_text = context.get_context_text()
        system_prompt = f"{SYSTEM_PROMPT_BASE}\n\n{ctx_text}"

    user_prompt = f"【当前赛场画面描述】\n{description}\n\n请根据以上画面描述，生成解说词JSON。"

    print(f"\n[DeepSeek] 正在生成解说对话...")
    completion = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        max_completion_tokens=2048,
        extra_body={"thinking": {"type": "disabled"}}
    )

    content = completion.choices[0].message.content
    usage = getattr(completion, 'usage', None)
    if usage:
        print(f"[DeepSeek] Token - 输入: {usage.prompt_tokens}, 输出: {usage.completion_tokens}")

    try:
        result = json.loads(content)
        segments = result.get("segments", [])
        pause_val = result.get("pause", 0)
        if context and pause_val and int(pause_val) > 0:
            context.pause_seconds = int(pause_val)
            print(f"[DeepSeek] 请求静默观赏 {context.pause_seconds} 秒")
        else:
            if context:
                context.pause_seconds = 0
        if not segments:
            raise ValueError("segments 为空")
    except (json.JSONDecodeError, ValueError) as e:
        print(f"[DeepSeek] JSON解析失败: {e}，尝试修复...")
        json_match = re.search(r'\{[\s\S]*"segments"[\s\S]*\[[\s\S]*\][\s\S]*\}', content)
        if json_match:
            result = json.loads(json_match.group())
            segments = result.get("segments", [])

    if not segments:
        print("[错误] 无法从 API 响应中提取解说词")
        print(f"[调试] 原始响应: {content[:500]}")
        return [{"speaker": "大刘", "text": "精彩的比赛正在进行中，我跟你说这节奏真不错！"},
                {"speaker": "小鹿", "text": "是的刘哥，今天的比赛一定会非常激烈！"}]

    print(f"[DeepSeek] 成功生成 {len(segments)} 段解说词")
    for i, seg in enumerate(segments):
        speaker = seg.get("speaker", "?")
        text = seg.get("text", "")
        print(f"  [{i+1}] {speaker}: {text[:60]}{'...' if len(text) > 60 else ''}")

    return segments

# ============================================================
# 3. 语音合成 (TTS)
# ============================================================
TTS_STYLE_MAP = {
    "大刘": "用退役车手大刘的风格播报。三十多岁中年男性的嗓音，略带沙哑的磁性，说话豪爽接地气，像在跟老朋友聊天。语速中等偏快，激动时会不自觉提高音量。咬字清楚，偶尔冒出\"嘿\"\"我跟你说\"这类口头禅。专业术语脱口而出但讲得很生活化，有种\"过来人\"的笃定感。",
    "小鹿": "用赛车记者小鹿的风格播报。年轻女性清亮活泼的声音，语速稍快，咬字清晰利落。语气中带着聪明和机灵劲儿，像邻家姐姐在跟你聊比赛。，时而俏皮吐槽时而认真分析，声音充满感染力。普通话标准带一点南方口音的柔软感。",
    "男": "用F1赛事专业解说员的风格播报，沉稳有力，充满专业感与爆发力，语速偏快，富有激情与权威感，仿佛置身赛场现场",
    "女": "用赛车频道女解说的风格播报，声音明亮活泼，语速偏快，充满感染力与紧张感，善于捕捉比赛细节与气氛变化",
}


def generate_tts(text: str, voice: str, style: str) -> tuple[np.ndarray, int]:
    """调用 MiMo-V2.5-TTS 生成语音，返回 (音频数据, 采样率)。"""
    client = OpenAI(api_key=MIMO_API_KEY, base_url=MIMO_BASE_URL)

    is_singing = text.startswith("(唱歌)") or text.startswith("(sing)")
    if is_singing:
        style = "用自然的唱歌方式演唱，像在KTV即兴哼唱一样，不必太专业，略带随意感，与当前解说气氛融合。不要像专业歌手表演，更像是解说员一时兴起随口唱两句。"

    completion = client.chat.completions.create(
        model=MODEL_TTS,
        messages=[
            {"role": "user", "content": style},
            {"role": "assistant", "content": text}
        ],
        extra_body={"audio": {"format": "wav", "voice": voice}}
    )

    msg_dict = completion.model_dump()
    audio_b64 = msg_dict['choices'][0]['message']['audio']['data']
    audio_bytes = base64.b64decode(audio_b64)

    audio_data, sr = sf.read(io.BytesIO(audio_bytes))
    return audio_data, sr


def generate_all_tts(segments: list[dict]) -> list[dict]:
    """为所有解说段生成语音，返回带音频数据的段列表。"""
    results = [None] * len(segments)

    def process_one(idx: int, seg: dict):
        speaker = seg.get("speaker", "大刘")
        text = seg.get("text", "")
        is_male = speaker in ("大刘", "Dave", "男")
        voice = (MALE_VOICE_EN if is_male else FEMALE_VOICE_EN) if LANGUAGE == "en" else (MALE_VOICE if is_male else FEMALE_VOICE)
        style = TTS_STYLE_MAP.get(speaker, TTS_STYLE_MAP["大刘"])

        print(f"  [TTS {idx+1}/{len(segments)}] {speaker}: {text[:40]}...")
        try:
            audio_data, sr = generate_tts(text, voice, style)
            duration = len(audio_data) / sr
            results[idx] = {
                "speaker": speaker,
                "text": text,
                "audio": audio_data,
                "sample_rate": sr,
                "duration": duration
            }
            print(f"  [TTS {idx+1}] 完成, 时长: {duration:.1f}秒")
        except Exception as e:
            print(f"  [TTS {idx+1}] 失败: {e}，重试中...")
            time.sleep(1)
            try:
                audio_data, sr = generate_tts(text, voice, style)
                duration = len(audio_data) / sr
                results[idx] = {
                    "speaker": speaker, "text": text,
                    "audio": audio_data, "sample_rate": sr, "duration": duration
                }
                print(f"  [TTS {idx+1}] 重试成功")
            except Exception as e2:
                print(f"  [TTS {idx+1}] 重试失败: {e2}，使用空音频")
                sr = 24000
                audio_data = np.zeros(int(0.5 * sr), dtype=np.float32)
                results[idx] = {
                    "speaker": speaker, "text": text,
                    "audio": audio_data, "sample_rate": sr, "duration": 0.5
                }

    print(f"\n[TTS] 开始为 {len(segments)} 段解说生成语音...")
    threads = []
    for i, seg in enumerate(segments):
        t = threading.Thread(target=process_one, args=(i, seg))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    print(f"[TTS] 全部语音生成完成")
    return results

# ============================================================
# 4. 字幕叠加 + 音频播放
# ============================================================
class SubtitleOverlay:
    """在屏幕底部居中显示带圆角的字幕悬浮窗口，宽度自适应文字。"""

    RADIUS = 18      # 圆角半径
    PAD_X = 60       # 左右留白
    PAD_Y = 30       # 上下留白
    FONT_SIZE = 20
    NAME_SIZE = 10

    def __init__(self):
        self.segments: list[dict] = []
        self.total_duration: float = 0.0
        self.start_time: float = None
        self.running: bool = True

        self.root = tk.Tk()
        self.root.title("AI赛车解说")
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        self.root.attributes('-alpha', 0.82)

        self._font = tkfont.Font(family="Microsoft YaHei", size=self.FONT_SIZE, weight="bold")
        self._name_font = tkfont.Font(family="Microsoft YaHei", size=self.NAME_SIZE)

        self.root.bind("<Button-1>", lambda e: self._close())
        self.root.protocol("WM_DELETE_WINDOW", self._close)

        self._hwnd = None
        self._tick_count = 0
        self._last_text = ""
        self._last_speaker = ""

        self.canvas = tk.Canvas(self.root, highlightthickness=0, bg=SUBTITLE_BG)
        self.canvas.pack(fill="both", expand=True)

        self._update_window("", "")
        self.root.after(100, self._grab_hwnd)

    def _update_window(self, text: str, speaker: str):
        """根据文字内容重新计算窗口尺寸并重绘圆角背景。"""
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()

        if text:
            text_w = self._font.measure(text)
        else:
            text_w = 200
        win_w = max(200, text_w + self.PAD_X * 2)
        name_h = 20 if speaker else 0
        win_h = self.FONT_SIZE + self.PAD_Y * 2 + name_h

        win_x = (screen_w - win_w) // 2
        win_y = screen_h - win_h - 40

        self.root.geometry(f"{win_w}x{win_h}+{win_x}+{win_y}")

        self.canvas.delete("all")
        self._draw_round_rect(0, 0, win_w, win_h, self.RADIUS, SUBTITLE_BG)

        if text:
            txt_y = self.PAD_Y + self.FONT_SIZE // 2
            color = MALE_COLOR if speaker in ("大刘", "Dave") else FEMALE_COLOR
            self.canvas.create_text(win_w // 2, txt_y, text=text, fill=color,
                                     font=self._font, anchor="center")
        if speaker:
            name_y = win_h - 10
            color = MALE_COLOR if speaker in ("大刘", "Dave") else FEMALE_COLOR
            self.canvas.create_text(win_w // 2, name_y, text=speaker,
                                     fill=color, font=self._name_font, anchor="s")

    def _draw_round_rect(self, x1, y1, x2, y2, r, fill_color):
        """在 Canvas 上绘制真正的圆角矩形（arc + rect）。"""
        r = min(r, (x2 - x1) // 2, (y2 - y1) // 2)

        # 四个角弧
        self.canvas.create_arc(x1, y1, x1 + 2*r, y1 + 2*r, start=90, extent=90,
                                fill=fill_color, outline="")
        self.canvas.create_arc(x2 - 2*r, y1, x2, y1 + 2*r, start=0, extent=90,
                                fill=fill_color, outline="")
        self.canvas.create_arc(x1, y2 - 2*r, x1 + 2*r, y2, start=180, extent=90,
                                fill=fill_color, outline="")
        self.canvas.create_arc(x2 - 2*r, y2 - 2*r, x2, y2, start=270, extent=90,
                                fill=fill_color, outline="")

        # 四个直边矩形
        self.canvas.create_rectangle(x1 + r, y1, x2 - r, y1 + r, fill=fill_color, outline="")
        self.canvas.create_rectangle(x1 + r, y2 - r, x2 - r, y2, fill=fill_color, outline="")
        self.canvas.create_rectangle(x1, y1 + r, x1 + r, y2 - r, fill=fill_color, outline="")
        self.canvas.create_rectangle(x2 - r, y1 + r, x2, y2 - r, fill=fill_color, outline="")

        # 中间大矩形
        self.canvas.create_rectangle(x1 + r, y1 + r, x2 - r, y2 - r, fill=fill_color, outline="")

    def reset(self, segments: list[dict], total_duration: float):
        self.segments = segments
        self.total_duration = total_duration
        self.start_time = None
        self._update_window("", "")
        self._last_text = ""
        self._last_speaker = ""

    def _grab_hwnd(self):
        try:
            self._hwnd = int(self.root.winfo_id())
        except Exception:
            self._hwnd = None

    def _force_topmost(self):
        if not self.running:
            return
        if self._hwnd is None:
            self._grab_hwnd()
            if self._hwnd is None:
                return
        try:
            HWND_TOPMOST = -1
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOACTIVATE = 0x0010
            flags = SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
            ctypes.windll.user32.SetWindowPos(
                ctypes.c_void_p(self._hwnd),
                ctypes.c_void_p(HWND_TOPMOST),
                0, 0, 0, 0, flags
            )
        except Exception:
            pass

    def start_playback(self):
        self.start_time = time.time()

    def _get_current_segment(self):
        if self.start_time is None:
            return None
        elapsed = time.time() - self.start_time
        if elapsed > self.total_duration:
            return None
        cumulative = 0.0
        for seg in self.segments:
            seg_end = cumulative + seg["duration"]
            if elapsed < seg_end:
                return seg
            cumulative = seg_end
        return None

    def tick(self):
        if not self.running:
            return False

        self._tick_count += 1
        if self._tick_count % 10 == 0:
            self._force_topmost()

        current_seg = self._get_current_segment()

        if current_seg:
            speaker = current_seg["speaker"]
            text = current_seg["text"]
            if text != self._last_text or speaker != self._last_speaker:
                self._update_window(text, speaker)
                self._last_text = text
                self._last_speaker = speaker
        else:
            if self._last_text:
                self._update_window("", "")
                self._last_text = ""
                self._last_speaker = ""

        try:
            self.root.update()
        except tk.TclError:
            return False
        return True

    def _close(self):
        self.running = False
        try:
            self.root.destroy()
        except Exception:
            pass

    def destroy(self):
        self._close()


def play_commentary(segments: list[dict], overlay: SubtitleOverlay = None):
    """播放解说音频并在屏幕上显示字幕。overlay 为 None 时自动创建。"""
    if not segments:
        print("[播放] 无解说内容可播放")
        return

    print(f"\n[播放] 准备播放 {len(segments)} 段解说...")

    # 拼接音频并计算时间轴
    sr = segments[0]["sample_rate"]
    all_audio_parts = []
    cumulative = 0.0
    for seg in segments:
        if seg["sample_rate"] != sr:
            ratio = sr / seg["sample_rate"]
            n_samples = int(len(seg["audio"]) * ratio)
            old_idx = np.arange(len(seg["audio"]))
            new_idx = np.linspace(0, len(seg["audio"]) - 1, n_samples)
            seg["audio"] = np.interp(new_idx, old_idx, seg["audio"]).astype(np.float32)
            seg["sample_rate"] = sr
            seg["duration"] = len(seg["audio"]) / sr
        all_audio_parts.append(seg["audio"])
        seg["_start"] = cumulative
        cumulative += seg["duration"]
        seg["_end"] = cumulative

    concatenated = np.concatenate(all_audio_parts)
    total_duration = len(concatenated) / sr

    print(f"[播放] 总时长: {total_duration:.1f}秒 (采样率: {sr}Hz)")

    own_overlay = overlay is None
    if own_overlay:
        overlay = SubtitleOverlay()
    overlay.reset(segments, total_duration)

    sd.play(concatenated, samplerate=sr)
    overlay.start_playback()

    print("[播放] 开始播放 (点击字幕窗口可关闭)\n")

    # 轮询刷新字幕直到音频播完
    while overlay.running:
        elapsed = time.time() - overlay.start_time
        if elapsed >= total_duration + 0.3:
            break
        if not overlay.tick():
            break
        time.sleep(0.05)

    if own_overlay:
        overlay.destroy()

    sd.stop()

# ============================================================
# 5. 主流程
# ============================================================
ENV_FILE = Path(__file__).parent / ".env"


def save_api_key(mimo_key: str = "", deepseek_key: str = ""):
    """增量更新 .env 文件中的 API Key，不会覆盖未传入的 Key。"""
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()

    if mimo_key:
        env["MIMO_API_KEY"] = mimo_key
    if deepseek_key:
        env["DEEPSEEK_API_KEY"] = deepseek_key

    lines = [f"{k}={v}" for k, v in env.items() if v]
    ENV_FILE.write_text("\n".join(lines), encoding="utf-8")
    print("[配置] .env 已更新")


def delete_api_key():
    """删除 .env 中保存的 API Key。"""
    if ENV_FILE.exists():
        ENV_FILE.unlink()
        print("[配置] .env 已删除")
        return True
    return False


def _validate_api_key():
    global MIMO_API_KEY
    just_entered = False
    if not MIMO_API_KEY:
        MIMO_API_KEY = input("\n请输入 MiMo API Key: ").strip()
        just_entered = True
        if not MIMO_API_KEY:
            print("[错误] 未提供 API Key，请在 https://platform.xiaomimimo.com/console/balance 获取")
            print("或创建 .env 文件设置 MIMO_API_KEY=your_key")
            sys.exit(1)
    print("\n[验证] 正在验证 API Key...")
    try:
        client = OpenAI(api_key=MIMO_API_KEY, base_url=MIMO_BASE_URL)
        client.models.list()
        print("[验证] API Key 有效")
        if just_entered:
            save_api_key(mimo_key=MIMO_API_KEY, deepseek_key=DEEPSEEK_API_KEY)
    except Exception as e:
        print(f"[错误] API Key 验证失败: {e}")
        sys.exit(1)


def _run_single_cycle(tmp_dir: Path, cycle_num: int = 0, auto: bool = False,
                      context: CommentaryContext = None,
                      overlay: SubtitleOverlay = None):
    """执行一轮: 录制→分析→TTS→播放。返回更新后的上下文。"""
    if context is None:
        context = CommentaryContext()

    if auto:
        video_path = str(tmp_dir / f"screen_record_{cycle_num}.mp4")
        print(f"\n[自动] 第 {cycle_num} 轮: 开始录制...")
        video_path = record_screen(video_path, duration=RECORD_DURATION, fps=RECORD_FPS)
    else:
        video_path = str(tmp_dir / "screen_record.mp4")
        video_path = record_screen(video_path, duration=RECORD_DURATION, fps=RECORD_FPS)

    segments = generate_commentary(video_path, context=context)
    if not segments:
        print("[警告] 未生成解说词，跳过本轮播放")
        if os.path.exists(video_path):
            os.remove(video_path)
        return context

    # 更新上下文（在播放前记录，这样下一轮能看到）
    context.update(segments)

    if not auto:
        print("\n" + "=" * 60)
        print("  生成的解说词预览")
        print("=" * 60)
        for i, seg in enumerate(segments):
            print(f"  [{i+1}] {seg['speaker']}: {seg['text']}")
        print("=" * 60)
        if input("\n是否继续生成语音? (Y/n): ").strip().lower() == 'n':
            print("已取消")
            if os.path.exists(video_path):
                os.remove(video_path)
            return context

    segments_with_audio = generate_all_tts(segments)
    print(f"\n[播放] 开始播放解说 (第{cycle_num}轮)...")
    play_commentary(segments_with_audio, overlay=overlay)

    if os.path.exists(video_path):
        try:
            os.remove(video_path)
        except Exception:
            pass

    return context


def _run_loop_mode(tmp_dir: Path, max_cycles: int = 0):
    """自动循环模式: 无限轮录制→分析→TTS→播放，带跨轮次上下文。"""
    print("\n[循环] 自动循环模式启动 (Ctrl+C 退出)")
    print("[循环] 每轮流程: 录制30秒 → AI分析 → 语音合成 → 播放解说")
    print("[循环] 上下文会在轮次间累积，解说员会引用之前发生的事")

    context = CommentaryContext()
    overlay = SubtitleOverlay()
    cycle = 0
    try:
        while True:
            if max_cycles > 0 and cycle >= max_cycles:
                break
            cycle += 1
            print(f"\n[循环] 上下文已累积 {len(context.events)} 轮历史")
            try:
                context = _run_single_cycle(tmp_dir, cycle_num=cycle, auto=True,
                                            context=context, overlay=overlay)
            except KeyboardInterrupt:
                print("\n[循环] 用户中断")
                break
            except Exception as e:
                print(f"[循环] 第 {cycle} 轮出错: {e}，2秒后重试...")
                import traceback
                traceback.print_exc()
                time.sleep(2)
            print(f"\n[循环] 第 {cycle} 轮完成，即将开始下一轮...")
    finally:
        overlay.destroy()


def _run_single_mode(tmp_dir: Path, video_path: str = ""):
    """单次模式: 用户选择录制或使用已有视频。"""
    print("\n请选择视频来源:")
    print("  1. 录制屏幕 (30秒)")
    print("  2. 使用已有视频文件")
    choice = input("请输入选项 (1/2, 默认1): ").strip() or "1"

    if choice == "2":
        if not video_path:
            video_path = input("请输入视频文件路径: ").strip()
        if not os.path.isfile(video_path):
            print(f"[错误] 文件不存在: {video_path}")
            sys.exit(1)
        print(f"[信息] 使用已有视频: {video_path}")

        segments = generate_commentary(video_path)
        if not segments:
            print("[错误] 未能生成任何解说词")
            sys.exit(1)

        print("\n" + "=" * 60)
        print("  生成的解说词预览")
        print("=" * 60)
        for i, seg in enumerate(segments):
            print(f"  [{i+1}] {seg['speaker']}: {seg['text']}")
        print("=" * 60)

        if input("\n是否继续生成语音? (Y/n): ").strip().lower() == 'n':
            print("已取消")
            sys.exit(0)

        segments_with_audio = generate_all_tts(segments)
        play_commentary(segments_with_audio, overlay=overlay)
    else:
        print("\n请打开你的赛车游戏或赛车视频，准备好后按 Enter 开始录制...")
        input()
        _run_single_cycle(tmp_dir, cycle_num=1, auto=False)


def main():
    loop_mode = "--loop" in sys.argv or "-l" in sys.argv
    max_cycles = 0
    video_file = ""

    for i, arg in enumerate(sys.argv):
        if arg in ("--count", "-c") and i + 1 < len(sys.argv):
            try:
                max_cycles = int(sys.argv[i + 1])
            except ValueError:
                pass
        if arg in ("--file", "-f") and i + 1 < len(sys.argv):
            video_file = sys.argv[i + 1]

    print("=" * 60)
    print("  TrackTalk")
    print("  基于小米 MiMo-V2.5 系列模型")
    if loop_mode:
        print("  模式: 自动循环")
    print("=" * 60)

    _validate_api_key()

    tmp_dir = Path(tempfile.gettempdir()) / "racing_commentator"
    tmp_dir.mkdir(exist_ok=True)

    try:
        if loop_mode:
            _run_loop_mode(tmp_dir, max_cycles=max_cycles)
        else:
            _run_single_mode(tmp_dir, video_path=video_file)
    except KeyboardInterrupt:
        print("\n已退出")
    finally:
        print("\n解说结束，感谢使用!")


if __name__ == "__main__":
    import argparse
    main()
