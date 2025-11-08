# app.py
import os
import re
import time
import json
import uuid
import shutil
import tempfile
import requests
import subprocess
import platform
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional

import gradio as gr
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
import pyttsx3
from dotenv import load_dotenv
import imageio_ffmpeg

# --- NEW: repo ingestion helpers ---
from repo_ingest.github_ingest import ingest_github
from repo_ingest.local_ingest import ingest_local

# =========================
# Load secrets / toggles
# =========================
load_dotenv()

FAST_MODE = bool(os.getenv("EXPLAINER_FAST", ""))
SKIP_VIDEO = bool(os.getenv("EXPLAINER_NO_VIDEO", ""))
SKIP_WEB = bool(os.getenv("EXPLAINER_NO_WEB", ""))
PREF_CONTAINER = (os.getenv("EXPLAINER_CONTAINER") or "").lower()  # "mp4" | "mov" | ""

# =========================
# Project paths
# =========================
OUTPUT_DIR = os.path.join(os.getcwd(), "outputs")
VIDEO_DIR = os.path.join(OUTPUT_DIR, "videos")
AUDIO_DIR = os.path.join(OUTPUT_DIR, "audio")
FRAME_DIR = os.path.join(OUTPUT_DIR, "frames")
for d in (OUTPUT_DIR, VIDEO_DIR, AUDIO_DIR, FRAME_DIR):
    os.makedirs(d, exist_ok=True)

# Force temp to project-local folder (prevents /var/folders/* exhaustion)
PROJECT_TMP = os.path.join(OUTPUT_DIR, "tmp")
os.makedirs(PROJECT_TMP, exist_ok=True)
tempfile.tempdir = PROJECT_TMP
os.environ["TMPDIR"] = PROJECT_TMP  # helps ffmpeg/child procs

def _purge_old_tmp(prefixes=("cx_", "cxconcat_", "tmp_cx_", "tmp_repo_"), max_age_hours=6):
    now = time.time()
    for name in os.listdir(PROJECT_TMP):
        if any(name.startswith(p) for p in prefixes):
            p = os.path.join(PROJECT_TMP, name)
            try:
                st = os.stat(p)
                if (now - st.st_mtime) / 3600.0 > max_age_hours:
                    shutil.rmtree(p, ignore_errors=True)
            except Exception:
                pass

_purge_old_tmp()

# =========================
# OpenAI (text)
# =========================
try:
    from openai import OpenAI
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY missing. Put OPENAI_API_KEY=... in .env")
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    OPENAI_INIT_ERROR = None
except Exception as e:
    openai_client = None
    OPENAI_INIT_ERROR = str(e)

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# =========================
# Utilities
# =========================
def timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")

def safe_filename(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-\.]+", "_", name)

