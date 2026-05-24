from __future__ import annotations
import re
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from ascii_art import converter
from ascii_art import settings as cfg
from ascii_art import database as db


def _strip_ansi(text: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", text)


_COLOR_TOKEN_RE = re.compile(r"\033\[38;2;(\d+);(\d+);(\d+)m(.)\033\[0m")


def _parse_colored(text: str) -> list[tuple[str | None, str]]:
    """Split ANSI-colored text into (hex_color | None, chars) batched runs."""
    runs: list[tuple[str | None, str]] = []

    def push(color: str | None, s: str) -> None:
        if runs and runs[-1][0] == color:
            runs[-1] = (color, runs[-1][1] + s)
        else:
            runs.append((color, s))

    pos = 0
    for m in _COLOR_TOKEN_RE.finditer(text):
        if m.start() > pos:
            push(None, text[pos:m.start()])
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        push(f"#{r:02x}{g:02x}{b:02x}", m.group(4))
        pos = m.end()
    if pos < len(text):
        push(None, text[pos:])
    return runs


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Конвертер изображений в ASCII-арт")
        self.geometry("1100x650")
        self.minsize(800, 500)

        self._settings = cfg.load()
        self._image_paths: list[str] = []
        self._current_result = ""
        self._debounce_id: str | None = None
        self._color_tags: set[str] = set()

        self._frames: list[tuple[str, int]] = []
        self._frame_idx = 0
        self._anim_id: str | None = None
        self._paused = False
        self._convert_gen = 0

        self._current_image_id: int | None = None
        self._current_conversion_id: int | None = None
        db.init_db()

        self._build_ui()

    def _build_ui(self) -> None:
        left = ttk.Frame(self, width=255, padding=(10, 10))
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 2))
        left.pack_propagate(False)

        ttk.Label(left, text="Изображения", font=("TkDefaultFont", 10, "bold")).pack(anchor=tk.W)
        btn_row = ttk.Frame(left)
        btn_row.pack(fill=tk.X, pady=(4, 2))
        ttk.Button(btn_row, text="Открыть…", command=self._open_files, width=10).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="Очистить", command=self._clear_files, width=8).pack(side=tk.LEFT, padx=4)
        self._listbox = tk.Listbox(left, height=5, selectmode=tk.SINGLE, activestyle="dotbox")
        self._listbox.pack(fill=tk.X, pady=(2, 8))
        self._listbox.bind("<<ListboxSelect>>", self._on_file_select)

        ttk.Separator(left).pack(fill=tk.X, pady=4)

        ttk.Label(left, text="Ширина (символов):").pack(anchor=tk.W)
        self._width_var = tk.StringVar(value=str(self._settings["width"]))
        ttk.Spinbox(left, from_=10, to=300, textvariable=self._width_var, width=8).pack(
            anchor=tk.W, pady=(2, 6)
        )
        self._width_var.trace_add("write", self._schedule_convert)

        self._height_auto = tk.BooleanVar(value=self._settings["height_auto"])
        ttk.Checkbutton(
            left, text="Высота авто", variable=self._height_auto, command=self._on_height_auto
        ).pack(anchor=tk.W)
        self._height_var = tk.StringVar(value=str(self._settings["height"]))
        self._height_spin = ttk.Spinbox(
            left, from_=5, to=300, textvariable=self._height_var, width=8
        )
        self._height_spin.pack(anchor=tk.W, pady=(2, 8))
        self._height_var.trace_add("write", self._schedule_convert)
        # sync state without scheduling (called before _anim_btn exists)
        self._height_spin.configure(
            state=tk.DISABLED if self._height_auto.get() else tk.NORMAL
        )

        ttk.Separator(left).pack(fill=tk.X, pady=4)

        ttk.Label(left, text="Набор символов:").pack(anchor=tk.W)
        self._charset_var = tk.StringVar(value=self._settings["charset"])
        for name in converter.CHAR_SETS:
            ttk.Radiobutton(
                left, text=name.capitalize(), variable=self._charset_var,
                value=name, command=self._schedule_convert,
            ).pack(anchor=tk.W)

        ttk.Separator(left).pack(fill=tk.X, pady=4)

        self._invert_var = tk.BooleanVar(value=self._settings["invert"])
        ttk.Checkbutton(
            left, text="Инверсия яркости", variable=self._invert_var,
            command=self._schedule_convert,
        ).pack(anchor=tk.W)
        self._color_var = tk.BooleanVar(value=self._settings["color"])
        ttk.Checkbutton(
            left, text="Цветной (ANSI)", variable=self._color_var,
            command=self._schedule_convert,
        ).pack(anchor=tk.W)

        ttk.Separator(left).pack(fill=tk.X, pady=4)

        ttk.Label(left, text="Анимация:").pack(anchor=tk.W)
        self._rotate_var = tk.BooleanVar(value=self._settings.get("rotate", False))
        ttk.Checkbutton(
            left, text="Вращать изображение", variable=self._rotate_var,
            command=self._on_rotate_change,
        ).pack(anchor=tk.W)

        row1 = ttk.Frame(left)
        row1.pack(fill=tk.X, pady=(2, 0))
        ttk.Label(row1, text="Кадров:").pack(side=tk.LEFT)
        self._n_frames_var = tk.StringVar(value=str(self._settings.get("n_frames", 24)))
        self._n_frames_spin = ttk.Spinbox(
            row1, from_=2, to=120, textvariable=self._n_frames_var, width=5
        )
        self._n_frames_spin.pack(side=tk.LEFT, padx=4)
        self._n_frames_var.trace_add("write", self._schedule_convert)

        row2 = ttk.Frame(left)
        row2.pack(fill=tk.X, pady=(2, 8))
        ttk.Label(row2, text="FPS:   ").pack(side=tk.LEFT)
        self._fps_var = tk.StringVar(value=str(self._settings.get("fps", 12)))
        self._fps_spin = ttk.Spinbox(
            row2, from_=1, to=60, textvariable=self._fps_var, width=5
        )
        self._fps_spin.pack(side=tk.LEFT, padx=4)
        self._fps_var.trace_add("write", self._schedule_convert)

        # sync spinbox state (before _anim_btn exists, no schedule)
        rot_state = tk.NORMAL if self._rotate_var.get() else tk.DISABLED
        self._n_frames_spin.configure(state=rot_state)
        self._fps_spin.configure(state=rot_state)

        ttk.Separator(left).pack(fill=tk.X, pady=4)

        ttk.Button(left, text="Конвертировать", command=self._convert_now).pack(fill=tk.X, pady=2)
        ttk.Button(left, text="Пакетная обработка…", command=self._batch).pack(fill=tk.X, pady=2)
        ttk.Button(left, text="Сохранить в .txt…", command=self._save).pack(fill=tk.X, pady=2)
        ttk.Button(left, text="Копировать в буфер", command=self._copy).pack(fill=tk.X, pady=2)
        ttk.Button(left, text="История", command=self._show_history).pack(fill=tk.X, pady=2)
        self._anim_btn = ttk.Button(
            left, text="⏸  Пауза", command=self._toggle_anim, state=tk.DISABLED
        )
        self._anim_btn.pack(fill=tk.X, pady=(6, 2))

        right = ttk.Frame(self, padding=(4, 10, 10, 10))
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ttk.Label(right, text="Предпросмотр", font=("TkDefaultFont", 10, "bold")).pack(anchor=tk.W)
        pf = ttk.Frame(right)
        pf.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        pf.columnconfigure(0, weight=1)
        pf.rowconfigure(0, weight=1)
        self._text = tk.Text(
            pf, wrap=tk.NONE, font=("Courier New", 8),
            bg="#1e1e1e", fg="#cccccc", state=tk.DISABLED,
        )
        v_sb = ttk.Scrollbar(pf, orient=tk.VERTICAL, command=self._text.yview)
        h_sb = ttk.Scrollbar(pf, orient=tk.HORIZONTAL, command=self._text.xview)
        self._text.configure(yscrollcommand=v_sb.set, xscrollcommand=h_sb.set)
        self._text.grid(row=0, column=0, sticky=tk.NSEW)
        v_sb.grid(row=0, column=1, sticky=tk.NS)
        h_sb.grid(row=1, column=0, sticky=tk.EW)

        self._status = tk.StringVar(value="Готово. Откройте изображение.")
        ttk.Label(
            self, textvariable=self._status, relief=tk.SUNKEN, anchor=tk.W, padding=(6, 2)
        ).pack(side=tk.BOTTOM, fill=tk.X)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _start_animation(self, frames: list[tuple[str, int]]) -> None:
        self._stop_animation()
        self._frames = frames
        self._frame_idx = 0
        self._paused = False
        self._anim_btn.configure(state=tk.NORMAL, text="⏸  Пауза")
        self._anim_tick()

    def _stop_animation(self) -> None:
        if self._anim_id:
            self.after_cancel(self._anim_id)
            self._anim_id = None
        self._frames = []
        self._frame_idx = 0
        self._paused = False
        if hasattr(self, "_anim_btn"):
            self._anim_btn.configure(state=tk.DISABLED, text="⏸  Пауза")

    def _toggle_anim(self) -> None:
        if self._paused:
            self._paused = False
            self._anim_btn.configure(text="⏸  Пауза")
            self._anim_tick()
        else:
            self._paused = True
            self._anim_btn.configure(text="▶  Играть")
            if self._anim_id:
                self.after_cancel(self._anim_id)
                self._anim_id = None

    def _anim_tick(self) -> None:
        if not self._frames or self._paused:
            return
        text, duration = self._frames[self._frame_idx]
        self._current_result = text
        self._set_text(text)
        self._status.set(f"Анимация: кадр {self._frame_idx + 1}/{len(self._frames)}")
        self._frame_idx = (self._frame_idx + 1) % len(self._frames)
        self._anim_id = self.after(duration, self._anim_tick)

    def _on_height_auto(self) -> None:
        self._height_spin.configure(
            state=tk.DISABLED if self._height_auto.get() else tk.NORMAL
        )
        self._schedule_convert()

    def _on_rotate_change(self) -> None:
        state = tk.NORMAL if self._rotate_var.get() else tk.DISABLED
        self._n_frames_spin.configure(state=state)
        self._fps_spin.configure(state=state)
        self._schedule_convert()

    def _schedule_convert(self, *_) -> None:
        # Never stop animation here — let it play until new result is ready
        if self._debounce_id:
            self.after_cancel(self._debounce_id)
        self._debounce_id = self.after(400, self._convert_now)

    def _open_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Выберите изображения",
            initialdir=self._settings.get("last_directory") or None,
            filetypes=[
                ("Изображения", "*.png *.jpg *.jpeg *.bmp *.gif"),
                ("Все файлы", "*.*"),
            ],
        )
        if not paths:
            return
        self._settings["last_directory"] = str(Path(paths[0]).parent)
        for p in paths:
            if p not in self._image_paths:
                self._image_paths.append(p)
                self._listbox.insert(tk.END, Path(p).name)
        self._listbox.selection_clear(0, tk.END)
        self._listbox.selection_set(tk.END)
        self._stop_animation()
        self._convert_now()

    def _clear_files(self) -> None:
        self._stop_animation()
        self._image_paths.clear()
        self._listbox.delete(0, tk.END)
        self._set_text("")
        self._current_result = ""
        self._status.set("Готово. Откройте изображение.")

    def _on_file_select(self, _=None) -> None:
        self._stop_animation()
        self._convert_now()

    def _selected_path(self) -> str | None:
        sel = self._listbox.curselection()
        if sel and sel[0] < len(self._image_paths):
            return self._image_paths[sel[0]]
        return None

    def _params(self) -> dict:
        try:
            width = max(10, min(300, int(self._width_var.get())))
        except ValueError:
            width = 120
        height = None
        if not self._height_auto.get():
            try:
                height = max(5, min(300, int(self._height_var.get())))
            except ValueError:
                pass
        try:
            n_frames = max(2, min(120, int(self._n_frames_var.get())))
        except ValueError:
            n_frames = 24
        try:
            fps = max(1, min(60, int(self._fps_var.get())))
        except ValueError:
            fps = 12
        return dict(
            width=width,
            height=height,
            charset=self._charset_var.get(),
            invert=self._invert_var.get(),
            color=self._color_var.get(),
            rotate=self._rotate_var.get(),
            n_frames=n_frames,
            fps=fps,
        )

    def _convert_now(self) -> None:
        path = self._selected_path()
        if not path:
            return
        self._convert_gen += 1
        gen = self._convert_gen
        params = self._params()
        self._status.set(f"Конвертирование: {Path(path).name}…")
        threading.Thread(target=self._worker, args=(path, params, gen), daemon=True).start()

    def _worker(self, path: str, params: dict, gen: int) -> None:
        import time
        import os
        rotate = params.pop("rotate", False)
        n_frames = params.pop("n_frames", 24)
        fps = params.pop("fps", 12)
        duration = max(16, int(1000 / max(1, fps)))

        try:
            from PIL import Image as _PIL
            _img = _PIL.open(path)
            orig_w, orig_h = _img.size
            file_size = os.path.getsize(path)
        except Exception:
            orig_w = orig_h = file_size = None
        image_id = db.add_image(Path(path).name, path, file_size, orig_w, orig_h)

        t0 = time.perf_counter()
        try:
            ext = Path(path).suffix.lower()
            if rotate:
                frames = converter.generate_rotation_frames(
                    path, **params, n_frames=n_frames, duration=duration
                )
                elapsed = time.perf_counter() - t0
                conv_id = db.add_conversion(
                    image_id, params.get("width", 120), params.get("height"),
                    params.get("charset", "standard"),
                    bool(params.get("invert", False)), bool(params.get("color", False)), "",
                )
                self.after(0, self._on_anim_done, frames, gen, elapsed, Path(path).name, image_id, conv_id)
            elif ext == ".gif":
                frames = converter.convert_gif_frames(path, **params)
                elapsed = time.perf_counter() - t0
                if len(frames) > 1:
                    conv_id = db.add_conversion(
                        image_id, params.get("width", 120), params.get("height"),
                        params.get("charset", "standard"),
                        bool(params.get("invert", False)), bool(params.get("color", False)), "",
                    )
                    self.after(0, self._on_anim_done, frames, gen, elapsed, Path(path).name, image_id, conv_id)
                else:
                    result = frames[0][0]
                    conv_id = db.add_conversion(
                        image_id, params.get("width", 120), params.get("height"),
                        params.get("charset", "standard"),
                        bool(params.get("invert", False)), bool(params.get("color", False)), result,
                    )
                    self.after(0, self._on_static_done, result, gen, elapsed, Path(path).name, image_id, conv_id)
            else:
                result = converter.convert_image(path, **params)
                elapsed = time.perf_counter() - t0
                conv_id = db.add_conversion(
                    image_id, params.get("width", 120), params.get("height"),
                    params.get("charset", "standard"),
                    bool(params.get("invert", False)), bool(params.get("color", False)), result,
                )
                self.after(0, self._on_static_done, result, gen, elapsed, Path(path).name, image_id, conv_id)
        except Exception as exc:
            if gen == self._convert_gen:
                self.after(0, self._status.set, f"Ошибка: {exc}")

    def _on_anim_done(
        self, frames: list, gen: int, elapsed: float, name: str,
        image_id: int | None = None, conv_id: int | None = None,
    ) -> None:
        if gen != self._convert_gen:
            return
        self._current_image_id = image_id
        self._current_conversion_id = conv_id
        self._start_animation(frames)
        self._status.set(f"{name} — {len(frames)} кадров ({elapsed:.2f} с)")

    def _on_static_done(
        self, result: str, gen: int, elapsed: float, name: str,
        image_id: int | None = None, conv_id: int | None = None,
    ) -> None:
        if gen != self._convert_gen:
            return
        self._current_image_id = image_id
        self._current_conversion_id = conv_id
        self._stop_animation()
        self._current_result = result
        self._set_text(result)
        self._status.set(f"{name} — готово ({elapsed:.2f} с)")

    def _set_text(self, text: str) -> None:
        if "\033[" in text:
            self._set_text_colored(text)
        else:
            self._set_text_plain(text)

    def _set_text_plain(self, text: str) -> None:
        self._text.configure(state=tk.NORMAL)
        self._text.delete("1.0", tk.END)
        self._text.insert("1.0", text)
        self._text.configure(state=tk.DISABLED)

    def _set_text_colored(self, text: str) -> None:
        self._text.configure(state=tk.NORMAL)
        self._text.delete("1.0", tk.END)
        for color, segment in _parse_colored(text):
            if color:
                tag = f"fg_{color[1:]}"
                if tag not in self._color_tags:
                    self._text.tag_configure(tag, foreground=color)
                    self._color_tags.add(tag)
                self._text.insert(tk.END, segment, tag)
            else:
                self._text.insert(tk.END, segment)
        self._text.configure(state=tk.DISABLED)

    def _save(self) -> None:
        if not self._current_result:
            messagebox.showwarning("Нет данных", "Сначала конвертируйте изображение.")
            return
        path = filedialog.asksaveasfilename(
            title="Сохранить ASCII-арт",
            defaultextension=".txt",
            filetypes=[("Текстовый файл", "*.txt"), ("Все файлы", "*.*")],
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(_strip_ansi(self._current_result))
            if self._current_conversion_id is not None:
                db.add_export(self._current_conversion_id, path, "txt")
            self._status.set(f"Сохранено: {path}")

    def _copy(self) -> None:
        if not self._current_result:
            messagebox.showwarning("Нет данных", "Сначала конвертируйте изображение.")
            return
        self.clipboard_clear()
        self.clipboard_append(_strip_ansi(self._current_result))
        self._status.set("Скопировано в буфер обмена.")

    def _batch(self) -> None:
        if not self._image_paths:
            messagebox.showwarning("Нет файлов", "Добавьте изображения для обработки.")
            return
        out_dir = filedialog.askdirectory(title="Папка для сохранения результатов")
        if not out_dir:
            return
        params = {
            k: v for k, v in self._params().items()
            if k not in ("rotate", "n_frames", "fps")
        }
        threading.Thread(
            target=self._batch_worker, args=(list(self._image_paths), params, out_dir), daemon=True
        ).start()

    def _batch_worker(self, paths: list[str], params: dict, out_dir: str) -> None:
        total = len(paths)
        for i, path in enumerate(paths, 1):
            self.after(0, self._status.set, f"Пакетная обработка {i}/{total}: {Path(path).name}…")
            try:
                ext = Path(path).suffix.lower()
                if ext == ".gif":
                    frames = converter.convert_gif_frames(path, **params)
                    for fi, (text, _) in enumerate(frames):
                        suffix = f"_{fi + 1:03d}" if len(frames) > 1 else ""
                        out_path = Path(out_dir) / (Path(path).stem + suffix + ".txt")
                        with open(out_path, "w", encoding="utf-8") as f:
                            f.write(_strip_ansi(text))
                else:
                    result = converter.convert_image(path, **params)
                    out_path = Path(out_dir) / (Path(path).stem + ".txt")
                    with open(out_path, "w", encoding="utf-8") as f:
                        f.write(_strip_ansi(result))
            except Exception as exc:
                self.after(0, self._status.set, f"Ошибка {Path(path).name}: {exc}")
        self.after(0, self._status.set, f"Пакетная обработка завершена: {total} файл(ов).")

    def _show_history(self) -> None:
        rows = db.q2_recent_history(50)
        win = tk.Toplevel(self)
        win.title("История конвертаций")
        win.geometry("760x340")
        win.resizable(True, True)

        cols = ("Файл", "Ширина", "Высота", "Набор", "Инверсия", "Цвет", "Дата")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=14)
        widths = (180, 70, 70, 90, 70, 60, 160)
        for col, w in zip(cols, widths):
            tree.heading(col, text=col)
            tree.column(col, width=w, anchor=tk.CENTER if w < 100 else tk.W)

        for row in rows:
            tree.insert("", tk.END, values=(
                row["filename"],
                row["ascii_width"],
                row["ascii_height"] if row["ascii_height"] else "авто",
                row["charset"],
                "да" if row["inverted"] else "нет",
                "да" if row["colored"] else "нет",
                row["converted_at"],
            ))

        sb = ttk.Scrollbar(win, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0), pady=6)
        sb.pack(side=tk.RIGHT, fill=tk.Y, pady=6, padx=(0, 6))

    def _on_close(self) -> None:
        self._stop_animation()
        try:
            s = self._settings
            s["width"] = int(self._width_var.get())
            s["height_auto"] = self._height_auto.get()
            s["height"] = int(self._height_var.get())
            s["charset"] = self._charset_var.get()
            s["invert"] = self._invert_var.get()
            s["color"] = self._color_var.get()
            s["rotate"] = self._rotate_var.get()
            s["n_frames"] = int(self._n_frames_var.get())
            s["fps"] = int(self._fps_var.get())
        except Exception:
            pass
        cfg.save(self._settings)
        self.destroy()
