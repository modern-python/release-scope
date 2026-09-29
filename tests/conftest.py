import typing

import pytest
import respx

from tests.payloads import (
    API,
    COMMIT_MERGE_REQUESTS,
    COMMITS,
    FAILED_BRIDGES,
    FAILED_JOBS,
    JIRA_ISSUE_API,
    JIRA_ISSUES,
    JIRA_REMOTE_LINKS,
    JIRA_SEARCH,
    MERGED_MERGE_REQUESTS,
    PREVIEW_DEPLOYMENT,
    PRODUCTION_DEPLOYMENT,
    PUSH_PIPELINES,
    SERVICE,
    SERVICE_API,
    TAG_PIPELINES,
    TAGS,
    jira_page,
)


_SETTINGS_ENV: typing.Final = (
    "GITLAB_TOKEN",
    "RELEASE_SCOPE_GITLAB__TOKEN",
    "RELEASE_SCOPE_GITLAB__ENDPOINT",
    "RELEASE_SCOPE_JIRA_ENDPOINT",
    "RELEASE_SCOPE_JIRA_TOKEN",
    "JIRA_TOKEN",
    "RELEASE_SCOPE_JIRA_PROJECT_KEYS",
    "RELEASE_SCOPE_ENVIRONMENTS",
    "RELEASE_SCOPE_PRODUCTION_ENVIRONMENT",
    "RELEASE_SCOPE_REQUEST_TIMEOUT",
    "RELEASE_SCOPE_MAX_COMMITS",
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _SETTINGS_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def gitlab(httpx2_mock: respx.Router) -> respx.Router:
    httpx2_mock.get(f"{API}/groups/team/projects", name="group").respond(json=[SERVICE])
    httpx2_mock.get(
        f"{SERVICE_API}/deployments", params={"environment": "production"}, name="deploy:production"
    ).respond(json=[PRODUCTION_DEPLOYMENT])
    httpx2_mock.get(f"{SERVICE_API}/deployments", params={"environment": "preview"}, name="deploy:preview").respond(
        json=[PREVIEW_DEPLOYMENT]
    )
    httpx2_mock.get(f"{SERVICE_API}/repository/commits", name="commits").respond(json=COMMITS)
    httpx2_mock.get(f"{SERVICE_API}/merge_requests", name="merged_mrs").respond(json=MERGED_MERGE_REQUESTS)
    for sha, merge_requests in COMMIT_MERGE_REQUESTS.items():
        httpx2_mock.get(f"{SERVICE_API}/repository/commits/{sha}/merge_requests", name=f"commit_mrs:{sha}").respond(
            json=merge_requests
        )
    httpx2_mock.get(f"{SERVICE_API}/repository/tags", name="tags").respond(json=TAGS)
    httpx2_mock.get(f"{SERVICE_API}/pipelines", params={"source": "push"}, name="push_pipelines").respond(
        json=PUSH_PIPELINES
    )
    for ref, pipelines in TAG_PIPELINES.items():
        httpx2_mock.get(f"{SERVICE_API}/pipelines", params={"ref": ref}, name=f"pipeline:{ref}").respond(json=pipelines)
    for pipeline_id, jobs in FAILED_JOBS.items():
        httpx2_mock.get(f"{SERVICE_API}/pipelines/{pipeline_id}/jobs", name=f"jobs:{pipeline_id}").respond(json=jobs)
    for pipeline_id, bridges in FAILED_BRIDGES.items():
        httpx2_mock.get(f"{SERVICE_API}/pipelines/{pipeline_id}/bridges", name=f"bridges:{pipeline_id}").respond(
            json=bridges
        )
    return httpx2_mock


@pytest.fixture
def jira(gitlab: respx.Router) -> respx.Router:
    gitlab.post(JIRA_SEARCH, name="jira_search").respond(json=jira_page(*JIRA_ISSUES))
    for key, links in JIRA_REMOTE_LINKS.items():
        gitlab.get(f"{JIRA_ISSUE_API}/{key}/remotelink", name=f"remote_links:{key}").respond(json=links)
    return gitlab
