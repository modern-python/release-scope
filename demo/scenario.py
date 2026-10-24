import dataclasses
import datetime as dt
import hashlib
import typing

import respx


ENDPOINT: typing.Final = "https://gitlab.example.com"
JIRA_ENDPOINT: typing.Final = "https://jira.example.com"
GROUP: typing.Final = "shop"
ENVIRONMENTS: typing.Final = ("staging",)
_API: typing.Final = f"{ENDPOINT}/api/v4"


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class Change:
    title: str
    hours_ago: int
    author: str
    iid: int | None = None
    branch: str | None = None
    description: str | None = None
    tag: str | None = None
    pipeline: str = "success"
    failed_jobs: tuple[str, ...] = ()
    on_staging: bool = False


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class LinkedMergeRequest:
    iid: int
    title: str
    state: str
    target_branch: str = "main"


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class DemoService:
    id: int
    name: str
    production: str
    older_tags: tuple[str, ...] = ()
    changes: tuple[Change, ...] = ()
    linked: tuple[LinkedMergeRequest, ...] = ()

    @property
    def path(self) -> str:
        return f"{GROUP}/{self.name}"

    @property
    def url(self) -> str:
        return f"{ENDPOINT}/{self.path}"


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class DemoIssue:
    key: str
    summary: str
    status: str
    category: str
    issue_type: str = "Story"
    links: tuple[str, ...] = ()
    blocked_by: tuple[str, ...] = ()
    blocks: tuple[str, ...] = ()
    parent: str | None = None
    subtasks: tuple[str, ...] = ()


SERVICES: typing.Final = (
    DemoService(
        id=11,
        name="api",
        production="2.3.0",
        older_tags=("2.2.0",),
        changes=(
            Change(
                title="SHOP-41 Rate limit the checkout endpoint",
                hours_ago=3,
                author="dina",
                iid=58,
                branch="feature/SHOP-41-rate-limit",
                pipeline="running",
            ),
            Change(
                title="SHOP-38 Export orders as CSV",
                hours_ago=26,
                author="anna",
                iid=57,
                branch="feature/SHOP-38-order-export",
                tag="2.5.0",
                on_staging=True,
            ),
            Change(
                title="Fix VAT rounding for mixed carts",
                hours_ago=30,
                author="ben",
                iid=55,
                branch="fix/vat-rounding",
                description="Closes SHOP-35",
            ),
            Change(
                title="Bump httpx and pydantic",
                hours_ago=52,
                author="renovate-bot",
                iid=54,
                branch="renovate/all",
                tag="2.4.0",
                pipeline="failed",
                failed_jobs=("lint",),
            ),
            Change(
                title="SHOP-33 Search products by SKU",
                hours_ago=75,
                author="chen",
                iid=52,
                branch="feature/SHOP-33-sku-search",
                on_staging=True,
            ),
        ),
        linked=(LinkedMergeRequest(iid=40, title="SHOP-36 Theme tokens endpoint", state="merged"),),
    ),
    DemoService(
        id=12,
        name="web",
        production="1.8.0",
        older_tags=("1.7.1",),
        changes=(
            Change(title="Tidy the footer links", hours_ago=5, author="anna"),
            Change(title="Fix typo in the footer", hours_ago=12, author="anna", tag="1.9.1"),
            Change(
                title="SHOP-38 Export button on the orders page",
                hours_ago=28,
                author="anna",
                iid=120,
                branch="feature/SHOP-38-export-button",
                tag="1.9.0",
                on_staging=True,
            ),
            Change(
                title="SHOP-36 Dark mode",
                hours_ago=49,
                author="chen",
                iid=118,
                branch="feature/SHOP-36-dark-mode",
            ),
        ),
        linked=(
            LinkedMergeRequest(iid=125, title="SHOP-41 Show a retry hint on 429", state="opened"),
            LinkedMergeRequest(iid=99, title="SHOP-33 SKU field in search", state="closed"),
        ),
    ),
    DemoService(
        id=13,
        name="worker",
        production="0.14.2",
        older_tags=("0.14.1",),
        changes=(
            Change(
                title="SHOP-40 Retry failed webhooks with backoff",
                hours_ago=8,
                author="ben",
                iid=32,
                branch="feature/SHOP-40-webhook-retries",
            ),
            Change(
                title="SHOP-35 Recalculate VAT on invoices",
                hours_ago=31,
                author="ben",
                iid=31,
                branch="feature/SHOP-35-invoice-vat",
                tag="0.15.0",
                on_staging=True,
            ),
        ),
        linked=(
            LinkedMergeRequest(
                iid=29, title="SHOP-40 Webhook retries hotfix", state="merged", target_branch="release/0.14"
            ),
        ),
    ),
    DemoService(
        id=14,
        name="admin",
        production="3.1.0",
        linked=(LinkedMergeRequest(iid=15, title="SHOP-44 Export permission for managers", state="opened"),),
    ),
)

