from __future__ import annotations

from git_analysis.analysis_paths import dir_key_for_path, language_for_path, normalize_numstat_path, should_exclude_path


def test_normalize_numstat_path_rename_braces() -> None:
    assert normalize_numstat_path("src/{old => new}/file.py") == "new/file.py"
    assert normalize_numstat_path("src/{old.py => new.py}") == "new.py"


def test_language_for_path() -> None:
    assert language_for_path("Dockerfile") == "Dockerfile"
    assert language_for_path("Makefile") == "Makefile"
    assert language_for_path("src/main.py") == "Python"
    assert language_for_path("src/thing.unknownext") == "Other"


def test_dir_key_for_path() -> None:
    assert dir_key_for_path("src/app/main.py", depth=1) == "src"
    assert dir_key_for_path("src/app/main.py", depth=2) == "src/app"
    assert dir_key_for_path("file.py", depth=1) == "(root)"


def test_should_exclude_path_prefixes_and_globs() -> None:
    assert should_exclude_path("vendor/lib.c", ["vendor"], []) is True
    assert should_exclude_path("src/vendor/lib.c", ["vendor"], []) is True
    assert should_exclude_path("src/app.py", [], ["*.py"]) is True
    assert should_exclude_path("src/app.js", [], ["*.py"]) is False

