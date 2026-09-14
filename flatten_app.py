#!/usr/bin/env python3
"""
폴더 평탄화(Flatten) GUI 유틸리티
─────────────────────────────────
드래그 앤 드롭 또는 폴더 선택으로 대상 폴더를 지정하고,
모든 하위 파일을 'all_files' 폴더로 모은 뒤 빈 폴더를 삭제합니다.

빌드:
    pip install pyinstaller windnd
    pyinstaller --onefile --windowed --name flatten_app flatten_app.py
"""

from __future__ import annotations

import csv
import os
import shutil
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional, Tuple

try:
    import windnd

    HAS_WINDND = True
except ImportError:
    HAS_WINDND = False


# ═══════════════════════════════ 유틸리티 ═══════════════════════════════


def long_path(p: str) -> str:
    """Windows 260자 경로 제한 우회."""
    if sys.platform == "win32" and not p.startswith("\\\\?\\"):
        return "\\\\?\\" + os.path.abspath(p)
    return p


# ═══════════════════════════════ 핵심 로직 ═══════════════════════════════


def scan_files(target_dir: Path, all_files_dir: Path) -> List[Path]:
    """target_dir 하위를 재귀 스캔하여 이동 대상 파일 목록을 반환."""
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
            # flatten_log 파일 제외
            if fname.startswith("flatten_log_") and fname.endswith(".csv"):
                continue
            full_path = real_dirpath / fname
            # 이미 루트에 있는 파일은 이동 불필요
            if full_path.parent.resolve() == target_dir.resolve():
                continue
            collected.append(full_path)

    return collected


