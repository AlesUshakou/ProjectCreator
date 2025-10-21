# ProjectCreator v1.01. Aleš Ushakou, 2025
# -*- coding: utf-8 -*-

import sys
import re
import shutil
import threading
import traceback
from pathlib import Path
import configparser

SCRIPT_DIR = Path(__file__).resolve().parent
ERR_LOG_PATH = SCRIPT_DIR / "ProjectCreator_error.log"
PRESETS_DIR = SCRIPT_DIR / "presets"
INI_PATH = SCRIPT_DIR / "ProjectCreator.ini"

VIDEO_EXTS = {".mov", ".mp4", ".mxf"}
SEQ_EXTS   = {".exr", ".dpx", ".tiff", ".tif", ".png", ".jpg", ".jpeg"}

ITEMS = []
ROW_IDS = []
HEADER_TEX_ID = None

def _safe_int(val, default=0):
    try:
        return int(str(val).strip())
    except Exception:
        return default

def _log_early(msg: str):
    try:
        with ERR_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(msg.rstrip() + "\n")
    except Exception:
        pass

def _install_global_exception_hook():
    import traceback as _tb, sys as _sys
    def _hook(exc_type, exc, tb):
        txt = "".join(_tb.format_exception(exc_type, exc, tb))
        _log_early("\n=== Unhandled exception ===\n" + txt)
        print(txt, file=_sys.stderr, flush=True)
    _sys.excepthook = _hook

_install_global_exception_hook()

try:
    import dearpygui.dearpygui as dpg
except Exception as e:
    _log_early(f"DearPyGUI import error: {e}")
    raise

# --- INI ---
def load_nuke_cfg():
    cfg = configparser.ConfigParser()
    if INI_PATH.exists():
        try:
            cfg.read(INI_PATH, encoding="utf-8")
        except Exception as e:
            _log_early(f"INI read error: {e}")
    section = cfg["nuke"] if "nuke" in cfg else {}
    color_model = section.get("color_model", "Nuke")
    colorspace = section.get("colorspace", "linear")
    fps = section.get("fps", "25")
    first_frame = _safe_int(section.get("first_frame", "1"), 1)
    preset_name = section.get("preset", "")
    preset_path = (PRESETS_DIR / preset_name) if preset_name else None
    return {
        "color_model": color_model,
        "colorspace": colorspace,
        "fps": fps,
        "first_frame": first_frame,
        "preset_path": preset_path if (preset_path and preset_path.exists()) else None
    }

# --- helpers ---
def is_sequence_folder(folder: Path) -> bool:
    if not folder.is_dir():
        return False
    for p in folder.iterdir():
        if p.is_file() and p.suffix.lower() in SEQ_EXTS:
            return True
    return False

def scan_resources_with_progress(src_dir: Path, progress_tag: str):
    items = []
    entries = list(sorted(src_dir.iterdir()))
    total = max(len(entries), 1)
    for i, entry in enumerate(entries, 1):
        if entry.is_file() and entry.suffix.lower() in VIDEO_EXTS:
            items.append({"type": "video", "name": entry.stem, "src": entry})
        elif entry.is_dir() and is_sequence_folder(entry):
            items.append({"type": "sequence", "name": entry.name, "src": entry})
        dpg.set_value(progress_tag, i / total)
    return items

def log(msg: str):
    if dpg.does_item_exist("log_region"):
        try:
            dpg.add_text(msg, parent="log_region")
        except Exception as e:
            _log_early(f"[UI log err] {e}: {msg}")
    else:
        _log_early(msg)
    print(msg, flush=True)

def set_progress(tag: str, value: float):
    if dpg.does_item_exist(tag):
        dpg.set_value(tag, value)

def enable_ui(enabled: bool):
    for tag in ("scan_btn", "create_btn", "src_input", "dst_input",
                "overwrite_chk", "opt_plate", "opt_camera"):
        if dpg.does_item_exist(tag):
            try:
                dpg.configure_item(tag, enabled=enabled)
            except Exception as e:
                _log_early(f"configure_item err {tag}: {e}")

def ensure_project_folders(project_root: Path, make_plate: bool, make_camera: bool):
    # убираем лишнюю 'prew'; используем 'preview' (и 'out', 'comp', 'in')
    subfolders = ["in", "preview", "comp", "out"]
    if make_plate:
        subfolders.append("plate")
    if make_camera:
        subfolders.append("camera")
    for sf in subfolders:
        (project_root / sf).mkdir(parents=True, exist_ok=True)

