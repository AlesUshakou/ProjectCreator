# nuke_params for ProjectCreator
# Aleš Ushakou, 2025
# -*- coding: utf-8 -*-

from pathlib import Path
import dearpygui.dearpygui as dpg

ROOT = Path(__file__).resolve().parent
INI_PATH = ROOT / "ProjectCreator.ini"
PRESETS_DIR = ROOT / "presets"
NUKE_PRESETS_GLOB = "*.nk"

# --- секционные имена ровно как в ТЗ ---
SEC_NUKE       = "nuke"
SEC_FIRST_LIST = "First.frame"
SEC_FPS_LIST   = "FPS"
SEC_CS_NUKE    = "colorspaces.Nuke"
SEC_CS_ACES    = "colorspaces.ACES"

# --- дефолтные значения для [nuke] при первом создании ini ---
NUKE_DEFAULTS = {
    "preset": "",
    "color_model": "Nuke",
    "colorspace": "AlexaV3LogC",  # из примера пользователя
    "First frame": "1001",
    "FPS": "25",
}

# --- шаблон ProjectCreator.ini при отсутствии файла (точно как в сообщении) ---
INI_TEMPLATE = """[nuke]
preset = 
color_model = Nuke
colorspace = AlexaV3LogC
First frame = 1001
FPS = 25   

[First.frame]
1
1001

[FPS]
24
25
30


[colorspaces.Nuke]
AlexaV3LogC
ARRILogC4
linear
sRGB
rec709


[colorspaces.ACES]
"Input - ARRI - V3 LogC (EI800) - Wide Gamut"
"ACES - ACEScg"
"ACES - ACES2065-1"
"Utility - Linear - sRGB"
"Output - Rec.709"
"""

# ----------------------------- low-level INI text utils -----------------------------

def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="ignore").splitlines() if path.exists() else []

def _write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Всегда завершаем переводом строки
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

def _ensure_ini_exists() -> None:
    if not INI_PATH.exists():
        _write_lines(INI_PATH, INI_TEMPLATE.splitlines())

def _find_section(lines: list[str], section_name: str) -> tuple[int, int]:
    """Вернёт (start_idx, end_idx) диапазон строк секции, включая заголовок [..]. Если нет — (-1, -1)."""
    header = f"[{section_name}]"
    start = -1
    for i, ln in enumerate(lines):
        if ln.strip() == header:
            start = i
            break
    if start == -1:
        return -1, -1
    end = len(lines)
    for j in range(start + 1, len(lines)):
        s = lines[j].strip()
        if s.startswith("[") and s.endswith("]"):
            end = j
            break
    return start, end

def _read_kv_section(lines: list[str], section_name: str) -> dict:
    """Читает key = value пары из секции (без кавычек обработки). Остальные секции не трогаем."""
    s, e = _find_section(lines, section_name)
    res = {}
    if s == -1:
        return res
    for ln in lines[s+1:e]:
        t = ln.strip()
        if not t or t.startswith(("#", ";", "//")):
            continue
        if "=" in t:
            k, v = t.split("=", 1)
            res[k.strip()] = v.strip()
    return res

def _write_kv_section(lines: list[str], section_name: str, kv: dict, key_order: list[str]) -> list[str]:
    """Полностью перезаписывает секцию key=value в указанном порядке ключей. Остальные секции нетронуты."""
    s, e = _find_section(lines, section_name)
    block = [f"[{section_name}]"]
    for k in key_order:
        block.append(f"{k} = {kv.get(k, '')}")
    block.append("")  # пустая строка после секции
    if s == -1:
        # добавить в конец, соблюдая пустую строку между секциями
        if lines and lines[-1].strip():
            lines = lines + [""]
        return lines + block
    else:
        return lines[:s] + block + lines[e:]

def _read_plain_list_section(lines: list[str], section_name: str) -> list[str]:
    """Возвращает сырой список строк из секции-списка (без '='), сохраняя порядок и кавычки."""
    s, e = _find_section(lines, section_name)
    if s == -1:
        return []
    out = []
    for ln in lines[s+1:e]:
        t = ln.strip()
        if not t or t.startswith(("#", ";", "//")):
            continue
        if "=" in t:
            # эта секция по ТЗ — список, игнорируем key=value на всякий случай
            continue
        out.append(t)
    return out

# ----------------------------- presets listing -----------------------------

def _list_nk_presets() -> list[str]:
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    return sorted([p.name for p in PRESETS_DIR.glob(NUKE_PRESETS_GLOB)])

# ----------------------------- DPG callbacks -----------------------------

