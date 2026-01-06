from __future__ import annotations

import fnmatch
from pathlib import Path


def should_exclude_path(path: str, exclude_prefixes: list[str], exclude_globs: list[str]) -> bool:
    p = path.replace("\\", "/").lstrip("./")
    for pref in exclude_prefixes:
        pr = (pref or "").replace("\\", "/").lstrip("./")
        if not pr:
            continue
        if not pr.endswith("/"):
            pr = pr + "/"
        if p.startswith(pr) or f"/{pr}" in p:
            return True
    for pat in exclude_globs:
        if pat and fnmatch.fnmatch(p, pat):
            return True
    return False


def normalize_numstat_path(path: str) -> str:
    p = path.strip()
    # `git log --numstat` may render renames like: src/{old => new}/file.py or src/{old.py => new.py}
    if " => " in p:
        p = p.replace("{", "").replace("}", "")
        p = p.split(" => ")[-1]
    return p.strip()


def language_for_path(path: str) -> str:
    p = path.replace("\\", "/")
    base = p.rsplit("/", 1)[-1]
    if base == "Dockerfile" or base.lower().startswith("dockerfile."):
        return "Dockerfile"
    if base == "Makefile" or base == "makefile":
        return "Makefile"

    ext = Path(base).suffix.lower()
    by_ext = {
        ".py": "Python",
        ".ipynb": "Jupyter",
        ".js": "JavaScript",
        ".jsx": "JavaScript",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".mjs": "JavaScript",
        ".cjs": "JavaScript",
        ".java": "Java",
        ".kt": "Kotlin",
        ".swift": "Swift",
        ".go": "Go",
        ".rs": "Rust",
        ".php": "PHP",
        ".rb": "Ruby",
        ".cs": "C#",
        ".c": "C",
        ".h": "C/C++ Headers",
        ".cpp": "C++",
        ".hpp": "C++",
        ".mm": "Objective-C++",
        ".m": "Objective-C",
        ".scala": "Scala",
        ".sql": "SQL",
        ".tf": "Terraform",
        ".yml": "YAML",
        ".yaml": "YAML",
        ".json": "JSON",
        ".toml": "TOML",
        ".ini": "INI",
        ".md": "Markdown",
        ".rst": "reStructuredText",
        ".html": "HTML",
        ".htm": "HTML",
        ".css": "CSS",
        ".scss": "SCSS",
        ".sass": "Sass",
        ".less": "Less",
        ".sh": "Shell",
        ".bash": "Shell",
        ".zsh": "Shell",
        ".ps1": "PowerShell",
        ".bat": "Batch",
        ".dockerignore": "Docker",
        ".gradle": "Gradle",
        ".xml": "XML",
        ".proto": "Protobuf",
    }
    if ext in by_ext:
        return by_ext[ext]
    return "Other"


def dir_key_for_path(path: str, depth: int = 1) -> str:
    p = path.replace("\\", "/").lstrip("./")
    if not p or "/" not in p:
        return "(root)"
    parts = [x for x in p.split("/") if x]
    if not parts:
        return "(root)"
    d = "/".join(parts[: max(1, depth)])
    return d

