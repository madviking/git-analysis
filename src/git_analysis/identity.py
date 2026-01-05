from __future__ import annotations

import dataclasses
import fnmatch


def normalize_email(email: str) -> str:
    return email.strip().lower()


def normalize_name(name: str) -> str:
    return name.strip().casefold()


def normalize_github_username(username: str) -> str:
    return username.strip().lstrip("@").casefold()


def github_username_from_email(email: str) -> str:
    """
    Extract GitHub username from GitHub noreply patterns:
      - username@users.noreply.github.com
      - 123456+username@users.noreply.github.com
    Returns normalized username or "".
    """
    e = normalize_email(email)
    if not e:
        return ""
    if not e.endswith("@users.noreply.github.com"):
        return ""
    local = e.split("@", 1)[0]
    if "+" in local:
        local = local.rsplit("+", 1)[-1]
    return normalize_github_username(local)


@dataclasses.dataclass(frozen=True)
class MeMatcher:
    emails: frozenset[str]
    names: frozenset[str]
    email_globs: tuple[str, ...] = ()
    name_globs: tuple[str, ...] = ()
    github_usernames: frozenset[str] = frozenset()

    def matches(self, author_name: str, author_email: str) -> bool:
        email = normalize_email(author_email)
        if email and email in self.emails:
            return True
        name = normalize_name(author_name)
        if name and name in self.names:
            return True
        gh = github_username_from_email(email) if email else ""
        if gh and gh in self.github_usernames:
            return True
        if name and name in self.github_usernames:
            return True
        if email:
            for pat in self.email_globs:
                if fnmatch.fnmatch(email, pat):
                    return True
        if name:
            for pat in self.name_globs:
                if fnmatch.fnmatch(name, pat):
                    return True
        return False