def read_text_file(fp: str) -> str:
    with open(fp, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def extract_code_blocks_from_markdown(md_text: str) -> List[Tuple[str, str]]:
    fence_pattern = re.compile(r"```(\w+)?\s*?\n(.*?)```", re.DOTALL)
    blocks = []
    for m in fence_pattern.finditer(md_text):
        lang = (m.group(1) or "").strip().lower()
        code = m.group(2)
        blocks.append((lang, code))
    return blocks

def summarize_file(md_text: str, max_chars: int = 20000) -> str:
    return md_text[:max_chars]

def ddg_search_links(query: str, k: int = 8) -> List[str]:
    if SKIP_WEB:
        return []
    try:
        r = requests.get(
            "https://duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=6,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        links = []
        for a in soup.select("a.result__a")[:k * 2]:
            href = a.get("href")
            if not href:
                continue
            if "uddg=" in href:
                from urllib.parse import parse_qs, urlparse, unquote
                try:
                    qs = parse_qs(urlparse(href).query)
                    if "uddg" in qs:
                        href = unquote(qs["uddg"][0])
                except Exception:
                    pass
            if href.startswith("http"):
                links.append(href)
            if len(links) >= k:
                break
        return links
    except Exception:
        return []

def pick_research_queries(lang: str, code: str) -> List[str]:
    base = [
        f"{lang} code walkthrough {lang} tutorial",
        f"{lang} best practices error handling",
        f"{lang} unit testing guide",
        f"{lang} performance optimization tips",
    ]
    if "async" in code:
        base.append(f"{lang} async await guide")
    if "class " in code:
        base.append(f"{lang} OOP patterns")
    if "import " in code or "require(" in code:
        base.append(f"{lang} modules and packaging")
    return list(dict.fromkeys(base))[:6]

def openai_explain(audience: str, code_blocks: List[Tuple[str, str]], file_summary: str) -> Dict:
    if openai_client is None:
        return {
            "overview": f"(Offline) OpenAI unavailable: {OPENAI_INIT_ERROR or 'Unknown'}.",
            "key_concepts": [f"Concepts tailored to {audience}."],
            "walkthrough": "Step-by-step logic overview.",
            "complexity": "Time/space complexity or performance discussion.",
            "pitfalls": ["Edge cases", "Common mistakes"],
            "quiz": [{"q": "What does this function do?", "a": "It ..."}],
            "tl_dr": "Short summary.",
        }

    joined, total = [], 0
    for lang, code in code_blocks:
        piece = f"\n\n---LANG={lang or 'plain'}---\n{code}"
        total += len(piece)
        if total > 12000:
            break
        joined.append(piece)
    code_ctx = "".join(joined) if joined else file_summary[:8000]

    sys_msg = (
        "You are a senior software instructor. Produce clear, accurate explanations. "
        "Use precise, approachable language appropriate to the requested audience level."
    )
    user_msg = f"""
File summary (truncated):
{file_summary}

Code context (truncated):
{code_ctx}

Audience level to tailor for: {audience}

Please produce a compact JSON with EXACT keys:
overview (string),
key_concepts (array of strings),
walkthrough (string),
complexity (string),
pitfalls (array of strings),
quiz (array of objects with q (string) and a (string)),
tl_dr (string)

Keep it concise but useful. Avoid backticks in values.
"""

    try:
        resp = openai_client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[{"role": "system", "content": sys_msg},
                      {"role": "user", "content": user_msg}],
            temperature=0.3,
            timeout=60,
        )
    except TypeError:
        resp = openai_client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[{"role": "system", "content": sys_msg},
                      {"role": "user", "content": user_msg}],
            temperature=0.3,
            request_timeout=60,
        )
    content = resp.choices[0].message.content.strip()
    content = re.sub(r"^```(json)?\s*|\s*```$", "", content, flags=re.DOTALL)
    try:
        data = json.loads(content)
    except Exception:
        data = {
            "overview": content,
            "key_concepts": [],
            "walkthrough": "",
            "complexity": "",
            "pitfalls": [],
            "quiz": [],
            "tl_dr": "",
        }
    for k, v in {
        "overview": "",
        "key_concepts": [],
        "walkthrough": "",
        "complexity": "",
        "pitfalls": [],
        "quiz": [],
        "tl_dr": "",
    }.items():
        data.setdefault(k, v)
    return data

# =========================
# ffmpeg selection & runner
# =========================
def get_ffmpeg_bin() -> str:
    env_bin = os.getenv("FFMPEG_BIN")
    if env_bin and os.path.exists(env_bin):
        return env_bin
    for c in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"):
        if os.path.exists(c):
            return c
    return imageio_ffmpeg.get_ffmpeg_exe()

FFMPEG_BIN = get_ffmpeg_bin()
print(f"[Code Explainer] ffmpeg -> {FFMPEG_BIN}")

def _pretty_cmd(cmd: List[str]) -> str:
    out = []
    for c in cmd:
        sc = str(c)
        if " " in sc or "'" in sc or '"' in sc:
            out.append("'" + sc.replace("'", "'\"'\"'") + "'")
        else:
            out.append(sc)
    return " ".join(out)

def _run(cmd: List[str], timeout: int = 300) -> None:
    print("[ffmpeg] CMD:", _pretty_cmd(cmd))
    try:
        subprocess.run(cmd, check=True, timeout=timeout)
    except subprocess.CalledProcessError as e:
        print("[ffmpeg] ERROR rc=", e.returncode)
        raise
    except subprocess.TimeoutExpired:
        print("[ffmpeg] TIMEOUT after", timeout, "seconds")
        raise