ISSUES: typing.Final = (
    DemoIssue(
        key="SHOP-33",
        summary="Search products by SKU",
        status="Ready for release",
        category="done",
        links=(f"{ENDPOINT}/shop/web/-/merge_requests/99", f"{ENDPOINT}/shop/api/-/merge_requests/54"),
    ),
    DemoIssue(
        key="SHOP-35",
        summary="VAT is off by a cent on mixed carts",
        status="Ready for release",
        category="done",
        issue_type="Bug",
        links=(f"{ENDPOINT}/shop/worker/-/merge_requests/31",),
        blocks=("SHOP-40",),
    ),
    DemoIssue(
        key="SHOP-36",
        summary="Dark mode",
        status="In Review",
        category="indeterminate",
        links=(f"{ENDPOINT}/shop/api/-/merge_requests/40",),
        blocked_by=("SHOP-45",),
        subtasks=("SHOP-46",),
    ),
    DemoIssue(
        key="SHOP-38",
        summary="Export orders as CSV",
        status="Ready for release",
        category="done",
        links=(
            f"{ENDPOINT}/shop/api/-/merge_requests/57",
            f"{ENDPOINT}/shop/web/-/merge_requests/120",
            f"{ENDPOINT}/partners/mobile/-/merge_requests/7",
        ),
        blocked_by=("SHOP-44",),
    ),
    DemoIssue(
        key="SHOP-40",
        summary="Retry failed webhooks",
        status="In Progress",
        category="indeterminate",
        links=(f"{ENDPOINT}/shop/worker/-/merge_requests/29",),
    ),
    DemoIssue(
        key="SHOP-41",
        summary="Rate limit checkout",
        status="In Progress",
        category="indeterminate",
        links=(f"{ENDPOINT}/shop/web/-/merge_requests/125",),
    ),
    DemoIssue(
        key="SHOP-44",
        summary="Only managers may export orders",
        status="In Progress",
        category="indeterminate",
        links=(f"{ENDPOINT}/shop/admin/-/merge_requests/15", f"{ENDPOINT}/legacy/admin/-/merge_requests/3"),
    ),
    DemoIssue(key="SHOP-45", summary="Pick the dark palette with design", status="To Do", category="new"),
    DemoIssue(key="SHOP-46", summary="Dark mode in emails", status="To Do", category="new", parent="SHOP-36"),
)


def _sha(*parts: str) -> str:
    return hashlib.sha1("/".join(parts).encode(), usedforsecurity=False).hexdigest()


def _time(now: dt.datetime, hours_ago: float) -> str:
    return (now - dt.timedelta(hours=hours_ago)).isoformat()


def _project(service: DemoService) -> dict[str, typing.Any]:
    return {
        "id": service.id,
        "path_with_namespace": service.path,
        "web_url": service.url,
        "default_branch": "main",
    }


def _commit(service: DemoService, change: Change, now: dt.datetime) -> dict[str, typing.Any]:
    sha: typing.Final = _sha(service.path, change.title)
    title: typing.Final = f"Merge branch '{change.branch}' into 'main'" if change.iid else change.title
    return {
        "id": sha,
        "short_id": sha[:8],
        "title": title,
        "message": title,
        "author_name": change.author,
        "committed_date": _time(now, change.hours_ago),
        "web_url": f"{service.url}/-/commit/{sha}",
    }


def _merge_request(service: DemoService, change: Change, now: dt.datetime) -> dict[str, typing.Any]:
    return {
        "iid": change.iid,
        "title": change.title,
        "description": change.description,
        "source_branch": change.branch,
        "target_branch": "main",
        "state": "merged",
        "web_url": f"{service.url}/-/merge_requests/{change.iid}",
        "merge_commit_sha": _sha(service.path, change.title),
        "merged_at": _time(now, change.hours_ago),
        "author": {"username": change.author, "name": change.author},
    }


def _linked_merge_request(service: DemoService, linked: LinkedMergeRequest, now: dt.datetime) -> dict[str, typing.Any]:
    return {
        "iid": linked.iid,
        "title": linked.title,
        "source_branch": f"branch-{linked.iid}",
        "target_branch": linked.target_branch,
        "state": linked.state,
        "web_url": f"{service.url}/-/merge_requests/{linked.iid}",
        "merged_at": _time(now, 24 * 20) if linked.state == "merged" else None,
        "author": {"username": "dev", "name": "dev"},
    }


def _pipeline(  # noqa: PLR0913, PLR0917
    service: DemoService, pipeline_id: int, sha: str, ref: str, status: str, at: str
) -> dict[str, typing.Any]:
    return {
        "id": pipeline_id,
        "sha": sha,
        "ref": ref,
        "status": status,
        "web_url": f"{service.url}/-/pipelines/{pipeline_id}",
        "updated_at": at,
    }


def _deployment(deployment_id: int, ref: str, sha: str, at: str, *, tag: bool) -> dict[str, typing.Any]:
    return {
        "id": deployment_id,
        "ref": ref,
        "sha": sha,
        "created_at": at,
        "deployable": {"web_url": None, "tag": tag, "finished_at": at},
    }


