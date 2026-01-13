# create_nk for ProjectCreator 
# Aleš Ushakou, 2025
# -*- coding: utf-8 -*-

from pathlib import Path
import re
import subprocess
import shutil
import sys
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent

VIDEO_EXTS = {".mov", ".mp4", ".mxf"}
SEQ_EXTS   = {".exr", ".dpx", ".tiff", ".tif", ".png", ".jpg", ".jpeg"}

# ------------------- utils -------------------
def _posix(s: str) -> str:
    return s.replace("\\", "/")

def _safe_int(x, default=None):
    try:
        return int(x)
    except Exception:
        return default

def _find_ffprobe():
    local = SCRIPT_DIR / "ffmpeg" / ("ffprobe.exe" if sys.platform.startswith("win") else "ffprobe")
    if local.exists():
        return str(local)
    return shutil.which("ffprobe")

def video_frame_count_ffprobe(video_path: Path) -> Optional[int]:
    """Пытаемся получить количество кадров для видео (не критично, если не получится)."""
    ffprobe_bin = _find_ffprobe()
    if not ffprobe_bin:
        return None
    cmds = [
        # 1) nb_read_frames (работает не везде)
        [ffprobe_bin, "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=nb_read_frames", "-of", "default=nokey=1:noprint_wrappers=1", str(video_path)],
        # 2) nb_frames (тоже не всегда заполняется)
        [ffprobe_bin, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=nb_frames", "-of", "default=nokey=1:noprint_wrappers=1", str(video_path)],
        # 3) duration + r_frame_rate (надёжный запасной вариант)
        [ffprobe_bin, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=duration,r_frame_rate", "-of", "default=nokey=1:noprint_wrappers=1", str(video_path)],
    ]
    for cmd in cmds:
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, universal_newlines=True, timeout=8)
            lines = [l.strip() for l in (out or "").splitlines() if l.strip()]
            if not lines:
                continue
            # Случай одной строки с числом
            if len(lines) == 1:
                val = _safe_int(lines[0])
                if val and val > 0:
                    return val
            # duration + r_frame_rate
            if len(lines) >= 2:
                try:
                    duration = float(lines[0])
                    num, den = lines[1].split("/")
                    fps = float(num) / float(den) if den != "0" else 0.0
                    frames = int(round(duration * fps))
                    if frames > 0:
                        return frames
                except Exception:
                    pass
        except Exception:
            pass
    return None

def detect_sequence_info(seq_dir: Path):
    """Определяем паддинг и диапазон кадров по именам файлов."""
    files = [p for p in seq_dir.iterdir() if p.is_file() and p.suffix.lower() in SEQ_EXTS and not p.name.startswith(".")]
    if not files:
        return None
    files.sort()
    nums = []
    pad = None
    base = None
    ext  = None
    for f in files:
        m = re.match(r"^(.*?)(\d+)(\.[^.]+)$", f.name)
        if not m:
            continue
        b, d, e = m.groups()
        n = _safe_int(d)
        if n is None:
            continue
        nums.append(n)
        if pad is None:
            base, pad, ext = b, len(d), e
    if not nums or pad is None:
        return None
    return {
        "base": base,
        "pad":  pad,
        "ext":  ext,
        "min":  min(nums),
        "max":  max(nums),
    }

# --------------- block helpers ---------------
def _strip_lines(block: str, keys):
    pat = r"(?m)^\s*(?:%s)\b.*\r?\n" % "|".join(re.escape(k) for k in keys)
    return re.sub(pat, "", block)

def _replace_line(block: str, key: str, value_line: str) -> str:
    """Заменить строку 'key ...' или вставить перед '}'."""
    pat = rf"(?m)^\s*{re.escape(key)}\b.*$"
    if re.search(pat, block):
        return re.sub(pat, value_line, block)
    return re.sub(r"\n\}", f"\n{value_line}\n}}", block, count=1)

def _insert_after_open(block: str, nodename: str, lines: list[str]) -> str:
    """Вставить строки сразу после строки с '{' узла."""
    pos_node = block.find(nodename)
    brace = block.find("{", pos_node if pos_node >= 0 else 0)
    if brace == -1:
        return block
    nl = block.find("\n", brace)
    ins = (brace + 1) if nl == -1 else (nl + 1)
    payload = "".join(line + "\n" for line in lines)
    return block[:ins] + payload + block[ins:]

def _iter_node_blocks(nk: str, node_type: str):
    """Итератор по блокам указанного типа (Read/Write/Root)."""
    i, n = 0, len(nk)
    while i < n:
        i = nk.find(node_type, i)
        if i == -1:
            return
        j = nk.find("{", i)
        if j == -1:
            return
        depth = 0
        k = j
        while k < n:
            if nk[k] == "{":
                depth += 1
            elif nk[k] == "}":
                depth -= 1
                if depth == 0:
                    yield i, k + 1, nk[i:k+1]
                    i = k + 1
                    break
            k += 1

def _find_root(nk: str):
    for start, end, block in _iter_node_blocks(nk, "Root"):
        return start, end, block
    return None

def _find_read_source(nk: str):
    for start, end, block in _iter_node_blocks(nk, "Read"):
        if re.search(r"(?m)^\s*name\s+Read_source\b", block):
            return start, end, block
    # если нет — возьмём первый Read и переименуем
    for start, end, block in _iter_node_blocks(nk, "Read"):
        return start, end, block
    return None

def _ensure_node_name(block: str, desired: str) -> str:
    if re.search(r"(?m)^\s*name\s+\S+", block):
        return re.sub(r"(?m)^\s*name\s+\S+", f" name {desired}", block, count=1)
    return re.sub(r"\n\}", f"\n name {desired}\n}}", block, count=1)

# --------------- Root ops ---------------
def _set_root_name(nk: str, new_name: str, log=print) -> str:
    found = _find_root(nk)
    if not found:
        log("[NK] Root not found; creating new Root with name.")
        return f"Root {{\n name {new_name}\n}}\n\n" + nk
    s, e, block = found
    if re.search(r"(?m)^\s*name\s+\S+", block):
        block2 = re.sub(r"(?m)^\s*name\s+\S+", f" name {new_name}", block, count=1)
    else:
        block2 = _insert_after_open(block, "Root", [f" name {new_name}"])
    log(f"[NK] Root name -> {new_name}")
    return nk[:s] + block2 + nk[e:]

def _set_root_first_last_fps(nk: str, first_frame: int, last_frame: int, fps: int, log=print) -> str:
    found = _find_root(nk)
    insertion = [
        f" first_frame {first_frame}",
        f" last_frame {last_frame}",
        f" fps {fps}",
    ]
    if not found:
        log("[NK] Root not found; creating new Root with fps/range.")
        return "Root {\n" + "\n".join(insertion) + "\n}\n\n" + nk
    s, e, block = found
    block = _strip_lines(block, ["first_frame", "last_frame", "fps"])
    proj = re.search(r"(?m)^\s*project_directory\b.*$", block)
    if proj:
        pos = proj.end()
        block2 = block[:pos] + "\n" + "\n".join(insertion) + block[pos:]
        where = "after project_directory"
    else:
        block2 = re.sub(r"\n\}", "\n" + "\n".join(insertion) + "\n}", block, count=1)
        where = "before }"
    log(f"[NK] Root range/fps set ({where}): ff={first_frame}, lf={last_frame}, fps={fps}")
    return nk[:s] + block2 + nk[e:]

def _insert_on_script_load(nk: str, log=print) -> str:
    line = (
        " onScriptLoad \"import nuke; "
        "n=nuke.toNode('Read_source'); "
        "w=int(n.metadata('input/width') or n.width()) if n else 0; "
        "h=int(n.metadata('input/height') or n.height()) if n else 0; "
        "pa=float(n.metadata('input/pixel_aspect')) if (n and n.metadata('input/pixel_aspect')) else 1; "
        "fn=f'PC_auto_{w}x{h}'; "
        "nuke.addFormat(f'{w} {h} {pa} {fn}'); "
        "nuke.root()['format'].setValue(fn)\"\\n"
    )
    found = _find_root(nk)
    if not found:
        log("[NK] Root not found; creating with onScriptLoad.")
        return "Root {\n" + line + "}\n\n" + nk
    s, e, block = found
    if "onScriptLoad" in block:
        log("[NK] onScriptLoad already exists; skip.")
        return nk
    block2 = re.sub(r"\n\}\s*$", f"\n{line}}}", block, count=1)
    log("[NK] onScriptLoad inserted.")
    return nk[:s] + block2 + nk[e:]

# --------------- Read / Write ops ---------------
def _patch_read_source(nk: str, item: dict, first_frame: int, colorspace: str, log=print) -> tuple[str, int, int, str]:
    """
    Возвращает (nk_text, src_first, src_last, in_basename).
    src_first/src_last - диапазон исходного медиа (для расчёта Root/Write).
    """
    found = _find_read_source(nk)
    if not found:
        log("[NK] Read node not found; cannot patch Read.")
        return nk, first_frame, first_frame, "input"
    s, e, block = found
    block = _ensure_node_name(block, "Read_source")

    if item["type"] == "video":
        in_file = Path(item["src"])
        in_basename = in_file.stem
        rel = f"../in/{in_file.name}"
        block = _replace_line(block, "file", f' file "{_posix(rel)}"')

        # Надёжный подсчёт количества кадров
        frames = video_frame_count_ffprobe(in_file)
        if not frames or frames < 1:
            frames = 1  # fallback, если ffprobe не дал число

        # Диапазон источника (как у секвенций: 1..frames)
        src_first, src_last = 1, frames

        # Прописываем colorspace, first/last и старт кадра (frame_mode "start at", frame <first_frame>)
        block = _replace_line(block, "colorspace", f' colorspace "{colorspace}"')
        block = _replace_line(block, "first",     f" first {src_first}")
        block = _replace_line(block, "last",      f" last {src_last}")
        block = _strip_lines(block, ["frame_mode", "frame"])
        block = re.sub(r"(?m)^\s*name\s+Read_source\b.*$",
                       f' frame_mode "start at"\n frame {first_frame}\n name Read_source',
                       block)

        log(f"[NK] Read_source(video): file={rel}, frames={frames}, colorspace={colorspace}")

    else:
        seq_dir = Path(item["src"])
        in_basename = seq_dir.name
        info = detect_sequence_info(seq_dir)
        if info:
            pattern = f"{info['base']}%0{info['pad']}d{info['ext']}"
            rel = f"../in/{seq_dir.name}/{pattern}"
            block = _replace_line(block, "file",      f' file "{_posix(rel)}"')
            block = _replace_line(block, "first",     f" first {info['min']}")
            block = _replace_line(block, "last",      f" last {info['max']}")
            block = _replace_line(block, "colorspace",f' colorspace "{colorspace}"')
            block = _strip_lines(block, ["frame_mode", "frame"])
            block = re.sub(r"(?m)^\s*name\s+Read_source\b.*$",
                           f' frame_mode "start at"\n frame {first_frame}\n name Read_source',
                           block)
            src_first, src_last = info["min"], info["max"]
            log(f"[NK] Read_source(seq): file={rel}, first={info['min']}, last={info['max']}, colorspace={colorspace}")
        else:
            files = sorted([p for p in seq_dir.iterdir() if p.is_file() and not p.name.startswith(".")])
            rel = f"../in/{seq_dir.name}/{files[0].name}" if files else f"../in/{seq_dir.name}"
            block = _replace_line(block, "file",      f' file "{_posix(rel)}"')
            block = _replace_line(block, "colorspace",f' colorspace "{colorspace}"')
            block = _strip_lines(block, ["frame_mode", "frame"])
            block = re.sub(r"(?m)^\s*name\s+Read_source\b.*$",
                           f' frame_mode "start at"\n frame {first_frame}\n name Read_source',
                           block)
            src_first, src_last = first_frame, first_frame
            log(f"[NK] Read_source(fallback): file={rel}, colorspace={colorspace}")

    nk = nk[:s] + block + nk[e:]
    return nk, src_first, src_last, in_basename

def _patch_write_blocks(nk: str, in_basename: str, first_frame: int, last_frame: int,
                        colorspace: str, item: dict, log=print) -> str:
    """Patch Write_preview and Write_comp blocks without deleting preset lines (codecs, etc.)."""
    out = []; last = 0
    for s, e, block in _iter_node_blocks(nk, "Write"):
        name_m = re.search(r"(?m)^\s*name\s+([^\s\}]+)", block)
        node_name = name_m.group(1) if name_m else ""

        if node_name in ("Write2", "Write_preview"):
            # preview: только путь + first/last/use_limit/create_directories (+ file_type mov)
            rel = f"../preview/{in_basename}_prew_v001.mov"
            b = block
            if node_name != "Write_preview":
                b = re.sub(r"(?m)^\s*name\s+\S+", " name Write_preview", b, count=1)

            b = _replace_line(b, "file",               f' file "{_posix(rel)}"')
            b = _replace_line(b, "first",              f" first {first_frame}")
            b = _replace_line(b, "last",               f" last {last_frame}")
            b = _replace_line(b, "use_limit",          " use_limit true")
            b = _replace_line(b, "create_directories", " create_directories true")
            b = _replace_line(b, "file_type",          " file_type mov")

            out.extend([nk[last:s], b]); last = e
            log(f"[NK] Write_preview -> file={rel}; first/last/use_limit/create_directories set")

        elif node_name in ("Write1", "Write_comp"):
            b = block
            if node_name != "Write_comp":
                b = re.sub(r"(?m)^\s*name\s+\S+", " name Write_comp", b, count=1)

            if item["type"] == "sequence":
                info = detect_sequence_info(Path(item["src"]))
                pad = info["pad"] if info else 7
                hashes = "#" * pad
                ext = (info["ext"].lstrip(".") if info else "exr")
                rel = f"../out/{in_basename}_comp_v001/{in_basename}_comp_v001.{hashes}.{ext}"

                b = _replace_line(b, "file",               f' file "{_posix(rel)}"')
                b = _replace_line(b, "file_type",          f" file_type {ext}")
                b = _replace_line(b, "colorspace",         f' colorspace "{colorspace}"')
                b = _replace_line(b, "first",              f" first {first_frame}")
                b = _replace_line(b, "last",               f" last {last_frame}")
                b = _replace_line(b, "use_limit",          " use_limit true")
                b = _replace_line(b, "create_directories", " create_directories true")

                out.extend([nk[last:s], b]); last = e
                log(f"[NK] Write_comp(seq) -> file={rel}; file_type={ext}; colorspace={colorspace}; first/last/use_limit/create_directories set")
            else:
                # video → mov; не трогаем codec-строки из пресета
                rel = f"../out/{in_basename}_comp_v001.mov"

                b = _replace_line(b, "file",               f' file "{_posix(rel)}"')
                b = _replace_line(b, "file_type",          " file_type mov")
                b = _replace_line(b, "colorspace",         f' colorspace "{colorspace}"')
                b = _replace_line(b, "first",              f" first {first_frame}")
                b = _replace_line(b, "last",               f" last {last_frame}")
                b = _replace_line(b, "use_limit",          " use_limit true")
                b = _replace_line(b, "create_directories", " create_directories true")

                out.extend([nk[last:s], b]); last = e
                log(f"[NK] Write_comp(video) -> file={rel}; colorspace={colorspace}; first/last/use_limit/create_directories set")

        else:
            # любые другие Write оставляем как есть
            pass

    out.append(nk[last:])
    return "".join(out)

# --------------- Public API ---------------
def generate_nk_text(cfg: dict, project_name: str, item: dict,
                     preset_path: Optional[Path] = None, log=print) -> str:
    """
    Читает .nk пресет и правит нужные поля.
    Если пресет не найден — выбрасывает FileNotFoundError.
    """
    # 1) загрузка пресета
    preset = preset_path or (Path(cfg["preset"]) if cfg.get("preset") else None)
    if not preset or not Path(preset).exists():
        msg = f"[ERROR] Preset .nk file not found: {preset or '(not specified)'}"
        log(msg)
        raise FileNotFoundError(msg)

    try:
        nk = Path(preset).read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        msg = f"[ERROR] Failed to read preset {preset}: {e}"
        log(msg)
        raise

    if not nk.strip():
        msg = f"[ERROR] Preset {preset} is empty or unreadable."
        log(msg)
        raise ValueError(msg)

    # 2) значения
    colorspace  = cfg.get("colorspace") or "scene_linear"
    fps         = _safe_int(cfg.get("fps"), 25) or 25
    first_frame = _safe_int(cfg.get("first_frame"), 1001) or 1001

    # 3) Read_source (получим src диапазон и базовое имя)
    nk, src_first, src_last, in_basename = _patch_read_source(nk, item, first_frame, colorspace, log=log)

    # 4) Root: имя, диапазоны/ fps
    proj_first = first_frame
    proj_last  = proj_first + (src_last - src_first)   # = ff + (N-1)
    nk = _set_root_name(nk, project_name, log=log)
    nk = _set_root_first_last_fps(nk, proj_first, proj_last, fps, log=log)

    # 5) Write_preview & Write_comp
    nk = _patch_write_blocks(nk, in_basename, proj_first, proj_last, colorspace, item, log=log)

    # 6) onScriptLoad — без квадратных скобок
    nk = _insert_on_script_load(nk, log=log)

    return nk