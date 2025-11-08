# Code Explainer — Markdown → Text + Video

Turn a **code markdown file** into:
- audience-specific explanations (Beginner / Intermediate / Advanced),
- a reference list fetched from the web, and
- a narrated **video** (slides + TTS).

UI is built with **Gradio**. Narration uses **macOS `say`** (fast) with automatic fallback to **`pyttsx3`**. Video is rendered via **ffmpeg** (no MoviePy dependency).

---

## ✨ Features

- Extracts fenced code blocks from `.md` and asks an LLM to explain them by level.
- Builds clean markdown output (overview, key concepts, walkthrough, pitfalls, quiz, TL;DR).
- Fetches a few helpful links via DuckDuckGo HTML (no API key).
- Renders a short narrated slideshow video per level.
- “Fast” mode for quick iteration.
- Robust temp-dir management and disk-space checks.

---

## 📦 Requirements

- Python 3.10+ (3.12/3.13 OK)
- `ffmpeg` in PATH (Homebrew recommended on macOS):
  ```bash
  brew install ffmpeg
  ```
- macOS (preferred, for fast `say` TTS). Linux/Windows will fall back to `pyttsx3`.

---

## 🔐 Environment

Create a `.env` in the repo root:

```
OPENAI_API_KEY=sk-********************************
OPENAI_MODEL=gpt-4o-mini
```

**Optional toggles**

```
# Use Homebrew/system ffmpeg (recommended)
FFMPEG_BIN=/opt/homebrew/bin/ffmpeg

# Use macOS 'say' voice (e.g., Samantha, Alex, Victoria). If unset, default system voice is used.
EXPLAINER_VOICE=Samantha

# Speed up everything (smaller slides, shorter narration)
EXPLAINER_FAST=1

# Skip web search for links
EXPLAINER_NO_WEB=1

# Skip video generation (for debugging text only)
EXPLAINER_NO_VIDEO=1

# Restrict which levels run: comma-sep subset of beginner,intermediate,advanced
EXPLAINER_LEVELS=beginner,advanced
```

mkdir -p outputs/{videos,audio,frames,tmp}
touch outputs/README.md

**Tip (disk space / temp path):**
By default the app writes temp files to `outputs/tmp/`. You can also point `TMPDIR` to a larger disk:

```bash
export TMPDIR="$PWD/outputs/tmp"
```

---

## 🛠️ Installation

```bash
git clone git@github.com:pranavsaji/code-_explainer.git
cd code-_explainer
python -m venv .venv
source .venv/bin/activate
pip install -U pip wheel
pip install -r requirements.txt   # if present; otherwise:
# pip install gradio openai python-dotenv beautifulsoup4 pillow pyttsx3 imageio-ffmpeg requests
```

---

## ▶️ Run

```bash
python app.py
```

Open the URL printed in the console (e.g., `http://0.0.0.0:7870`) and:

1. Upload a `.md` file containing your code/notes.
2. Choose the audience levels.
3. Click **Generate Explanations + Videos**.

Outputs are saved under:

```
outputs/
  videos/   # Final .mov/.mp4
  audio/    # (if enabled by you later)
  frames/   # (if enabled by you later)
  tmp/      # working scratch space
```

---

## 🧪 CLI Quick Test (ffmpeg + TTS)

If video creation fails, confirm ffmpeg first:

```bash
echo "hello" > /tmp/a.txt
say -o /tmp/a.aiff --data-format=LEI16@16000 -r 175 -f /tmp/a.txt   # macOS
ffmpeg -y -i /tmp/a.aiff -acodec pcm_s16le -ac 1 -ar 16000 /tmp/a.wav
ffmpeg -y -loop 1 -framerate 1 -i /System/Library/CoreServices/DefaultDesktop.jpg \
       -i /tmp/a.wav -shortest -c:v libx264 -pix_fmt yuv420p -r 1 -c:a aac /tmp/test.mp4
```

---

## 🧩 Troubleshooting

**“Opening output file failed: fmt?” (from `say`)**
- Usually happens when `say` dislikes the output path or options.
- The app already falls back to `pyttsx3`. If you want to force `say`, try a different voice:
  ```bash
  say -v ? | less   # list voices
  export EXPLAINER_VOICE=Alex
  ```

**“No space left on device”**
- You’re low on free disk. Free up space or set:
  ```bash
  export TMPDIR="$PWD/outputs/tmp"
  ```
- The app checks for space and logs a helpful message; videos are skipped if critically low.

**ffmpeg exits with signal 9 (SIGKILL)**
- On lightweight machines this can be macOS OOM killer. Use **FAST** mode:
  ```bash
  export EXPLAINER_FAST=1
  ```
  and keep your markdown shorter or fewer levels at once:
  ```bash
  export EXPLAINER_LEVELS=beginner
  ```

**Video won’t mux on MP4**
- The app retries with safer flags and can produce `.mov` (MJPEG+PCM) which is very reliable, then concatenate losslessly.

---

## 🗂️ Repo Hygiene

We **do not** commit generated assets. `.gitignore` already excludes:
- `.env`
- `outputs/` (you may keep a `README.md` inside if you like)
- `__pycache__/`, `.DS_Store`, virtualenvs, etc.

If you need to share videos:
- attach to GitHub Releases, use Git LFS, or upload to cloud storage and link in your README.

---

## 🧭 Project Structure

```
app.py                # main app (Gradio UI + pipeline + ffmpeg/tts helpers)
requirements.txt      # (optional) pinned deps
README.md             # this file
.gitignore
outputs/
  videos/             # generated videos (ignored by Git)
  tmp/                # working dir (ignored by Git)
```

---

## 🔒 Privacy

- The app sends **only** your prompt (code summary + code excerpts) to OpenAI’s API to generate explanations.
- Web search uses DuckDuckGo HTML; no API key needed.
- Generated artifacts are local to your machine.

---

## 📝 License

MIT (or update to your preferred license).

---

## 🙋 FAQ

**Can I use a different LLM?**  
Yes—swap the OpenAI call in `openai_explain()` for your provider.

**Can I change the slide style?**  
See `wrap_text_to_image()`—tweak font, size, colors.

**Can I skip web links?**  
Set `EXPLAINER_NO_WEB=1`.

**Only text, no video?**  
Set `EXPLAINER_NO_VIDEO=1`.

---

## 🔧 Common Commands

```bash
# Start (fast mode, one level)
export EXPLAINER_FAST=1
export EXPLAINER_LEVELS=beginner
python app.py

# Use a specific ffmpeg binary
export FFMPEG_BIN=/opt/homebrew/bin/ffmpeg

# Force larger temp path
export TMPDIR="$PWD/outputs/tmp"
```