def ensure_space_or_raise(min_free_mb=500):
    for p in (PROJECT_TMP, OUTPUT_DIR, VIDEO_DIR):
        total, used, free = shutil.disk_usage(p)
        if free < min_free_mb * 1024 * 1024:
            raise RuntimeError(f"Low disk space (<{min_free_mb}MB) in {p}")

# =========================
# TTS: macOS 'say' (preferred) or pyttsx3 → AIFF → WAV
# =========================
def tts_to_wav(text: str, wav_path: str, rate_delta: int = 0):
    """
    - On macOS: use 'say' with -f (temp file), produce AIFF (default), then ffmpeg -> 16k mono WAV
      (NOTE: removed '--data-format' to avoid 'Opening output file failed: fmt?' on some macOS builds)
    - Else: pyttsx3 to AIFF, then ffmpeg -> WAV
    """
    os.makedirs(os.path.dirname(wav_path), exist_ok=True)
    use_say = (platform.system() == "Darwin" and shutil.which("say"))
    aiff_segments: List[str] = []

    def _split_chunks(s: str, max_len: int = 800) -> List[str]:
        parts = re.split(r'(?<=[\.\!\?])\s+', s.strip())
        chunks, cur = [], ""
        for p in parts:
            if len(cur) + 1 + len(p) <= max_len:
                cur = (cur + " " + p).strip()
            else:
                if cur:
                    chunks.append(cur)
                if len(p) <= max_len:
                    cur = p
                else:
                    import textwrap
                    chunks.extend(textwrap.wrap(p, max_len))
                    cur = ""
        if cur:
            chunks.append(cur)
        return [c for c in chunks if c.strip()]

    chunks = _split_chunks(text, 800)
    base = os.path.splitext(os.path.basename(wav_path))[0]
    work_dir = os.path.dirname(wav_path)

    if use_say:
        voice = os.getenv("EXPLAINER_VOICE")  # e.g., Samantha
        base_rate = 175
        rate = max(120, base_rate + rate_delta)
        for i, chunk in enumerate(chunks, 1):
            txt_fp = os.path.join(work_dir, f"{base}_seg{i}.txt")
            aiff_fp = os.path.join(work_dir, f"{base}_seg{i}.aiff")
            with open(txt_fp, "w", encoding="utf-8") as f:
                f.write(chunk)
            cmd = ["say"]
            if voice:
                cmd += ["-v", voice]
            # No --data-format to avoid 'fmt?' errors; default AIFF is fine
            cmd += ["-o", aiff_fp, "-r", str(int(rate)), "-f", txt_fp]
            print("[proc] CMD:", _pretty_cmd(cmd))
            try:
                subprocess.run(cmd, check=True, timeout=120)
            except Exception as e:
                print("[proc] ERROR (say) -> falling back to pyttsx3:", e)
                use_say = False
                break
            finally:
                try:
                    os.remove(txt_fp)
                except Exception:
                    pass
            if not os.path.exists(aiff_fp) or os.path.getsize(aiff_fp) == 0:
                use_say = False
                break
            aiff_segments.append(aiff_fp)

    if not use_say:
        aiff_fp = os.path.join(work_dir, f"{base}_seg1.aiff")
        engine = pyttsx3.init()
        rate = engine.getProperty("rate")
        engine.setProperty("rate", max(100, rate + rate_delta))
        engine.save_to_file(text, aiff_fp)
        engine.runAndWait()
        if not os.path.exists(aiff_fp) or os.path.getsize(aiff_fp) == 0:
            raise RuntimeError("pyttsx3 produced empty audio")
        aiff_segments = [aiff_fp]

    # Concat AIFFs if multiple
    if len(aiff_segments) == 1:
        concat_aiff = aiff_segments[0]
    else:
        tmpdir = tempfile.mkdtemp(prefix="tmp_cx_")
        try:
            list_fp = os.path.join(tmpdir, "list.txt")
            with open(list_fp, "w", encoding="utf-8") as f:
                for pth in aiff_segments:
                    f.write(f"file '{pth}'\n")
            concat_aiff = os.path.join(tmpdir, f"{base}_concat.aiff")
            cmd = [
                FFMPEG_BIN, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "concat", "-safe", "0", "-i", list_fp,
                "-c", "copy",
                concat_aiff,
            ]
            _run(cmd, timeout=120)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        # cleanup segments
        for p in aiff_segments:
            try:
                os.remove(p)
            except Exception:
                pass

    # AIFF -> WAV (16k mono s16)
    cmd = [
        FFMPEG_BIN, "-y", "-hide_banner", "-loglevel", "error",
        "-i", concat_aiff,
        "-acodec", "pcm_s16le", "-ac", "1", "-ar", "16000",
        wav_path,
    ]
    _run(cmd, timeout=180)
    try:
        if os.path.abspath(concat_aiff) != os.path.abspath(wav_path):
            os.remove(concat_aiff)
    except Exception:
        pass

