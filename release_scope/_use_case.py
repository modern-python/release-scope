import collections.abc
import dataclasses
import datetime as dt
import http
import typing
from urllib.parse import quote

from release_scope._cache import Cache, CachedPipeline
from release_scope._candidates import build_candidates
from release_scope._errors import AuthError, ConfigError, GitLabError, JiraError
from release_scope._gitlab import Commit, Deployment, GitLabApi, MergeRequest, Pipeline, Project
from release_scope._jira import JiraApi
from release_scope._jira_keys import extract_jira_keys
from release_scope._links import parse_gitlab_link
from release_scope._messages import (
    commits_truncated,
    explain_failure,
    merged_elsewhere,
    no_default_branch,
    no_production,
    skip_reason,
    tags_truncated,
)
from release_scope._report import (
    CommitRef,
    EnvironmentState,
    FailedJob,
    JiraIssue,
    JiraKeyRef,
    JiraState,
    LinkedChange,
    MergeRequestRef,
    Message,
    PipelineState,
    Release,
    Report,
    Row,
    Service,
    TagRef,
)
from release_scope._rows import RowDraft, group_rows, match_merge_requests
from release_scope._settings import Settings


_SETTLED_PIPELINE_STATUSES: typing.Final = frozenset({"success", "failed", "canceled", "skipped"})


def _resolution_error(error: GitLabError, target: str) -> Exception:
    if error.status == http.HTTPStatus.FORBIDDEN:
        return AuthError(
            f"GitLab denied access to {target} (403). "
            "Check that the token has the 'read_api' scope and that its user can see it."
        )
    return error


def _environment_state(name: str, deployment: Deployment) -> EnvironmentState:
    return EnvironmentState(
        name=name,
        ref=deployment.ref,
        sha=deployment.sha,
        deployed_at=deployment.created_at,
        deployment_url=deployment.deployable.web_url if deployment.deployable else None,
        tag=deployment.deployable.tag if deployment.deployable else False,
    )


def _merge_request_ref(merge_request: MergeRequest) -> MergeRequestRef:
    author: typing.Final = merge_request.author
    return MergeRequestRef(
        iid=merge_request.iid,
        title=merge_request.title,
        url=merge_request.web_url,
        author=(author.username or author.name) if author else None,
        merged_at=merge_request.merged_at,
    )


def _commit_ref(commit: Commit) -> CommitRef:
    return CommitRef(
        sha=commit.id,
        short_sha=commit.short_id,
        title=commit.title,
        url=commit.web_url,
        author=commit.author_name,
        committed_at=commit.committed_date,
    )


def _row_keys(services: list[Service]) -> list[str]:
    return sorted({key.key for service in services for row in service.rows if row.in_scope for key in row.jira_keys})


