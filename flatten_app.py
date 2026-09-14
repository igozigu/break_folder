#!/usr/bin/env python3
"""
폴더 평탄화(Flatten) GUI 유틸리티
─────────────────────────────────
드래그 앤 드롭 또는 폴더 선택으로 대상 폴더를 지정하고,
모든 하위 파일을 'all_files' 폴더로 모은 뒤 빈 폴더를 삭제합니다.

빌드:
    pip install pyinstaller tkinterdnd2
    pyinstaller --onefile --windowed --collect-all tkinterdnd2 --name flatten_app flatten_app.py
"""

from __future__ import annotations

import csv
import ctypes
import os
import shutil
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# TkinterDnD2 임포트 시도
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_TKDND = True
except Exception:
    HAS_TKDND = False


# ═══════════════════════════════ 유틸리티 ═══════════════════════════════

def long_path(p: str) -> str:
    """Windows 260자 경로 제한 우회."""
    if sys.platform == "win32" and not p.startswith("\\\\?\\"):
        return "\\\\?\\" + os.path.abspath(p)
    return p


# ═══════════════════════════════ 핵심 로직 ═══════════════════════════════

def scan_files(target_dir: Path, all_files_dir: Path) -> List[Path]:
    """
    target_dir 하위를 재귀 스캔하여 이동 대상 파일 목록을 반환.
    - 최상위 폴더에 있는 파일도 모두 all_files 이동 대상에 포함
    - all_files 폴더 내부는 스캔에서 제외
    - 실행 파일(exe/py) 자체는 보호
    """
    collected: List[Path] = []
    all_files_resolved = all_files_dir.resolve()

    for dirpath, dirnames, filenames in os.walk(str(target_dir)):
        real_dirpath = Path(dirpath)

        # all_files 폴더 진입 차단
        if real_dirpath.resolve() == all_files_resolved:
            dirnames.clear()
            continue
        af_name = all_files_dir.name
        if af_name in dirnames:
            dirnames.remove(af_name)

        for fname in filenames:
            # 실행 파일 및 스크립트 자신 제외
            if getattr(sys, "frozen", False) and fname == Path(sys.executable).name:
                continue
            if not getattr(sys, "frozen", False) and fname == Path(__file__).name:
                continue

            full_path = real_dirpath / fname
            # 최상위 및 모든 하위 파일 수집
            collected.append(full_path)

    return collected


def plan_renames(
    files: List[Path],
    target_dir: Path,
    all_files_dir: Path,
) -> List[Tuple[Path, Path, str]]:
    """충돌 없는 이동 계획을 수립 (최상위 파일 및 하위 파일 모두 처리)."""
    plan: List[Tuple[Path, Path, str]] = []
    used_names: set[str] = set()

    if all_files_dir.exists():
        for existing in all_files_dir.iterdir():
            if existing.is_file():
                used_names.add(existing.name.lower())

    for src in files:
        stem = src.stem
        suffix = src.suffix
        candidate = src.name
        renamed = "N"

        if candidate.lower() in used_names:
            rel = src.relative_to(target_dir)
            parent_tag = "__".join(rel.parent.parts)
            if parent_tag:
                candidate = f"{stem}__{parent_tag}{suffix}"
            else:
                candidate = f"{stem}{suffix}"
            renamed = "Y"

            counter = 2
            base_candidate = candidate
            while candidate.lower() in used_names:
                base_stem = Path(base_candidate).stem
                candidate = f"{base_stem}_{counter}{suffix}"
                counter += 1

        used_names.add(candidate.lower())
        dest = all_files_dir / candidate
        plan.append((src, dest, renamed))

    return plan


# ═══════════════════════════════ GUI 앱 ═══════════════════════════════