def _save_current_ui_to_ini():
    _ensure_ini_exists()
    lines = _read_lines(INI_PATH)

    # читаем текущий блок [nuke]
    kv = _read_kv_section(lines, SEC_NUKE)
    # применяем дефолты по умолчанию для отсутствующих ключей
    merged = {
        "preset": kv.get("preset", NUKE_DEFAULTS["preset"]),
        "color_model": kv.get("color_model", NUKE_DEFAULTS["color_model"]),
        "colorspace": kv.get("colorspace", NUKE_DEFAULTS["colorspace"]),
        "First frame": kv.get("First frame", NUKE_DEFAULTS["First frame"]),
        "FPS": kv.get("FPS", NUKE_DEFAULTS["FPS"]),
    }

    # заменить значениями из UI
    merged["preset"] = dpg.get_value("nuke_preset_combo") or merged["preset"]
    merged["color_model"] = dpg.get_value("nuke_color_combo") or merged["color_model"]
    merged["colorspace"] = dpg.get_value("nuke_colorspace_combo") or merged["colorspace"]
    merged["First frame"] = str(dpg.get_value("nuke_first_combo") or merged["First frame"])
    merged["FPS"] = str(dpg.get_value("nuke_fps_combo") or merged["FPS"])

    # записать обратно только секцию [nuke] (ключи в заданном порядке)
    key_order = ["preset", "color_model", "colorspace", "First frame", "FPS"]
    new_lines = _write_kv_section(lines, SEC_NUKE, merged, key_order)
    _write_lines(INI_PATH, new_lines)

def _on_change_any(sender, app_data, user_data):
    _save_current_ui_to_ini()

def _on_change_color_model(sender, app_data, user_data):
    # сменили Nuke/ACES → обновить список ColorSpace из соответствующей секции-списка
    _ensure_ini_exists()
    lines = _read_lines(INI_PATH)
    model = dpg.get_value("nuke_color_combo") or "Nuke"
    if model == "ACES":
        cs_items = _read_plain_list_section(lines, SEC_CS_ACES)
    else:
        cs_items = _read_plain_list_section(lines, SEC_CS_NUKE)

    # сохранить предыдущий выбор, если он есть
    kv = _read_kv_section(lines, SEC_NUKE)
    prev_cs = kv.get("colorspace", NUKE_DEFAULTS["colorspace"])
    sel = prev_cs if prev_cs in cs_items else (cs_items[0] if cs_items else "")
    dpg.configure_item("nuke_colorspace_combo", items=cs_items, default_value=sel)
    dpg.set_value("nuke_colorspace_combo", sel)
    _save_current_ui_to_ini()

# ----------------------------- UI builder -----------------------------

def build_ui(parent_tag=None):
    if parent_tag is None:
        parent_tag = dpg.last_container()

    _ensure_ini_exists()
    lines = _read_lines(INI_PATH)

    # читаем [nuke]
    kv = _read_kv_section(lines, SEC_NUKE)
    preset_val      = kv.get("preset", NUKE_DEFAULTS["preset"])
    color_model_val = kv.get("color_model", NUKE_DEFAULTS["color_model"])
    colorspace_val  = kv.get("colorspace", NUKE_DEFAULTS["colorspace"])
    first_frame_val = kv.get("First frame", NUKE_DEFAULTS["First frame"])
    fps_val         = kv.get("FPS", NUKE_DEFAULTS["FPS"])

    # списки для выпадающих меню
    presets_list = _list_nk_presets()
    first_list   = _read_plain_list_section(lines, SEC_FIRST_LIST) or ["1", "1001"]
    fps_list     = _read_plain_list_section(lines, SEC_FPS_LIST)   or ["24", "25", "30"]

    cs_list = _read_plain_list_section(lines, SEC_CS_ACES if color_model_val == "ACES" else SEC_CS_NUKE)
    if colorspace_val not in cs_list and cs_list:
        colorspace_val = cs_list[0]

    with dpg.group(parent=parent_tag):
        # Row 1: Nuke preset
        with dpg.group(horizontal=True):
            dpg.add_text("Nuke preset:")
            dpg.add_combo(items=presets_list, tag="nuke_preset_combo",
                          width=360, default_value=preset_val,
                          callback=_on_change_any)

        dpg.add_spacer(height=8)

        # Row 2: Color | ColorSpace
        with dpg.group(horizontal=True):
            dpg.add_text("Color:")
            dpg.add_combo(items=["Nuke", "ACES"], tag="nuke_color_combo",
                          width=140, default_value=color_model_val,
                          callback=_on_change_color_model)

            dpg.add_spacer(width=16)

            dpg.add_text("ColorSpace:")
            dpg.add_combo(items=cs_list, tag="nuke_colorspace_combo",
                          width=320, default_value=colorspace_val,
                          callback=_on_change_any)

        dpg.add_spacer(height=8)

        # Row 3: First frame | FPS (из секций-списков)
        with dpg.group(horizontal=True):
            dpg.add_text("First frame:")
            dpg.add_combo(items=first_list, tag="nuke_first_combo",
                          width=120, default_value=first_frame_val,
                          callback=_on_change_any)

            dpg.add_spacer(width=16)

            dpg.add_text("FPS:")
            dpg.add_combo(items=fps_list, tag="nuke_fps_combo",
                          width=120, default_value=fps_val,
                          callback=_on_change_any)

    # мгновенно зафиксируем значения [nuke] (если только создали файл)
    _save_current_ui_to_ini()
