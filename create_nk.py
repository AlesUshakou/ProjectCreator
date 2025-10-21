# create_nk.py
# ProjectCreator v1.01. Aleš Ushakou, 2025
# -*- coding: utf-8 -*-

from pathlib import Path
import re
import subprocess
import shutil
import sys

SCRIPT_DIR = Path(__file__).resolve().parent

VIDEO_EXTS = {".mov", ".mp4", ".mxf"}
SEQ_EXTS   = {".exr", ".dpx", ".tiff", ".tif", ".png", ".jpg", ".jpeg"}

DEFAULT_TEMPLATE = """Root {
    fps 25
    colorManagement Nuke
}
Read {
 name Read_source
}
Write {
 name Write_comp
}
Write {
 name Write_preview
}
"""

# ---------- utils ----------
def _posix(s: str) -> str:
    return s.replace("\\", "/")

def _safe_int(s, default=None):
    try:
        return int(s)
    except Exception:
        return default

def detect_sequence_info(seq_dir: Path):
    frames = [p for p in seq_dir.iterdir() if p.is_file() and p.suffix.lower() in SEQ_EXTS]
    if not frames:
        return None
    frames.sort()
    nums = []
    base = None
    pad = None
    ext = None
    for f in frames:
        m = re.match(r"^(.*?)(\d+)(\.[^.]+)$", f.name)
        if not m:
            continue
        b, d, e = m.groups()
        n = _safe_int(d)
        if n is None:
            continue
        nums.append(n)
        if base is None:
            base, pad, ext = b, len(d), e
    if not nums or base is None:
        return None
    first_frame = min(nums)
    last_frame  = max(nums)
    printf_pattern = f"{base}%07d{ext}"
    return {
        "base": base,
        "pad": pad,
        "ext": ext,
        "printf_pattern": printf_pattern,
        "first_frame": first_frame,
        "last_frame": last_frame,
        "count": len(nums),
    }

def _find_ffprobe():
    local = SCRIPT_DIR / "ffmpeg" / ("ffprobe.exe" if sys.platform.startswith("win") else "ffprobe")
    if local.exists():
        return str(local)
    return shutil.which("ffprobe")