# =========================
# Render text slide (Pillow)
# =========================
def wrap_text_to_image(
    text: str,
    size=(480, 270) if FAST_MODE else (640, 360),
    margin: int = 48 if FAST_MODE else 64,
    line_spacing: int = 6 if FAST_MODE else 8,
    font_size: int = 24 if FAST_MODE else 28,
):
    W, H = size
    img = Image.new("RGB", (W, H), color=(248, 249, 251))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", font_size)
        title_font = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size + 4)
    except Exception:
        font = ImageFont.load_default()
        title_font = font

    def break_lines(s: str, fnt: ImageFont.FreeTypeFont, width: int) -> List[str]:
        words = s.split()
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if draw.textlength(test, font=fnt) <= width:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    title, body = None, text
    if "\n" in text:
        title, body = text.split("\n", 1)
    elif len(text) > 100:
        title = text[:60] + "…"
        body = text[60:]
    body_lines = break_lines((body or "").strip(), font, W - 2 * margin)
    y = margin
    if title:
        draw.text((margin, y), title.strip(), font=title_font, fill=(20, 20, 20))
        y += int((title_font.size * 1.5))
    for line in body_lines:
        draw.text((margin, y), line, font=font, fill=(30, 30, 30))
        y += int(font.size + line_spacing)
        if y > H - margin:
            break
    footer = "Generated by Code Explainer"
    fw = draw.textlength(footer, font=font)
    draw.text((W - fw - margin, H - margin - font.size), footer, font=font, fill=(90, 90, 90))
    return img

# =========================
# ffmpeg slide mux & concat
# =========================
def ffmpeg_still_with_audio(image_fp: str, audio_fp: str, out_fp: str):
    """
    Try MP4 first; if it fails, try MOV (MJPEG+PCM); if that fails, retry MP4 without -loop.
    """
    ensure_space_or_raise(200)

    # Primary MP4 path (ultrafast)
    cmd_mp4 = [
        FFMPEG_BIN, "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "image2", "-loop", "1", "-framerate", "1", "-i", image_fp,
        "-analyzeduration", "16k", "-probesize", "16k",
        "-i", audio_fp,
        "-shortest",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-tune", "stillimage",
        "-pix_fmt", "yuv420p", "-r", "1",
        "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart",
        "-f", "mp4",
        "-threads", "1",
        out_fp,
    ]

    # MOV fallback (very light encoding)
    mov_fp = os.path.splitext(out_fp)[0] + ".mov"
    cmd_mov = [
        FFMPEG_BIN, "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "image2", "-framerate", "1", "-i", image_fp,
        "-analyzeduration", "16k", "-probesize", "16k",
        "-i", audio_fp,
        "-shortest",
        "-c:v", "mjpeg", "-q:v", "5", "-pix_fmt", "yuvj420p", "-r", "1",
        "-c:a", "pcm_s16le",
        "-threads", "1",
        mov_fp,
    ]

    first = "mp4" if PREF_CONTAINER == "mp4" else ("mov" if PREF_CONTAINER == "mov" else "mp4")

    try:
        if first == "mp4":
            _run(cmd_mp4, timeout=300)
        else:
            _run(cmd_mov, timeout=300)
            return mov_fp
    except Exception as e:
        print("[ffmpeg] primary attempt failed, retrying alternate:", e)
        try:
            if first == "mp4":
                _run(cmd_mov, timeout=300)
                return mov_fp
            else:
                _run(cmd_mp4, timeout=300)
        except Exception as e2:
            print("[ffmpeg] alternate attempt failed:", e2)
            # Last resort: MP4 without -loop
            cmd_safe = [
                FFMPEG_BIN, "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
                "-f", "image2", "-framerate", "1", "-i", image_fp,
                "-analyzeduration", "16k", "-probesize", "16k",
                "-i", audio_fp,
                "-shortest",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-tune", "stillimage",
                "-pix_fmt", "yuv420p", "-r", "1",
                "-c:a", "aac", "-b:a", "96k",
                "-movflags", "+faststart",
                "-f", "mp4",
                "-threads", "1",
                out_fp,
            ]
            _run(cmd_safe, timeout=300)

    return out_fp

