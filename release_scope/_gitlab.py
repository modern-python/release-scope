import dataclasses
import datetime
import math
import typing
from urllib.parse import quote, unquote

import httpware
import pydantic

from release_scope._errors import AuthError, GitLabError


_API: typing.Final = "/api/v4"
_PER_PAGE: typing.Final = 100
_MAX_PAGES: typing.Final = 50

_ModelT = typing.TypeVar("_ModelT", bound=pydantic.BaseModel)


class Project(pydantic.BaseModel):
    id: int
    path_with_namespace: str
    web_url: str
    default_branch: str | None = None
    builds_access_level: str | None = None
    environments_access_level: str | None = None


class Deployable(pydantic.BaseModel):
    web_url: str | None = None


class Deployment(pydantic.BaseModel):
    id: int
    ref: str
    sha: str
    created_at: str
    deployable: Deployable | None = None


class TagCommit(pydantic.BaseModel):
    id: str


class Tag(pydantic.BaseModel):
    name: str
    commit: TagCommit


class Commit(pydantic.BaseModel):
    id: str
    short_id: str
    title: str
    message: str = ""
    author_name: str | None = None
    committed_date: datetime.datetime
    web_url: str | None = None


class Author(pydantic.BaseModel):
    username: str | None = None
    name: str | None = None


class MergeRequest(pydantic.BaseModel):
    iid: int
    title: str
    description: str | None = None
    source_branch: str | None = None
    target_branch: str
    state: str
    web_url: str
    sha: str | None = None
    merge_commit_sha: str | None = None
    squash_commit_sha: str | None = None
    merged_at: str | None = None
    author: Author | None = None


class Pipeline(pydantic.BaseModel):
    id: int
    sha: str
    ref: str
    status: str
    web_url: str
    updated_at: str


class Job(pydantic.BaseModel):
    name: str
    stage: str | None = None
    status: str
    allow_failure: bool = False
    web_url: str | None = None
    failure_reason: str | None = None


class DownstreamPipeline(pydantic.BaseModel):
    web_url: str | None = None


class Bridge(Job):
    downstream_pipeline: DownstreamPipeline | None = None


class _Projects(pydantic.RootModel[list[Project]]):
    pass


class _Deployments(pydantic.RootModel[list[Deployment]]):
    pass


class _Tags(pydantic.RootModel[list[Tag]]):
    pass


class _Commits(pydantic.RootModel[list[Commit]]):
    pass


class _MergeRequests(pydantic.RootModel[list[MergeRequest]]):
    pass


class _Pipelines(pydantic.RootModel[list[Pipeline]]):
    pass


class _Jobs(pydantic.RootModel[list[Job]]):
    pass


class _Bridges(pydantic.RootModel[list[Bridge]]):
    pass


Resource: typing.TypeAlias = typing.Literal[
    "group", "project", "deployments", "pipelines", "repository", "merge_requests"
]


def _translate(exc: httpware.ClientError, *, url: str, resource: Resource) -> Exception:
    if isinstance(exc, httpware.UnauthorizedError):
        return AuthError("GitLab rejected the token (401). Check that it is valid and not expired.")
    if isinstance(exc, httpware.StatusError):
        status: typing.Final = exc.response.status_code
        return GitLabError(f"GitLab returned {status} for {unquote(url)}.", resource=resource, status=status)
    reason: typing.Final = type(exc).__name__
    return GitLabError(f"GitLab request {unquote(url)} failed: {reason}.", resource=resource, reason=reason)


