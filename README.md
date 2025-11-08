# Code Explainer — Markdown/Repo → Text + Video

Turn a **markdown file** *or an entire codebase (GitHub URL / local path)* into:

* audience-specific explanations (**Beginner / Intermediate / Advanced**)
* a small **reference list** fetched from the web
* a narrated **video** (slides + TTS, no MoviePy)

UI is built with **Gradio**. Narration uses **macOS `say`** (fast) with automatic fallback to **`pyttsx3`**. Video is rendered via **ffmpeg**.

---

## ✨ What’s new

* **GitHub repo support:** Point to a public or authenticated Git URL; we’ll clone (shallow) and extract code/markdown automatically.
* **Local path support:** Point to a folder on your machine; we’ll walk it and extract code/markdown.
* **Smart file picking:** Looks for `README.md`, `*/docs/*.md`, and code files for context if no markdown is uploaded.

> The UI now has a **Source** selector:
>
> * **Upload Markdown** (existing behavior)
> * **GitHub Repo URL** (e.g., `https://github.com/owner/repo` or `git@github.com:owner/repo.git`)
> * **Local Project Path** (e.g., `/Users/you/dev/my-project`)

---

## 📦 Requirements

* Python 3.10+
* `ffmpeg` in PATH (Homebrew on macOS):

  ```bash
  brew install ffmpeg
  ```
* macOS recommended (fast `say`). Linux/Windows fall back to `pyttsx3`.
* **For GitHub**: `git` must be installed (`brew install git`).

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

# Skip web references or video (debugging)
EXPLAINER_NO_WEB=1
EXPLAINER_NO_VIDEO=1

# Limit which levels run
EXPLAINER_LEVELS=beginner,advanced
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
# pip install gradio openai python-dotenv beautifulsoup4 pillow pyttsx3 imageio-ffmpeg requests GitPython
```

---

## ▶️ Run the App

```bash
python app.py
```

Open the printed URL (e.g., `http://0.0.0.0:7870`) and choose one of the three **Source** modes:

### 1) Upload Markdown

* Click **Upload Markdown** and choose a `.md`.
* Select levels → **Generate**.

### 2) GitHub Repo URL

* Choose **GitHub Repo URL**.
* Paste a URL:

  * HTTPS: `https://github.com/owner/repo`
  * SSH: `git@github.com:owner/repo.git`
* (Optional) **Git Ref**: branch, tag, or commit (defaults to repo default branch).
* Click **Generate**.

**Private repos?**

* If using SSH URLs, ensure your SSH key has access and `ssh-agent` is running.
* If using HTTPS with PAT, use the `https://<token>@github.com/owner/repo` pattern, but prefer SSH for security.

### 3) Local Project Path

* Choose **Local Project Path**.
* Enter an absolute path (e.g., `/Users/you/dev/my-app`).
* Click **Generate**.

---

## 🧠 What the app does

1. **Collects content**

   * If you uploaded `.md`: uses that.
   * If **GitHub**: shallow clone → looks for `README*.md` / `docs/**/*.md` and code files.
   * If **Local path**: scans the folder similarly.
   * If no markdown is found, it synthesizes a summary from code snippets (safe length).

2. **Extracts fenced code blocks** from markdown (` ```lang … ``` `), and also samples representative code files for context.

3. **Asks the LLM** to produce: overview, key concepts, walkthrough, complexity, pitfalls, quiz, TL;DR — **tailored by level** (beginner/intermediate/advanced).

4. **Web references**: fetches a short list from DuckDuckGo HTML.

5. **Video**: creates short narrated slides (Overview → Concepts → Walkthrough → …) with OS TTS and ffmpeg.

Outputs land in:

```
outputs/
  videos/   # Final .mp4/.mov
  tmp/      # Working dir
```

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

* Prefer `README.md` / `README*.md`
* Then `docs/**/*.md`
* If nothing markdown-y exists, we:

  * sample a small set of **source files** (`.py`, `.js`, `.ts`, `.java`, `.go`, `.rb`, etc.)
  * extract top-of-file comments, key functions/classes (length-capped)
  * synthesize a short “context markdown” for the explainer

You can always upload your own curated `.md` to control context precisely.

---

## 🧪 Troubleshooting

**`Opening output file failed: fmt?` (from `say`)**

* Some macOS `say` voices don’t like the `--data-format` or path. The app auto-falls back to `pyttsx3`.
* Try a different voice:

  ```bash
  say -v ? | less
  export EXPLAINER_VOICE=Alex
  ```

**`No space left on device` / ffmpeg rc=228**

* Free disk or point `TMPDIR` to a larger folder:

  ```bash
  export TMPDIR="$PWD/outputs/tmp"
  ```
* Use fast mode + fewer levels:

  ```bash
  export EXPLAINER_FAST=1
  export EXPLAINER_LEVELS=beginner
  ```

**GitHub private repo errors**

* SSH: ensure your key is added (`ssh-add -K ~/.ssh/id_rsa`) and GitHub has your key.
* HTTPS: PAT must have `repo` scope; prefer SSH for security.
* Large repos: shallow clone keeps it light; still, consider setting **FAST** mode.

**MP4 muxing issues**

* App retries and can produce `.mov` (MJPEG+PCM), then concatenates copy-only.
* You can prefer container via env:

  ```bash
  export EXPLAINER_CONTAINER=mp4   # or mov
  ```

---

## 🗂️ Repo Hygiene

Generated stuff is **not committed**. `.gitignore` excludes:

* `.env`
* `outputs/` (generated videos/temp)
* `__pycache__/`, `.DS_Store`, virtualenvs, etc.

To share videos, use Releases, LFS, or cloud storage.

---

## 🔒 Privacy

* Only the curated summary + code excerpts are sent to the LLM.
* Web search uses DuckDuckGo HTML (no account).
* All artifacts stay local.

---

## 🧭 Project Layout

```
app.py                 # main app (UI + pipeline)
repo_fetcher.py        # clone/shallow-fetch & select files from Git repos
local_loader.py        # scan local paths & select files
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
Yes, but we sample files and cap prompt length. Fast mode helps.

**Can I bring my own LLM?**
Swap `openai_explain()` with your provider (API call + JSON schema).

**Can I style slides?**
Yes; tweak `wrap_text_to_image()` (font, colors, size).

**Only text, no video?**
`EXPLAINER_NO_VIDEO=1`.

**Skip web references?**
`EXPLAINER_NO_WEB=1`.

---