def ffmpeg_concat_parts(parts: List[str], out_fp: str):
    tmpdir = tempfile.mkdtemp(prefix="cxconcat_")
    list_fp = os.path.join(tmpdir, "list.txt")
    with open(list_fp, "w", encoding="utf-8") as f:
        for p in parts:
            f.write(f"file '{p}'\n")
    cmd = [
        FFMPEG_BIN, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", list_fp,
        "-c", "copy",
        out_fp,
    ]
    try:
        _run(cmd, timeout=240)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

# =========================
# Build video (no MoviePy)
# =========================
def build_video_from_sections_ffmpeg(
    sections: List[Tuple[str, str]],
    out_path: str,
    rate_delta: int = 0
) -> str:
    ensure_space_or_raise(500)
    tmp_dir = os.path.join(tempfile.gettempdir(), f"cx_{uuid.uuid4().hex}")
    os.makedirs(tmp_dir, exist_ok=True)
    slide_parts: List[str] = []
    try:
        for idx, (title, text) in enumerate(sections, start=1):
            full_text = (title + "\n" + text).strip()

            # 1) TTS → WAV
            audio_fp = os.path.join(tmp_dir, f"seg_{idx}.wav")
            tts_to_wav(full_text, audio_fp, rate_delta=rate_delta)

            # 2) Render slide image
            frame_fp = os.path.join(tmp_dir, f"frame_{idx}.png")
            wrap_text_to_image(full_text).save(frame_fp)

            # 3) Mux per-slide
            target_ext = ".mp4" if (PREF_CONTAINER == "mp4" or not PREF_CONTAINER) else ".mov"
            slide_fp = os.path.join(tmp_dir, f"part_{idx:03d}{target_ext}")
            result_fp = ffmpeg_still_with_audio(frame_fp, audio_fp, slide_fp)
            if result_fp and os.path.exists(result_fp):
                slide_parts.append(result_fp)
            else:
                slide_parts.append(slide_fp)

        ffmpeg_concat_parts(slide_parts, out_path)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return out_path

# =========================
# Core Pipeline
# =========================
@dataclass
class ExplainerResult:
    level: str
    text_markdown: str
    links: List[str]
    video_path: Optional[str]

