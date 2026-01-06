from __future__ import annotations

import dataclasses


@dataclasses.dataclass
class AuthorStats:
    name: str = ""
    email: str = ""
    commits: int = 0
    insertions: int = 0
    deletions: int = 0

    @property
    def changed(self) -> int:
        return self.insertions + self.deletions


@dataclasses.dataclass
class RepoYearStats:
    commits_total: int = 0
    insertions_total: int = 0
    deletions_total: int = 0
    commits_me: int = 0
    insertions_me: int = 0
    deletions_me: int = 0

    @property
    def changed_total(self) -> int:
        return self.insertions_total + self.deletions_total

    @property
    def changed_me(self) -> int:
        return self.insertions_me + self.deletions_me


@dataclasses.dataclass
class RepoResult:
    key: str
    path: str
    remote_name: str
    remote: str
    remote_canonical: str
    duplicates: list[str]
    first_commit_iso: str | None
    first_commit_author_name: str | None
    first_commit_author_email: str | None
    last_commit_iso: str | None
    period_stats_excl_bootstraps: dict[str, RepoYearStats]
    period_stats_bootstraps: dict[str, RepoYearStats]
    weekly_by_period_excl_bootstraps: dict[str, dict[str, dict[str, int]]]  # week_start -> {commits,insertions,deletions}
    weekly_by_period_bootstraps: dict[str, dict[str, dict[str, int]]]  # week_start -> {commits,insertions,deletions}
    authors_by_period_excl_bootstraps: dict[str, dict[str, AuthorStats]]  # email -> stats
    authors_by_period_bootstraps: dict[str, dict[str, AuthorStats]]  # email -> stats
    languages_by_period_excl_bootstraps: dict[str, dict[str, dict[str, int]]]  # language -> {insertions,deletions}
    languages_by_period_bootstraps: dict[str, dict[str, dict[str, int]]]  # language -> {insertions,deletions}
    dirs_by_period_excl_bootstraps: dict[str, dict[str, dict[str, int]]]  # dir -> {insertions,deletions,insertions_me,deletions_me}
    dirs_by_period_bootstraps: dict[str, dict[str, dict[str, int]]]  # dir -> {insertions,deletions,insertions_me,deletions_me}
    me_monthly_by_period_excl_bootstraps: dict[str, dict[str, dict[str, int]]]  # month -> {commits,insertions,deletions}
    me_monthly_by_period_bootstraps: dict[str, dict[str, dict[str, int]]]  # month -> {commits,insertions,deletions}
    me_monthly_tech_by_period_excl_bootstraps: dict[str, dict[str, dict[str, dict[str, int]]]]  # month -> tech -> {commits,insertions,deletions}
    me_monthly_tech_by_period_bootstraps: dict[str, dict[str, dict[str, dict[str, int]]]]  # month -> tech -> {commits,insertions,deletions}
    excluded_by_period: dict[str, dict[str, int]]  # counters for excluded paths
    bootstrap_commits_by_period: dict[str, list[dict[str, object]]]
    errors: list[str]


@dataclasses.dataclass(frozen=True)
class BootstrapConfig:
    changed_threshold: int = 50_000
    files_threshold: int = 200
    addition_ratio: float = 0.90

    def is_bootstrap(self, insertions: int, deletions: int, files_touched: int) -> bool:
        changed = insertions + deletions
        if changed < self.changed_threshold:
            return False
        if files_touched < self.files_threshold:
            return False
        if changed <= 0:
            return False
        ratio = insertions / changed
        return ratio >= self.addition_ratio