def _quote(value: str) -> str:
    return quote(value, safe="")


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class GitLabApi:
    http: httpware.Client

    def _get(self, url: str, params: dict[str, typing.Any], model: type[_ModelT], *, resource: Resource) -> _ModelT:
        try:
            return self.http.get(url, params=params, response_model=model)
        except httpware.ClientError as exc:
            raise _translate(exc, url=url, resource=resource) from exc

    def _pages(
        self,
        url: str,
        params: dict[str, typing.Any],
        model: type[pydantic.RootModel[list[_ModelT]]],
        *,
        resource: Resource,
        max_items: int | None = None,
    ) -> tuple[list[_ModelT], bool]:
        max_pages: typing.Final = _MAX_PAGES if max_items is None else math.ceil(max_items / _PER_PAGE)
        items: list[_ModelT] = []
        for page in range(1, max_pages + 1):
            try:
                response, batch = self.http.get_with_response(
                    url, params={**params, "per_page": _PER_PAGE, "page": page}, response_model=model
                )
            except httpware.ClientError as exc:
                raise _translate(exc, url=url, resource=resource) from exc
            items.extend(batch.root)
            if not response.headers.get("x-next-page"):
                break
        else:
            return items[:max_items], True
        if max_items is not None and len(items) > max_items:
            return items[:max_items], True
        return items, False

    def get_project(self, path: str) -> Project:
        return self._get(f"{_API}/projects/{_quote(path)}", {}, Project, resource="project")

    def list_group_projects(self, group: str, *, include_subgroups: bool) -> list[Project]:
        projects, _ = self._pages(
            f"{_API}/groups/{_quote(group)}/projects",
            {"archived": "false", "with_shared": "false", "include_subgroups": str(include_subgroups).lower()},
            _Projects,
            resource="group",
        )
        return projects

    def latest_deployment(self, project_id: int, environment: str) -> Deployment | None:
        deployments = self._get(
            f"{_API}/projects/{project_id}/deployments",
            {"environment": environment, "status": "success", "order_by": "id", "sort": "desc", "per_page": 1},
            _Deployments,
            resource="deployments",
        )
        return deployments.root[0] if deployments.root else None

    def list_tags(self, project_id: int) -> tuple[list[Tag], bool]:
        return self._pages(f"{_API}/projects/{project_id}/repository/tags", {}, _Tags, resource="repository")

    def list_first_parent_commits(
        self, project_id: int, ref_range: str, *, max_items: int
    ) -> tuple[list[Commit], bool]:
        return self._pages(
            f"{_API}/projects/{project_id}/repository/commits",
            {"ref_name": ref_range, "first_parent": "true"},
            _Commits,
            resource="repository",
            max_items=max_items,
        )

    def list_merged_merge_requests(
        self, project_id: int, *, target_branch: str, updated_after: datetime.datetime
    ) -> list[MergeRequest]:
        merge_requests, _ = self._pages(
            f"{_API}/projects/{project_id}/merge_requests",
            {"state": "merged", "target_branch": target_branch, "updated_after": updated_after.isoformat()},
            _MergeRequests,
            resource="merge_requests",
        )
        return merge_requests

    def commit_merge_requests(self, project_id: int, sha: str) -> list[MergeRequest]:
        merge_requests, _ = self._pages(
            f"{_API}/projects/{project_id}/repository/commits/{sha}/merge_requests",
            {},
            _MergeRequests,
            resource="merge_requests",
        )
        return merge_requests

    def list_push_pipelines(self, project_id: int, *, ref: str, updated_after: datetime.datetime) -> list[Pipeline]:
        pipelines, _ = self._pages(
            f"{_API}/projects/{project_id}/pipelines",
            {"ref": ref, "source": "push", "updated_after": updated_after.isoformat()},
            _Pipelines,
            resource="pipelines",
        )
        return pipelines

    def latest_pipeline(self, project_id: int, *, ref: str) -> Pipeline | None:
        pipelines = self._get(
            f"{_API}/projects/{project_id}/pipelines",
            {"ref": ref, "order_by": "id", "sort": "desc", "per_page": 1},
            _Pipelines,
            resource="pipelines",
        )
        return pipelines.root[0] if pipelines.root else None

    def failed_jobs(self, project_id: int, pipeline_id: int) -> list[Job]:
        jobs, _ = self._pages(
            f"{_API}/projects/{project_id}/pipelines/{pipeline_id}/jobs",
            {"scope[]": "failed"},
            _Jobs,
            resource="pipelines",
        )
        return jobs

    def failed_bridges(self, project_id: int, pipeline_id: int) -> list[Bridge]:
        # `trigger_jobs` replaces this route only from GitLab 19.2; older instances have `bridges` alone.
        bridges, _ = self._pages(
            f"{_API}/projects/{project_id}/pipelines/{pipeline_id}/bridges",
            {"scope[]": "failed"},
            _Bridges,
            resource="pipelines",
        )
        return bridges