def make_level_explainer(level: str, md_text: str, code_blocks: List[Tuple[str, str]]) -> ExplainerResult:
    summary = summarize_file(md_text)
    data = openai_explain(level, code_blocks, summary)

    lang = code_blocks[0][0] if code_blocks else "programming"
    joined_code = "\n".join(cb[1] for cb in code_blocks)[:5000]
    queries = pick_research_queries(lang, joined_code)
    links = []
    for q in queries:
        links.extend(ddg_search_links(q, k=3))
        if len(links) >= 10:
            break
    def sort_key(u): return (0 if u.startswith("https://") else 1, u)
    links = sorted(list(dict.fromkeys(links)), key=sort_key)[:10]

    # Markdown text output
    md_parts = []
    md_parts.append(f"# Code Explainer — {level.capitalize()}\n")
    md_parts.append(f"**TL;DR**: {data.get('tl_dr','').strip()}\n")
    md_parts.append("## Overview\n" + data.get("overview", "").strip() + "\n")
    if data.get("key_concepts"):
        md_parts.append("## Key Concepts")
        for c in data["key_concepts"]:
            md_parts.append(f"- {c}")
        md_parts.append("")
    if data.get("walkthrough"):
        md_parts.append("## Step-by-step Walkthrough\n" + data["walkthrough"].strip() + "\n")
    if data.get("complexity"):
        md_parts.append("## Complexity / Performance\n" + data["complexity"].strip() + "\n")
    if data.get("pitfalls"):
        md_parts.append("## Pitfalls & Edge Cases")
        for p in data["pitfalls"]:
            md_parts.append(f"- {p}")
        md_parts.append("")
    if data.get("quiz"):
        md_parts.append("## Quick Quiz (self-check)")
        for i, qa in enumerate(data["quiz"], start=1):
            q = qa.get("q", "")
            a = qa.get("a", "")
            md_parts.append(f"**Q{i}.** {q}\n\n*Answer.* {a}\n")
    if links:
        md_parts.append("## References / Further Reading")
        for u in links:
            md_parts.append(f"- {u}")
    text_md = "\n".join(md_parts).strip()

    # Shorten narration a bit for speed/stability (FAST mode shorter)
    MAX_PER_SECTION = 350 if FAST_MODE else 900
    def short(s: str) -> str:
        s = (s or "").strip()
        return (s[:MAX_PER_SECTION] + "…") if len(s) > MAX_PER_SECTION else s

    # Choose container for final
    out_ext = ".mp4" if (PREF_CONTAINER == "mp4" or not PREF_CONTAINER) else ".mov"
    vid_id = f"{timestamp()}_{safe_filename(level)}{out_ext}"
    out_video = os.path.join(VIDEO_DIR, vid_id)

    sections = []
    if data.get("overview"):
        sections.append(("Overview", short(data["overview"])))
    if data.get("key_concepts"):
        sections.append(("Key Concepts", short("; ".join(data["key_concepts"][:6]))))
    if data.get("walkthrough"):
        sections.append(("Walkthrough", short(data["walkthrough"])))
    if data.get("complexity"):
        sections.append(("Complexity", short(data["complexity"])))
    if data.get("pitfalls"):
        sections.append(("Pitfalls", short("; ".join(data["pitfalls"][:6]))))
    if data.get("tl_dr"):
        sections.append(("TL;DR", short(data["tl_dr"])))

    video_path = None
    if not SKIP_VIDEO and sections:
        try:
            ensure_space_or_raise(500)
            build_video_from_sections_ffmpeg(sections, out_video)
            video_path = out_video
        except RuntimeError as e:
            if "Low disk space" in str(e):
                text_md += "\n\n> ⚠️ Skipped video: low disk space. Free up space or set TMPDIR to a larger drive and try again."
            else:
                text_md += f"\n\n> ⚠️ Video generation failed: {e}"
        except Exception as e:
            print("[video] build failed:", e)
            text_md += f"\n\n> ⚠️ Video generation failed: {e}"

    return ExplainerResult(level=level, text_markdown=text_md, links=links, video_path=video_path)

def pipeline(file_obj, levels: List[str]):
    if file_obj is None:
        return "Please upload a markdown file.", None, None, None

    if OPENAI_INIT_ERROR:
        gr.Warning(f"⚠️ OpenAI initialization failed: {OPENAI_INIT_ERROR}")

    md_text = read_text_file(file_obj.name)
    blocks = extract_code_blocks_from_markdown(md_text)
    if not blocks:
        blocks = [("plain", md_text)]

    only_levels = os.getenv("EXPLAINER_LEVELS", "")
    if only_levels:
        wanted = {s.strip().lower() for s in only_levels.split(",") if s.strip()}
        levels = [lvl for lvl in levels if lvl.lower() in wanted] or levels

    results: Dict[str, ExplainerResult] = {}
    for lvl in levels:
        results[lvl] = make_level_explainer(lvl, md_text, blocks)

    text_outputs = "# All Explanations\n\n"
    files_to_return = []
    video_gallery = []
    for lvl in levels:
        r = results[lvl]
        text_outputs += r.text_markdown + "\n\n---\n\n"
        if r.video_path and os.path.exists(r.video_path):
            files_to_return.append(r.video_path)
            video_gallery.append(r.video_path)

    return text_outputs.strip(), video_gallery, files_to_return, f"Saved to {OUTPUT_DIR}"