# --- NK generation (via create_nk) ---
def write_initial_nuke_script(project_root: Path, project_name: str, item: dict):
    from create_nk import generate_nk_text  # импорт локально
    cfg = load_nuke_cfg()
    comp_dir = project_root / "comp"
    comp_dir.mkdir(parents=True, exist_ok=True)
    nk_path = comp_dir / f"{project_name}_comp_v001.nk"
    if nk_path.exists():
        log(f"Skip (exists): {nk_path}")
        return
    nk_text = generate_nk_text(cfg, project_name, item, preset_path=cfg.get("preset_path"), log=log)
    try:
        nk_path.write_text(nk_text, encoding="utf-8")
        log(f"Created Nuke script -> {nk_path}")
    except Exception as e:
        log(f"[ERROR] Can't write Nuke script: {nk_path} :: {e}")

# --- copy ---
def do_copy(items, dst_root: Path, overwrite: bool, make_plate: bool, make_camera: bool, progress_tag: str):
    total = max(len(items), 1)
    done = 0
    errors = 0

    for it in list(items):
        name = it["name"]
        src_path: Path = it["src"]
        target_project = dst_root / name

        try:
            ensure_project_folders(target_project, make_plate, make_camera)
            write_initial_nuke_script(target_project, name, it)

            target_in = target_project / "in"

            if it["type"] == "video":
                dst_file = target_in / src_path.name
                if dst_file.exists() and not overwrite:
                    log(f"Skip (exists): {dst_file}")
                else:
                    shutil.copy2(src_path, dst_file)
                    log(f"Copied video -> {dst_file}")
            else:
                dst_seq_folder = target_in / src_path.name
                if dst_seq_folder.exists():
                    if overwrite:
                        shutil.rmtree(dst_seq_folder)
                        log(f"Removed (overwrite): {dst_seq_folder}")
                    else:
                        log(f"Skip (exists): {dst_seq_folder}")
                if (not dst_seq_folder.exists()) or overwrite:
                    shutil.copytree(src_path, dst_seq_folder)
                    log(f"Copied sequence folder -> {dst_seq_folder}")

        except Exception as e:
            errors += 1
            log(f"[ERROR] {name}: {e}")
            _log_early(f"Copy error for {name}: {e}\n{traceback.format_exc()}")

        done += 1
        set_progress(progress_tag, done / total)

    log("✅ Done: all items processed successfully." if errors == 0 else f"⚠️ Done with {errors} error(s).")

# --- table UI ---
def clear_table_rows():
    global ROW_IDS
    for rid in ROW_IDS:
        if dpg.does_item_exist(rid):
            dpg.delete_item(rid)
    ROW_IDS = []

def refresh_items_table():
    clear_table_rows()
    for idx, it in enumerate(ITEMS):
        with dpg.table_row(parent="found_table") as row_id:
            dpg.add_text(it["type"])
            dpg.add_text(it["name"])
            dpg.add_text(str(it["src"]))
            dpg.add_button(label="Remove", callback=cb_remove_item, user_data=idx)
        ROW_IDS.append(row_id)

# --- file dialogs ---
def _extract_selected_path(app_data, expect_dir=True) -> str:
    path = None
    if isinstance(app_data, dict):
        sels = app_data.get("selections") or {}
        if len(sels) >= 1:
            path = next(iter(sels.values()))
        if not path:
            path = app_data.get("file_path_name") or app_data.get("current_path")
    else:
        path = str(app_data) if app_data is not None else ""
    if not path:
        return ""
    p = Path(path)
    if expect_dir:
        try:
            if p.name and p.parent.name and (p.name == p.parent.name):
                p = p.parent
        except Exception:
            pass
    return str(p)

