# Code Explainer — Markdown/Repo → Text + Video

Turn a **markdown file** *or an entire codebase (GitHub URL / local path)* into:

- audience-specific explanations (**Beginner / Intermediate / Advanced**)
- a small **reference list** fetched from the web
- an optional narrated **video** (slides + TTS, no MoviePy)

UI is built with **Gradio**. Narration uses **macOS `say`** (fast) with automatic fallback to **`pyttsx3`**. Video is rendered via **ffmpeg**.

---

## ✨ What’s new

- **GitHub repo support:** Point to a public or authenticated Git URL; we’ll shallow-clone and extract markdown/code automatically.
- **Local path support:** Point to a folder on your machine; we’ll walk it and extract markdown/code.
- **Smart file picking:** Looks for `README.md`, `*/docs/*.md`, and representative code files if no markdown is uploaded.
- **Detail level control:** Choose **Brief / Standard / Deep-dive** to get more (or less) explanation: deep-dive adds **Architecture, Data Flow, API Surface, Testing, Security, Deployment, Glossary** where helpful.
- **Create video? toggle:** Decide per run whether to render narrated slides (overrides `EXPLAINER_NO_VIDEO`).

> The UI now has **three source modes** and **two content controls**:
>
> - Source: **Upload Markdown** | **GitHub Repo URL** | **Local Project Path**
> - Content: **Detail level (Brief / Standard / Deep-dive)**, **Create video?** (checkbox)

---

## 📦 Requirements

- Python 3.10+
- `ffmpeg` on PATH (Homebrew on macOS):
  ```bash
  brew install ffmpeg
  ```
- macOS recommended (fast `say`). Linux/Windows fall back to `pyttsx3`.
- **For GitHub**: `git` must be installed (e.g., `brew install git`).

---

## 🔐 Environment

Create `.env` in the repo root:

```
OPENAI_API_KEY=sk-********************************
OPENAI_MODEL=gpt-4o-mini
```

**Optional toggles**

```
# ffmpeg binary (recommended on Apple Silicon)
FFMPEG_BIN=/opt/homebrew/bin/ffmpeg

# macOS 'say' voice (Samantha, Alex, Victoria, etc.)
EXPLAINER_VOICE=Samantha

# Faster/smaller slides + shorter narration
EXPLAINER_FAST=1

# Skip web references or video by default (UI can override video per run)
EXPLAINER_NO_WEB=1
EXPLAINER_NO_VIDEO=1

# Limit which audience levels run when multiple are selected in UI
EXPLAINER_LEVELS=beginner,advanced

# Prefer output container
EXPLAINER_CONTAINER=mp4   # or mov
```

**Temp / disk space**

All scratch goes to `outputs/tmp/` by default. You can force a different temp:

```bash
export TMPDIR="$PWD/outputs/tmp"
```

---

## 🛠️ Install

```bash
git clone git@github.com:pranavsaji/code-_explainer.git
cd code-_explainer
python -m venv .venv
source .venv/bin/activate
pip install -U pip wheel
pip install -r requirements.txt
# (If no lock file, then:)
# pip install gradio openai python-dotenv beautifulsoup4 pillow pyttsx3 imageio-ffmpeg requests
```

> You don’t need GitPython—the app shells out to your system `git`.

---

## ▶️ Run the App

```bash
python app.py
```

Open the printed URL (e.g., `http://0.0.0.0:7870`) and choose a **Source**:

### 1) Upload Markdown

- Click **Upload Markdown** and choose a `.md`.
- Pick **Audience Levels**.
- Choose **Detail level**: Brief / Standard / Deep-dive.
- (Optional) Toggle **Create video?** on/off.
- Click **Generate**.

### 2) GitHub Repo URL

- Select **GitHub Repo URL**.
- Paste a URL:
  - HTTPS: `https://github.com/owner/repo`
  - SSH: `git@github.com:owner/repo.git`
- (Optional) **Git Ref**: branch, tag, or commit (defaults to repo default branch).
- (Optional) **GitHub Token**: for private HTTPS repos; prefer SSH for security.
- Choose **levels**, **detail**, and **Create video?** → **Generate**.

**Private repos tips**

- SSH URLs: make sure your key has access and `ssh-agent` is running.
- HTTPS PAT: use token with `repo` scope; SSH is usually simpler/safer.

### 3) Local Project Path

- Select **Local Project Path**.
- Enter an **absolute path** (e.g., `/Users/you/dev/my-app`).
- Choose **levels**, **detail**, and **Create video?** → **Generate**.

---

## 🧠 What the app does

1. **Collects content**
   - If you uploaded `.md`: uses that.
   - If **GitHub**: shallow clone → prefer `README*.md`, `docs/**/*.md`, else sample representative code files.
   - If **Local path**: scans similarly.
   - If no markdown found, it synthesizes a compact summary from code snippets (length-capped).

2. **Extracts fenced code blocks** from markdown (```lang … ```), optionally mixes in sampled code for context.

3. **Asks the LLM** to produce: overview, key concepts, walkthrough, complexity, pitfalls, quiz, TL;DR — **tailored by level** (beginner/intermediate/advanced).  
   With **Deep-dive**, it additionally returns (when relevant): **Architecture**, **Data Flow**, **API Surface**, **Testing**, **Security**, **Deployment**, **Glossary**.

