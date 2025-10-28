# ProjectCreator.py
# ProjectCreator v1.11. Aleš Ushakou, 2025
# -*- coding: utf-8 -*-

from pathlib import Path
import shutil
import traceback
import importlib
import dearpygui.dearpygui as dpg
import sys
import os
import configparser

APP_TITLE = "ProjectCreator v1.11"
SCRIPT_DIR = Path(__file__).resolve().parent

VIDEO_EXTS = {".mov", ".mp4", ".mxf"}
SEQ_EXTS = {".exr", ".dpx", ".tiff", ".tif", ".png", ".jpg", ".jpeg"}

INI_PATH = SCRIPT_DIR / "ProjectCreator.ini"
HEADER_IMAGE_PATH =  SCRIPT_DIR / "src" / "ProjectCreator_header.png"

OVERWRITE_CHOICES = ["None", "All", "Source", "Nuke Script"]






# ---------------- Crash Handler ----------------
def _show_win_message_box(title: str, text: str):
    try:
        import ctypes
        MB_OK = 0x0
        ctypes.windll.user32.MessageBoxW(0, text, title, MB_OK)
    except Exception:
        pass

sys.excepthook = lambda exctype, value, tb: _show_win_message_box(
    "ProjectCreator - Error", f"An error occurred.\n{value}"
)

# ---------------- Logging ----------------
def log(msg: str):
    print(msg, flush=True)
    if dpg.does_item_exist("log_console"):
        dpg.add_text(str(msg), parent="log_console")

# ---------------- Helpers ----------------
def _safe_mkdir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def _is_hidden(p: Path) -> bool:
    return p.name.startswith(".")

def _dedupe_tail(path_str: str) -> str:
    if not path_str:
        return path_str
    p = Path(path_str)
    parts = p.parts
    if len(parts) >= 2 and parts[-1].lower() == parts[-2].lower():
        return str(Path(*parts[:-1]))
    return path_str

def _extract_path_from_dialog(app_data) -> str:
    # DearPyGui dialog returns a dict; normalize to a clean path string
    if isinstance(app_data, dict):
        sels = app_data.get("selections") or {}
        if sels:
            return _dedupe_tail(next(iter(sels.values())))
        cp = app_data.get("current_path")
        if cp:
            return _dedupe_tail(cp)
        fp = app_data.get("file_path_name")
        if fp:
            return _dedupe_tail(fp)
    return str(app_data or "")

def _dir_is_effectively_empty(p: Path) -> bool:
    """True, если папка не существует или в ней нет НЕскрытых элементов."""
    if not p.exists():
        return True
    try:
        for f in p.iterdir():
            if not _is_hidden(f):  # у тебя уже есть _is_hidden
                return False
    except Exception:
        return False
    return True

def _shot_prog_tag(shot_name: str) -> str:
    # стабильный tag для прогресс-бара конкретного шота
    return f"shot_prog__{shot_name}"

def _update_shot_progress(shot_name: str, value: float):
    """Обновляет прогресс (0..1) для шота в таблице, если бар существует."""
    tag = _shot_prog_tag(shot_name)
    if dpg.does_item_exist(tag):
        dpg.set_value(tag, max(0.0, min(1.0, float(value))))

def _list_sequence_files(src_seq_dir: Path) -> list[Path]:
    files = []
    for root, dirs, fnames in os.walk(src_seq_dir):
        # исключаем скрытые папки
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for fn in fnames:
            if fn.startswith('.'):
                continue
            p = Path(root) / fn
            if p.is_file():
                files.append(p)
    return files





# ----------- INI robust reading (supports lists without '=') -----------
def _clean_val(s: str) -> str:
    """Remove literal \n, quotes and trim spaces."""
    if s is None:
        return ""
    return s.replace("\\n", "").strip().strip("'").strip('"').strip()

def _cfg_get_any(sec, *keys, default=""):
    """Try multiple key spellings (case/space-insensitive)."""
    if not sec:
        return default
    for k in keys:
        if k in sec:
            return _clean_val(sec.get(k, default))
        kl = k.lower()
        for cand in list(sec.keys()):
            if cand.lower() == kl or cand.replace(" ", "").lower() == kl.replace(" ", ""):
                return _clean_val(sec.get(cand, default))
    return default