# --- callbacks ---
def cb_scan():
    global ITEMS
    enable_ui(False)
    if dpg.does_item_exist("log_region"):
        dpg.delete_item("log_region", children_only=True)
    set_progress("scan_progress", 0.0)

    try:
        src = Path(dpg.get_value("src_input")).expanduser()
    except Exception as e:
        log(f"[ERROR] Can't read Source path: {e}")
        enable_ui(True)
        return

    if not src.exists() or not src.is_dir():
        log(f"[ERROR] Source not found or not a folder: {src}")
        ITEMS = []
        refresh_items_table()
        enable_ui(True)
        return

    def worker():
        global ITEMS
        try:
            ITEMS = scan_resources_with_progress(src, "scan_progress")
            refresh_items_table()
            log("No .mov/.mp4/.mxf or sequence folders found." if not ITEMS else f"Found {len(ITEMS)} item(s).")
        except Exception as e:
            log(f"[ERROR] Scan failed: {e}")
            _log_early(f"Scan error: {e}\n{traceback.format_exc()}")
        finally:
            enable_ui(True)

    threading.Thread(target=worker, daemon=True).start()

def worker_create_projects():
    enable_ui(False)
    set_progress("create_progress", 0.0)
    if dpg.does_item_exist("log_region"):
        dpg.delete_item("log_region", children_only=True)

    try:
        dst = Path(dpg.get_value("dst_input")).expanduser()
        src = Path(dpg.get_value("src_input")).expanduser()
        overwrite = dpg.get_value("overwrite_chk")
        make_plate = dpg.get_value("opt_plate")
        make_camera = dpg.get_value("opt_camera")
    except Exception as e:
        log(f"[ERROR] Read UI values failed: {e}")
        enable_ui(True)
        return

    if not src.exists() or not src.is_dir():
        log(f"[ERROR] Source not found or not a folder: {src}")
        enable_ui(True)
        return
    if not dst.exists():
        try:
            dst.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            log(f"[ERROR] Cannot create destination: {e}")
            enable_ui(True)
            return

    items = ITEMS or scan_resources_with_progress(src, "scan_progress")
    refresh_items_table()
    if not items:
        log("Nothing to process.")
        enable_ui(True)
        return

    log(f"Creating projects in: {dst}")
    try:
        do_copy(items, dst, overwrite, make_plate, make_camera, "create_progress")
    except Exception as e:
        log(f"[ERROR] Create failed: {e}")
        _log_early(f"Create error: {e}\n{traceback.format_exc()}")
    finally:
        enable_ui(True)

def cb_create():
    threading.Thread(target=worker_create_projects, daemon=True).start()

def cb_pick_src(sender, app_data, user_data):
    dpg.set_value("src_input", _extract_selected_path(app_data, expect_dir=True))

def cb_pick_dst(sender, app_data, user_data):
    dpg.set_value("dst_input", _extract_selected_path(app_data, expect_dir=True))

def cb_remove_item(sender, app_data, user_data):
    global ITEMS
    idx = user_data
    if 0 <= idx < len(ITEMS):
        removed = ITEMS.pop(idx)
        log(f"Removed from list: {removed['name']}")
        refresh_items_table()

# --- header image ---
def try_load_header_image():
    global HEADER_TEX_ID
    img_path = SCRIPT_DIR / "ProjectCreator_header.png"
    if img_path.exists():
        try:
            w, h, c, data = dpg.load_image(str(img_path))
            with dpg.texture_registry(show=False):
                HEADER_TEX_ID = dpg.add_static_texture(w, h, data, tag="header_texture")
            return w, h
        except Exception as e:
            log(f"[WARN] Can't load header image: {e}")
    return None, None