def video_frame_count_ffprobe(video_path: Path) -> int | None:
    ffprobe_bin = _find_ffprobe()
    if not ffprobe_bin:
        return None
    cmds = [
        [ffprobe_bin, "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=nb_read_frames", "-of", "default=nokey=1:noprint_wrappers=1", str(video_path)],
        [ffprobe_bin, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=nb_frames", "-of", "default=nokey=1:noprint_wrappers=1", str(video_path)],
        [ffprobe_bin, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=duration,r_frame_rate", "-of", "default=nokey=1:noprint_wrappers=1", str(video_path)],
    ]
    for cmd in cmds:
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, universal_newlines=True, timeout=10)
            lines = [l.strip() for l in (out or "").splitlines() if l.strip()]
            if not lines: 
                continue
            if len(lines) == 1:
                val = _safe_int(lines[0])
                if val and val > 0:
                    return val
            if len(lines) >= 2:
                try:
                    duration = float(lines[0]); num, den = lines[1].split("/")
                    fps = float(num) / float(den) if den != "0" else 0.0
                    frames = int(round(duration * fps))
                    if frames > 0: 
                        return frames
                except Exception:
                    pass
        except Exception:
            pass
    return None

# ---------- helpers for blocks ----------
def _replace_param_in_block(block: str, key: str, value: str) -> str:
    pattern = rf"(?m)^\s*{re.escape(key)}\s+.*$"
    repl = f"{key} {value}"
    if re.search(pattern, block):
        return re.sub(pattern, repl, block)
    else:
        return re.sub(r"\n\}", f"\n    {repl}\n}}", block, count=1)

def _strip_lines(block: str, keys):
    pat = r"(?m)^\s*(?:%s)\b.*\r?\n" % "|".join(re.escape(k) for k in keys)
    return re.sub(pat, "", block)

def _find_root_block(nk: str):
    i = nk.find("Root")
    while i != -1:
        j = nk.find("{", i)
        if j == -1: return None
        if "\n" not in nk[i:j] and "\r" not in nk[i:j]: break
        i = nk.find("Root", i + 4)
    if i == -1: return None
    depth = 0; k = j; n = len(nk)
    while k < n:
        ch = nk[k]
        if ch == "{": depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0: return (i, k + 1, nk[i:k+1])
        k += 1
    return None

def _iter_write_blocks(nk: str):
    i = 0; n = len(nk)
    while True:
        i = nk.find("Write", i)
        if i == -1: return
        j = nk.find("{", i)
        if j == -1: return
        if "\n" in nk[i:j] or "\r" in nk[i:j]: i += 5; continue
        depth = 0; k = j
        while k < n:
            ch = nk[k]
            if ch == "{": depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    yield i, k + 1, nk[i:k+1]
                    i = k + 1; break
            k += 1
        else:
            return

def _find_read_source_block(nk: str):
    for m in re.finditer(r"(?s)\bRead\s*\{.*?\}", nk):
        block = m.group(0)
        if re.search(r"(?m)^\s*name\s+Read_source\b", block):
            return (m.start(), m.end(), block)
    return None

def _insert_after_write_open(block: str, lines_to_insert: list[str]) -> str:
    brace_pos = block.find("{", block.find("Write"))
    if brace_pos == -1: return block
    nl_pos = block.find("\n", brace_pos)
    insert_pos = (brace_pos + 1) if nl_pos == -1 else (nl_pos + 1)
    insertion = "".join(f"{line}\n" for line in lines_to_insert)
    return block[:insert_pos] + insertion + block[insert_pos:]

def _insert_before_name_read_source(block: str, lines_to_insert: list[str]) -> str:
    clean = _strip_lines(block, ["frame_mode", "frame"])
    m = re.search(r"(?m)^\s*name\s+Read_source\b.*$", clean)
    if not m: return clean
    insertion = "".join(f"{line}\n" for line in lines_to_insert)
    return clean[:m.start()] + insertion + clean[m.start():]

# ---------- Root insert (1-space indent) ----------
def _set_root_first_last_fps(nk: str, root_first: int, root_last: int, fps_value: str, log=print) -> str:
    found = _find_root_block(nk)
    insertion = f" first_frame {root_first}\n last_frame {root_last}\n fps {fps_value}\n"
    if not found:
        log("[NK] Root block not found — creating new Root at top")
        return f"Root {{\n{insertion}}}\n\n" + nk
    start, end, root_block = found
    root_clean = _strip_lines(root_block, ["first_frame", "last_frame", "fps"])
    proj_m = re.search(r"(?m)^\s*project_directory\b.*\r?\n", root_clean)
    if proj_m:
        new_root = root_clean[:proj_m.end()] + insertion + root_clean[proj_m.end():]
        where = "after project_directory"
    else:
        new_root = re.sub(r"\n\}", f"\n{insertion}}}", root_clean, count=1)
        where = "before }"
    log(f"[NK] Root updated ({where}) -> first_frame={root_first}, last_frame={root_last}, fps={fps_value}")
    return nk[:start] + new_root + nk[end:]

# ---------- main builder ----------
def build_nuke_from_preset(template_text: str,
                           cfg: dict,
                           project_name: str,
                           item: dict,
                           log=print) -> str:
    nk = template_text

    # --- Read_source ---
    in_basename = None
    seq_info = None
    video_frames = None

    found_read = _find_read_source_block(nk)
    if found_read:
        r_start, r_end, read_block = found_read
        ff_ui = int(cfg.get("first_frame", 1))
        read_block = _insert_before_name_read_source(
            read_block, [f" frame_mode \"start at\"", f" frame {ff_ui}"]
        )
        if item["type"] == "video":
            in_basename = item['src'].stem
            rel_in = f"../in/{item['src'].name}"
            read_block = _replace_param_in_block(read_block, "file", f"\"{_posix(rel_in)}\"")
            video_frames = video_frame_count_ffprobe(item['src'])
            if video_frames:
                read_block = _replace_param_in_block(read_block, "first", "1")
                read_block = _replace_param_in_block(read_block, "last", str(video_frames))
            read_block = _replace_param_in_block(read_block, "colorspace", cfg["colorspace"])
            log(f"[NK] Read_source(video) -> file={rel_in}, frame_mode=start at, frame={ff_ui}, colorspace={cfg['colorspace']}, frames={video_frames or 'n/a'}")
        else:
            seq_dir = item["src"]
            in_basename = seq_dir.name
            seq_info = detect_sequence_info(seq_dir)
            if seq_info:
                rel_in = f"../in/{seq_dir.name}/{seq_info['printf_pattern']}"
                read_block = _replace_param_in_block(read_block, "file", f"\"{_posix(rel_in)}\"")
                read_block = _replace_param_in_block(read_block, "first", str(seq_info['first_frame']))
                read_block = _replace_param_in_block(read_block, "last",  str(seq_info['last_frame']))
                read_block = _replace_param_in_block(read_block, "colorspace", cfg["colorspace"])
                log(f"[NK] Read_source(seq) -> file={rel_in}, frame_mode=start at, frame={ff_ui}, first={seq_info['first_frame']}, last={seq_info['last_frame']}, colorspace={cfg['colorspace']}")
            else:
                files = sorted([p for p in seq_dir.iterdir() if p.is_file()])
                first_name = files[0].name if files else ""
                rel_in = f"../in/{seq_dir.name}/{first_name}"
                read_block = _replace_param_in_block(read_block, "file", f"\"{_posix(rel_in)}\"")
                read_block = _replace_param_in_block(read_block, "colorspace", cfg["colorspace"])
                log(f"[NK] Read_source(seq-fallback) -> file={rel_in}, frame_mode=start at, frame={ff_ui}, colorspace={cfg['colorspace']}")
        nk = nk[:r_start] + read_block + nk[r_end:]
    else:
        log("[WARN] Node Read_source not found — using project name as base")
        in_basename = project_name

    # --- Root (first/last/fps) ---
    ff = int(cfg.get("first_frame", 1))
    if seq_info:
        read_last = seq_info['last_frame']
    elif video_frames:
        read_last = video_frames
    else:
        read_last = ff
    root_first = ff
    root_last  = (ff + read_last) - 1 if read_last else ff
    nk = _set_root_first_last_fps(nk, root_first, root_last, str(cfg.get("fps", "25")), log=log)

    # --- Write nodes ---
    out_chunks = []; last_idx = 0
    for start, end, block in _iter_write_blocks(nk):
        mname = re.search(r'\bname\s*"?([^\s"\}]+)"?', block)
        node_name = mname.group(1) if mname else ""

        if node_name == "Write_preview":
            rel = f"../preview/{in_basename}_prew_v001.mov"
            quoted = f"\"{_posix(rel)}\""
            clean = _strip_lines(block, ["file", "colorspace", "first", "last", "use_limit"])
            lines = [
                f" file {quoted}",
                f" colorspace {cfg['colorspace']}",
                f" first {root_first}",
                f" last {root_last}",
                " use_limit true",
            ]
            new_block = _insert_after_write_open(clean, lines)
            out_chunks.append(nk[last_idx:start]); out_chunks.append(new_block); last_idx = end
            log(f"[NK] Write_preview -> file={rel}, colorspace={cfg['colorspace']}, first={root_first}, last={root_last}, use_limit=true")

        elif node_name == "Write_comp":
            # если секвенция — подпапка <имя>_comp_v001/<имя>_comp_v001.%07d<ext>
            if seq_info:
                rel = f"../out/{in_basename}_comp_v001/{in_basename}_comp_v001.%07d{seq_info['ext']}"
                file_type = seq_info["ext"].lstrip(".").lower()
                extra_codec_lines = []  # для секвенций не нужно
            else:
                rel = f"../out/{in_basename}_comp_v001.mov"
                file_type = "mov"
                # codec-параметры только для видео
                extra_codec_lines = [
                    f" mov64_codec appr",
                    f" mov_prores_codec_profile \"ProRes 4:4:4:4 XQ 12-bit\"",
                ]

            quoted = f"\"{_posix(rel)}\""
            clean = _strip_lines(block, [
                "file", "file_type", "mov64_codec", "mov_prores_codec_profile",
                "colorspace", "create_directories", "first", "last", "use_limit"
            ])

            lines = [
                f" file {quoted}",
                f" file_type {file_type}",
                *extra_codec_lines,
                f" colorspace {cfg['colorspace']}",
                f" create_directories true",
                f" first {root_first}",
                f" last {root_last}",
                " use_limit true",
            ]

            new_block = _insert_after_write_open(clean, lines)
            out_chunks.append(nk[last_idx:start])
            out_chunks.append(new_block)
            last_idx = end

            log(
                f"[NK] Write_comp -> file={rel}, file_type={file_type}, "
                f"colorspace={cfg['colorspace']}, create_directories=true, "
                f"first={root_first}, last={root_last}, use_limit=true"
            )
        else:
            out_chunks.append(nk[last_idx:start]); out_chunks.append(block); last_idx = end

    out_chunks.append(nk[last_idx:])
    return "".join(out_chunks)

def generate_nk_text(cfg: dict,
                     project_name: str,
                     item: dict,
                     preset_path: Path | None = None,
                     log=print) -> str:
    tmpl = None
    if preset_path and Path(preset_path).exists():
        try:
            tmpl = Path(preset_path).read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            log(f"[WARN] Can't read preset {preset_path}: {e}")
    if not tmpl:
        tmpl = DEFAULT_TEMPLATE
    return build_nuke_from_preset(tmpl, cfg, project_name, item, log=log)
