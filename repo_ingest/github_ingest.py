# repo_ingest/github_ingest.py
import os
import re
import io
import sys
import zipfile
import shutil
import tempfile
import subprocess
from typing import Iterable, Optional, List, Tuple

import requests

DEFAULT_INCLUDE_EXTS = {
    ".py", ".ipynb", ".js", ".ts", ".tsx", ".jsx",
    ".java", ".kt", ".go", ".rs", ".rb", ".php",
    ".c", ".h", ".cpp", ".hpp", ".cs", ".swift",
    ".sql", ".scala", ".hs", ".lua", ".r", ".m", ".mm",
    ".sh", ".bash", ".zsh", ".ps1",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".md", ".rst", ".txt"
}

DEFAULT_EXCLUDE_DIRS = {
    ".git", ".hg", ".svn", ".idea", ".vscode",
    "node_modules", "dist", "build", "out", "target",
    ".venv", "venv", "__pycache__", ".ruff_cache", ".mypy_cache",
    ".pytest_cache", ".next", ".parcel-cache", ".turbo"
}

def _lang_from_ext(ext: str) -> str:
    ext = ext.lower()
    return {
        ".py": "python", ".ipynb": "json",
        ".js": "javascript", ".jsx": "jsx",
        ".ts": "typescript", ".tsx": "tsx",
        ".java": "java", ".kt": "kotlin",
        ".go": "go", ".rs": "rust", ".rb": "ruby",
        ".php": "php", ".c": "c", ".h": "c",
        ".cpp": "cpp", ".hpp": "cpp", ".cs": "csharp",
        ".swift": "swift", ".sql": "sql", ".scala": "scala",
        ".hs": "haskell", ".lua": "lua", ".r": "r",
        ".m": "objectivec", ".mm": "objectivec",
        ".sh": "bash", ".bash": "bash", ".zsh": "bash", ".ps1": "powershell",
        ".json": "json", ".yaml": "yaml", ".yml": "yaml",
        ".toml": "toml", ".ini": "ini", ".cfg": "ini",
        ".md": "markdown", ".rst": "rst", ".txt": "text",
    }.get(ext, "")

def _should_skip_dir(name: str) -> bool:
    low = name.lower()
    return (low in DEFAULT_EXCLUDE_DIRS) or low.startswith("._")

def _can_use_git() -> bool:
    return shutil.which("git") is not None

def _parse_github_url(url: str) -> Tuple[str, Optional[str]]:
    """
    Returns (https_url, ref) where ref may be branch/tag/commit or None.
    Accepts ssh or https; normalizes to https.
    Examples:
      git@github.com:user/repo.git -> https://github.com/user/repo
      https://github.com/user/repo/tree/dev -> https://github.com/user/repo , ref='dev'
    """
    if url.startswith("git@github.com:"):
        # convert ssh to https
        core = url[len("git@github.com:"):].rstrip(".git")
        https = f"https://github.com/{core}"
        return https, None
    if url.startswith("https://github.com/"):
        https = url
        # extract /tree/<ref> or /commit/<sha> or /releases/tag/<tag>
        m = re.search(r"/tree/([^/]+)", url)
        if m:
            ref = m.group(1)
            base = url.split("/tree/")[0]
            return base, ref
        m = re.search(r"/commit/([0-9a-fA-F]{6,})", url)
        if m:
            return url.split("/commit/")[0], m.group(1)
        m = re.search(r"/releases/tag/([^/]+)", url)
        if m:
            return url.split("/releases/tag/")[0], m.group(1)
        # strip .git at end if any
        if https.endswith(".git"):
            https = https[:-4]
        return https, None
    # last resort: return as-is
    return url, None

def _github_zip_url(https_repo_url: str, ref: Optional[str]) -> str:
    """
    Builds a zipball URL for GitHub.
    """
    # https://github.com/user/repo -> https://api.github.com/repos/user/repo/zipball/<ref_or_default>
    parts = https_repo_url.rstrip("/").split("/")
    if len(parts) < 5:
        # ['', 'https:', '', 'github.com', 'user', 'repo']
        user = parts[4]
        repo = parts[5] if len(parts) > 5 else ""
    else:
        user = parts[-2]
        repo = parts[-1]
    if not user or not repo:
        raise ValueError(f"Unrecognized GitHub URL: {https_repo_url}")
    if ref:
        return f"https://api.github.com/repos/{user}/{repo}/zipball/{ref}"
    return f"https://api.github.com/repos/{user}/{repo}/zipball"