def _read_list_section(cfg, section_name: str) -> list[str]:
    """
    Reads sections like:
      [FPS]
      24
      25
      30
    (allow_no_value=True treats each line as a key with value=None)
    Returns cleaned unique list preserving order.
    """
    if section_name not in cfg:
        return []
    sec = cfg[section_name]
    items = list(sec.keys())
    # include possible key=value forms too
    for k, v in sec.items():
        if v and v.strip():
            items.append(f"{k}={v}")
    out = []
    for it in items:
        it = _clean_val(it)
        if it:
            out.append(it)
    seen = set()
    uniq = []
    for x in out:
        if x not in seen:
            uniq.append(x)
            seen.add(x)
    return uniq

def _read_ini_values() -> dict:
    """
    Flexible INI reader:
    - supports list-like sections without '='
    - cleans quotes and literal \n if they accidentally got into file
    Returns minimal dict used by ProjectCreator.
    """
    cfg = configparser.ConfigParser(allow_no_value=True, strict=False, interpolation=None)
    cfg.optionxform = str  # keep key case
    if INI_PATH.exists():
        try:
            cfg.read(INI_PATH, encoding="utf-8")
        except Exception as e:
            log(f"[WARN] INI parse issue: {e}. Trying to clean \\n/quotes and re-read.")
            txt = INI_PATH.read_text(encoding="utf-8")
            txt2 = txt.replace("\\n", "")
            INI_PATH.write_text(txt2, encoding="utf-8")
            cfg.read(INI_PATH, encoding="utf-8")

    nuke_sec = cfg["nuke"] if "nuke" in cfg else {}

    preset      = _cfg_get_any(nuke_sec, "preset", default="")
    color_model = _cfg_get_any(nuke_sec, "color_model", "ColorModel", default="Nuke")
    colorspace  = _cfg_get_any(nuke_sec, "colorspace", "ColorSpace", default="AlexaV3LogC")
    first_frame = _cfg_get_any(nuke_sec, "First frame", "FirstFrame", default="1001")
    fps         = _cfg_get_any(nuke_sec, "FPS", default="25")

    # Optional lists (for other UIs like nuke_params.py)
    fps_list         = _read_list_section(cfg, "FPS")
    first_frame_list = _read_list_section(cfg, "First.frame")
    colors_nuke      = _read_list_section(cfg, "colorspaces.Nuke")
    colors_aces      = _read_list_section(cfg, "colorspaces.ACES")

    return {
        "preset": preset,
        "color_model": color_model,
        "colorspace": colorspace,
        "first_frame": first_frame,
        "fps": fps,
        "_lists": {
            "FPS": fps_list,
            "First.frame": first_frame_list,
            "colorspaces.Nuke": colors_nuke,
            "colorspaces.ACES": colors_aces,
        }
    }

def _import_create_nk():
    try:
        return importlib.import_module("create_nk")
    except Exception as e:
        log(f"[ERROR] Can't import create_nk.py: {e}")
        log(traceback.format_exc())
        return None

# ---------------- File scan ----------------
_found_items = []

def _is_sequence_dir(d: Path) -> bool:
    if not d.is_dir() or _is_hidden(d):
        return False
    try:
        for child in d.iterdir():
            if _is_hidden(child):
                continue
            if child.is_file() and child.suffix.lower() in SEQ_EXTS:
                return True
    except Exception:
        return False
    return False

def scan_resources(src_dir: Path):
    global _found_items
    _found_items = []
    _clear_found_table()
    if not src_dir.exists():
        log("[ERROR] Source folder invalid.")
        return

    items = [ch for ch in src_dir.iterdir() if not _is_hidden(ch)]
    total = max(len(items), 1)

    for i, child in enumerate(items, 1):
        if dpg.does_item_exist("scan_progress"):
            dpg.set_value("scan_progress", i / total)
        if child.is_file() and child.suffix.lower() in VIDEO_EXTS:
            it = {"name": child.stem, "type": "video", "src": child}
            _found_items.append(it)
            _add_item_row(it)
        elif _is_sequence_dir(child):
            it = {"name": child.name, "type": "sequence", "src": child}
            _found_items.append(it)
            _add_item_row(it)
    if not _found_items:
        log("No valid items found.")

