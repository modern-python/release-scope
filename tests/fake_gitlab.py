import dataclasses
import typing
from urllib.parse import parse_qs, unquote

import httpware
import httpx2


ENDPOINT: typing.Final = "https://gitlab.example.test"
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
class FakeProject:
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
    fail_with: int | None = None

    def as_json(self) -> dict[str, typing.Any]:
        return {
            "id": self.id,
            "path_with_namespace": self.path,
            "web_url": f"{ENDPOINT}/{self.path}",
            "default_branch": self.default_branch,
        }


@dataclasses.dataclass(kw_only=True)
class FakeGitLab:
    projects: list[FakeProject]
    groups: dict[str, list[int]] = dataclasses.field(default_factory=dict)
    per_page: int = 100
    status_override: int | None = None
    requests: list[str] = dataclasses.field(default_factory=list)

    def client(self) -> httpware.Client:
        return httpware.Client(httpx2_client=httpx2.Client(transport=httpx2.MockTransport(self), base_url=ENDPOINT))

    def paths(self) -> list[str]:
        return [item.split("?", 1)[0] for item in self.requests]

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        raw: typing.Final = request.url.raw_path.decode()
        self.requests.append(raw)
        if self.status_override is not None:
            return httpx2.Response(self.status_override, json={"message": "nope"})
        path, _, query = raw.partition("?")
        params: typing.Final = {key: values[0] for key, values in parse_qs(query).items()}
        parts: typing.Final = [unquote(part) for part in path.removeprefix("/api/v4/").split("/")]
        if parts[0] == "groups":
            members = [project.as_json() for project in self.projects if project.id in self.groups[parts[1]]]
            return self._page(members, params)
        project = next(
            (item for item in self.projects if parts[1] in {str(item.id), item.path}),
            None,
        )
        if project is None:
            return httpx2.Response(404, json={"message": "404 Project Not Found"})
        if project.fail_with is not None and len(parts) > 2:
            return httpx2.Response(project.fail_with, json={"message": "boom"})
        return self._route(project, parts[2:], params)

    def _route(self, project: FakeProject, rest: list[str], params: dict[str, str]) -> httpx2.Response:  # noqa: C901, PLR0911
        match rest:
            case []:
                return httpx2.Response(200, json=project.as_json())
            case ["deployments"]:
                deployment = project.deployments.get(params["environment"])
                return httpx2.Response(200, json=[deployment] if deployment else [])
            case ["repository", "tags"]:
                return self._page(project.tags, params)
            case ["repository", "commits"]:
                return self._page(project.commits, params)
            case ["repository", "commits", sha, "merge_requests"]:
                return self._page(project.commit_merge_requests.get(sha, []), params)
            case ["merge_requests"]:
                return self._page(project.merged_merge_requests, params)
            case ["pipelines"] if "source" in params:
                return self._page(project.push_pipelines, params)
            case ["pipelines"]:
                tag_pipeline = project.tag_pipelines.get(params["ref"])
                return httpx2.Response(200, json=[tag_pipeline] if tag_pipeline else [])
            case ["pipelines", pipeline_id, "jobs"]:
                return self._page(project.failed_jobs.get(int(pipeline_id), []), params)
            case ["pipelines", pipeline_id, "bridges"]:
                return self._page(project.failed_bridges.get(int(pipeline_id), []), params)
            case _:
                return httpx2.Response(404, json={"message": "404 Not Found"})

    def _page(self, items: JsonList, params: dict[str, str]) -> httpx2.Response:
        page: typing.Final = int(params.get("page", "1"))
        start: typing.Final = (page - 1) * self.per_page
        headers: typing.Final = {"x-next-page": str(page + 1) if start + self.per_page < len(items) else ""}
        return httpx2.Response(200, json=items[start : start + self.per_page], headers=headers)