def plan_renames(
    files: List[Path],
    target_dir: Path,
    all_files_dir: Path,
) -> List[Tuple[Path, Path, str]]:
    """충돌 없는 이동 계획을 수립."""
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
            candidate = f"{stem}__{parent_tag}{suffix}"
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

    # ─── Catppuccin Mocha 기반 색상 ───
    BG = "#1e1e2e"
    FG = "#cdd6f4"
    ACCENT = "#89b4fa"
    SUCCESS = "#a6e3a1"
    WARNING = "#f9e2af"
    ERROR = "#f38ba8"
    SURFACE = "#313244"
    OVERLAY = "#45475a"
    DARK = "#11111b"

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("폴더 평탄화 (Flatten)")
        self.root.geometry("780x680")
        self.root.minsize(640, 520)
        self.root.configure(bg=self.BG)

        self.target_dir: Optional[Path] = None
        self.cancel_event = threading.Event()
        self.is_running = False

        self._setup_styles()
        self._build_ui()

        # 전체 창에 드래그 앤 드롭 후킹
        if HAS_WINDND:
            windnd.hook_dropfiles(self.root, func=self._on_drop)

    # ────────────────────────── 스타일 ──────────────────────────

    def _setup_styles(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=self.BG)
        style.configure("TLabel", background=self.BG, foreground=self.FG, font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"), foreground=self.ACCENT)
        style.configure("Sub.TLabel", font=("Segoe UI", 9), foreground=self.OVERLAY)
        style.configure("Path.TLabel", font=("Segoe UI", 9, "bold"), foreground=self.SUCCESS)
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
            text="하위 폴더의 모든 파일을 all_files 폴더 하나로 모읍니다",
            style="Sub.TLabel",
        ).pack(pady=(0, 14))

        # ── 드롭 존 ──
        self.drop_frame = tk.Frame(
            main,
            bg=self.SURFACE,
            highlightbackground=self.ACCENT,
            highlightthickness=2,
            cursor="hand2",
        )
        self.drop_frame.pack(fill=tk.X, pady=(0, 8), ipady=28)

        self.drop_label = tk.Label(
            self.drop_frame,
            text="📂  폴더를 여기에 드래그하세요\n또는 클릭하여 폴더 선택",
            bg=self.SURFACE,
            fg=self.FG,
            font=("Segoe UI", 13),
            justify=tk.CENTER,
        )
        self.drop_label.pack(expand=True, pady=12)

        self.drop_frame.bind("<Button-1>", lambda _: self._browse_folder())
        self.drop_label.bind("<Button-1>", lambda _: self._browse_folder())

        if HAS_WINDND:
            windnd.hook_dropfiles(self.drop_frame, func=self._on_drop)

        # ── 선택 경로 ──
        self.path_var = tk.StringVar(value="선택된 폴더: (없음)")
        ttk.Label(main, textvariable=self.path_var, style="Path.TLabel").pack(
            anchor=tk.W, pady=(0, 14)
        )

        # ── 버튼 영역 ──
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(0, 14))

        self.start_btn = tk.Button(
            btn_frame,
            text="🚀  작업 시작",
            font=("Segoe UI", 13, "bold"),
            bg="#a6e3a1",
            fg="#1e1e2e",
            activebackground="#94d898",
            activeforeground="#1e1e2e",
            relief=tk.FLAT,
            cursor="hand2",
            padx=30,
            pady=10,
            command=self._start,
        )
        self.start_btn.pack(side=tk.LEFT, padx=(0, 12))

        self.cancel_btn = tk.Button(
            btn_frame,
            text="❌  작업 취소",
            font=("Segoe UI", 13, "bold"),
            bg="#f38ba8",
            fg="#1e1e2e",
            activebackground="#e67a95",
            activeforeground="#1e1e2e",
            relief=tk.FLAT,
            cursor="hand2",
            padx=30,
            pady=10,
            state=tk.DISABLED,
            command=self._cancel,
        )
        self.cancel_btn.pack(side=tk.LEFT, padx=(0, 12))

        self.browse_btn = tk.Button(
            btn_frame,
            text="📂  폴더 선택",
            font=("Segoe UI", 10),
            bg=self.OVERLAY,
            fg=self.FG,
            activebackground=self.SURFACE,
            activeforeground=self.FG,
            relief=tk.FLAT,
            cursor="hand2",
            padx=16,
            pady=7,
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
        self.progress.pack(fill=tk.X, pady=(0, 4))

        # ── 상태 텍스트 ──
        self.status_var = tk.StringVar(value="대기 중...")
        ttk.Label(main, textvariable=self.status_var, style="Status.TLabel").pack(
            anchor=tk.W, pady=(0, 8)
        )

        # ── 로그 영역 ──
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

    # ────────────────────────── 이벤트 핸들러 ──────────────────────────

    def _on_drop(self, files: list) -> None:
        """드래그 앤 드롭 콜백."""
        if self.is_running or not files:
            return
        path = files[0]
        if isinstance(path, bytes):
            path = path.decode("utf-8")
        p = Path(path)
        self._set_target(p if p.is_dir() else p.parent)

    def _browse_folder(self) -> None:
        """폴더 선택 다이얼로그."""
        if self.is_running:
            return
        folder = filedialog.askdirectory(title="평탄화할 폴더를 선택하세요")
        if folder:
            self._set_target(Path(folder))

    def _set_target(self, path: Path) -> None:
        self.target_dir = path.resolve()
        self.path_var.set(f"선택된 폴더: {self.target_dir}")
        self.drop_label.config(text=f"📂  {self.target_dir.name}\n(다른 폴더를 드래그하여 변경)")
        self._log(f"대상 폴더 설정: {self.target_dir}")

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
            messagebox.showwarning("경고", "먼저 폴더를 선택하거나 드래그하세요.")
            return
        if not self.target_dir.exists():
            messagebox.showerror("오류", f"폴더가 존재하지 않습니다:\n{self.target_dir}")
            return

        ok = messagebox.askyesno(
            "확인",
            f"다음 폴더를 평탄화합니다:\n\n{self.target_dir}\n\n"
            "모든 하위 파일이 'all_files' 폴더로 이동되고,\n"
            "빈 폴더가 삭제됩니다.\n\n계속하시겠습니까?",
        )
        if not ok:
            return

        self.is_running = True
        self.cancel_event.clear()
        self.start_btn.config(state=tk.DISABLED)
        self.cancel_btn.config(state=tk.NORMAL)
        self.browse_btn.config(state=tk.DISABLED)

        threading.Thread(target=self._run_flatten, daemon=True).start()

    def _cancel(self) -> None:
        if self.is_running:
            self.cancel_event.set()
            self._log("⚠️  취소 요청됨 — 현재 파일 처리 완료 후 중단합니다...")
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
            self.root.after(0, lambda: self._log(f"❌ 예상치 못한 오류: {exc}"))
            self.root.after(0, lambda: messagebox.showerror("오류", str(exc)))
        finally:
            self.root.after(0, self._finish)

    def _do_flatten(self) -> None:  # noqa: C901 — 의도적으로 단일 흐름 유지
        target_dir = self.target_dir
        all_files_dir = target_dir / "all_files"

        def ui(fn):
            """메인 스레드에서 UI 업데이트."""
            self.root.after(0, fn)

        # ── 1. 스캔 ──
        ui(lambda: self._update_progress(0, "파일 스캔 중..."))
        ui(lambda: self._log("▶ 1단계: 파일 스캔 중..."))

        files = scan_files(target_dir, all_files_dir)
        total = len(files)

        if total == 0:
            ui(lambda: self._log("이동할 하위 파일이 없습니다."))
            ui(lambda: self._update_progress(100, "완료 — 이동할 파일 없음"))
            ui(lambda: messagebox.showinfo("완료", "이동할 하위 파일이 없습니다."))
            return

        ui(lambda: self._log(f"  → 발견된 파일: {total}개"))

        if self.cancel_event.is_set():
            ui(lambda: self._log("❌ 사용자에 의해 취소됨"))
            return

        # ── 2. all_files 생성 + 리네임 계획 ──
        all_files_dir.mkdir(exist_ok=True)
        ui(lambda: self._update_progress(5, "충돌 검사 중..."))
        ui(lambda: self._log("▶ 2단계: 충돌 검사 및 리네임 계획..."))

        plan = plan_renames(files, target_dir, all_files_dir)
        renamed_count = sum(1 for _, _, r in plan if r == "Y")
        ui(lambda: self._log(f"  → 리네임 필요: {renamed_count}개"))

        if self.cancel_event.is_set():
            ui(lambda: self._log("❌ 사용자에 의해 취소됨"))
            return

        # ── 3. 파일 이동 ──
        ui(lambda: self._update_progress(10, "파일 이동 중..."))
        ui(lambda: self._log("▶ 3단계: 파일 이동 중..."))

        results: list[dict] = []
        success_count = 0
        fail_count = 0
        log_interval = max(1, total // 100)  # ~100회 UI 업데이트

        for idx, (src, dest, renamed) in enumerate(plan, 1):
            if self.cancel_event.is_set():
                ui(lambda i=idx: self._log(f"❌ 취소됨 ({i - 1}/{total} 처리 완료)"))
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
                        p, f"이동 중... {i}/{total}  성공={s} 실패={f}"
                    )
                )

        ui(lambda: self._log(f"  → 이동 완료: 성공={success_count}, 실패={fail_count}"))

        # ── 4. 빈 폴더 삭제 ──
        if not self.cancel_event.is_set():
            ui(lambda: self._update_progress(85, "빈 폴더 삭제 중..."))
            ui(lambda: self._log("▶ 4단계: 빈 폴더 삭제 중..."))

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

            ui(lambda: self._log(f"  → 삭제된 폴더: {removed}개"))

        # ── 5. 로그 기록 ──
        ui(lambda: self._update_progress(92, "로그 기록 중..."))
        ui(lambda: self._log("▶ 5단계: 로그 기록 중..."))

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = target_dir / f"flatten_log_{ts}.csv"

        try:
            with open(long_path(str(log_path)), "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["원본경로", "최종파일명", "상태", "리네임"])
                writer.writeheader()
                writer.writerows(results)
            ui(lambda: self._log(f"  → 로그 파일: {log_path}"))
        except Exception as exc:
            ui(lambda: self._log(f"  ⚠️ 로그 기록 실패: {exc}"))

        # ── 6. 무손실 검증 ──
        ui(lambda: self._update_progress(96, "검증 중..."))
        ui(lambda: self._log("▶ 6단계: 무손실 검증..."))

        actual_count = sum(1 for f in all_files_dir.iterdir() if f.is_file())
        match = (actual_count + fail_count) == total

        ui(
            lambda: self._log(
                f"  스캔={total}, all_files={actual_count}, 실패={fail_count}, "
                f"합계={actual_count + fail_count} → {'✅ 일치' if match else '⚠️ 불일치!'}"
            )
        )

        # ── 완료 메시지 ──
        if self.cancel_event.is_set():
            ui(lambda: self._update_progress(100, "취소됨 (일부 처리 완료)"))
            ui(
                lambda: messagebox.showwarning(
                    "취소됨",
                    f"작업이 취소되었습니다.\n"
                    f"처리: {success_count}/{total}\n"
                    f"로그: {log_path}",
                )
            )
        elif match:
            ui(lambda: self._update_progress(100, f"✅ 완료! {success_count}개 파일 이동"))
            ui(lambda: self._log("✅ 평탄화 작업이 성공적으로 완료되었습니다!"))
            ui(
                lambda: messagebox.showinfo(
                    "완료",
                    f"평탄화 완료!\n\n"
                    f"이동된 파일: {success_count}개\n"
                    f"로그: {log_path}",
                )
            )
        else:
            ui(lambda: self._update_progress(100, "⚠️ 완료 (검증 불일치)"))
            ui(
                lambda: messagebox.showwarning(
                    "경고",
                    f"파일 수 불일치!\n\n"
                    f"예상: {total}\n"
                    f"실제: {actual_count} + 실패 {fail_count}\n\n"
                    f"로그 확인: {log_path}",
                )
            )

    # ────────────────────────── 실행 ──────────────────────────

    def run(self) -> None:
        # 화면 중앙 배치
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
        # --windowed 모드에서도 오류 확인 가능하도록
        try:
            messagebox.showerror("치명적 오류", str(e))
        except Exception:
            pass
        sys.exit(1)