# ---------------- Table ----------------
def _make_table_theme():
    # alternate row background colors (DPG-compatible across versions)
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvTable):
            dpg.add_theme_color(dpg.mvThemeCol_TableRowBg, (35, 35, 40, 255))
            dpg.add_theme_color(dpg.mvThemeCol_TableRowBgAlt, (48, 48, 55, 255))
    return theme

def _ensure_found_table():
    if not dpg.does_item_exist("found_table"):
        with dpg.table(tag="found_table", header_row=True, resizable=True,
                       reorderable=True, row_background=True,
                       borders_innerH=True, borders_outerH=True,
                       borders_innerV=True, borders_outerV=True,
                       policy=dpg.mvTable_SizingStretchProp,
                       parent="found_table_region"):
            dpg.add_table_column(label="Name")
            dpg.add_table_column(label="Type")
            dpg.add_table_column(label="Source")
            dpg.add_table_column(label="Action")
            dpg.add_table_column(label="Progress")
        dpg.bind_item_theme("found_table", _make_table_theme())

def _clear_found_table():
    _ensure_found_table()
    rows = dpg.get_item_children("found_table", 1) or []
    for r in rows:
        dpg.delete_item(r)

def _add_item_row(item: dict):
    _ensure_found_table()
    row = dpg.add_table_row(parent="found_table")

    # столбец: Name
    dpg.add_text(item["name"], parent=row)
    # столбец: Type
    dpg.add_text(item["type"], parent=row)
    # столбец: Source
    dpg.add_text(str(item["src"]), parent=row)
    # столбец: Action
    dpg.add_button(label="Remove", user_data=item, callback=_cb_remove_item, parent=row)
    # столбец: Progress (новое)
    dpg.add_progress_bar(tag=_shot_prog_tag(item["name"]), parent=row, width=-1, default_value=0.0)

def _cb_remove_item(sender, app_data, user_data):
    global _found_items
    _found_items = [x for x in _found_items if x["src"] != user_data["src"]]
    _clear_found_table()
    for it in _found_items:
        _add_item_row(it)

# ---------------- Project creation ----------------
def _safe_copy(src, dst):
    if src.is_file():
        shutil.copy2(src, dst)
    else:
        shutil.copytree(src, dst, dirs_exist_ok=True)

def _create_basic_structure(dest: Path, item: dict):
    shot_dir = dest / item["name"]
    for sub in ("in", "preview", "comp", "out"):
        _safe_mkdir(shot_dir / sub)
    return shot_dir


def _resolve_preset(preset_value: str) -> Path | None:
    if not preset_value:
        return None

    # 1) как задан (может быть абсолютным или относительным к CWD)
    p = Path(preset_value)
    if p.is_file():
        return p.resolve()

    # 2) относительный к папке скрипта
    p2 = (SCRIPT_DIR / preset_value)
    if p2.is_file():
        return p2.resolve()

    # 3) в подпапке presets рядом со скриптом
    p3 = SCRIPT_DIR / "presets" / Path(preset_value).name
    if p3.is_file():
        return p3.resolve()

    # 4) попробуем взять только имя файла (на случай, если в ini был указан полный путь с ошибкой '\' vs '/')
    p4 = SCRIPT_DIR / "presets" / Path(preset_value).name.replace("\\", "/")
    if p4.is_file():
        return p4.resolve()

    return None


