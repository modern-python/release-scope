import collections.abc
import dataclasses
import datetime as dt
import typing

from release_scope._gitlab import Commit, MergeRequest


@dataclasses.dataclass(slots=True, kw_only=True)
class RowDraft:
    commits: list[Commit]
    merge_requests: list[MergeRequest]


def match_merge_requests(
    commits: collections.abc.Sequence[Commit],
    merge_requests: collections.abc.Iterable[MergeRequest],
) -> dict[str, list[MergeRequest]]:
    by_sha: dict[str, dict[int, MergeRequest]] = {}
    for merge_request in merge_requests:
        for sha in (merge_request.merge_commit_sha, merge_request.squash_commit_sha, merge_request.sha):
            if sha:
                by_sha.setdefault(sha, {})[merge_request.iid] = merge_request
    return {commit.id: list(by_sha[commit.id].values()) for commit in commits if commit.id in by_sha}


def group_rows(
    commits: collections.abc.Sequence[Commit],
    commit_merge_requests: collections.abc.Mapping[str, collections.abc.Sequence[MergeRequest]],
) -> list[RowDraft]:
    rows: dict[tuple[object, ...], RowDraft] = {}
    for commit in commits:
        merge_requests = sorted(commit_merge_requests.get(commit.id, ()), key=lambda item: item.iid)
        key: tuple[object, ...] = (
            tuple(item.iid for item in merge_requests) if merge_requests else ("commit", commit.id)
        )
        row = rows.setdefault(key, RowDraft(commits=[], merge_requests=list(merge_requests)))
        row.commits.append(commit)
    return list(rows.values())


def first_deployed(
    drafts: collections.abc.Sequence[RowDraft], deployments: collections.abc.Iterable[tuple[str, dt.datetime]]
) -> list[dt.datetime | None]:
    positions: typing.Final = {commit.id: index for index, draft in enumerate(drafts) for commit in draft.commits}
    earliest: typing.Final[list[dt.datetime | None]] = [None] * len(drafts)
    for sha, finished_at in deployments:
        if sha not in positions:
            continue
        for index in range(positions[sha], len(drafts)):
            current = earliest[index]
            if current is None or finished_at < current:
                earliest[index] = finished_at
    return earliest
