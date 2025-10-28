# PCUtility.py
# ProjectCreator v1.1. Aleš Ushakou, 2025
# -*- coding: utf-8 -*-

from pathlib import Path
import os
import dearpygui.dearpygui as dpg

# -------- Common helpers --------
def _dedupe_tail(path_str: str) -> str:
    if not path_str:
        return path_str
    p = Path(path_str)
    parts = p.parts
    if len(parts) >= 2 and parts[-1].strip("\\/").lower() == parts[-2].strip("\\/").lower():
        return str(Path(*parts[:-1]))
    return path_str

def _extract_selected_path(app_data) -> str:
    # Для directory_selector=True используем current_path
    if isinstance(app_data, dict):
        cp = app_data.get("current_path")
        if cp:
            return _dedupe_tail(cp)
        sels = app_data.get("selections") or {}
        if sels:
            return _dedupe_tail(next(iter(sels.values())))
        fp = app_data.get("file_path_name")
        if fp:
            return _dedupe_tail(fp)
        return ""
    return str(app_data or "")

def _log(msg: str):
    print(msg, flush=True)
    if dpg.does_item_exist("util_log"):
        dpg.add_text(msg, parent="util_log")

def _log_batch(lines):
    if not lines:
        return
    text = "\n".join(lines)
    print(text, flush=True)
    if dpg.does_item_exist("util_log"):
        dpg.add_text(text, parent="util_log")

# -------- Fast FS ops --------
def _iter_files(folder: Path, recursive: bool):
    if not recursive:
        try:
            with os.scandir(folder) as it:
                for entry in it:
                    if entry.is_file():
                        yield Path(entry.path)
        except Exception:
            return
    else:
        for root, dirs, files in os.walk(folder):
            dp = Path(root)
            for name in files:
                yield dp / name

def _get_dir_name_sets(dir_path: Path):
    cf_set, real_set = set(), set()
    try:
        with os.scandir(dir_path) as it:
            for e in it:
                real_set.add(e.name)
                cf_set.add(e.name.casefold())
    except FileNotFoundError:
        pass
    return cf_set, real_set

def _unique_target_name(dir_cf_set: set, base_name: str) -> str:
    name = base_name
    stem, dot, ext = base_name.partition(".")
    n = 1
    while name.casefold() in dir_cf_set:
        name = f"{stem}_r{n}{('.' + ext) if ext else ''}"
        n += 1
    dir_cf_set.add(name.casefold())
    return name

def _rename_in_dir(dir_path: Path, files: list[Path], patterns: list[str], replacement: str, progress_tag=None):
    log_lines, changed, errors = [], 0, 0
    dir_cf_set, _ = _get_dir_name_sets(dir_path)
    total = len(files) or 1
    done = 0
    for src in files:
        done += 1
        if progress_tag and dpg.does_item_exist(progress_tag):
            dpg.set_value(progress_tag, done / total)
        old = src.name
        new = old
        for pat in patterns:
            if pat:
                new = new.replace(pat, replacement)
        if new == old:
            continue
        old_cf = old.casefold()
        new_cf = new.casefold()
        target = src.parent / new
        if new_cf in dir_cf_set and new_cf != old_cf:
            new = _unique_target_name(dir_cf_set, new)
            target = src.parent / new
        else:
            dir_cf_set.add(new_cf)
        try:
            if old_cf == new_cf and old != new:
                tmp = src.parent / (_unique_target_name(dir_cf_set, f"__pc_tmp__{old}"))
                os.replace(src, tmp)
                os.replace(tmp, target)
            else:
                os.replace(src, target)
            changed += 1
            log_lines.append(f"✔ {old} → {target.name}")
        except Exception as e:
            errors += 1
            log_lines.append(f"[ERROR] {old}: {e}")
    return changed, errors, log_lines

def _group_by_parent(files_iter):
    buckets = {}
    for p in files_iter:
        buckets.setdefault(p.parent, []).append(p)
    return buckets