def _generate_nuke_script(shot_dir: Path, item: dict, cfg: dict, overwrite_nk: bool):
    """
    Генерирует .nk, передавая preset_path (Path или None) в create_nk.
    Теперь логирует, какой пресет используется и корректно обрабатывает ошибку отсутствия пресета.
    """
    create_nk = _import_create_nk()
    if not create_nk:
        log("[ERROR] create_nk module not available; skipping NK generation.")
        return

    nk_path = shot_dir / "comp" / f"{item['name']}_comp_v001.nk"
    if nk_path.exists() and not overwrite_nk:
        log(f"[SKIP] NK exists: {nk_path.name}")
        return

    # Получаем строку preset из cfg (если есть)
    preset_value = cfg.get("preset") if cfg else None

    preset_path = None
    if preset_value:
        preset_path = _resolve_preset(preset_value)
        if preset_path:
            log(f"[NK] Resolved preset: {preset_path}")
        else:
            log(f"[NK][WARN] Preset specified in INI but not found: '{preset_value}'")
    else:
        log("[NK] No preset specified in INI (cfg['preset'] empty).")

    try:
        # передаем Path или None — create_nk обязан бросать FileNotFoundError, если preset не найден
        nk_text = create_nk.generate_nk_text(cfg, item["name"], item, preset_path, log)
    except FileNotFoundError as fnf:
        # create_nk сообщил, что пресета нет — логируем и пропускаем этот shot
        log(f"[ERROR] create_nk: {fnf}. Skipping .nk creation for {item['name']}")
        return
    except Exception as e:
        # любая другая ошибка — логируем полную трассировку и пропускаем
        log(f"[ERROR] Unexpected error generating .nk for {item['name']}: {e}")
        try:
            import traceback
            traceback_text = traceback.format_exc()
            log(traceback_text)
        except Exception:
            pass
        return

    # если дошли сюда — nk_text успешно создан
    nk_path.write_text(nk_text, encoding="utf-8")
    log(f"[NK] Created {nk_path}")


def _on_create_projects(dest: Path, overwrite_mode: str):
    if not _found_items:
        log("[WARN] Nothing to create.")
        return

    overwrite_src = overwrite_mode in ("All", "Source")
    overwrite_nk  = overwrite_mode in ("All", "Nuke Script")
    cfg = _read_ini_values()

    total = len(_found_items) or 1
    for idx, item in enumerate(_found_items, 1):
        if dpg.does_item_exist("create_progress"):
            dpg.set_value("create_progress", idx / total)

        shot   = _create_basic_structure(dest, item)
        in_dir = shot / "in"
        _safe_mkdir(in_dir)

        shot_name = item["name"]
        _update_shot_progress(shot_name, 0.0)  # << добавили

        try:
            if item["type"] == "video":
                dst_file = in_dir / item["src"].name

                if overwrite_src:
                    _safe_copy(item["src"], dst_file)
                    log(f"[COPY] {item['name']}: {dst_file.name}")
                else:
                    if not dst_file.exists():
                        _safe_copy(item["src"], dst_file)
                        log(f"[COPY] {item['name']}: {dst_file.name}")
                    else:
                        log(f"[SKIP] {item['name']}: {dst_file.name} exists")

                _update_shot_progress(shot_name, 1.0)  # << добавили

            else:
                # === Новый блок для секвенций (пофайловое копирование + прогресс) ===
                src_seq_dir = item["src"]
                dst_seq_dir = in_dir / src_seq_dir.name

                files = _list_sequence_files(src_seq_dir)
                total_files = max(len(files), 1)
                copied = 0

                if overwrite_src:
                    if dst_seq_dir.exists():
                        shutil.rmtree(dst_seq_dir, ignore_errors=True)
                    _safe_mkdir(dst_seq_dir)

                    for sp in files:
                        rel = sp.relative_to(src_seq_dir)
                        dp = dst_seq_dir / rel
                        dp.parent.mkdir(parents=True, exist_ok=True)
                        _safe_copy(sp, dp)
                        copied += 1
                        _update_shot_progress(shot_name, copied / total_files)

                    log(f"[COPY] {item['name']}: seq {dst_seq_dir.name}")

                else:
                    if not dst_seq_dir.exists():
                        _safe_mkdir(dst_seq_dir)

                    for sp in files:
                        rel = sp.relative_to(src_seq_dir)
                        dp = dst_seq_dir / rel
                        dp.parent.mkdir(parents=True, exist_ok=True)
                        if not dp.exists():
                            _safe_copy(sp, dp)
                        copied += 1
                        _update_shot_progress(shot_name, copied / total_files)

                    if copied == 0 and any(dst_seq_dir.iterdir()):
                        log(f"[SKIP] {item['name']}: seq {dst_seq_dir.name} exists")
                    else:
                        log(f"[COPY] {item['name']}: seq {dst_seq_dir.name}")

            _generate_nuke_script(shot, item, cfg, overwrite_nk)

        except Exception as e:
            log(f"[ERROR] {item.get('name','<unknown>')}: {e}")
            _update_shot_progress(shot_name, 1.0)  # чтобы не зависал на 0 при ошибке

    log("✅ Copy/Create finished. Done!")


