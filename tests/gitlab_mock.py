import collections.abc
import dataclasses
import typing
from urllib.parse import quote

import httpx
import respx


ENDPOINT: typing.Final = "https://gitlab.example.test"
API: typing.Final = f"{ENDPOINT}/api/v4"
JsonList: typing.TypeAlias = list[dict[str, typing.Any]]


def commit(sha: str, title: str, *, date: str, message: str | None = None) -> dict[str, typing.Any]:
    return {
        "id": sha,
        "short_id": sha[:8],
        "title": title,
        "message": message if message is not None else title,
        "author_name": "Dev",
        "committed_date": date,
        "web_url": f"{ENDPOINT}/team/svc/-/commit/{sha}",
    }


def merge_request(iid: int, title: str, **fields: typing.Any) -> dict[str, typing.Any]:  # noqa: ANN401
    return {
        "iid": iid,
        "title": title,
        "description": None,
        "source_branch": f"branch-{iid}",
        "target_branch": "main",
        "state": "merged",
        "web_url": f"{ENDPOINT}/team/svc/-/merge_requests/{iid}",
        "merged_at": "2026-09-20T10:00:00Z",
        "author": {"username": "dev", "name": "Dev"},
        **fields,
    }


def pipeline(pipeline_id: int, sha: str, ref: str, status: str) -> dict[str, typing.Any]:
    return {
        "id": pipeline_id,
        "sha": sha,
        "ref": ref,
        "status": status,
        "web_url": f"{ENDPOINT}/team/svc/-/pipelines/{pipeline_id}",
        "updated_at": f"2026-09-2{pipeline_id % 10}T00:00:00Z",
    }


def job(name: str, *, allow_failure: bool = False, **fields: typing.Any) -> dict[str, typing.Any]:  # noqa: ANN401
    return {
        "name": name,
        "stage": "test",
        "status": "failed",
        "allow_failure": allow_failure,
        "web_url": f"{ENDPOINT}/team/svc/-/jobs/{name}",
        "failure_reason": "script_failure",
        **fields,
    }


@dataclasses.dataclass(kw_only=True)
class ServiceData:
    id: int
    path: str
    default_branch: str | None = "main"
    deployments: dict[str, dict[str, typing.Any]] = dataclasses.field(default_factory=dict)
    commits: JsonList = dataclasses.field(default_factory=list)
    tags: JsonList = dataclasses.field(default_factory=list)
    merged_merge_requests: JsonList = dataclasses.field(default_factory=list)
    commit_merge_requests: dict[str, JsonList] = dataclasses.field(default_factory=dict)
    push_pipelines: JsonList = dataclasses.field(default_factory=list)
    tag_pipelines: dict[str, dict[str, typing.Any]] = dataclasses.field(default_factory=dict)
    failed_jobs: dict[int, JsonList] = dataclasses.field(default_factory=dict)
    failed_bridges: dict[int, JsonList] = dataclasses.field(default_factory=dict)

    def as_json(self) -> dict[str, typing.Any]:
        return {
            "id": self.id,
            "path_with_namespace": self.path,
            "web_url": f"{ENDPOINT}/{self.path}",
            "default_branch": self.default_branch,
        }


@dataclasses.dataclass(kw_only=True)
class Paging:
    per_page: int = 100


def _paged(
    items: collections.abc.Callable[[], JsonList], paging: Paging
) -> collections.abc.Callable[..., httpx.Response]:
    def respond(request: httpx.Request, **_: str) -> httpx.Response:
        page: typing.Final = int(request.url.params.get("page", "1"))
        start: typing.Final = (page - 1) * paging.per_page
        everything: typing.Final = items()
        more: typing.Final = start + paging.per_page < len(everything)
        return httpx.Response(
            200,
            json=everything[start : start + paging.per_page],
            headers={"x-next-page": str(page + 1) if more else ""},
        )

    return respond


def mock_group(router: respx.Router, group: str, services: list[ServiceData], paging: Paging) -> None:
    router.get(f"{API}/groups/{quote(group, safe='')}/projects", name=f"group:{group}").mock(
        side_effect=_paged(lambda: [service.as_json() for service in services], paging)
    )


def mock_service(router: respx.Router, data: ServiceData, paging: Paging) -> None:
    prefix: typing.Final = f"{API}/projects/{data.id}"

    def deployments(request: httpx.Request) -> httpx.Response:
        deployment = data.deployments.get(request.url.params["environment"])
        return httpx.Response(200, json=[deployment] if deployment else [])

    def pipelines(request: httpx.Request) -> httpx.Response:
        if "source" in request.url.params:
            return _paged(lambda: data.push_pipelines, paging)(request)
        tag_pipeline = data.tag_pipelines.get(request.url.params["ref"])
        return httpx.Response(200, json=[tag_pipeline] if tag_pipeline else [])

    def by_pipeline(source: dict[int, JsonList]) -> collections.abc.Callable[..., httpx.Response]:
        def respond(request: httpx.Request, pipeline_id: str) -> httpx.Response:
            return _paged(lambda: source.get(int(pipeline_id), []), paging)(request)

        return respond

    def commit_merge_requests(request: httpx.Request, sha: str) -> httpx.Response:
        return _paged(lambda: data.commit_merge_requests[sha], paging)(request)

    router.get(f"{API}/projects/{quote(data.path, safe='')}", name=f"{data.id}:project").mock(
        side_effect=lambda _: httpx.Response(200, json=data.as_json())
    )
    router.get(f"{prefix}/deployments", name=f"{data.id}:deployments").mock(side_effect=deployments)
    router.get(f"{prefix}/repository/tags", name=f"{data.id}:tags").mock(side_effect=_paged(lambda: data.tags, paging))
    router.get(
        url__regex=rf"{prefix}/repository/commits/(?P<sha>[^/]+)/merge_requests", name=f"{data.id}:commit_mrs"
    ).mock(side_effect=commit_merge_requests)
    router.get(f"{prefix}/repository/commits", name=f"{data.id}:commits").mock(
        side_effect=_paged(lambda: data.commits, paging)
    )
    router.get(f"{prefix}/merge_requests", name=f"{data.id}:merged_mrs").mock(
        side_effect=_paged(lambda: data.merged_merge_requests, paging)
    )
    router.get(url__regex=rf"{prefix}/pipelines/(?P<pipeline_id>\d+)/jobs", name=f"{data.id}:jobs").mock(
        side_effect=by_pipeline(data.failed_jobs)
    )
    router.get(url__regex=rf"{prefix}/pipelines/(?P<pipeline_id>\d+)/bridges", name=f"{data.id}:bridges").mock(
        side_effect=by_pipeline(data.failed_bridges)
    )
    router.get(f"{prefix}/pipelines", name=f"{data.id}:pipelines").mock(side_effect=pipelines)


def fail_service(router: respx.Router, data: ServiceData, status: int) -> None:
    for route in router.routes:
        if route.name and route.name.startswith(f"{data.id}:") and route.name != f"{data.id}:project":
            route.mock(side_effect=None, return_value=httpx.Response(status, json={"message": "boom"}))


def fail_everything(router: respx.Router, status: int) -> None:
    for route in router.routes:
        route.mock(side_effect=None, return_value=httpx.Response(status, json={"message": "nope"}))