def _gather_files_as_markdown(root: str,
                              max_files: int = 300,
                              max_bytes_per_file: int = 500_000,
                              include_exts: Optional[Iterable[str]] = None) -> str:
    include_exts = set(include_exts or DEFAULT_INCLUDE_EXTS)
    files_added = 0
    parts: List[str] = []

    readme_first: List[str] = []
    others: List[Tuple[str, str]] = []

    for dirpath, dirnames, filenames in os.walk(root):
        # prune excluded dirs
        dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]

        for fn in sorted(filenames):
            if files_added >= max_files:
                break
            ext = os.path.splitext(fn)[1].lower()
            if ext not in include_exts:
                continue
            fp = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(fp) > max_bytes_per_file:
                    continue
            except OSError:
                continue
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except Exception:
                continue

            rel = os.path.relpath(fp, root)
            lang = _lang_from_ext(ext)
            block = []
            block.append(f"\n\n<!-- file: {rel} -->\n")
            if lang in ("markdown", "rst", "text", ""):
                # keep as-is without fencing to avoid nested fences
                block.append(content.strip())
            else:
                block.append(f"```{lang}\n{content.strip()}\n```")
            chunk = "\n".join(block)

            if fn.lower().startswith("readme"):
                readme_first.append(chunk)
            else:
                others.append((rel, chunk))
            files_added += 1

        if files_added >= max_files:
            break

    # sort others by path for stability
    others = [c for _, c in sorted(others, key=lambda x: x[0])]
    parts.extend(readme_first)
    parts.extend(others)
    return "\n".join(parts).strip() or "# (empty)"

def ingest_github(
    repo_url: str,
    output_md_path: str,
    branch_or_ref: Optional[str] = None,
    github_token: Optional[str] = None,
    max_files: int = 300,
    max_bytes_per_file: int = 500_000,
    include_exts: Optional[Iterable[str]] = None,
) -> str:
    """
    Fetches a GitHub repo (via shallow clone if git is available, else via zip),
    filters files, and writes a combined markdown at output_md_path. Returns that path.
    """
    https_url, parsed_ref = _parse_github_url(repo_url)
    ref = branch_or_ref or parsed_ref

    tmp_root = tempfile.mkdtemp(prefix="tmp_repo_")
    try:
        # Try git shallow clone first (fast & tiny)
        if _can_use_git() and https_url.startswith("https://github.com/"):
            clone_cmd = ["git", "clone", "--depth", "1"]
            if ref:
                clone_cmd += ["--branch", ref]
            clone_cmd += [https_url, tmp_root]
            try:
                subprocess.run(clone_cmd, check=True, timeout=120)
            except Exception:
                # fall back to zip
                _download_zip_to(tmp_root, https_url, ref, github_token)
        else:
            _download_zip_to(tmp_root, https_url, ref, github_token)

        # if zip path contains a single root folder (GitHub zipball), descend into it
        entries = os.listdir(tmp_root)
        if len(entries) == 1 and os.path.isdir(os.path.join(tmp_root, entries[0])):
            repo_root = os.path.join(tmp_root, entries[0])
        else:
            repo_root = tmp_root

        md_text = _gather_files_as_markdown(
            repo_root, max_files=max_files,
            max_bytes_per_file=max_bytes_per_file,
            include_exts=include_exts
        )
        os.makedirs(os.path.dirname(output_md_path), exist_ok=True)
        with open(output_md_path, "w", encoding="utf-8") as f:
            f.write(md_text)
        return output_md_path
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

def _download_zip_to(tmp_root: str, https_repo_url: str, ref: Optional[str], token: Optional[str]):
    url = _github_zip_url(https_repo_url, ref)
    headers = {"User-Agent": "repo-ingest/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.get(url, headers=headers, timeout=120)
    resp.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(resp.content))
    z.extractall(tmp_root)
