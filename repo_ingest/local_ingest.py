# repo_ingest/local_ingest.py
import os
from typing import Iterable, Optional, List

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

def ingest_local(
    project_root: str,
    output_md_path: str,
    max_files: int = 300,
    max_bytes_per_file: int = 500_000,
    include_exts: Optional[Iterable[str]] = None,
) -> str:
    """
    Walks a local project folder and writes a combined markdown at output_md_path.
    """
    if not os.path.isdir(project_root):
        raise ValueError(f"Not a directory: {project_root}")

    include_exts = set(include_exts or DEFAULT_INCLUDE_EXTS)
    files_added = 0
    parts: List[str] = []

    readme_first: List[str] = []
    others: List[str] = []

    for dirpath, dirnames, filenames in os.walk(project_root):
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

            rel = os.path.relpath(fp, project_root)
            lang = _lang_from_ext(ext)
            block = []
            block.append(f"\n\n<!-- file: {rel} -->\n")
            if lang in ("markdown", "rst", "text", ""):
                block.append(content.strip())
            else:
                block.append(f"```{lang}\n{content.strip()}\n```")
            chunk = "\n".join(block)

            if fn.lower().startswith("readme"):
                readme_first.append(chunk)
            else:
                others.append(chunk)
            files_added += 1

        if files_added >= max_files:
            break

    parts.extend(readme_first)
    parts.extend(others)
    md_text = "\n".join(parts).strip() or "# (empty)"
    os.makedirs(os.path.dirname(output_md_path), exist_ok=True)
    with open(output_md_path, "w", encoding="utf-8") as f:
        f.write(md_text)
    return output_md_path
