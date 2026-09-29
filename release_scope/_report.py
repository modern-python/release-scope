import datetime
import typing

import pydantic


SCHEMA_VERSION: typing.Final = 2


class FailedJob(pydantic.BaseModel):
    kind: typing.Literal["job", "bridge"]
    name: str
    stage: str | None
    status: str
    allow_failure: bool
    url: str | None
    failure_reason: str | None
    downstream_pipeline_url: str | None = None


class PipelineState(pydantic.BaseModel):
    id: int
    status: str
    url: str
    failed_jobs: list[FailedJob]


class TagRef(pydantic.BaseModel):
    name: str
    url: str
    pipeline: PipelineState | None


class MergeRequestRef(pydantic.BaseModel):
    iid: int
    title: str
    url: str
    author: str | None
    merged_at: str | None


class CommitRef(pydantic.BaseModel):
    sha: str
    short_sha: str
    title: str
    url: str | None
    author: str | None
    committed_at: datetime.datetime


class JiraKeyRef(pydantic.BaseModel):
    key: str
    url: str | None


class Row(pydantic.BaseModel):
    kind: typing.Literal["merge_request", "commit"]
    tags: list[TagRef]
    merge_requests: list[MergeRequestRef]
    commits: list[CommitRef]
    jira_keys: list[JiraKeyRef]
    environments: list[str]
    main_pipeline: PipelineState | None


class EnvironmentState(pydantic.BaseModel):
    name: str
    ref: str
    sha: str
    deployed_at: str
    deployment_url: str | None


class Service(pydantic.BaseModel):
    project: str
    project_url: str
    default_branch: str | None = None
    environments: list[EnvironmentState] = pydantic.Field(default_factory=list)
    rows: list[Row] = pydantic.Field(default_factory=list)
    warnings: list[str] = pydantic.Field(default_factory=list)
    error: str | None = None


class LinkedChange(pydantic.BaseModel):
    kind: typing.Literal["merge_request", "commit"]
    project: str
    project_url: str
    url: str
    iid: int | None = None
    sha: str | None = None


class JiraIssue(pydantic.BaseModel):
    key: str
    summary: str
    status: str
    status_category: str | None
    issue_type: str | None
    links: list[LinkedChange] = pydantic.Field(default_factory=list)


class JiraState(pydantic.BaseModel):
    issues: dict[str, JiraIssue] = pydantic.Field(default_factory=dict)
    missing: list[str] = pydantic.Field(default_factory=list)
    error: str | None = None


class Report(pydantic.BaseModel):
    schema_version: typing.Literal[2] = SCHEMA_VERSION
    collected_at: datetime.datetime
    production_environment: str
    services: list[Service]
    jira: JiraState | None = None
