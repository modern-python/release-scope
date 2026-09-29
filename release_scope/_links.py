import re
import typing

from release_scope._report import LinkedChange


_CHANGE_PATH: typing.Final = re.compile(
    r"(?P<project>[^?#]+?)/-/(?:merge_requests/(?P<iid>\d+)|commit/(?P<sha>[0-9a-fA-F]{7,64}))(?:[/?#].*)?"
)


def parse_gitlab_link(url: str | None, gitlab_endpoint: str) -> LinkedChange | None:
    base: typing.Final = gitlab_endpoint.rstrip("/") + "/"
    if not url or not url.startswith(base):
        return None
    match: typing.Final = _CHANGE_PATH.fullmatch(url.removeprefix(base))
    if match is None:
        return None
    project: typing.Final = match["project"]
    iid: typing.Final = match["iid"]
    return LinkedChange(
        kind="merge_request" if iid else "commit",
        project=project,
        project_url=base + project,
        url=url,
        iid=int(iid) if iid else None,
        sha=match["sha"],
    )