# --- UI ---
def build_ui():
    dpg.create_context()
    dpg.configure_app(init_file="", load_init_file=False)
    dpg.create_viewport(title="ProjectCreator v1.01", width=1060, height=840)

    with dpg.window(label="ProjectCreator v1.01", tag="main_window", pos=(10, 10), width=1040, height=820):

        header_w, header_h = try_load_header_image()
        with dpg.child_window(autosize_x=True, height=140, border=False):
            if HEADER_TEX_ID and header_w and header_h:
                dpg.add_image("header_texture")
            else:
                with dpg.drawlist(width=1016, height=120):
                    dpg.draw_rectangle(pmin=(10, 10), pmax=(1006, 110),
                                       color=(40, 40, 70, 255), fill=(35, 35, 60, 255),
                                       rounding=12, thickness=2)
                    dpg.draw_text((30, 40), "ProjectCreator v1.01", color=(220, 230, 255, 255), size=28)
                    dpg.draw_text((32, 76), "by Ales Ushakou", color=(180, 190, 220, 255), size=16)

        dpg.add_separator()

        with dpg.tab_bar():
            with dpg.tab(label="Project Parameters"):
                dpg.add_spacer(height=4)

                with dpg.group(horizontal=True):
                    dpg.add_input_text(tag="src_input", width=780,
                                       hint="Source folder with .mov/.mp4/.mxf and/or sequence folders")
                    dpg.add_button(label="Browse", callback=lambda: dpg.show_item("file_dialog_src"))

                with dpg.group(horizontal=True):
                    dpg.add_input_text(tag="dst_input", width=780,
                                       hint="Destination folder where projects will be created")
                    dpg.add_button(label="Browse", callback=lambda: dpg.show_item("file_dialog_dst"))

                dpg.add_separator()

                with dpg.group(horizontal=True):
                    dpg.add_button(tag="scan_btn", label="Scan", callback=cb_scan)
                    dpg.add_progress_bar(tag="scan_progress", default_value=0.0, width=300)

                dpg.add_spacer(height=6)
                dpg.add_text("Found items:")

                with dpg.table(tag="found_table",
                               borders_innerH=True, borders_innerV=True,
                               borders_outerH=True, borders_outerV=True,
                               resizable=True, policy=dpg.mvTable_SizingStretchProp,
                               scrollY=True, height=340):
                    dpg.add_table_column(label="Type", width_fixed=True, init_width_or_weight=80)
                    dpg.add_table_column(label="Name", width_stretch=True)
                    dpg.add_table_column(label="Source path", width_stretch=True)
                    dpg.add_table_column(label="Actions", width_fixed=True, init_width_or_weight=100)

                dpg.add_spacer(height=8)

                with dpg.group(horizontal=True):
                    dpg.add_button(tag="create_btn", label="Create Project", callback=cb_create, width=160)
                    dpg.add_progress_bar(tag="create_progress", default_value=0.0, width=300)

                with dpg.group(horizontal=True):
                    dpg.add_checkbox(tag="overwrite_chk", label="Overwrite if exists", default_value=False)
                    dpg.add_checkbox(tag="opt_plate", label="Create 'plate' folder", default_value=False)
                    dpg.add_checkbox(tag="opt_camera", label="Create 'camera' folder", default_value=False)

                dpg.add_spacer(height=8)
                dpg.add_text("Log:")
                with dpg.child_window(tag="log_region", autosize_x=True, height=200, border=True):
                    pass

            with dpg.tab(label="Nuke Script parameters"):
                try:
                    import importlib
                    mod = importlib.import_module("nuke_params")
                    if hasattr(mod, "build_ui"):
                        mod.build_ui(parent_tag=dpg.last_container())
                    else:
                        dpg.add_text("[WARN] nuke_params.py найден, но нет функции build_ui(parent_tag=...)")
                except ModuleNotFoundError:
                    with dpg.group():
                        dpg.add_text("Nuke preset:")
                        dpg.add_input_text(tag="nuke_preset_combo", width=360, callback=lambda *a, **k: None)
                        dpg.add_text("Color:")
                        dpg.add_combo(items=["Nuke", "ACES"], tag="nuke_color_combo", width=140)
                        dpg.add_text("ColorSpace:")
                        dpg.add_combo(items=["linear"], tag="nuke_colorspace_combo", width=320)
                        dpg.add_text("[WARN] nuke_params.py не найден рядом со скриптом.")
                except Exception as e:
                    dpg.add_text(f"[ERROR] Ошибка при загрузке nuke_params.py: {e}")
                    _log_early(f"nuke_params import error: {e}\n{traceback.format_exc()}")

    with dpg.file_dialog(directory_selector=True, show=False,
                         callback=cb_pick_src, tag="file_dialog_src",
                         width=700, height=400):
        dpg.add_file_extension("")
    with dpg.file_dialog(directory_selector=True, show=False,
                         callback=cb_pick_dst, tag="file_dialog_dst",
                         width=700, height=400):
        dpg.add_file_extension("")

    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("main_window", True)
    dpg.start_dearpygui()
    dpg.destroy_context()

def main():
    try:
        PRESETS_DIR.mkdir(parents=True, exist_ok=True)
        build_ui()
    except Exception as e:
        txt = f"\n=== Fatal error on startup (v1.01) ===\n{e}\n{traceback.format_exc()}"
        _log_early(txt)
        print(txt, file=sys.stderr, flush=True)

if __name__ == "__main__":
    main()