# ---------------- Callbacks ----------------
def _cb_pick_source(sender, app_data, user_data):
    dpg.set_value("source_input", _extract_path_from_dialog(app_data))

def _cb_pick_dest(sender, app_data, user_data):
    dpg.set_value("dest_input", _extract_path_from_dialog(app_data))

def _cb_scan():
    src = Path(dpg.get_value("source_input") or "")
    if not src.exists():
        log("[ERROR] Invalid source.")
        return
    scan_resources(src)

def _cb_create():
    dest = Path(dpg.get_value("dest_input") or "")
    if not dest.exists():
        log("[ERROR] Invalid destination.")
        return
    overwrite_mode = dpg.get_value("overwrite_mode") or "None"
    _on_create_projects(dest, overwrite_mode)

# ---------------- Header (centered) ----------------
_HEADER_TEX = None
_HEADER_W = 1260
_HEADER_H = 100

def _recenter_header():
    """Center header image/group by adjusting indent based on viewport width."""
    try:
        vpw = dpg.get_viewport_width()
    except Exception:
        return
    indent = max(0, int((vpw - _HEADER_W) / 2))
    if dpg.does_item_exist("header_wrap"):
        dpg.configure_item("header_wrap", indent=indent)

def _build_header(parent):
    header_wrap = dpg.add_group(tag="header_wrap", parent=parent, indent=0)
    if _HEADER_TEX:
        dpg.add_image(_HEADER_TEX, parent=header_wrap)
    else:
        dl = dpg.add_drawlist(parent=header_wrap, width=_HEADER_W, height=90)
        dpg.draw_rectangle((0, 0), (_HEADER_W, 90),
                           fill=(30, 30, 35, 255), color=(0, 0, 0, 0), parent=dl)
        dpg.draw_text((16, 14), "ProjectCreator", size=28, color=(230, 230, 240, 255), parent=dl)
        dpg.draw_text((18, 48), "by Ales Ushakou", size=16, color=(160, 160, 170, 255), parent=dl)
        dpg.draw_text((290, 18), "v1.10", size=18, color=(200, 200, 210, 255), parent=dl)

# ---------------- Tabs ----------------
def _build_project_params_tab(parent):
    root = dpg.add_group(parent=parent)
    _build_header(root)
    dpg.add_spacer(height=8, parent=root)

    row_src = dpg.add_group(parent=root, horizontal=True)
    dpg.add_text("Source folder:", parent=row_src)
    dpg.add_input_text(tag="source_input", width=520, parent=row_src)
    dpg.add_button(label="Browse", callback=lambda: dpg.show_item("dlg_source"), parent=row_src)

    dpg.add_spacer(height=6, parent=root)
    row_dst = dpg.add_group(parent=root, horizontal=True)
    dpg.add_text("Destination:", parent=row_dst)
    dpg.add_input_text(tag="dest_input", width=520, parent=row_dst)
    dpg.add_button(label="Browse", callback=lambda: dpg.show_item("dlg_dest"), parent=row_dst)

    dpg.add_spacer(height=8, parent=root)
    row_scan = dpg.add_group(parent=root, horizontal=True)
    dpg.add_button(label="Scan", width=120, callback=_cb_scan, parent=row_scan)
    dpg.add_progress_bar(tag="scan_progress", width=400, parent=row_scan)

    dpg.add_spacer(height=6, parent=root)
    dpg.add_text("Found items:", parent=root)
    # фиксируем высоту, чтобы не прыгало при ресайзе окна
    dpg.add_child_window(tag="found_table_region",
                         autosize_x=True, autosize_y=False,
                         height=260, border=True, parent=root)
    _ensure_found_table()

    dpg.add_spacer(height=6, parent=root)
    row_create = dpg.add_group(parent=root, horizontal=True)
    dpg.add_button(label="Create Project", width=140, callback=_cb_create, parent=row_create)
    dpg.add_progress_bar(tag="create_progress", width=400, parent=row_create)

    dpg.add_spacer(height=6, parent=root)
    row_opts = dpg.add_group(parent=root, horizontal=True)
    dpg.add_text("Overwrite if exists:", parent=row_opts)
    dpg.add_combo(OVERWRITE_CHOICES, default_value="All", tag="overwrite_mode", width=160, parent=row_opts)

    dpg.add_spacer(height=10, parent=root)
    dpg.add_text("Log:", parent=root)
    dpg.add_child_window(tag="log_console", autosize_x=True, height=220, border=True, parent=root)