@dataclasses.dataclass(slots=True, kw_only=True)
class _Walk:
    truncated: bool
    drafts: list[RowDraft] = dataclasses.field(default_factory=list)
    tags_by_sha: dict[str, list[str]] = dataclasses.field(default_factory=dict)
    main_pipelines: dict[str, Pipeline] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class _LinkTarget:
    merged: set[int]
    shas: list[str]
    pending: list[MergeRequestRef]
    warnings: list[Message]

    def matches(self, draft: RowDraft) -> bool:
        return any(item.iid in self.merged for item in draft.merge_requests) or any(
            commit.id.startswith(sha) for commit in draft.commits for sha in self.shas
        )


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class CollectUseCase:
    api: GitLabApi
    jira: JiraApi | None
    settings: Settings

    def __call__(
        self,
        *,
        groups: collections.abc.Sequence[str],
        projects: collections.abc.Sequence[str],
        include_subgroups: bool,
        cache: Cache,
    ) -> Report:
        services: typing.Final = [
            self._collect_or_explain(project, cache, links=None)
            for project in self._resolve_projects(groups=groups, projects=projects, include_subgroups=include_subgroups)
        ]
        return Report(
            collected_at=dt.datetime.now(dt.UTC),
            production_environment=self.settings.production_environment,
            services=services,
            jira=self._read_issues(self.jira, _row_keys(services)) if self.jira else None,
        )

    def for_issues(self, *, keys: collections.abc.Sequence[str], cache: Cache) -> Report:
        if self.jira is None:
            msg = "--jira needs RELEASE_SCOPE_JIRA_ENDPOINT and RELEASE_SCOPE_JIRA_TOKEN."
            raise ConfigError(msg)
        state: typing.Final = self._read_issues(self.jira, keys)
        services: typing.Final[list[Service]] = []
        if state.error is None:
            links_by_project: dict[str, list[LinkedChange]] = {}
            for key in keys:
                issue = state.issues.get(key)
                for link in issue.links if issue else []:
                    links_by_project.setdefault(link.project, []).append(link)
            services.extend(
                self._scoped_service(path, links_by_project[path], cache) for path in sorted(links_by_project)
            )
            row_state: typing.Final = self._read_issues(self.jira, sorted(set(_row_keys(services)) - set(keys)))
            state.issues.update(row_state.issues)
            state.missing.extend(row_state.missing)
            state.error = row_state.error
        return Report(
            collected_at=dt.datetime.now(dt.UTC),
            production_environment=self.settings.production_environment,
            services=services,
            jira=state,
            jira_scope=list(keys),
        )

    def _scoped_service(self, path: str, links: list[LinkedChange], cache: Cache) -> Service:
        try:
            project: typing.Final = self.api.get_project(path)
        except GitLabError as exc:
            project_url: typing.Final = links[0].project_url
            return Service(project=path, project_url=project_url, error=explain_failure(path, project_url, exc))
        return self._collect_or_explain(project, cache, links=links)

    def _collect_or_explain(self, project: Project, cache: Cache, *, links: list[LinkedChange] | None) -> Service:
        try:
            return self._collect_service(project, cache, links=links)
        except GitLabError as exc:
            cache.keep_project(project.id)
            return Service(
                project=project.path_with_namespace,
                project_url=project.web_url,
                error=explain_failure(project.path_with_namespace, project.web_url, exc),
            )

    def _read_issues(self, jira: JiraApi, keys: collections.abc.Sequence[str]) -> JiraState:
        state: typing.Final = JiraState()
        if not keys:
            return state
        try:
            issues: typing.Final = {issue.key: issue for issue in jira.search_issues(keys)}
        except JiraError as exc:
            state.error = exc.message
            return state
        for key in keys:
            issue = issues.get(key)
            if issue is None:
                state.missing.append(key)
                continue
            fields = issue.fields
            state.issues[key] = JiraIssue(
                key=key,
                summary=fields.summary,
                status=fields.status.name,
                status_category=fields.status.category.key if fields.status.category else None,
                issue_type=fields.issuetype.name if fields.issuetype else None,
                url=self._jira_url(key),
            )
        try:
            for key, issue in state.issues.items():
                issue.links = self._linked_changes(jira, key)
        except JiraError as exc:
            state.error = exc.message
        return state

    def _linked_changes(self, jira: JiraApi, key: str) -> list[LinkedChange]:
        changes: typing.Final[dict[str, LinkedChange]] = {}
        for link in jira.remote_links(key):
            change = parse_gitlab_link(link.target.url if link.target else None, self.settings.gitlab.endpoint)
            if change is not None:
                changes.setdefault(change.url, change)
        return list(changes.values())

    def _resolve_projects(
        self,
        *,
        groups: collections.abc.Sequence[str],
        projects: collections.abc.Sequence[str],
        include_subgroups: bool,
    ) -> list[Project]:
        resolved: dict[int, Project] = {}
        for group in groups:
            try:
                listed = self.api.list_group_projects(group, include_subgroups=include_subgroups)
            except GitLabError as exc:
                raise _resolution_error(exc, f"group '{group}'") from exc
            resolved.update((project.id, project) for project in listed)
        for path in projects:
            try:
                project = self.api.get_project(path)
            except GitLabError as exc:
                raise _resolution_error(exc, f"project '{path}'") from exc
            resolved[project.id] = project
        return sorted(resolved.values(), key=lambda item: item.path_with_namespace)

    def _collect_service(self, project: Project, cache: Cache, *, links: list[LinkedChange] | None) -> Service:
        cache.visit(project.id)
        service: typing.Final = Service(
            project=project.path_with_namespace, project_url=project.web_url, default_branch=project.default_branch
        )
        reason: typing.Final = skip_reason(project)
        if reason is not None:
            service.warnings.append(reason)
            return service
        for name in self.settings.environments:
            deployment = self.api.latest_deployment(project.id, name)
            if deployment is not None:
                service.environments.append(_environment_state(name, deployment))
        production: typing.Final = next(
            (item for item in service.environments if item.name == self.settings.production_environment), None
        )
        if project.default_branch is None:
            service.warnings.append(no_default_branch())
            return service
        if production is None:
            service.warnings.append(no_production(self.settings.production_environment, project.default_branch))

        walk: typing.Final = self._walk(
            project, project.default_branch, production.sha if production else None, service, cache
        )
        drafts, linked, in_scope = walk.drafts, [False] * len(walk.drafts), [True] * len(walk.drafts)
        if links is not None:
            drafts, linked, in_scope = self._scope_rows(project, project.default_branch, service, walk, links, cache)
        service.rows.extend(
            self._build_row(
                project=project,
                draft=draft,
                tags_by_sha=walk.tags_by_sha,
                main_pipelines=walk.main_pipelines,
                environments=service.environments,
                cache=cache,
            ).model_copy(update={"linked": is_linked, "in_scope": is_in_scope})
            for draft, is_linked, is_in_scope in zip(drafts, linked, in_scope, strict=True)
        )
        service.candidates.extend(build_candidates(service, production))
        return service

    def _walk(
        self, project: Project, default_branch: str, baseline: str | None, service: Service, cache: Cache
    ) -> _Walk:
        commits, truncated = self.api.list_first_parent_commits(
            project.id,
            f"{baseline}..{default_branch}" if baseline else default_branch,
            max_items=self.settings.max_commits,
        )
        walk: typing.Final = _Walk(truncated=truncated)
        service.truncated = truncated
        if truncated:
            service.warnings.append(commits_truncated(self.settings.max_commits))
        if not commits:
            return walk
        since: typing.Final = min(commit.committed_date for commit in commits)
        walk.drafts = group_rows(commits, self._commit_merge_requests(project, default_branch, commits, since, cache))
        tags, tag_list_cut = self.api.list_tags(project.id)
        if tag_list_cut:
            service.warnings.append(tags_truncated())
        for tag in tags:
            walk.tags_by_sha.setdefault(tag.commit.id, []).append(tag.name)
        walk.main_pipelines = self._latest_by_sha(
            self.api.list_push_pipelines(project.id, ref=default_branch, updated_after=since)
        )
        return walk

    def _scope_rows(  # noqa: PLR0913, PLR0917
        self,
        project: Project,
        default_branch: str,
        service: Service,
        walk: _Walk,
        links: list[LinkedChange],
        cache: Cache,
    ) -> tuple[list[RowDraft], list[bool], list[bool]]:
        target: typing.Final = self._link_target(project, default_branch, links, cache)
        service.warnings.extend(target.warnings)
        index: typing.Final = next(
            (position for position, draft in enumerate(walk.drafts) if target.matches(draft)), None
        )
        service.release = self._release(project, target, walk, index, cache)
        if index is None:
            return [], [], []
        return (
            walk.drafts,
            [target.matches(draft) for draft in walk.drafts],
            [position >= index for position in range(len(walk.drafts))],
        )

    def _link_target(
        self, project: Project, default_branch: str, links: list[LinkedChange], cache: Cache
    ) -> _LinkTarget:
        merged: typing.Final[set[int]] = set()
        pending: typing.Final[list[MergeRequestRef]] = []
        warnings: typing.Final[list[Message]] = []
        for link in links:
            if link.iid is None:
                continue
            merge_request = self._linked_merge_request(project, link.iid, cache)
            if merge_request.state != "merged":
                pending.append(_merge_request_ref(merge_request))
            elif merge_request.target_branch != default_branch:
                warnings.append(merged_elsewhere(merge_request.iid, merge_request.target_branch, default_branch))
            else:
                merged.add(merge_request.iid)
        return _LinkTarget(
            merged=merged, shas=[link.sha for link in links if link.sha], pending=pending, warnings=warnings
        )

    def _linked_merge_request(self, project: Project, iid: int, cache: Cache) -> MergeRequest:
        cached: typing.Final = cache.get_merge_request(project.id, iid)
        if cached is not None:
            return cached
        merge_request: typing.Final = self.api.get_merge_request(project.id, iid)
        if merge_request.state == "merged":
            cache.put_merge_request(project.id, merge_request)
        return merge_request

    def _release(self, project: Project, target: _LinkTarget, walk: _Walk, index: int | None, cache: Cache) -> Release:
        if index is None:
            if target.merged and not walk.truncated:
                state: typing.Literal["in_production", "not_merged", "not_found"] = "in_production"
            elif target.pending and not target.merged:
                state = "not_merged"
            else:
                state = "not_found"
            return Release(state=state, pending_merge_requests=target.pending)
        tag_name: typing.Final = next(
            (
                names[-1]
                for draft in reversed(walk.drafts[: index + 1])
                if (names := [name for commit in draft.commits for name in walk.tags_by_sha.get(commit.id, [])])
            ),
            None,
        )
        return Release(
            state="pending",
            tag=self._tag_ref(project, tag_name, cache) if tag_name else None,
            pending_merge_requests=target.pending,
        )

    def _commit_merge_requests(
        self, project: Project, default_branch: str, commits: list[Commit], since: dt.datetime, cache: Cache
    ) -> dict[str, list[MergeRequest]]:
        merged: typing.Final = self.api.list_merged_merge_requests(
            project.id, target_branch=default_branch, updated_after=since
        )
        matched: typing.Final = match_merge_requests(commits, merged)
        for commit in commits:
            if commit.id in matched:
                continue
            cached = cache.get_commit_merge_requests(project.id, commit.id)
            if cached is None:
                cached = [
                    item
                    for item in self.api.commit_merge_requests(project.id, commit.id)
                    if item.state == "merged" and item.target_branch == default_branch
                ]
                cache.put_commit_merge_requests(project.id, commit.id, cached)
            if cached:
                matched[commit.id] = cached
        return matched

    @staticmethod
    def _latest_by_sha(pipelines: list[Pipeline]) -> dict[str, Pipeline]:
        latest: dict[str, Pipeline] = {}
        for pipeline in pipelines:
            if pipeline.sha not in latest or pipeline.id > latest[pipeline.sha].id:
                latest[pipeline.sha] = pipeline
        return latest

    def _build_row(  # noqa: PLR0913
        self,
        *,
        project: Project,
        draft: RowDraft,
        tags_by_sha: dict[str, list[str]],
        main_pipelines: dict[str, Pipeline],
        environments: list[EnvironmentState],
        cache: Cache,
    ) -> Row:
        shas: typing.Final = {commit.id for commit in draft.commits}
        if draft.merge_requests:
            texts: list[str | None] = []
            for merge_request in draft.merge_requests:
                texts.extend((merge_request.title, merge_request.source_branch, merge_request.description))
        else:
            texts = [commit.message or commit.title for commit in draft.commits]
        head_pipeline: typing.Final = main_pipelines.get(draft.commits[0].id)
        return Row(
            kind="merge_request" if draft.merge_requests else "commit",
            tags=[
                self._tag_ref(project, name, cache)
                for commit in draft.commits
                for name in tags_by_sha.get(commit.id, [])
            ],
            merge_requests=[_merge_request_ref(item) for item in draft.merge_requests],
            commits=[_commit_ref(commit) for commit in draft.commits],
            jira_keys=[
                JiraKeyRef(key=key, url=self._jira_url(key))
                for key in extract_jira_keys(texts, allowed_projects=self.settings.jira_project_keys)
            ],
            environments=[item.name for item in environments if item.sha in shas],
            main_pipeline=self._pipeline_state(project, head_pipeline, cache) if head_pipeline else None,
        )

    def _tag_ref(self, project: Project, name: str, cache: Cache) -> TagRef:
        pipeline: typing.Final = self.api.latest_pipeline(project.id, ref=name)
        return TagRef(
            name=name,
            url=f"{project.web_url}/-/tags/{quote(name, safe='')}",
            pipeline=self._pipeline_state(project, pipeline, cache) if pipeline else None,
        )

    def _jira_url(self, key: str) -> str | None:
        if not self.settings.jira_endpoint:
            return None
        return f"{self.settings.jira_endpoint.rstrip('/')}/browse/{key}"

    def _pipeline_state(self, project: Project, pipeline: Pipeline, cache: Cache) -> PipelineState:
        failed_jobs = cache.get_failed_jobs(project.id, pipeline.id, pipeline.updated_at)
        if failed_jobs is None:
            failed_jobs = self._fetch_failed_jobs(project, pipeline)
            if pipeline.status in _SETTLED_PIPELINE_STATUSES:
                cache.put_failed_jobs(
                    project.id, pipeline.id, CachedPipeline(updated_at=pipeline.updated_at, failed_jobs=failed_jobs)
                )
        return PipelineState(id=pipeline.id, status=pipeline.status, url=pipeline.web_url, failed_jobs=failed_jobs)

    def _fetch_failed_jobs(self, project: Project, pipeline: Pipeline) -> list[FailedJob]:
        failed: typing.Final = [
            FailedJob(
                kind="job",
                name=job.name,
                stage=job.stage,
                status=job.status,
                allow_failure=job.allow_failure,
                url=job.web_url,
                failure_reason=job.failure_reason,
            )
            for job in self.api.failed_jobs(project.id, pipeline.id)
        ]
        failed.extend(
            FailedJob(
                kind="bridge",
                name=bridge.name,
                stage=bridge.stage,
                status=bridge.status,
                allow_failure=bridge.allow_failure,
                url=bridge.web_url,
                failure_reason=bridge.failure_reason,
                downstream_pipeline_url=bridge.downstream_pipeline.web_url if bridge.downstream_pipeline else None,
            )
            for bridge in self.api.failed_bridges(project.id, pipeline.id)
        )
        return failed