def _rename_files_fast(folder: Path, patterns: list[str], replacement: str, include_subdirs: bool):
    if not folder.exists() or not folder.is_dir():
        return 0, 0, ["[ERROR] Folder not found or not a directory."]
    buckets = _group_by_parent(_iter_files(folder, include_subdirs))
    if not buckets:
        return 0, 0, ["No files to rename."]
    total_changed = total_errors = 0
    all_logs = []
    for dir_path, files in buckets.items():
        changed, errors, logs = _rename_in_dir(dir_path, files, patterns, replacement, progress_tag="util_progress")
        total_changed += changed
        total_errors += errors
        all_logs.append(f"[{dir_path}] changed: {changed}, errors: {errors}")
        all_logs.extend(logs)
    return total_changed, total_errors, all_logs

# -------- UI & callbacks --------
def _cb_pick_folder(sender, app_data, user_data):
    dpg.set_value("util_folder_input", _extract_selected_path(app_data))

def _cb_do_rename():
    folder = Path(dpg.get_value("util_folder_input") or "").expanduser()
    raw_patterns = dpg.get_value("util_search_input") or ""
    replacement = dpg.get_value("util_replace_input") or ""
    include_subdirs = bool(dpg.get_value("util_recursive_chk"))

    if dpg.does_item_exist("util_log"):
        dpg.delete_item("util_log", children_only=True)
    if dpg.does_item_exist("util_progress"):
        dpg.set_value("util_progress", 0.0)

    patterns = [s.strip() for s in raw_patterns.split(",") if s.strip()]

    if not folder or not folder.exists():
        _log("[ERROR] Please select a valid folder.")
        return
    if not patterns:
        _log("[WARN] Nothing to search for (empty patterns).")
        return

    _log(f"Bulk rename in: {folder}")
    _log(f"Search: {patterns} | Replace with: {'(remove)' if replacement == '' else replacement} | Recursive: {include_subdirs}")

    changed, errors, lines = _rename_files_fast(folder, patterns, replacement, include_subdirs)
    _log_batch(lines)
    _log(f"Done. Renamed: {changed}, errors: {errors}")

def build_ui(parent_tag=None):
    if parent_tag is None:
        parent_tag = dpg.last_container()

    if not dpg.does_item_exist("util_file_dialog"):
        with dpg.file_dialog(directory_selector=True, show=False,
                             callback=_cb_pick_folder, tag="util_file_dialog",
                             width=700, height=400):
            dpg.add_file_extension("")

    root = dpg.add_group(parent=parent_tag)
    dpg.add_text("Bulk Rename", bullet=True, parent=root)
    dpg.add_separator(parent=root)

    row_folder = dpg.add_group(horizontal=True, parent=root)
    dpg.add_input_text(tag="util_folder_input", width=700,
                       hint="Select folder to bulk rename files in", parent=row_folder)
    dpg.add_button(label="Browse", callback=lambda: dpg.show_item("util_file_dialog"), parent=row_folder)

    dpg.add_spacer(height=6, parent=root)

    row_repl = dpg.add_group(horizontal=True, parent=root)
    dpg.add_text("Search (comma-separated):", parent=row_repl)
    dpg.add_input_text(tag="util_search_input", width=360, hint="e.g. _v001,_WIP,raw", parent=row_repl)
    dpg.add_spacer(width=12, parent=row_repl)
    dpg.add_text("Replace with:", parent=row_repl)
    dpg.add_input_text(tag="util_replace_input", width=220, hint="leave empty to remove", parent=row_repl)

    dpg.add_spacer(height=6, parent=root)

    row_opts = dpg.add_group(horizontal=True, parent=root)
    dpg.add_checkbox(tag="util_recursive_chk", label="Include subfolders", default_value=True, parent=row_opts)
    dpg.add_spacer(width=12, parent=row_opts)
    dpg.add_button(label="Rename", width=120, callback=_cb_do_rename, parent=row_opts)
    dpg.add_spacer(width=12, parent=row_opts)
    dpg.add_progress_bar(tag="util_progress", default_value=0.0, width=240, parent=row_opts)

    dpg.add_spacer(height=8, parent=root)
    dpg.add_text("Log:", parent=root)
    dpg.add_child_window(tag="util_log", autosize_x=True, height=220, border=True, parent=root)