def _build_nuke_params_tab(parent):
    container = dpg.add_group(parent=parent)
    try:
        mod = importlib.import_module("nuke_params")
        if hasattr(mod, "build_ui"):
            mod.build_ui(parent_tag=container)
        else:
            dpg.add_text("[WARN] nuke_params.py found, but build_ui() is missing.", parent=container)
    except ModuleNotFoundError:
        dpg.add_text("[WARN] nuke_params.py not found next to the script.", parent=container)
    except Exception as e:
        dpg.add_text(f"[ERROR] Failed to load nuke_params.py: {e}", parent=container)
        log(traceback.format_exc())

def _build_utility_tab(parent):
    container = dpg.add_group(parent=parent)
    try:
        util_mod = importlib.import_module("PCUtility")
        if hasattr(util_mod, "build_ui"):
            util_mod.build_ui(parent_tag=container)
        else:
            dpg.add_text("[WARN] PCUtility.py found, but build_ui() is missing.", parent=container)
    except ModuleNotFoundError:
        dpg.add_text("[WARN] PCUtility.py not found next to the script.", parent=container)
    except Exception as e:
        dpg.add_text(f"[ERROR] Failed to load PCUtility.py: {e}", parent=container)
        log(traceback.format_exc())

# ---------------- Main ----------------
def build_ui():
    global _HEADER_TEX, _HEADER_W, _HEADER_H
    # load header image if exists
    if HEADER_IMAGE_PATH.exists():
        w, h, ch, data = dpg.load_image(str(HEADER_IMAGE_PATH))
        dpg.add_texture_registry(tag="pc_texreg")
        _HEADER_TEX = dpg.add_static_texture(w, h, data, parent="pc_texreg")
        _HEADER_W, _HEADER_H = w, h

    # dialogs
    dpg.add_file_dialog(directory_selector=True, show=False, callback=_cb_pick_source, tag="dlg_source")
    dpg.add_file_dialog(directory_selector=True, show=False, callback=_cb_pick_dest, tag="dlg_dest")

    # main window + tabs
    main_window = dpg.add_window(label=APP_TITLE, tag="main_window", width=1280, height=860)
    tab_bar = dpg.add_tab_bar(parent=main_window)

    tab_project = dpg.add_tab(label="Project Parameters", parent=tab_bar)
    _build_project_params_tab(tab_project)

    tab_nuke = dpg.add_tab(label="Nuke Script parameters", parent=tab_bar)
    _build_nuke_params_tab(tab_nuke)

    tab_util = dpg.add_tab(label="Utility", parent=tab_bar)
    _build_utility_tab(tab_util)

def main():
    dpg.create_context()
    build_ui()
    dpg.create_viewport(title=APP_TITLE, width=1280, height=880)
    dpg.setup_dearpygui()
    dpg.show_viewport()

    # Center header on show and on resize
    _recenter_header()
    try:
        dpg.set_viewport_resize_callback(lambda s, a: _recenter_header())
    except Exception:
        pass

    dpg.set_primary_window("main_window", True)
    dpg.start_dearpygui()
    dpg.destroy_context()

if __name__ == "__main__":
    main()
