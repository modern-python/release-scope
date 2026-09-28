import collections.abc
import re
import typing


JIRA_KEY_PATTERN: typing.Final = re.compile(r"(?<![A-Za-z0-9])[A-Z][A-Z0-9]+-\d+(?![A-Z0-9])")


def extract_jira_keys(
    texts: collections.abc.Iterable[str | None],
    *,
    allowed_projects: collections.abc.Collection[str] = (),
) -> list[str]:
    keys: dict[str, None] = {}
    for text in texts:
        if not text:
            continue
        for key in JIRA_KEY_PATTERN.findall(text):
            if allowed_projects and key.split("-", 1)[0] not in allowed_projects:
                continue
            keys[key] = None
    return list(keys)
