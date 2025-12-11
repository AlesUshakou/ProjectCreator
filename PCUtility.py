# PCUtility for ProjectCreator
# Bulk Rename
# by Aleš Ushakou, 2025

from __future__ import annotations

import os
from pathlib import Path
import dearpygui.dearpygui as dpg
from typing import List

# ---------------------------
# UI helpers / logging
# ---------------------------

def _util_log(msg: str):
    if dpg.does_item_exist("util_log"):
        dpg.set_value("util_log", dpg.get_value("util_log") + msg + "\n")
    else:
        print(msg)

def _browse_dir_to(tag: str):
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    folder = filedialog.askdirectory()
    if folder:
        dpg.set_value(tag, folder)

def _util_set_progress(value: float):
    """0..1, обновляет прогресс и проценты поверх."""
    if not dpg.does_item_exist("util_progress"):
        return
    v = max(0.0, min(1.0, float(value)))
    dpg.set_value("util_progress", v)
    try:
        dpg.configure_item("util_progress", overlay=f"{int(round(v * 100))}%")
    except Exception:
        pass

# ---------------------------
# Rename logic
# ---------------------------

def _parse_find_terms(raw: str) -> List[str]:
    # Разбиваем по запятой, чистим пробелы, убираем пустые
    terms = [t.strip() for t in (raw or "").split(",")]
    return [t for t in terms if t]

def _multi_replace(text: str, find_terms: List[str], replacement: str) -> str:
    # Последовательная замена: слева направо
    out = text
    for term in find_terms:
        if term:
            out = out.replace(term, replacement)
    return out

def _unique_target_path(dst: Path) -> Path:
    """Если цель уже существует — добавляем суффикс (2), (3), …"""
    if not dst.exists():
        return dst
    base = dst.stem
    ext  = dst.suffix
    parent = dst.parent
    i = 2
    while True:
        candidate = parent / f"{base} ({i}){ext}"
        if not candidate.exists():
            return candidate
        i += 1

def _safe_rename(src: Path, dst: Path):
    """Безопасное переименование с автоконфликт-резолвером."""
    if src == dst:
        return
    target = _unique_target_path(dst)
    src.rename(target)

def _rename_file(path: Path, find_terms: List[str], replacement: str):
    new_name = _multi_replace(path.name, find_terms, replacement)
    if new_name != path.name:
        _safe_rename(path, path.with_name(new_name))
        _util_log(f"[FILE] {path.name}  ->  {new_name}")

def _rename_dir(path: Path, find_terms: List[str], replacement: str):
    new_name = _multi_replace(path.name, find_terms, replacement)
    if new_name != path.name:
        _safe_rename(path, path.with_name(new_name))
        _util_log(f"[DIR]  {path.name}  ->  {new_name}")

def _bulk_rename_run():
    root_dir = Path(dpg.get_value("util_root_dir") or "")
    if not root_dir.exists():
        _util_log("[WARN] Select valid folder.")
        return

    find_raw   = dpg.get_value("util_find_terms") or ""
    replace_to = dpg.get_value("util_replace_to") or ""
    recursive  = dpg.get_value("util_recursive")  or False

    find_terms = _parse_find_terms(find_raw)
    if not find_terms:
        _util_log("[WARN] Nothing to find — enter comma-separated terms.")
        return

    _util_log(f"[RUN] Root: {root_dir}")
    _util_log(f"[RUN] Find: {find_terms}  Replace: '{replace_to}'  Recursive: {recursive}")

    # сброс прогресса
    _util_set_progress(0.0)

    try:
        # 1) сначала собираем цели (файлы и папки)
        targets = []  # список (Path, "file"/"dir")

        if recursive:
            # ВАЖНО: topdown=False — сначала вложенные, потом родительские папки
            for root, dirs, files in os.walk(root_dir, topdown=False):
                rpath = Path(root)

                for name in files:
                    targets.append((rpath / name, "file"))

                for d in dirs:
                    targets.append((rpath / d, "dir"))
        else:
            # Только прямые дети
            for p in root_dir.iterdir():
                if p.is_file():
                    targets.append((p, "file"))
            for p in root_dir.iterdir():
                if p.is_dir():
                    targets.append((p, "dir"))

        total = len(targets) or 1

        # 2) обрабатываем и двигаем прогресс
        for idx, (path, kind) in enumerate(targets, 1):
            if kind == "file":
                _rename_file(path, find_terms, replace_to)
            else:
                _rename_dir(path, find_terms, replace_to)

            _util_set_progress(idx / total)

        _util_log("[OK] Bulk rename finished.")
        _util_set_progress(1.0)

    except Exception as e:
        _util_log(f"[ERROR] {e}")
        _util_set_progress(1.0)


# ---------------------------
# UI build
# ---------------------------

def build_ui(parent_tag: str):
    """
    Создаёт вкладку Utility с блоком Bulk Rename.
    parent_tag — tag контейнера вкладки (из ProjectCreator.py).
    """
    with dpg.group(parent=parent_tag):
        dpg.add_separator()
        dpg.add_text("Bulk Rename", bullet=False)
        dpg.add_spacer(height=4)

        # Папка
        with dpg.group(horizontal=True):
            dpg.add_text("Folder")
            dpg.add_input_text(tag="util_root_dir", width=520, hint="Select folder to rename inside...")
            dpg.add_button(label="Browse", callback=lambda: _browse_dir_to("util_root_dir"))

        dpg.add_spacer(height=4)

        # Строка поиска и замены (в одну строку)
        with dpg.group(horizontal=True):
            dpg.add_text("Find (comma-separated)")
            dpg.add_input_text(tag="util_find_terms", width=260, hint="e.g. shot_, v001, temp")
            dpg.add_text(" Replace")
            dpg.add_input_text(tag="util_replace_to", width=180, hint="leave empty to remove")

        dpg.add_spacer(height=4)

        # Опции
        with dpg.group(horizontal=True):
            dpg.add_checkbox(tag="util_recursive", label="Rename in subfolders (recursive)", default_value=True)

        dpg.add_spacer(height=6)

        with dpg.group(horizontal=True):
            dpg.add_button(label="Start Bulk Rename", width=180, callback=_bulk_rename_run)
            dpg.add_spacer(width=10)
            dpg.add_progress_bar(tag="util_progress", width=200, default_value=0.0, overlay="0%")

        dpg.add_spacer(height=6)
        dpg.add_input_text(tag="util_log", multiline=True, readonly=True, width=-1, height=200)

