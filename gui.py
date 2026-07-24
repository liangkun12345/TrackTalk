"""
TrackTalk - GUI 界面
提供配置、窗口选择、字幕位置设置、一键启停等功能。
"""

import os
import sys
from pathlib import Path

def _log(msg):
    """写日志到文件和 stderr，确保可见。"""
    import traceback as _tb
    try:
        with open(Path(__file__).parent / "gui_debug.log", "a", encoding="utf-8") as f:
            f.write(f"{msg}\n")
    except Exception:
        pass
    try:
        sys.stderr.write(f"{msg}\n")
        sys.stderr.flush()
    except Exception:
        pass

_log("gui.py 模块开始加载")
import time
import random
import queue
import threading
import ctypes
import tkinter as tk
from tkinter import ttk, messagebox

sys.path.insert(0, str(Path(__file__).parent))
import main as engine


class RacingCommentatorGUI:
    """主 GUI 窗口。"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("TrackTalk")
        self.root.geometry("520x480")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.root.attributes('-topmost', True)
        self.root.after(500, lambda: self.root.attributes('-topmost', False))

        self._running = False
        self._thread = None
        self._msg_queue = queue.Queue()
        self._overlay: engine.SubtitleOverlay | None = None
        self._audio_stream_active = False

        self._api_key_var = tk.StringVar(value=engine.MIMO_API_KEY)
        self._deepseek_key_var = tk.StringVar(value=engine.DEEPSEEK_API_KEY)
        self._lang_var = tk.StringVar(value=engine.LANGUAGE)
        self._duration_var = tk.IntVar(value=engine.RECORD_DURATION)
        self._width_var = tk.IntVar(value=engine.TARGET_WIDTH)
        self._height_var = tk.IntVar(value=engine.TARGET_HEIGHT)
        self._subtitle_pos_var = tk.StringVar(value="bottom")
        self._subtitle_offset_var = tk.IntVar(value=40)
        self._monitor_var = tk.StringVar(value="")
        self._monitors: dict = {}

        self._build_ui()
        self.root.after(100, self._init_monitors)
        self._process_queue()
        self.root.mainloop()

    # ================================================================
    # 显示器枚举
    # ================================================================
    def _init_monitors(self):
        """延迟初始化显示器列表，避免启动时卡住。"""
        self._monitors = self._enum_monitors()
        if self._monitors:
            keys = list(self._monitors.keys())
            self._mon_combo["values"] = keys
            self._monitor_var.set(keys[1] if len(keys) > 1 else keys[0])

    def _enum_monitors(self) -> dict:
        """用 mss 枚举所有显示器。"""
        try:
            import mss
            sct = mss.MSS()
            result = {}
            for i, m in enumerate(sct.monitors):
                if i == 0:
                    result["所有显示器 (0)"] = m
                else:
                    result[f"显示器 {i} ({m['width']}x{m['height']})"] = m
            return result
        except Exception:
            return {"主显示器": None}

    # ================================================================
    # UI 构建
    # ================================================================
    def _build_ui(self):
        pad = {"padx": 10, "pady": 5}
        main_frame = ttk.Frame(self.root, padding=15)
        main_frame.pack(fill="both", expand=True)

        # ---- 标题 ----
        ttk.Label(main_frame, text="TrackTalk",
                  font=("Microsoft YaHei", 16, "bold")).pack(anchor="center", **pad)

        nb = ttk.Notebook(main_frame)
        nb.pack(fill="both", expand=True, pady=10)
        nb.add(self._build_config_tab(nb), text="配置")
        nb.add(self._build_display_tab(nb), text="字幕 & 窗口")
        nb.add(self._build_log_tab(nb), text="日志")

        # ---- 控制按钮 ----
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill="x", pady=(10, 0))
        self._start_btn = ttk.Button(btn_frame, text="▶  开始录制解说",
                                     command=self._start, width=22)
        self._start_btn.pack(side="left", padx=5)
        self._stop_btn = ttk.Button(btn_frame, text="⏹  停止",
                                    command=self._stop, width=10, state="disabled")
        self._stop_btn.pack(side="left", padx=5)

        self._status_label = ttk.Label(main_frame, text="状态: 就绪", foreground="gray")
        self._status_label.pack(anchor="w", **pad)

    def _build_config_tab(self, parent):
        f = ttk.Frame(parent, padding=10)
        pad = {"padx": 5, "pady": 6, "sticky": "w"}

        # API Key
        ttk.Label(f, text="MiMo API Key:").grid(row=0, column=0, **pad)
        key_frame = ttk.Frame(f)
        key_frame.grid(row=0, column=1, columnspan=2, sticky="w")
        key_entry = ttk.Entry(key_frame, textvariable=self._api_key_var, width=38, show="*")
        key_entry.pack(side="left")
        ttk.Button(key_frame, text="验证并保存", command=self._verify_key, width=10).pack(side="left", padx=3)
        ttk.Button(key_frame, text="删除", command=self._delete_key, width=5).pack(side="left")

        # DeepSeek API Key
        ttk.Label(f, text="DeepSeek API Key:").grid(row=1, column=0, **pad)
        dk_frame = ttk.Frame(f)
        dk_frame.grid(row=1, column=1, columnspan=2, sticky="w")
        ttk.Entry(dk_frame, textvariable=self._deepseek_key_var, width=38, show="*").pack(side="left")
        ttk.Button(dk_frame, text="验证并保存", command=self._verify_deepseek_key, width=10).pack(side="left", padx=3)
        ttk.Button(dk_frame, text="删除", command=self._delete_deepseek_key, width=5).pack(side="left")

        # 录制时长
        ttk.Label(f, text="录制时长 (秒):").grid(row=2, column=0, **pad)
        dur_combo = ttk.Combobox(f, textvariable=self._duration_var,
                                 values=[10, 15, 20, 25, 30], width=10)
        dur_combo.grid(row=2, column=1, **pad)

        # 分辨率
        ttk.Label(f, text="分辨率:").grid(row=3, column=0, **pad)
        res_frame = ttk.Frame(f)
        res_frame.grid(row=3, column=1, **pad)
        ttk.Entry(res_frame, textvariable=self._width_var, width=6).pack(side="left")
        ttk.Label(res_frame, text=" x ").pack(side="left")
        ttk.Entry(res_frame, textvariable=self._height_var, width=6).pack(side="left")
        res_values = ["640x360", "854x480", "960x540", "1280x720"]
        ttk.Combobox(res_frame, values=res_values, width=10,
                     state="readonly").pack(side="left", padx=5)
        self._res_combo = res_frame.winfo_children()[-1]
        self._res_combo.bind("<<ComboboxSelected>>", self._on_res_selected)

        # 男声 / 女声
        self._male_voice_label = ttk.Label(f, text=engine.MALE_VOICE)
        self._female_voice_label = ttk.Label(f, text=engine.FEMALE_VOICE)
        ttk.Label(f, text="男解说音色:").grid(row=4, column=0, **pad)
        self._male_voice_label.grid(row=4, column=1, **pad)
        ttk.Label(f, text="女解说音色:").grid(row=5, column=0, **pad)
        self._female_voice_label.grid(row=5, column=1, **pad)

        # 语言
        ttk.Label(f, text="解说语言:").grid(row=6, column=0, **pad)
        lang_frame = ttk.Frame(f)
        lang_frame.grid(row=6, column=1, **pad)
        ttk.Radiobutton(lang_frame, text="中文", variable=self._lang_var,
                        value="zh", command=self._on_lang_change).pack(side="left")
        ttk.Radiobutton(lang_frame, text="English", variable=self._lang_var,
                        value="en", command=self._on_lang_change).pack(side="left", padx=15)

        return f

    def _build_display_tab(self, parent):
        f = ttk.Frame(parent, padding=10)
        pad = {"padx": 5, "pady": 6, "sticky": "w"}

        # 字幕位置
        ttk.Label(f, text="字幕位置:").grid(row=0, column=0, **pad)
        pos_frame = ttk.Frame(f)
        pos_frame.grid(row=0, column=1, **pad)
        ttk.Radiobutton(pos_frame, text="底部", variable=self._subtitle_pos_var,
                        value="bottom").pack(side="left")
        ttk.Radiobutton(pos_frame, text="顶部", variable=self._subtitle_pos_var,
                        value="top").pack(side="left", padx=15)

        # 字幕偏移
        ttk.Label(f, text="屏幕边距 (px):").grid(row=1, column=0, **pad)
        ttk.Scale(f, from_=0, to=200, variable=self._subtitle_offset_var,
                  orient="horizontal", length=200).grid(row=1, column=1, **pad)
        ttk.Label(f, textvariable=self._subtitle_offset_var, width=4).grid(row=1, column=2)

        # 显示器选择
        ttk.Label(f, text="录制显示器:").grid(row=2, column=0, **pad)
        self._mon_combo = ttk.Combobox(f, textvariable=self._monitor_var,
                                       values=["加载中..."],
                                       width=35, state="readonly")
        self._mon_combo.grid(row=2, column=1, columnspan=2, **pad)

        # 颜色预览
        ttk.Label(f, text="男解说颜色:").grid(row=3, column=0, **pad)
        male_preview = tk.Label(f, text="  ■■■  ", fg=engine.MALE_COLOR,
                                bg="#222222", font=("", 12))
        male_preview.grid(row=3, column=1, **pad)

        ttk.Label(f, text="女解说颜色:").grid(row=4, column=0, **pad)
        female_preview = tk.Label(f, text="  ■■■  ", fg=engine.FEMALE_COLOR,
                                  bg="#222222", font=("", 12))
        female_preview.grid(row=4, column=1, **pad)

        return f

    def _build_log_tab(self, parent):
        f = ttk.Frame(parent, padding=5)
        self._log_text = tk.Text(f, height=14, width=70, bg="#1a1a1a", fg="#cccccc",
                                 font=("Consolas", 9), wrap="word", state="disabled")
        scroll = ttk.Scrollbar(f, command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=scroll.set)
        self._log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return f

    # ================================================================
    # 事件处理
    # ================================================================
    def _on_res_selected(self, event):
        val = self._res_combo.get()
        if "x" in val:
            w, h = val.split("x")
            self._width_var.set(int(w))
            self._height_var.set(int(h))

    def _on_lang_change(self):
        lang = self._lang_var.get()
        if lang == "en":
            self._male_voice_label.config(text=engine.MALE_VOICE_EN)
            self._female_voice_label.config(text=engine.FEMALE_VOICE_EN)
        else:
            self._male_voice_label.config(text=engine.MALE_VOICE)
            self._female_voice_label.config(text=engine.FEMALE_VOICE)

    def _verify_key(self):
        key = self._api_key_var.get().strip()
        if not key:
            messagebox.showwarning("提示", "请先输入 API Key")
            return
        engine.MIMO_API_KEY = key
        try:
            from openai import OpenAI
            client = OpenAI(api_key=key, base_url=engine.MIMO_BASE_URL)
            client.models.list()
            engine.save_api_key(key)
            messagebox.showinfo("成功", "API Key 验证通过，已保存到 .env!")
            self._log("API Key 验证通过并保存")
        except Exception as e:
            messagebox.showerror("失败", f"验证失败: {e}")
            self._log(f"[错误] API Key 验证失败: {e}")

    def _delete_key(self):
        if messagebox.askyesno("确认", "确定要删除已保存的 MiMo Key 吗？"):
            engine.delete_api_key()
            self._api_key_var.set("")
            engine.MIMO_API_KEY = ""
            if engine.DEEPSEEK_API_KEY:
                engine.save_api_key("", deepseek_key=engine.DEEPSEEK_API_KEY)
            self._log("MiMo Key 已删除")

    def _verify_deepseek_key(self):
        key = self._deepseek_key_var.get().strip()
        if not key:
            messagebox.showwarning("提示", "请先输入 DeepSeek API Key")
            return
        engine.DEEPSEEK_API_KEY = key
        try:
            from openai import OpenAI
            client = OpenAI(api_key=key, base_url=engine.DEEPSEEK_BASE_URL)
            client.models.list()
            engine.save_api_key(engine.MIMO_API_KEY, deepseek_key=key)
            messagebox.showinfo("成功", "DeepSeek Key 验证通过，已保存到 .env!")
            self._log("DeepSeek Key 验证通过并保存")
        except Exception as e:
            messagebox.showerror("失败", f"验证失败: {e}")
            self._log(f"[错误] DeepSeek Key 验证失败: {e}")

    def _delete_deepseek_key(self):
        if messagebox.askyesno("确认", "确定要删除已保存的 DeepSeek Key 吗？"):
            engine.delete_api_key()
            self._deepseek_key_var.set("")
            engine.DEEPSEEK_API_KEY = ""
            # 重新保存仅 mimo key
            if engine.MIMO_API_KEY:
                engine.save_api_key(engine.MIMO_API_KEY)
            self._log("DeepSeek Key 已删除")

    def _start(self):
        key = self._api_key_var.get().strip()
        dk = self._deepseek_key_var.get().strip()
        if not key:
            messagebox.showwarning("提示", "请先配置并验证 MiMo API Key")
            return

        engine.MIMO_API_KEY = key
        engine.DEEPSEEK_API_KEY = dk
        engine.LANGUAGE = self._lang_var.get()
        engine.RECORD_DURATION = self._duration_var.get()
        engine.TARGET_WIDTH = self._width_var.get()
        engine.TARGET_HEIGHT = self._height_var.get()

        self._running = True
        self._start_btn.config(state="disabled")
        self._stop_btn.config(state="normal")
        self._status_label.config(text="状态: 运行中...", foreground="green")
        self._log("===== 开始解说 =====")
        self._log(f"设置: {engine.RECORD_DURATION}秒, "
                  f"{engine.TARGET_WIDTH}x{engine.TARGET_HEIGHT}")

        self._thread = threading.Thread(target=self._cycle_thread, daemon=True)
        self._thread.start()

    def _stop(self):
        self._running = False
        self._start_btn.config(state="normal")
        self._stop_btn.config(state="disabled")
        self._status_label.config(text="状态: 已停止", foreground="gray")
        self._log("===== 用户停止 =====")

    def _on_close(self):
        self._running = False
        if self._overlay:
            self._overlay.destroy()
        self.root.destroy()

    # ================================================================
    # 日志
    # ================================================================
    def _log(self, msg: str):
        self._msg_queue.put(("log", msg))

    def _write_log(self, msg: str):
        self._log_text.config(state="normal")
        self._log_text.insert("end", msg + "\n")
        self._log_text.see("end")
        self._log_text.config(state="disabled")
        self._log_text.yview_moveto(1.0)

    # ================================================================
    # 后台线程
    # ================================================================
    def _cycle_thread(self):
        """录制→分析→TTS 循环（后台线程）。录制与上一轮播放并行。"""
        import tempfile
        tmp_dir = Path(tempfile.gettempdir()) / "racing_commentator"
        tmp_dir.mkdir(exist_ok=True)

        context = engine.CommentaryContext()
        cycle = 0
        record_sec = engine.RECORD_DURATION  # 动态时长，初始用默认值

        while self._running:
            cycle += 1

            # 随机间隔，避免说话太密集
            delay = random.randint(5, 15)
            self._msg_queue.put(("log", f"\n--- 第 {cycle} 轮 ({delay}秒后录制) ---"))
            self._msg_queue.put(("status", f"状态: {delay}秒后开始录制..."))
            for _ in range(delay):
                if not self._running:
                    break
                time.sleep(1)

            if not self._running:
                break

            try:
                self._msg_queue.put(("log", f"\n--- 第 {cycle} 轮 (录制{record_sec}秒) ---"))
                self._msg_queue.put(("status", f"状态: 第{cycle}轮 录制中..."))

                # 1. 录制（与上一轮播放并行进行）
                video_path = str(tmp_dir / f"screen_record_{cycle}.mp4")
                monitor = self._get_selected_monitor()
                self._msg_queue.put(("log", f"[录制] 录制 {record_sec} 秒..."))
                video_path = engine.record_screen(video_path, duration=record_sec,
                                                   fps=engine.RECORD_FPS,
                                                   target_w=engine.TARGET_WIDTH,
                                                   target_h=engine.TARGET_HEIGHT)

                # 2. 分析
                self._msg_queue.put(("log", "[分析] 发送视频到 MiMo..."))
                self._msg_queue.put(("status", f"状态: 第{cycle}轮 AI分析中..."))
                segments = engine.generate_commentary(video_path, context=context)
                if not segments:
                    self._msg_queue.put(("log", "[警告] 未生成解说词，跳过"))
                    self._cleanup_video(video_path)
                    continue
                new_song = context.update(segments)
                if new_song:
                    self._msg_queue.put(("log", f"🎶 唱歌: {new_song}"))

                # 3. TTS
                self._msg_queue.put(("log", f"[TTS] 生成 {len(segments)} 段语音..."))
                self._msg_queue.put(("status", f"状态: 第{cycle}轮 语音合成中..."))
                segments_audio = engine.generate_all_tts(segments)

                # 根据本轮 TTS 总时长动态调整下次录制时长
                tts_total = sum(s.get("duration", 0) for s in segments_audio)
                record_sec = max(6, min(int(tts_total + 5), 15))
                self._msg_queue.put(("log", f"[动态] TTS时长={tts_total:.1f}秒 → 下次录制={record_sec}秒"))

                # 4. 等待上一轮播放结束再提交本轮
                while self._running and self._audio_stream_active:
                    time.sleep(0.05)

                self._msg_queue.put(("play", segments_audio))
                self._msg_queue.put(("log", f"[播放] 第{cycle}轮开始播放 (约{tts_total:.1f}秒)"))
                self._msg_queue.put(("status", f"状态: 第{cycle}轮 播放中..."))

                self._cleanup_video(video_path)

                # 5. 静默观赏模式：AI 请求暂停录制
                if context.pause_seconds > 0:
                    pause_sec = context.pause_seconds
                    self._msg_queue.put(("log", f"[静默] AI 请求静默观赏 {pause_sec} 秒，暂停录制..."))
                    for _ in range(pause_sec):
                        if not self._running:
                            break
                        remaining = max(0, pause_sec - _)
                        if remaining % 10 == 0:
                            self._msg_queue.put(("status", f"状态: 静默观赏中... {remaining}秒"))
                        time.sleep(1)
                    context.pause_seconds = 0
                    self._msg_queue.put(("log", "[静默] 静默结束，恢复录制"))

            except Exception as e:
                self._msg_queue.put(("log", f"[错误] 第{cycle}轮: {e}"))
                import traceback
                self._msg_queue.put(("log", traceback.format_exc()))
                time.sleep(2)

        self._msg_queue.put(("log", "循环已退出"))
        self._msg_queue.put(("status", "状态: 已停止"))
        self._msg_queue.put(("done",))

    def _get_selected_monitor(self):
        """返回用户选择的 mss monitor 字典。"""
        mon_name = self._monitor_var.get()
        return self._monitors.get(mon_name, None)

    def _cleanup_video(self, path):
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    # ================================================================
    # 队列处理 (主线程 via after)
    # ================================================================
    def _process_queue(self):
        """每 100ms 检查消息队列，处理来自后台线程的消息。"""
        try:
            while True:
                msg = self._msg_queue.get_nowait()
                msg_type = msg[0]

                if msg_type == "log":
                    self._write_log(msg[1])
                elif msg_type == "status":
                    self._status_label.config(text=msg[1])
                elif msg_type == "play":
                    self._start_playback(msg[1])
                elif msg_type == "done":
                    pass  # 线程已退出

        except queue.Empty:
            pass

        # 如果正在播放，驱动字幕刷新
        if self._overlay and self._overlay.running and self._audio_stream_active:
            elapsed = time.time() - self._overlay.start_time
            if elapsed >= self._overlay.total_duration + 0.3:
                self._audio_stream_active = False
            else:
                self._overlay.tick()

        self.root.after(100, self._process_queue)

    def _start_playback(self, segments_audio):
        """在主线程中创建/更新字幕叠加层并播放音频。"""
        import numpy as np
        import sounddevice as sd

        if not segments_audio:
            return

        # 拼接音频
        sr = segments_audio[0]["sample_rate"]
        parts = []
        cumulative = 0.0
        for seg in segments_audio:
            if seg["sample_rate"] != sr:
                ratio = sr / seg["sample_rate"]
                n = int(len(seg["audio"]) * ratio)
                old_idx = np.arange(len(seg["audio"]))
                new_idx = np.linspace(0, len(seg["audio"]) - 1, n)
                seg["audio"] = np.interp(new_idx, old_idx, seg["audio"]).astype(np.float32)
                seg["sample_rate"] = sr
                seg["duration"] = len(seg["audio"]) / sr
            parts.append(seg["audio"])
            seg["_start"] = cumulative
            cumulative += seg["duration"]
            seg["_end"] = cumulative

        concatenated = np.concatenate(parts)
        total_duration = len(concatenated) / sr

        # 创建或重置字幕窗口
        if self._overlay is None:
            self._overlay = engine.SubtitleOverlay()

        self._overlay.reset(segments_audio, total_duration)

        # 播放音频
        sd.play(concatenated, samplerate=sr)
        self._overlay.start_playback()
        self._audio_stream_active = True

def main():
    gui = RacingCommentatorGUI()


if __name__ == "__main__":
    main()