def _mock_service(router: respx.Router, service: DemoService, now: dt.datetime) -> None:
    api: typing.Final = f"{_API}/projects/{service.id}"
    production_sha: typing.Final = _sha(service.path, "production")
    production: typing.Final = _deployment(
        service.id * 100, service.production, production_sha, _time(now, 24 * 9), tag=True
    )
    router.get(f"{api}/deployments", params={"environment": "production"}).respond(json=[production])
    staged: typing.Final = [
        _deployment(
            service.id * 100 + index,
            "main",
            _sha(service.path, change.title),
            _time(now, change.hours_ago - 1),
            tag=False,
        )
        for index, change in enumerate(reversed(service.changes), start=1)
        if change.on_staging
    ]
    router.get(f"{api}/deployments", params={"environment": "staging", "order_by": "finished_at"}).respond(json=staged)
    router.get(f"{api}/deployments", params={"environment": "staging"}).respond(json=staged[-1:] or [production])
    router.get(f"{api}/repository/commits").respond(json=[_commit(service, change, now) for change in service.changes])
    router.get(f"{api}/merge_requests", params={"state": "merged"}).respond(
        json=[_merge_request(service, change, now) for change in service.changes if change.iid]
    )
    for linked in service.linked:
        router.get(f"{api}/merge_requests/{linked.iid}").respond(json=_linked_merge_request(service, linked, now))
    for change in service.changes:
        if not change.iid:
            router.get(f"{api}/repository/commits/{_sha(service.path, change.title)}/merge_requests").respond(json=[])
    tags: typing.Final = [
        {"name": change.tag, "commit": {"id": _sha(service.path, change.title)}}
        for change in service.changes
        if change.tag
    ]
    tags.append({"name": service.production, "commit": {"id": production_sha}})
    tags.extend({"name": name, "commit": {"id": _sha(service.path, name)}} for name in service.older_tags)
    router.get(f"{api}/repository/tags").respond(json=tags)
    push: typing.Final = []
    for index, change in enumerate(service.changes):
        pipeline_id = service.id * 1000 + index
        sha = _sha(service.path, change.title)
        push.append(_pipeline(service, pipeline_id, sha, "main", change.pipeline, _time(now, change.hours_ago)))
        router.get(f"{api}/pipelines/{pipeline_id}/jobs").respond(
            json=[
                {
                    "name": name,
                    "stage": "test",
                    "status": "failed",
                    "web_url": f"{service.url}/-/jobs/{pipeline_id}{position}",
                    "failure_reason": "script_failure",
                }
                for position, name in enumerate(change.failed_jobs)
            ]
        )
        router.get(f"{api}/pipelines/{pipeline_id}/bridges").respond(json=[])
        if change.tag:
            tag_pipeline = service.id * 1000 + 500 + index
            router.get(f"{api}/pipelines", params={"ref": change.tag}).respond(
                json=[_pipeline(service, tag_pipeline, sha, change.tag, "success", _time(now, change.hours_ago - 1))]
            )
            router.get(f"{api}/pipelines/{tag_pipeline}/jobs").respond(json=[])
            router.get(f"{api}/pipelines/{tag_pipeline}/bridges").respond(json=[])
    router.get(f"{api}/pipelines", params={"source": "push"}).respond(json=push)


_BLOCKS: typing.Final = {"name": "Blocks", "inward": "is blocked by", "outward": "blocks"}


def _issue(issue: DemoIssue) -> dict[str, typing.Any]:
    return {
        "key": issue.key,
        "fields": {
            "summary": issue.summary,
            "status": {"name": issue.status, "statusCategory": {"key": issue.category}},
            "issuetype": {"name": issue.issue_type},
            "issuelinks": [
                *({"type": _BLOCKS, "inwardIssue": {"key": key}} for key in issue.blocked_by),
                *({"type": _BLOCKS, "outwardIssue": {"key": key}} for key in issue.blocks),
            ],
            "parent": {"key": issue.parent} if issue.parent else None,
            "subtasks": [{"key": key} for key in issue.subtasks],
        },
    }


def mock(router: respx.Router, now: dt.datetime) -> None:
    router.get(f"{_API}/groups/{GROUP}/projects").respond(json=[_project(service) for service in SERVICES])
    for service in SERVICES:
        _mock_service(router, service, now)
    router.post(f"{JIRA_ENDPOINT}/rest/api/2/search").respond(
        json={"startAt": 0, "maxResults": 100, "total": len(ISSUES), "issues": [_issue(issue) for issue in ISSUES]}
    )
    for issue in ISSUES:
        router.get(f"{JIRA_ENDPOINT}/rest/api/2/issue/{issue.key}/remotelink").respond(
            json=[
                {"id": index, "object": {"url": url, "title": "GitLab"}}
                for index, url in enumerate(issue.links, start=1)
            ]
        )