class FlattenApp:
    """폴더 평탄화 GUI 앱."""

    # ─── 테마 색상 ───
    BG = "#1e1e2e"
    FG = "#cdd6f4"
    ACCENT = "#89b4fa"
    SUCCESS = "#a6e3a1"
    WARNING = "#f9e2af"
    ERROR = "#f38ba8"
    SURFACE = "#313244"
    SURFACE_HOVER = "#45475a"
    OVERLAY = "#585b70"
    DARK = "#11111b"

    def __init__(self) -> None:
        # TkinterDnD 사용 가능 시 TkinterDnD.Tk() 인스턴스 생성
        if HAS_TKDND:
            try:
                self.root = TkinterDnD.Tk()
                self.use_tkdnd = True
            except Exception:
                self.root = tk.Tk()
                self.use_tkdnd = False
        else:
            self.root = tk.Tk()
            self.use_tkdnd = False

        self.root.title("폴더 평탄화 (Flatten)")
        self.root.geometry("780x700")
        self.root.minsize(640, 540)
        self.root.configure(bg=self.BG)

        self.target_dir: Optional[Path] = None
        self.cancel_event = threading.Event()
        self.is_running = False

        self._setup_styles()
        self._build_ui()
        self._setup_drag_and_drop()

    # ────────────────────────── 스타일 ──────────────────────────

    def _setup_styles(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=self.BG)
        style.configure("TLabel", background=self.BG, foreground=self.FG, font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"), foreground=self.ACCENT)
        style.configure("Sub.TLabel", font=("Segoe UI", 9), foreground=self.FG)
        style.configure("Path.TLabel", font=("Segoe UI", 10, "bold"), foreground=self.SUCCESS)
        style.configure("Status.TLabel", font=("Segoe UI", 10), foreground=self.WARNING)
        style.configure(
            "green.Horizontal.TProgressbar",
            troughcolor=self.SURFACE,
            background=self.SUCCESS,
        )

    # ────────────────────────── UI 구성 ──────────────────────────

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=20)
        main.pack(fill=tk.BOTH, expand=True)

        # ── 타이틀 ──
        ttk.Label(main, text="📁 폴더 평탄화 (Flatten)", style="Title.TLabel").pack(pady=(0, 4))
        ttk.Label(
            main,
            text="하위 폴더의 모든 파일을 all_files 폴더 하나로 모으고 빈 폴더를 정리합니다",
            style="Sub.TLabel",
        ).pack(pady=(0, 14))

        # ── 드롭 존 ──
        self.drop_frame = tk.Frame(
            main,
            bg=self.SURFACE,
            highlightbackground=self.ACCENT,
            highlightthickness=3,
            cursor="hand2",
        )
        self.drop_frame.pack(fill=tk.X, pady=(0, 10), ipady=24)

        self.drop_icon = tk.Label(
            self.drop_frame,
            text="📂",
            bg=self.SURFACE,
            fg=self.ACCENT,
            font=("Segoe UI Emoji", 32),
        )
        self.drop_icon.pack(pady=(8, 2))

        self.drop_label = tk.Label(
            self.drop_frame,
            text="폴더를 이곳에 드래그 앤 드롭하세요\n(또는 클릭하여 폴더 선택)",
            bg=self.SURFACE,
            fg=self.FG,
            font=("Segoe UI", 12, "bold"),
            justify=tk.CENTER,
        )
        self.drop_label.pack(expand=True, pady=(0, 8))

        # 클릭 이벤트 바인딩
        for widget in (self.drop_frame, self.drop_icon, self.drop_label):
            widget.bind("<Button-1>", lambda _: self._browse_folder())

        # ── 선택 경로 표시 ──
        path_box = tk.Frame(main, bg=self.SURFACE, padx=10, pady=8)
        path_box.pack(fill=tk.X, pady=(0, 14))

        ttk.Label(path_box, text="선택된 폴더:", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        self.path_var = tk.StringVar(value="아직 선택된 폴더가 없습니다")
        self.path_label = tk.Label(
            path_box,
            textvariable=self.path_var,
            bg=self.SURFACE,
            fg=self.SUCCESS,
            font=("Segoe UI", 9, "bold"),
            anchor=tk.W,
        )
        self.path_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

        # ── 큰 액션 버튼 영역 (시작 / 취소) ──
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(0, 14))

        self.start_btn = tk.Button(
            btn_frame,
            text="🚀  작업 시작",
            font=("Segoe UI", 14, "bold"),
            bg="#a6e3a1",
            fg="#11111b",
            activebackground="#94d898",
            activeforeground="#11111b",
            relief=tk.RAISED,
            bd=3,
            cursor="hand2",
            padx=32,
            pady=12,
            command=self._start,
        )
        self.start_btn.pack(side=tk.LEFT, padx=(0, 14))

        self.cancel_btn = tk.Button(
            btn_frame,
            text="❌  작업 취소",
            font=("Segoe UI", 14, "bold"),
            bg="#f38ba8",
            fg="#11111b",
            activebackground="#e67a95",
            activeforeground="#11111b",
            relief=tk.RAISED,
            bd=3,
            cursor="hand2",
            padx=32,
            pady=12,
            state=tk.DISABLED,
            command=self._cancel,
        )
        self.cancel_btn.pack(side=tk.LEFT, padx=(0, 14))

        self.browse_btn = tk.Button(
            btn_frame,
            text="📁 폴더 찾아보기...",
            font=("Segoe UI", 11),
            bg=self.OVERLAY,
            fg=self.FG,
            activebackground=self.SURFACE,
            activeforeground=self.FG,
            relief=tk.FLAT,
            cursor="hand2",
            padx=18,
            pady=10,
            command=self._browse_folder,
        )
        self.browse_btn.pack(side=tk.RIGHT)

        # ── 프로그레스 바 ──
        self.progress_var = tk.DoubleVar(value=0)
        self.progress = ttk.Progressbar(
            main,
            variable=self.progress_var,
            maximum=100,
            style="green.Horizontal.TProgressbar",
        )
        self.progress.pack(fill=tk.X, pady=(0, 6))

        # ── 상태 텍스트 ──
        self.status_var = tk.StringVar(value="대기 중... 폴더를 드래그하거나 선택해주세요.")
        ttk.Label(main, textvariable=self.status_var, style="Status.TLabel").pack(
            anchor=tk.W, pady=(0, 8)
        )

        # ── 로그 영역 ──
        log_header = ttk.Frame(main)
        log_header.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(log_header, text="작업 로그", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)

        log_frame = tk.Frame(main, bg=self.SURFACE)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(
            log_frame,
            bg=self.DARK,
            fg=self.FG,
            font=("Consolas", 9),
            relief=tk.FLAT,
            padx=10,
            pady=10,
            state=tk.DISABLED,
            wrap=tk.WORD,
        )
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    # ──────────────────────── 드래그 앤 드롭 설정 ────────────────────────

    def _setup_drag_and_drop(self) -> None:
        """TkinterDnD 또는 Windows Win32 API를 통한 드래그 앤 드롭 등록."""
        if self.use_tkdnd:
            self._setup_tkdnd()
        else:
            self._setup_win32_dnd()

    def _setup_tkdnd(self) -> None:
        """tkinterdnd2 기반 드래그앤드롭."""
        try:
            for w in (self.root, self.drop_frame, self.drop_label, self.drop_icon):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._on_tkdnd_drop)
                w.dnd_bind("<<DragEnter>>", self._on_drag_enter)
                w.dnd_bind("<<DragLeave>>", self._on_drag_leave)
            self._log("드래그 앤 드롭 활성화 완료 (TkinterDnD2 엔진)")
        except Exception as e:
            self._log(f"TkinterDnD 바인딩 실패, 대체 수단 시도: {e}")
            self._setup_win32_dnd()

    def _on_drag_enter(self, _event) -> None:
        self.drop_frame.config(bg=self.SURFACE_HOVER, highlightbackground=self.SUCCESS)
        self.drop_icon.config(bg=self.SURFACE_HOVER)
        self.drop_label.config(bg=self.SURFACE_HOVER)

    def _on_drag_leave(self, _event) -> None:
        self.drop_frame.config(bg=self.SURFACE, highlightbackground=self.ACCENT)
        self.drop_icon.config(bg=self.SURFACE)
        self.drop_label.config(bg=self.SURFACE)

    def _on_tkdnd_drop(self, event) -> None:
        self._on_drag_leave(None)
        if self.is_running:
            return
        data = event.data
        if not data:
            return

        try:
            # tkinter splitlist로 감싸인 경로 분리
            paths = self.root.tk.splitlist(data)
            if paths:
                first_path = paths[0]
                self._handle_dropped_path(first_path)
        except Exception as e:
            self._log(f"드롭 데이터 처리 오류: {e}")

    def _setup_win32_dnd(self) -> None:
        """순수 ctypes Win32 API(DragAcceptFiles) 기반 폴더 드롭 수신."""
        if sys.platform != "win32":
            return

        try:
            self.root.update_idletasks()
            hwnd = self.root.winfo_id()
            GA_ROOT = 2
            root_hwnd = ctypes.windll.user32.GetAncestor(hwnd, GA_ROOT)
            target_hwnd = root_hwnd if root_hwnd else hwnd

            # UIPI 필터 해제 (관리자/일반 권한 차이 완화)
            WM_DROPFILES = 0x0233
            WM_COPYDATA = 0x004A
            WM_COPYGLOBALDATA = 0x0049
            MSGFLT_ALLOW = 1

            ChangeWindowMessageFilter = getattr(ctypes.windll.user32, "ChangeWindowMessageFilter", None)
            if ChangeWindowMessageFilter:
                for msg in (WM_DROPFILES, WM_COPYDATA, WM_COPYGLOBALDATA):
                    ChangeWindowMessageFilter(msg, MSGFLT_ALLOW)

            # 드롭 수신 활성화
            ctypes.windll.shell32.DragAcceptFiles(target_hwnd, True)

            # WndProc 서브클래싱
            is_64bit = sys.maxsize > 2**32
            argtype = ctypes.c_uint64 if is_64bit else ctypes.c_uint32
            prototype = ctypes.WINFUNCTYPE(argtype, argtype, argtype, argtype, argtype)
            GetWindowLongPtr = (
                ctypes.windll.user32.GetWindowLongPtrW if is_64bit else ctypes.windll.user32.GetWindowLongW
            )
            SetWindowLongPtr = (
                ctypes.windll.user32.SetWindowLongPtrW if is_64bit else ctypes.windll.user32.SetWindowLongW
            )
            GWL_WNDPROC = -4

            def win_drop_proc(h, msg, wp, lp):
                if msg == WM_DROPFILES:
                    hdrop = argtype(wp)
                    count = ctypes.windll.shell32.DragQueryFileW(hdrop, -1, None, 0)
                    if count > 0:
                        buf = ctypes.create_unicode_buffer(512)
                        ctypes.windll.shell32.DragQueryFileW(hdrop, 0, buf, ctypes.sizeof(buf))
                        dropped = buf.value
                        self.root.after(0, lambda: self._handle_dropped_path(dropped))
                    ctypes.windll.shell32.DragFinish(hdrop)
                return ctypes.windll.user32.CallWindowProcW(self._old_wndproc, h, msg, wp, lp)

            self._drop_cb = prototype(win_drop_proc)
            self._old_wndproc = GetWindowLongPtr(target_hwnd, GWL_WNDPROC)
            SetWindowLongPtr(target_hwnd, GWL_WNDPROC, self._drop_cb)

            self._log("드래그 앤 드롭 활성화 완료 (Win32 OLE 대체 엔진)")
        except Exception as e:
            self._log(f"Win32 OLE 드래그 앤 드롭 등록 실패: {e}")

    def _handle_dropped_path(self, path_str: str) -> None:
        """드롭된 경로를 분석하여 대상 폴더 설정."""
        p = Path(path_str).resolve()
        if p.is_file():
            # 파일을 끌어다 놓은 경우 그 파일이 있는 폴더로 자동 지정
            self._set_target(p.parent)
        elif p.is_dir():
            self._set_target(p)
        else:
            self._log(f"유효하지 않은 경로입니다: {path_str}")

    # ────────────────────────── 이벤트 핸들러 ──────────────────────────

    def _browse_folder(self) -> None:
        """폴더 선택 다이얼로그."""
        if self.is_running:
            return
        folder = filedialog.askdirectory(title="평탄화할 폴더를 선택하세요")
        if folder:
            self._set_target(Path(folder))

    def _set_target(self, path: Path) -> None:
        self.target_dir = path.resolve()
        self.path_var.set(str(self.target_dir))
        self.drop_icon.config(text="✅", fg=self.SUCCESS)
        self.drop_label.config(
            text=f"선택된 폴더: {self.target_dir.name}\n(다른 폴더를 드래그하여 언제든 변경 가능)",
            fg=self.SUCCESS,
        )
        self.status_var.set(f"폴더가 선택되었습니다: {self.target_dir.name}  →  [🚀 작업 시작] 버튼을 누르세요.")
        self._log(f"대상 폴더 지정: {self.target_dir}")

    def _log(self, msg: str) -> None:
        self.log_text.config(state=tk.NORMAL)
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{ts}] {msg}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _update_progress(self, value: float, status: str = "") -> None:
        self.progress_var.set(value)
        if status:
            self.status_var.set(status)

    # ────────────────────────── 시작 / 취소 ──────────────────────────

    def _start(self) -> None:
        if self.target_dir is None:
            self.status_var.set("⚠️ 먼저 평탄화할 대상 폴더를 드래그하거나 선택해주세요.")
            self._log("⚠️ 대상 폴더가 지정되지 않았습니다.")
            return
        if not self.target_dir.exists():
            self.status_var.set(f"❌ 폴더가 존재하지 않습니다: {self.target_dir}")
            self._log(f"❌ 폴더가 존재하지 않습니다: {self.target_dir}")
            return

        # 확인 팝업 없이 즉시 시작
        self.is_running = True
        self.cancel_event.clear()
        self.start_btn.config(state=tk.DISABLED)
        self.cancel_btn.config(state=tk.NORMAL)
        self.browse_btn.config(state=tk.DISABLED)

        threading.Thread(target=self._run_flatten, daemon=True).start()

    def _cancel(self) -> None:
        if self.is_running:
            self.cancel_event.set()
            self._log("⚠️ 작업 취소 요청됨 — 현재 파일 이동 완료 후 중단합니다...")
            self.cancel_btn.config(state=tk.DISABLED)

    def _finish(self) -> None:
        self.is_running = False
        self.start_btn.config(state=tk.NORMAL)
        self.cancel_btn.config(state=tk.DISABLED)
        self.browse_btn.config(state=tk.NORMAL)

    # ────────────────────────── 평탄화 워커 ──────────────────────────

    def _run_flatten(self) -> None:
        try:
            self._do_flatten()
        except Exception as exc:
            self.root.after(0, lambda: self._log(f"❌ 오류 발생: {exc}"))
            self.root.after(0, lambda: self.status_var.set(f"❌ 오류: {exc}"))
        finally:
            self.root.after(0, self._finish)

    def _do_flatten(self) -> None:
        target_dir = self.target_dir
        all_files_dir = target_dir / "all_files"

        def ui(fn):
            self.root.after(0, fn)

        # ── 1. 스캔 ──
        ui(lambda: self._update_progress(0, "파일 스캔 중..."))
        ui(lambda: self._log("▶ 1단계: 하위 파일 전체 스캔 시작..."))

        files = scan_files(target_dir, all_files_dir)
        total = len(files)

        if total == 0:
            ui(lambda: self._log("ℹ️ 이동할 하위 파일이 없습니다 (이미 평탄화되어 있거나 비어있음)."))
            ui(lambda: self._update_progress(100, "완료 — 이동할 파일 없음"))
            return

        ui(lambda: self._log(f"  → 발견된 총 파일: {total}개"))

        if self.cancel_event.is_set():
            ui(lambda: self._log("❌ 사용자에 의해 작업이 취소되었습니다."))
            return

        # ── 2. all_files 생성 + 리네임 계획 ──
        all_files_dir.mkdir(exist_ok=True)
        ui(lambda: self._update_progress(5, "충돌 검사 및 리네임 계획 수립 중..."))
        ui(lambda: self._log("▶ 2단계: 파일명 충돌 검사 및 리네임 계획..."))

        plan = plan_renames(files, target_dir, all_files_dir)
        renamed_count = sum(1 for _, _, r in plan if r == "Y")
        ui(lambda: self._log(f"  → 파일명 중복 충돌로 리네임되는 파일: {renamed_count}개"))

        if self.cancel_event.is_set():
            ui(lambda: self._log("❌ 사용자에 의해 작업이 취소되었습니다."))
            return

        # ── 3. 파일 이동 ──
        ui(lambda: self._update_progress(10, "파일 이동 중..."))
        ui(lambda: self._log("▶ 3단계: all_files 폴더로 파일 이동 시작..."))

        results: list[dict] = []
        success_count = 0
        fail_count = 0
        log_interval = max(1, total // 80)

        for idx, (src, dest, renamed) in enumerate(plan, 1):
            if self.cancel_event.is_set():
                ui(lambda i=idx: self._log(f"❌ 취소됨 ({i - 1}/{total}개 처리 완료 후 중단)"))
                break

            try:
                shutil.move(long_path(str(src)), long_path(str(dest)))
                status = "성공"
                success_count += 1
            except Exception as exc:
                status = f"실패: {exc}"
                fail_count += 1

            results.append(
                {
                    "원본경로": str(src),
                    "최종파일명": dest.name,
                    "상태": status,
                    "리네임": renamed,
                }
            )

            if idx % log_interval == 0 or idx == total:
                pct = 10 + (idx / total) * 70
                ui(
                    lambda p=pct, i=idx, s=success_count, f=fail_count: self._update_progress(
                        p, f"이동 중... {i}/{total}건 (성공: {s}, 실패: {f})"
                    )
                )

        ui(lambda: self._log(f"  → 이동 결과: 성공 {success_count}건, 실패 {fail_count}건"))

        # ── 4. 빈 폴더 삭제 ──
        if not self.cancel_event.is_set():
            ui(lambda: self._update_progress(85, "빈 폴더 정리(삭제) 중..."))
            ui(lambda: self._log("▶ 4단계: 비어있는 하위 폴더 삭제..."))

            removed = 0
            all_files_resolved = all_files_dir.resolve()

            for dirpath, _dirnames, _filenames in os.walk(str(target_dir), topdown=False):
                dp = Path(dirpath).resolve()
                if dp == target_dir.resolve():
                    continue
                if dp == all_files_resolved or str(dp).startswith(str(all_files_resolved)):
                    continue
                try:
                    if not list(Path(dirpath).iterdir()):
                        os.rmdir(long_path(str(dirpath)))
                        removed += 1
                except Exception as exc:
                    ui(lambda d=dirpath, e=exc: self._log(f"  ⚠️ 폴더 삭제 실패: {d} ({e})"))

            ui(lambda: self._log(f"  → 삭제 완료된 빈 폴더: {removed}개"))

        # ── 5. 무손실 검증 ──
        ui(lambda: self._update_progress(95, "무손실 검증 중..."))
        ui(lambda: self._log("▶ 5단계: 무손실 검증 수행..."))

        actual_count = sum(1 for f in all_files_dir.iterdir() if f.is_file())
        match = (actual_count + fail_count) == total

        ui(
            lambda: self._log(
                f"  검증 수치: 대상 {total}개 = (all_files {actual_count}개 + 실패 {fail_count}건) "
                f"→ {'✅ 일치 (모든 파일 보존)' if match else '⚠️ 불일치!'}"
            )
        )

        # ── 완료 처리 (별도 팝업 및 CSV 파일 생성 없이 UI 내 직접 반영) ──
        if self.cancel_event.is_set():
            ui(lambda: self._update_progress(100, "⚠️ 작업 취소됨 (부분 완료)"))
            ui(lambda: self._log(f"⚠️ 작업이 취소되었습니다. (이동 완료: {success_count}/{total}개)"))
        elif match:
            ui(lambda: self._update_progress(100, f"✅ 평탄화 완료! ({success_count}개 파일 모두 이동)"))
            ui(lambda: self._log(f"🎉 모든 평탄화 작업이 완료되었습니다! (총 이동: {success_count}개, 리네임: {renamed_count}개)"))
        else:
            ui(lambda: self._update_progress(100, "⚠️ 완료되었으나 수치 불일치"))
            ui(lambda: self._log(f"⚠️ 파일 수 불일치! 대상: {total}, 이동됨: {actual_count}, 실패: {fail_count}"))

    # ────────────────────────── 실행 ──────────────────────────

    def run(self) -> None:
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"+{x}+{y}")
        self.root.mainloop()


# ═══════════════════════════════ 엔트리포인트 ═══════════════════════════════

def main() -> None:
    app = FlattenApp()
    app.run()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            messagebox.showerror("치명적 오류", str(e))
        except Exception:
            pass
        sys.exit(1)
