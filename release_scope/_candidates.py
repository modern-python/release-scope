import collections.abc
import re
import typing
from urllib.parse import quote, urlencode

from release_scope._report import Candidate, EnvironmentState, Service, Untagged


_VERSION_PATTERN: typing.Final = re.compile(r"(v?)(\d+)\.(\d+)\.(\d+)")


def build_candidates(service: Service, production: EnvironmentState | None) -> list[Candidate]:
    base: str | None = None
    if production is not None:
        base = quote(production.ref if production.tag else production.sha)
    candidates: list[Candidate] = []
    for index, row in enumerate(service.rows):
        shipped = service.rows[index:]
        keys = {key.key: key for item in shipped if item.in_scope for key in item.jira_keys}
        candidates.extend(
            Candidate(
                tag=tag,
                compare_url=f"{service.project_url}/-/compare/{base}...{quote(tag.name)}"
                if base
                else f"{service.project_url}/-/commits/{quote(tag.name)}",
                rows=len(shipped),
                jira_keys=list(keys.values()),
            )
            for tag in row.tags
        )
    return candidates


def build_untagged(service: Service, tag_names: collections.abc.Iterable[str]) -> Untagged | None:
    rows: typing.Final = next((index for index, row in enumerate(service.rows) if row.tags), len(service.rows))
    if not rows:
        return None
    head_sha: typing.Final = service.rows[0].commits[0].sha
    next_tag: typing.Final = _next_minor(tag_names)
    query: typing.Final = urlencode({"tag_name": next_tag, "ref": head_sha} if next_tag else {"ref": head_sha})
    return Untagged(
        rows=rows, head_sha=head_sha, next_tag=next_tag, create_url=f"{service.project_url}/-/tags/new?{query}"
    )


def _next_minor(tag_names: collections.abc.Iterable[str]) -> str | None:
    versions: typing.Final = [match for name in tag_names if (match := _VERSION_PATTERN.fullmatch(name))]
    if not versions:
        return None
    highest: typing.Final = max(versions, key=lambda match: tuple(int(part) for part in match.groups()[1:]))
    prefix, major, minor, _ = highest.groups()
    return f"{prefix}{major}.{int(minor) + 1}.0"
