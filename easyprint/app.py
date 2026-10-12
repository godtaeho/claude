"""간편출력 메인 화면 (tkinter)."""
from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import APP_NAME, __version__, shell
from .backend import get_backend
from .caps import PaperInfo, PrinterCaps
from .documents import FILE_DIALOG_TYPES, is_supported
from .engine import JobResult, print_files
from .presets import (DMBIN_AUTO, DMPAPER_USER, DUPLEX_LONG, DUPLEX_SHORT, DUPLEX_SIMPLEX,
                      ORIENT_LANDSCAPE, ORIENT_PORTRAIT, SCALE_ACTUAL, SCALE_FIT, Preset, PresetStore)

CUSTOM_PAPER_LABEL = "사용자 지정 크기 (mm 직접 입력)"
AUTO_BIN_LABEL = "자동 선택 (프린터 판단)"
DUPLEX_LABELS = {DUPLEX_SIMPLEX: "단면", DUPLEX_LONG: "양면 - 긴 쪽 넘김", DUPLEX_SHORT: "양면 - 짧은 쪽 넘김"}
ENVELOPE_HINTS = ("봉투", "env", "dl", "c5", "#10")


class App:
    def __init__(self, root: tk.Tk, files: list[str] | None = None, store: PresetStore | None = None,
                 backend=None):
        self.root = root
        self.backend = backend or get_backend()
        self.store = store or PresetStore.load()
        self.caps_cache: dict[str, PrinterCaps] = {}
        self.caps: PrinterCaps | None = None
        self.files: list[str] = []
        self.msgs: queue.Queue = queue.Queue()
        self.cancel_event: threading.Event | None = None
        self.worker: threading.Thread | None = None
        self._loading = False  # 프리셋 적용 중에는 '수정됨' 표시 계산을 멈춤

        root.title(f"{APP_NAME} {__version__}")
        root.minsize(620, 640)
        self._setup_style()
        self._build()
        self._load_printers()
        self._rebuild_preset_buttons()
        self.apply_preset(self.store.last_used)
        self.add_files(files or [])
        if self.store.load_warning:
            messagebox.showwarning(APP_NAME, self.store.load_warning)
        root.after(100, self._poll)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------ 화면 구성
    def _setup_style(self):
        style = ttk.Style(self.root)
        family = None
        if sys.platform == "win32":
            family = "맑은 고딕"
            for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
                try:
                    tkfont.nametofont(name).configure(family=family, size=10)
                except tk.TclError:
                    pass
        big = tkfont.nametofont("TkDefaultFont").copy()
        big.configure(size=13, weight="bold", **({"family": family} if family else {}))
        self._big_font = big
        style.configure("Preset.Toolbutton", padding=(12, 6))
        style.configure("Print.TButton", font=big, padding=(10, 8))
        style.configure("Hint.TLabel", foreground="#666")
        style.configure("Warn.TLabel", foreground="#b45309")

    def _build(self):
        r = self.root
        pad = {"padx": 10, "pady": 5}
        main = ttk.Frame(r, padding=8)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)

        # --- 저장된 형식 (즉시 전환)
        pf = ttk.LabelFrame(main, text=" 저장된 출력 형식 (클릭하면 바로 적용) ", padding=6)
        pf.grid(row=0, column=0, sticky="ew", **pad)
        pf.columnconfigure(0, weight=1)
        self.preset_var = tk.StringVar()
        self.preset_btns = ttk.Frame(pf)
        self.preset_btns.grid(row=0, column=0, sticky="w")
        tools = ttk.Frame(pf)
        tools.grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Button(tools, text="현재 형식에 덮어쓰기", command=self.save_current).pack(side="left")
        ttk.Button(tools, text="새 형식으로 저장", command=self.save_as_new).pack(side="left", padx=4)
        ttk.Button(tools, text="이름 변경", command=self.rename_preset).pack(side="left")
        ttk.Button(tools, text="◀", width=3, command=lambda: self.move_preset(-1)).pack(side="left", padx=(4, 0))
        ttk.Button(tools, text="▶", width=3, command=lambda: self.move_preset(1)).pack(side="left")
        ttk.Button(tools, text="삭제", command=self.delete_preset).pack(side="left", padx=4)
        self.modified_lbl = ttk.Label(tools, text="", style="Warn.TLabel")
        self.modified_lbl.pack(side="left", padx=6)

        # --- 1. 파일
        ff = ttk.LabelFrame(main, text=" 1. 파일 선택 ", padding=6)
        ff.grid(row=1, column=0, sticky="nsew", **pad)
        main.rowconfigure(1, weight=1)
        ff.columnconfigure(0, weight=1)
        ff.rowconfigure(0, weight=1)
        self.file_list = tk.Listbox(ff, height=6, selectmode="extended", activestyle="none")
        self.file_list.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(ff, orient="vertical", command=self.file_list.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.file_list.configure(yscrollcommand=sb.set)
        fb = ttk.Frame(ff)
        fb.grid(row=0, column=2, sticky="n", padx=(6, 0))
        ttk.Button(fb, text="파일 추가...", command=self.choose_files).pack(fill="x")
        ttk.Button(fb, text="선택 빼기", command=self.remove_selected).pack(fill="x", pady=4)
        ttk.Button(fb, text="모두 비우기", command=self.clear_files).pack(fill="x")
        ttk.Button(fb, text="▲", command=lambda: self.move_file(-1)).pack(fill="x", pady=(10, 0))
        ttk.Button(fb, text="▼", command=lambda: self.move_file(1)).pack(fill="x")
        self.file_list.bind("<Delete>", lambda e: self.remove_selected())
        ttk.Label(ff, text="PDF · 이미지 · 한글(hwp) · 워드 · 엑셀 · 파워포인트  |  "
                           "탐색기에서 '보내기 → 간편출력'으로도 추가할 수 있습니다",
                  style="Hint.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

        # --- 2. 프린터
        prf = ttk.LabelFrame(main, text=" 2. 프린터 선택 ", padding=6)
        prf.grid(row=2, column=0, sticky="ew", **pad)
        prf.columnconfigure(0, weight=1)
        self.printer_var = tk.StringVar()
        self.printer_cb = ttk.Combobox(prf, textvariable=self.printer_var, state="readonly")
        self.printer_cb.grid(row=0, column=0, sticky="ew")
        self.printer_cb.bind("<<ComboboxSelected>>", lambda e: self._on_printer_changed())
        ttk.Button(prf, text="새로고침", command=self._reload_printers).grid(row=0, column=1, padx=(6, 0))

        # --- 3. 출력 방식
        of = ttk.LabelFrame(main, text=" 3. 출력 방식 ", padding=6)
        of.grid(row=3, column=0, sticky="ew", **pad)
        of.columnconfigure(1, weight=1)

        ttk.Label(of, text="용지").grid(row=0, column=0, sticky="w")
        self.paper_var = tk.StringVar()
        self.paper_cb = ttk.Combobox(of, textvariable=self.paper_var, state="readonly")
        self.paper_cb.grid(row=0, column=1, columnspan=3, sticky="ew", pady=2)
        self.paper_cb.bind("<<ComboboxSelected>>", lambda e: self._on_paper_changed())

        self.custom_frame = ttk.Frame(of)
        self.custom_frame.grid(row=1, column=1, columnspan=3, sticky="w")
        self.cw_var = tk.StringVar(value="220")
        self.ch_var = tk.StringVar(value="105")
        ttk.Label(self.custom_frame, text="가로").pack(side="left")
        ttk.Entry(self.custom_frame, textvariable=self.cw_var, width=6).pack(side="left", padx=2)
        ttk.Label(self.custom_frame, text="mm   세로").pack(side="left")
        ttk.Entry(self.custom_frame, textvariable=self.ch_var, width=6).pack(side="left", padx=2)
        ttk.Label(self.custom_frame, text="mm  (프린터가 지원해야 적용됨)", style="Hint.TLabel").pack(side="left")

        ttk.Label(of, text="방향").grid(row=2, column=0, sticky="w")
        self.orient_var = tk.IntVar(value=ORIENT_PORTRAIT)
        o = ttk.Frame(of)
        o.grid(row=2, column=1, columnspan=3, sticky="w", pady=2)
        ttk.Radiobutton(o, text="세로", value=ORIENT_PORTRAIT, variable=self.orient_var).pack(side="left")
        ttk.Radiobutton(o, text="가로", value=ORIENT_LANDSCAPE, variable=self.orient_var).pack(side="left", padx=10)

        ttk.Label(of, text="색상").grid(row=3, column=0, sticky="w")
        self.color_var = tk.BooleanVar(value=True)
        c = ttk.Frame(of)
        c.grid(row=3, column=1, columnspan=3, sticky="w", pady=2)
        self.color_rb = ttk.Radiobutton(c, text="컬러", value=True, variable=self.color_var)
        self.color_rb.pack(side="left")
        ttk.Radiobutton(c, text="흑백", value=False, variable=self.color_var).pack(side="left", padx=10)

        ttk.Label(of, text="급지함").grid(row=4, column=0, sticky="w")
        self.bin_var = tk.StringVar()
        self.bin_cb = ttk.Combobox(of, textvariable=self.bin_var, state="readonly")
        self.bin_cb.grid(row=4, column=1, columnspan=3, sticky="ew", pady=2)

        ttk.Label(of, text="양면").grid(row=5, column=0, sticky="w")
        self.duplex_var = tk.StringVar(value=DUPLEX_LABELS[DUPLEX_SIMPLEX])
        self.duplex_cb = ttk.Combobox(of, textvariable=self.duplex_var, state="readonly",
                                      values=list(DUPLEX_LABELS.values()))
        self.duplex_cb.grid(row=5, column=1, columnspan=3, sticky="ew", pady=2)

        ttk.Label(of, text="크기").grid(row=6, column=0, sticky="w")
        self.scale_var = tk.StringVar(value=SCALE_FIT)
        s = ttk.Frame(of)
        s.grid(row=6, column=1, columnspan=3, sticky="w", pady=2)
        ttk.Radiobutton(s, text="용지에 맞춤", value=SCALE_FIT, variable=self.scale_var).pack(side="left")
        ttk.Radiobutton(s, text="실제 크기(100%)", value=SCALE_ACTUAL, variable=self.scale_var).pack(side="left", padx=10)
        self.rotate_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(s, text="방향 자동 회전", variable=self.rotate_var).pack(side="left", padx=10)

        ttk.Label(of, text="매수").grid(row=7, column=0, sticky="w")
        self.copies_var = tk.StringVar(value="1")
        ttk.Spinbox(of, from_=1, to=999, textvariable=self.copies_var, width=6).grid(row=7, column=1, sticky="w", pady=2)

        ttk.Label(of, text="※ 여기 설정은 이번 출력에만 적용되며, 프린터 기본 설정은 바뀌지 않습니다.",
                  style="Hint.TLabel").grid(row=8, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self.paper_warn = ttk.Label(of, text="", style="Warn.TLabel", wraplength=560)
        self.paper_warn.grid(row=9, column=0, columnspan=4, sticky="w")

        # --- 4. 출력
        bf = ttk.Frame(main)
        bf.grid(row=4, column=0, sticky="ew", **pad)
        bf.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(value="준비")
        ttk.Label(bf, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(bf, mode="indeterminate")
        self.progress.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.print_btn = ttk.Button(bf, text="🖨  출력", style="Print.TButton", command=self.start_print)
        self.print_btn.grid(row=0, column=1, rowspan=2, padx=(10, 0), sticky="ns")
        self.cancel_btn = ttk.Button(bf, text="취소", command=self.cancel_print, state="disabled")
        self.cancel_btn.grid(row=0, column=2, rowspan=2, padx=(6, 0), sticky="ns")

        foot = ttk.Frame(main)
        foot.grid(row=5, column=0, sticky="ew", padx=10)
        self.sendto_btn = ttk.Button(foot, command=self.toggle_sendto)
        self.sendto_btn.pack(side="right")
        self._update_sendto_btn()

        for v in (self.paper_var, self.orient_var, self.color_var, self.bin_var, self.duplex_var,
                  self.scale_var, self.rotate_var, self.copies_var, self.cw_var, self.ch_var, self.printer_var):
            v.trace_add("write", lambda *a: self._update_modified())

    # ------------------------------------------------------------ 프린터
    def _printer_labels(self) -> list[str]:
        d = self.default_name
        return [f"Windows 기본 프린터 ({d})" if d else "Windows 기본 프린터"] + self.printers

    def _load_printers(self):
        try:
            self.printers = self.backend.list_printers()
            self.default_name = self.backend.default_printer()
        except Exception as e:
            self.printers, self.default_name = [], ""
            messagebox.showerror(APP_NAME, f"프린터 목록을 가져오지 못했습니다.\n{e}")
        self.printer_cb["values"] = self._printer_labels()

    def _reload_printers(self):
        cur = self.selected_printer()
        self.caps_cache.clear()
        self._load_printers()
        self._select_printer(cur)
        self._on_printer_changed()

    def selected_printer(self) -> str:
        """'' 이면 Windows 기본 프린터"""
        idx = self.printer_cb.current()
        return "" if idx <= 0 else self.printers[idx - 1]

    def _select_printer(self, name: str) -> bool:
        if name and name in self.printers:
            self.printer_cb.current(self.printers.index(name) + 1)
            return True
        self.printer_cb.current(0)
        return not name

    def _get_caps(self, printer: str) -> PrinterCaps | None:
        key = printer or self.default_name
        if key in self.caps_cache:
            return self.caps_cache[key]
        self.root.config(cursor="watch")
        self.root.update_idletasks()
        try:
            caps = self.backend.get_capabilities(printer)
        except Exception as e:
            self.status_var.set(f"⚠ 프린터 정보를 읽지 못했습니다: {e}")
            caps = None
        finally:
            self.root.config(cursor="")
        if caps:
            self.caps_cache[key] = caps
        return caps

    def _on_printer_changed(self):
        """프린터가 바뀌면 용지/급지함 목록을 새로 채우고, 가능한 한 기존 선택을 유지한다."""
        keep = self._collect(validate=False)
        self._fill_from_caps(keep)

    def _fill_from_caps(self, p: Preset):
        self._loading = True
        try:
            self.caps = self._get_caps(self.selected_printer())
            caps = self.caps or PrinterCaps("", [], [], True, True)
            self.paper_cb["values"] = [x.label for x in caps.papers] + [CUSTOM_PAPER_LABEL]
            self.bin_cb["values"] = [AUTO_BIN_LABEL] + [n for _, n in caps.bins]
            warn = []

            # 용지
            if p.paper_id == DMPAPER_USER:
                self.paper_cb.current(len(caps.papers))
            else:
                idx = self._find_paper(caps.papers, p.paper_id, p.paper_name)
                if idx is None:
                    warn.append(f"⚠ 이 프린터는 '{p.paper_name}' 용지(번호 {p.paper_id})가 목록에 없습니다. "
                                f"알맞은 용지를 고른 뒤 [현재 형식에 덮어쓰기]로 저장하세요.")
                    idx = self._guess_paper(caps.papers, p) if caps.papers else len(caps.papers)
                self.paper_cb.current(idx)
            self.cw_var.set(f"{p.custom_width_mm:g}")
            self.ch_var.set(f"{p.custom_height_mm:g}")

            # 급지함
            bidx = 0
            if p.bin_id != DMBIN_AUTO:
                found = next((i for i, (bid, _) in enumerate(caps.bins) if bid == p.bin_id), None)
                if found is None:
                    found = next((i for i, (_, bn) in enumerate(caps.bins) if bn == p.bin_name), None)
                if found is None:
                    warn.append(f"⚠ 급지함 '{p.bin_name}'이(가) 없어 자동 선택으로 출력합니다.")
                else:
                    bidx = found + 1
            self.bin_cb.current(bidx)

            self.orient_var.set(p.orientation)
            self.color_var.set(p.color)
            self.color_rb.configure(state="normal" if caps.color else "disabled")
            if not caps.color and p.color:
                self.color_var.set(False)
                warn.append("ⓘ 흑백 전용 프린터라 흑백으로 출력됩니다.")
            self.duplex_var.set(DUPLEX_LABELS[p.duplex])
            self.duplex_cb.configure(state="readonly" if caps.duplex else "disabled")
            if not caps.duplex and p.duplex != DUPLEX_SIMPLEX:
                self.duplex_var.set(DUPLEX_LABELS[DUPLEX_SIMPLEX])
                warn.append("ⓘ 양면 인쇄를 지원하지 않는 프린터라 단면으로 출력됩니다.")
            self.scale_var.set(p.scale)
            self.rotate_var.set(p.auto_rotate)
            self.copies_var.set(str(p.copies))
            self.paper_warn.configure(text="\n".join(warn))
            self._on_paper_changed()
        finally:
            self._loading = False
        self._update_modified()

    @staticmethod
    def _find_paper(papers: list[PaperInfo], pid: int, pname: str) -> int | None:
        for i, x in enumerate(papers):
            if x.id == pid:
                return i
        for i, x in enumerate(papers):
            if x.name == pname:
                return i
        return None

    @staticmethod
    def _guess_paper(papers: list[PaperInfo], p: Preset) -> int:
        if "봉투" in p.name or "env" in p.paper_name.lower():
            for i, x in enumerate(papers):
                if any(h in x.name.lower() for h in ENVELOPE_HINTS):
                    return i
        return 0

    def _on_paper_changed(self):
        custom = self.paper_cb.current() == len(self.caps.papers if self.caps else [])
        if custom:
            self.custom_frame.grid()
        else:
            self.custom_frame.grid_remove()

    # ------------------------------------------------------------ 프리셋
    def _rebuild_preset_buttons(self):
        for w in self.preset_btns.winfo_children():
            w.destroy()
        for i, name in enumerate(self.store.names()):
            b = ttk.Radiobutton(self.preset_btns, text=name, value=name, variable=self.preset_var,
                                style="Preset.Toolbutton", command=lambda n=name: self.apply_preset(n))
            b.grid(row=i // 4, column=i % 4, padx=2, pady=2, sticky="ew")

    def apply_preset(self, name: str):
        p = self.store.get(name) or self.store.presets[0]
        self.preset_var.set(p.name)
        self.store.last_used = p.name
        self._loading = True
        try:
            if not self._select_printer(p.printer):
                self.status_var.set(f"⚠ 저장된 프린터 '{p.printer}'을(를) 찾을 수 없어 기본 프린터를 선택했습니다.")
            else:
                self.status_var.set(f"'{p.name}' 형식을 적용했습니다.")
        finally:
            self._loading = False
        self._fill_from_caps(p)

    def _collect(self, validate: bool = True, name: str | None = None) -> Preset:
        """화면의 현재 설정을 Preset 으로 만든다."""
        caps = self.caps
        papers = caps.papers if caps else []
        pidx = self.paper_cb.current()
        if 0 <= pidx < len(papers):
            paper_id, paper_name = papers[pidx].id, papers[pidx].name
        elif pidx == len(papers):
            paper_id, paper_name = DMPAPER_USER, "사용자 지정"
        else:
            cur = self.store.get(self.preset_var.get())
            paper_id, paper_name = (cur.paper_id, cur.paper_name) if cur else (9, "A4")
        bidx = self.bin_cb.current()
        bin_id, bin_name = (caps.bins[bidx - 1] if caps and 1 <= bidx <= len(caps.bins) else (DMBIN_AUTO, ""))
        duplex = next((k for k, v in DUPLEX_LABELS.items() if v == self.duplex_var.get()), DUPLEX_SIMPLEX)

        def num(var, default):
            try:
                return float(var.get().replace(",", "."))
            except ValueError:
                if validate:
                    raise ValueError(f"숫자를 입력하세요: {var.get()!r}")
                return default

        try:
            copies = int(self.copies_var.get())
        except ValueError:
            if validate:
                raise ValueError("매수는 1 이상의 숫자로 입력하세요")
            copies = 1
        p = Preset(
            name=name or self.preset_var.get() or "임시",
            printer=self.selected_printer(),
            paper_id=paper_id, paper_name=paper_name,
            custom_width_mm=num(self.cw_var, 220.0), custom_height_mm=num(self.ch_var, 105.0),
            orientation=self.orient_var.get(), color=bool(self.color_var.get()),
            bin_id=bin_id, bin_name=bin_name, duplex=duplex,
            scale=self.scale_var.get(), auto_rotate=bool(self.rotate_var.get()), copies=copies,
        )
        if validate:
            if copies < 1:
                raise ValueError("매수는 1 이상이어야 합니다")
            p.validate()
        return p

    def _update_modified(self):
        if self._loading:
            return
        saved = self.store.get(self.preset_var.get())
        try:
            cur = self._collect(validate=False)
        except Exception:
            return
        changed = saved is not None and cur.to_dict() != saved.to_dict()
        self.modified_lbl.configure(text="● 수정됨 (저장하지 않아도 이번 출력엔 적용됩니다)" if changed else "")

    def save_current(self):
        name = self.preset_var.get()
        try:
            p = self._collect(name=name)
        except ValueError as e:
            return messagebox.showerror(APP_NAME, str(e))
        if not messagebox.askyesno(APP_NAME, f"'{name}' 형식을 지금 설정으로 덮어쓸까요?"):
            return
        self.store.upsert(p)
        self._save_store()
        self._update_modified()
        self.status_var.set(f"'{name}' 형식을 저장했습니다.")

    def _ask_name(self, title: str, initial: str = "") -> str | None:
        name = simpledialog.askstring(APP_NAME, title, initialvalue=initial, parent=self.root)
        if name is None:
            return None
        name = name.strip()
        if not name:
            messagebox.showerror(APP_NAME, "이름을 입력하세요.")
            return None
        return name

    def save_as_new(self):
        name = self._ask_name("새 출력 형식의 이름 (예: 회의자료 A3 흑백)")
        if not name:
            return
        if self.store.get(name) and not messagebox.askyesno(APP_NAME, f"'{name}'이(가) 이미 있습니다. 덮어쓸까요?"):
            return
        try:
            p = self._collect(name=name)
        except ValueError as e:
            return messagebox.showerror(APP_NAME, str(e))
        self.store.upsert(p)
        self.store.last_used = name
        self._save_store()
        self._rebuild_preset_buttons()
        self.preset_var.set(name)
        self._update_modified()
        self.status_var.set(f"'{name}' 형식을 추가했습니다.")

    def rename_preset(self):
        old = self.preset_var.get()
        p = self.store.get(old)
        if not p:
            return
        new = self._ask_name("새 이름", old)
        if not new or new == old:
            return
        if self.store.get(new):
            return messagebox.showerror(APP_NAME, f"'{new}'은(는) 이미 있는 이름입니다.")
        p.name = new
        if self.store.last_used == old:
            self.store.last_used = new
        self._save_store()
        self._rebuild_preset_buttons()
        self.preset_var.set(new)

    def move_preset(self, delta: int):
        name = self.preset_var.get()
        if self.store.get(name):
            self.store.move(name, delta)
            self._save_store()
            self._rebuild_preset_buttons()

    def delete_preset(self):
        name = self.preset_var.get()
        if not messagebox.askyesno(APP_NAME, f"'{name}' 형식을 삭제할까요?"):
            return
        try:
            self.store.delete(name)
        except ValueError as e:
            return messagebox.showerror(APP_NAME, str(e))
        self._save_store()
        self._rebuild_preset_buttons()
        self.apply_preset(self.store.last_used)

    def _save_store(self):
        try:
            self.store.save()
        except OSError as e:
            messagebox.showerror(APP_NAME, f"설정을 저장하지 못했습니다.\n{e}")

    # ------------------------------------------------------------ 파일
    def choose_files(self):
        paths = filedialog.askopenfilenames(parent=self.root, title="출력할 파일 선택", filetypes=FILE_DIALOG_TYPES)
        self.add_files(list(paths))

    def add_files(self, paths: list[str]):
        skipped = []
        for p in paths:
            p = str(Path(p))
            if Path(p).is_dir():
                skipped.append(f"{Path(p).name} (폴더)")
            elif not is_supported(p):
                skipped.append(Path(p).name)
            elif p not in self.files:
                self.files.append(p)
        self._refresh_files()
        if skipped:
            messagebox.showwarning(APP_NAME, "지원하지 않는 형식이라 제외했습니다:\n" + "\n".join(skipped))

    def _refresh_files(self):
        self.file_list.delete(0, "end")
        for p in self.files:
            self.file_list.insert("end", f"{Path(p).name}    —  {Path(p).parent}")

    def remove_selected(self):
        for i in sorted(self.file_list.curselection(), reverse=True):
            del self.files[i]
        self._refresh_files()

    def clear_files(self):
        self.files.clear()
        self._refresh_files()

    def move_file(self, delta: int):
        sel = self.file_list.curselection()
        if len(sel) != 1:
            return
        i, j = sel[0], sel[0] + delta
        if 0 <= j < len(self.files):
            self.files[i], self.files[j] = self.files[j], self.files[i]
            self._refresh_files()
            self.file_list.selection_set(j)

    # ------------------------------------------------------------ 출력
    def start_print(self):
        if self.worker and self.worker.is_alive():
            return
        if not self.files:
            return messagebox.showinfo(APP_NAME, "출력할 파일을 먼저 추가하세요.")
        try:
            preset = self._collect()
        except ValueError as e:
            return messagebox.showerror(APP_NAME, str(e))
        self.store.last_used = self.preset_var.get()
        self._save_store()

        files = list(self.files)
        self.cancel_event = threading.Event()
        self._set_busy(True)

        def work():
            device = None
            try:
                device = self.backend.open_device(preset.printer, preset)
                res = print_files(device, files, preset, progress=lambda s: self.msgs.put(("status", s)),
                                  cancel=self.cancel_event)
                self.msgs.put(("done", res))
            except Exception as e:
                self.msgs.put(("error", e))
            finally:
                if device is not None:
                    try:
                        device.close()
                    except Exception:
                        pass

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def cancel_print(self):
        if self.cancel_event:
            self.cancel_event.set()
            self.status_var.set("취소하는 중... (현재 페이지까지 처리 후 멈춥니다)")

    def _set_busy(self, busy: bool):
        self.print_btn.configure(state="disabled" if busy else "normal")
        self.cancel_btn.configure(state="normal" if busy else "disabled")
        if busy:
            self.progress.start(12)
            self.status_var.set("출력 준비 중...")
        else:
            self.progress.stop()
            self.progress["value"] = 0

    def _poll(self):
        try:
            while True:
                kind, val = self.msgs.get_nowait()
                if kind == "status":
                    self.status_var.set(val)
                elif kind == "done":
                    self._set_busy(False)
                    self._report(val)
                elif kind == "error":
                    self._set_busy(False)
                    self.status_var.set("출력 실패")
                    messagebox.showerror(APP_NAME, f"출력하지 못했습니다.\n\n{val}")
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _report(self, res: JobResult):
        lines = []
        if res.cancelled:
            lines.append("출력을 취소했습니다.")
        lines.append(f"보낸 파일 {len(res.printed_files)}개, 총 {res.pages}쪽")
        if res.failed:
            lines.append("\n실패한 파일:")
            lines += [f" • {Path(f).name}: {why}" for f, why in res.failed]
        if res.warnings:
            lines.append("\n참고:")
            lines += [f" • {w}" for w in res.warnings]
        self.status_var.set(("⚠ " if res.failed or res.cancelled else "✔ ") + lines[0])
        if res.failed or res.warnings or res.cancelled:
            (messagebox.showwarning if res.failed else messagebox.showinfo)(APP_NAME, "\n".join(lines))

    # ------------------------------------------------------------ 기타
    def _update_sendto_btn(self):
        if sys.platform != "win32":
            self.sendto_btn.configure(text="'보내기' 메뉴 등록 (Windows 전용)", state="disabled")
        elif shell.is_registered():
            self.sendto_btn.configure(text="탐색기 '보내기' 메뉴에서 제거")
        else:
            self.sendto_btn.configure(text="탐색기 '보내기' 메뉴에 등록")

    def toggle_sendto(self):
        try:
            if shell.is_registered():
                shell.unregister_sendto()
                self.status_var.set("'보내기' 메뉴에서 제거했습니다.")
            else:
                shell.register_sendto()
                self.status_var.set("등록 완료: 파일 우클릭 → 보내기 → 간편출력")
        except Exception as e:
            messagebox.showerror(APP_NAME, f"'보내기' 메뉴 설정에 실패했습니다.\n{e}")
        self._update_sendto_btn()

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(APP_NAME, "출력 중입니다. 취소하고 닫을까요?"):
                return
            self.cancel_event.set()
            self.worker.join(timeout=5)
        self._save_store()
        self.root.destroy()


def selftest(out_file: str) -> int:
    """배포용 exe 점검: 필수 모듈이 모두 포함됐는지, 프린터 정보를 읽을 수 있는지 확인해 파일로 남긴다."""
    import json
    import traceback

    import PIL
    import pymupdf

    report: dict = {"version": __version__, "pymupdf": pymupdf.VersionBind, "pillow": PIL.__version__}
    try:
        b = get_backend()
        report["backend"] = type(b).__name__
        report["printers"] = b.list_printers()
        report["default"] = b.default_printer()
        if report["printers"]:
            caps = b.get_capabilities(report["printers"][0])
            report["first_caps"] = {"papers": len(caps.papers), "bins": len(caps.bins),
                                    "color": caps.color, "duplex": caps.duplex}
        if sys.platform == "win32":
            import pythoncom  # noqa: F401  (한글/오피스 변환에 필요)
            import win32com.client  # noqa: F401
        report["ok"] = True
    except Exception:
        report["ok"] = False
        report["error"] = traceback.format_exc()
    Path(out_file).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1


def run(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 2 and argv[0] == "--selftest":
        sys.exit(selftest(argv[1]))
    if sys.platform == "win32":
        try:  # 고해상도 모니터에서 글자가 흐려지지 않게
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    App(root, files=argv)
    root.mainloop()
