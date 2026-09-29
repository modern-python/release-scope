import dataclasses
import pathlib
import typing

import pydantic

from release_scope._files import write_text_atomic
from release_scope._gitlab import MergeRequest
from release_scope._report import FailedJob


CACHE_SCHEMA_VERSION: typing.Final = 1

_EntryT = typing.TypeVar("_EntryT")


class CachedPipeline(pydantic.BaseModel):
    updated_at: str
    failed_jobs: list[FailedJob]


class CacheData(pydantic.BaseModel):
    schema_version: typing.Literal[1] = CACHE_SCHEMA_VERSION
    commit_merge_requests: dict[str, dict[str, list[MergeRequest]]] = pydantic.Field(default_factory=dict)
    pipelines: dict[str, dict[str, CachedPipeline]] = pydantic.Field(default_factory=dict)
    merge_requests: dict[str, dict[str, MergeRequest]] = pydantic.Field(default_factory=dict)


@dataclasses.dataclass(slots=True, kw_only=True)
class Cache:
    previous: CacheData = dataclasses.field(default_factory=CacheData)
    current: CacheData = dataclasses.field(default_factory=CacheData)
    visited: set[str] = dataclasses.field(default_factory=set)

    @classmethod
    def load(cls, path: pathlib.Path) -> tuple["Cache", str | None]:
        if not path.exists():
            return cls(), None
        try:
            return cls(previous=CacheData.model_validate_json(path.read_bytes())), None
        except (OSError, pydantic.ValidationError) as exc:
            return cls(), f"Ignoring unreadable cache {path}: {type(exc).__name__}."

    def save(self, path: pathlib.Path) -> None:
        write_text_atomic(path, self.pruned().model_dump_json(indent=2))

    def visit(self, project_id: int) -> None:
        self.visited.add(str(project_id))

    def pruned(self) -> CacheData:
        return CacheData(
            commit_merge_requests=self._unvisited(self.previous.commit_merge_requests)
            | self.current.commit_merge_requests,
            pipelines=self._unvisited(self.previous.pipelines) | self.current.pipelines,
            merge_requests=self._unvisited(self.previous.merge_requests) | self.current.merge_requests,
        )

    def _unvisited(self, entries: dict[str, _EntryT]) -> dict[str, _EntryT]:
        return {project: entry for project, entry in entries.items() if project not in self.visited}

    def get_merge_request(self, project_id: int, iid: int) -> MergeRequest | None:
        cached = self.previous.merge_requests.get(str(project_id), {}).get(str(iid))
        if cached is not None:
            self.put_merge_request(project_id, cached)
        return cached

    def put_merge_request(self, project_id: int, merge_request: MergeRequest) -> None:
        self.current.merge_requests.setdefault(str(project_id), {})[str(merge_request.iid)] = merge_request

    def get_commit_merge_requests(self, project_id: int, sha: str) -> list[MergeRequest] | None:
        cached = self.previous.commit_merge_requests.get(str(project_id), {}).get(sha)
        if cached is not None:
            self.put_commit_merge_requests(project_id, sha, cached)
        return cached

    def put_commit_merge_requests(self, project_id: int, sha: str, merge_requests: list[MergeRequest]) -> None:
        self.current.commit_merge_requests.setdefault(str(project_id), {})[sha] = merge_requests

    def get_failed_jobs(self, project_id: int, pipeline_id: int, updated_at: str) -> list[FailedJob] | None:
        cached = self.previous.pipelines.get(str(project_id), {}).get(str(pipeline_id))
        if cached is None or cached.updated_at != updated_at:
            return None
        self.put_failed_jobs(project_id, pipeline_id, cached)
        return cached.failed_jobs

    def put_failed_jobs(self, project_id: int, pipeline_id: int, entry: CachedPipeline) -> None:
        self.current.pipelines.setdefault(str(project_id), {})[str(pipeline_id)] = entry

    def keep_project(self, project_id: int) -> None:
        key: typing.Final = str(project_id)
        self.current.commit_merge_requests[key] = {
            **self.previous.commit_merge_requests.get(key, {}),
            **self.current.commit_merge_requests.get(key, {}),
        }
        self.current.pipelines[key] = {
            **self.previous.pipelines.get(key, {}),
            **self.current.pipelines.get(key, {}),
        }
        self.current.merge_requests[key] = {
            **self.previous.merge_requests.get(key, {}),
            **self.current.merge_requests.get(key, {}),
        }