4. **Web references**: pulls a short list via DuckDuckGo HTML (more links for deeper detail).

5. **Video** (optional): creates narrated slides (Overview → Concepts → Walkthrough → …) with OS TTS + ffmpeg.

Outputs land in:

```
outputs/
  videos/   # Final .mp4/.mov
  tmp/      # Working dir
```

---

## 🎛️ Detail level & video toggle

- **Detail level**
  - **Brief**: punchy summary; fewer links; shorter slides.
  - **Standard**: balanced; good defaults.
  - **Deep-dive**: adds Architecture/Data Flow/API/Testing/Security/Deployment/Glossary when helpful; more links and longer narration.

- **Create video?**
  - Per-run checkbox in the UI.
  - This **overrides** `EXPLAINER_NO_VIDEO` (env default) for that run.

---

## 🧪 Quick Sanity Checks

**ffmpeg + say:**

```bash
echo "hello" > /tmp/a.txt
say -o /tmp/a.aiff --data-format=LEI16@16000 -r 175 -f /tmp/a.txt   # macOS
ffmpeg -y -i /tmp/a.aiff -acodec pcm_s16le -ac 1 -ar 16000 /tmp/a.wav
ffmpeg -y -loop 1 -framerate 1 -i /System/Library/CoreServices/DefaultDesktop.jpg \
       -i /tmp/a.wav -shortest -c:v libx264 -pix_fmt yuv420p -r 1 -c:a aac /tmp/test.mp4
```

**git access (SSH):**

```bash
ssh -T git@github.com
# Should greet you by username if your key is loaded
```

---

## 🧩 CLI/ENV Overrides (optional power-user)

You can pre-set a source via env vars (useful for headless runs):

```
# one of: upload | git | path
EXPLAINER_SOURCE=git
EXPLAINER_SOURCE_URL=git@github.com:owner/repo.git
EXPLAINER_GIT_REF=main

# or:
# EXPLAINER_SOURCE=path
# EXPLAINER_SOURCE_PATH=/absolute/path/to/project
```

Then run:

```bash
python app.py
```

The UI will pre-populate fields and use those values if you don’t upload a file.

---

## 🧩 How code selection works (repos/paths)

- Prefer `README.md` / `README*.md`
- Then `docs/**/*.md`
- If nothing markdown-y exists, we:
  - sample a small set of **source files** (`.py`, `.js`, `.ts`, `.java`, `.go`, `.rb`, etc.)
  - extract top-of-file comments and key functions/classes (length-capped)
  - synthesize a compact “context markdown” for the explainer

> Want full control? Upload your own curated `.md`.

---

## 🧪 Troubleshooting

**`Opening output file failed: fmt?` (from `say`)**
- Some macOS `say` voices don’t like certain data-format flags or paths. The app auto-falls back to `pyttsx3`.
- Try a different voice:
  ```bash
  say -v ? | less
  export EXPLAINER_VOICE=Alex
  ```

**`No space left on device` / ffmpeg rc=228**
- Free disk or point `TMPDIR` to a larger folder:
  ```bash
  export TMPDIR="$PWD/outputs/tmp"
  ```
- Use fast mode + fewer levels:
  ```bash
  export EXPLAINER_FAST=1
  export EXPLAINER_LEVELS=beginner
  ```

**GitHub private repo errors**
- SSH: ensure your key is added (`ssh-add -K ~/.ssh/id_rsa`) and GitHub has your key.
- HTTPS: PAT must have `repo` scope; prefer SSH for security.
- Very large repos: shallow clone helps; **FAST** mode reduces load.

**MP4 muxing issues**
- App retries and can produce `.mov` (MJPEG+PCM), then concatenates copy-only.
- Prefer container via:
  ```bash
  export EXPLAINER_CONTAINER=mp4   # or mov
  ```

---

## 🗂️ Repo Hygiene

Generated stuff is **not committed**. `.gitignore` excludes:

- `.env`
- `outputs/` (generated videos/temp)
- `__pycache__/`, `.DS_Store`, virtualenvs, etc.

To share videos, use Releases, LFS, or cloud storage.

---

## 🔒 Privacy

- Only the curated summary + code excerpts are sent to the LLM.
- Web search uses DuckDuckGo HTML (no account).
- All artifacts stay local.

---

## 🧭 Project Layout

```
app.py
repo_ingest/
  github_ingest.py     # shallow clone + selection
  local_ingest.py      # local folder scanning + selection
requirements.txt
README.md
.gitignore
outputs/
  videos/              # generated (ignored by Git)
  tmp/                 # temp working (ignored by Git)
```

---

## 📝 License

MIT (or change as desired).

---

## 🙋 FAQ

**Does it work on huge repos?**  
Yes—files are sampled and prompts are length-capped. **FAST** mode helps.

**Can I bring my own LLM?**  
Swap the OpenAI call in `openai_explain()` and keep the same JSON schema.

**Can I style slides?**  
Yes; tweak `wrap_text_to_image()` (font, colors, size).

**Only text, no video?**  
Uncheck **Create video?** in the UI or set `EXPLAINER_NO_VIDEO=1`.

**Skip web references?**  
Set `EXPLAINER_NO_WEB=1`.