# =========================
# NEW: GitHub & Local pipelines
# =========================
def pipeline_from_github(repo_url: str, levels: List[str], ref: str = "", token: str = ""):
    if not repo_url.strip():
        return "Enter a GitHub repo URL.", None, None, None
    tmp_md = os.path.join(OUTPUT_DIR, "ingest", f"github_{timestamp()}.md")
    os.makedirs(os.path.dirname(tmp_md), exist_ok=True)
    try:
        ingest_github(repo_url.strip(), tmp_md, branch_or_ref=(ref.strip() or None),
                      github_token=(token.strip() or None))
    except Exception as e:
        return f"GitHub ingest failed: {e}", None, None, None
    class _Tmp: name = tmp_md
    return pipeline(_Tmp, levels)

def pipeline_from_local(local_path: str, levels: List[str]):
    if not local_path.strip():
        return "Enter a local project folder path.", None, None, None
    tmp_md = os.path.join(OUTPUT_DIR, "ingest", f"local_{timestamp()}.md")
    os.makedirs(os.path.dirname(tmp_md), exist_ok=True)
    try:
        ingest_local(os.path.expanduser(local_path.strip()), tmp_md)
    except Exception as e:
        return f"Local ingest failed: {e}", None, None, None
    class _Tmp: name = tmp_md
    return pipeline(_Tmp, levels)

# =========================
# Gradio UI
# =========================
with gr.Blocks(title="Code Explainer (Markdown → Text + Video)") as demo:
    gr.Markdown(
        """
# 🧠 Code Explainer — Markdown → Text + Video (Local TTS)
Upload a **code markdown** file OR point at a **GitHub repo** / **local folder**.  
This builds audience-specific explanations (Beginner / Intermediate / Advanced), fetches **reference links**, and creates **local videos** with offline/OS TTS.

**Secrets:** `.env` → `OPENAI_API_KEY`, optional `OPENAI_MODEL`  
**Output:** `./outputs/` (videos under `outputs/videos/`)  
**Fast mode:** set `EXPLAINER_FAST=1` for smaller, faster videos
        """
    )

    with gr.Tabs():
        with gr.Tab("Upload .md"):
            with gr.Row():
                file_in = gr.File(label="Upload Markdown (.md)", file_types=[".md"])
                levels_u = gr.CheckboxGroup(
                    choices=["beginner", "intermediate", "advanced"],
                    value=["beginner", "intermediate", "advanced"],
                    label="Audience Levels"
                )
            run_btn_u = gr.Button("Generate (from .md)", variant="primary")

        with gr.Tab("GitHub Repo"):
            gh_url = gr.Textbox(label="GitHub URL (https or git@)", placeholder="https://github.com/user/repo or git@github.com:user/repo.git")
            gh_ref = gr.Textbox(label="Branch/Tag/Commit (optional)")
            gh_token = gr.Textbox(label="GitHub Token (optional, for private repos)", type="password")
            levels_g = gr.CheckboxGroup(
                choices=["beginner", "intermediate", "advanced"],
                value=["beginner", "intermediate", "advanced"],
                label="Audience Levels"
            )
            run_btn_g = gr.Button("Generate (from GitHub)", variant="primary")

        with gr.Tab("Local Folder"):
            local_path = gr.Textbox(label="Local project path", placeholder="/Users/you/dev/my-project")
            levels_l = gr.CheckboxGroup(
                choices=["beginner", "intermediate", "advanced"],
                value=["beginner", "intermediate", "advanced"],
                label="Audience Levels"
            )
            run_btn_l = gr.Button("Generate (from local folder)", variant="primary")

    # Shared outputs
    text_out = gr.Markdown(label="Text Explanations")
    vids = gr.Gallery(label="Generated Videos", columns=3, height=240)
    files = gr.Files(label="Download Video Files")
    save_loc = gr.Textbox(label="Output Folder", value=OUTPUT_DIR, interactive=False)

    # Wire actions
    run_btn_u.click(fn=pipeline, inputs=[file_in, levels_u], outputs=[text_out, vids, files, save_loc], api_name="run_from_md")
    run_btn_g.click(fn=pipeline_from_github, inputs=[gh_url, levels_g, gh_ref, gh_token], outputs=[text_out, vids, files, save_loc], api_name="run_from_github")
    run_btn_l.click(fn=pipeline_from_local, inputs=[local_path, levels_l], outputs=[text_out, vids, files, save_loc], api_name="run_from_local")

# serialize jobs (avoid overlapping encodes); compatible with older Gradio
demo.queue(max_size=1)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7870, share=False)
