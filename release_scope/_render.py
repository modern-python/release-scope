import collections.abc
import datetime
import html
import typing
from urllib.parse import quote

from release_scope._report import (
    EnvironmentState,
    FailedJob,
    JiraIssue,
    JiraKeyRef,
    JiraState,
    PipelineState,
    Report,
    Row,
    Service,
    TagRef,
)


_STATUS_ICONS: typing.Final = {
    "success": "✅",
    "failed": "❌",
    "created": "🔄",
    "waiting_for_resource": "🔄",
    "preparing": "🔄",
    "pending": "🔄",
    "running": "🔄",
    "scheduled": "🔄",
    "canceled": "⏭",
    "skipped": "⏭",
    "manual": "⏭",
}
_LEGEND: typing.Final = (
    "Legend: ✅ success · ❌ failed · 🔄 running · ⏭ canceled or skipped · ⚠️ warning or allowed failure"
)
_FAILED, _SKIPPED, _PENDING = 0, 1, 2
_UNRELEASED: typing.Final = {"not_merged": "⏳ not merged", "not_found": "⚠️ linked change not found"}
_LINKED: typing.Final = "🎯"


def _inline(value: str) -> str:
    return html.escape(value, quote=False).replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")


def _cell(value: str) -> str:
    return _inline(value).replace("\r\n", "<br>").replace("\n", "<br>")


def _link(label: str, url: str | None) -> str:
    if not url:
        return label
    return f"[{label}]({url.replace(' ', '%20').replace(')', '%29').replace('|', '%7C')})"


def _icon(status: str) -> str:
    return _STATUS_ICONS.get(status, f"`{status}`")


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _nonzero(separator: str, parts: collections.abc.Iterable[tuple[int, str]]) -> str:
    return separator.join(text for count, text in parts if count)


def _table(
    header: collections.abc.Sequence[str], rows: collections.abc.Iterable[collections.abc.Sequence[str]]
) -> list[str]:
    lines: typing.Final = [f"| {' | '.join(header)} |", f"|{'---|' * len(header)}"]
    lines.extend(f"| {' | '.join(row)} |" for row in rows)
    return lines


def _collapsed(summary: str, body: list[str]) -> list[str]:
    return ["<details>", f"<summary>{summary}</summary>", "", *body, "", "</details>", ""]


def _state(service: Service) -> int | None:
    if service.error:
        return _FAILED
    if service.rows:
        return _PENDING
    if service.release and service.release.state in _UNRELEASED:
        return _SKIPPED
    return _SKIPPED if service.warnings else None


def _environment_names(report: Report) -> list[str]:
    names: dict[str, None] = {report.production_environment: None}
    for service in report.services:
        names.update((item.name, None) for item in service.environments)
    return list(names)


def _environment(service: Service, name: str) -> EnvironmentState | None:
    return next((item for item in service.environments if item.name == name), None)


def _environment_ref(environment: EnvironmentState | None) -> str:
    return _link(_cell(environment.ref), environment.deployment_url) if environment else "—"


def _failure_counts(service: Service) -> str:
    pipelines: typing.Final = [row.main_pipeline for row in service.rows] + [
        tag.pipeline for row in service.rows for tag in row.tags
    ]
    jobs: typing.Final = [job for pipeline in pipelines if pipeline for job in pipeline.failed_jobs]
    allowed: typing.Final = sum(1 for job in jobs if job.allow_failure)
    blocking: typing.Final = len(jobs) - allowed
    return _nonzero(" · ", [(blocking, f"❌ {blocking}"), (allowed, f"⚠️ {allowed} allowed")])


def _pending(service: Service) -> str:
    state: typing.Final = _state(service)
    release: typing.Final = service.release
    if state == _FAILED:
        return "❌ failed to collect"
    if state == _SKIPPED:
        return _UNRELEASED.get(release.state, "⚠️ see below") if release else "⚠️ see below"
    if release:
        suffix = f" · release {_tag(release.tag)}" if release.tag else " · needs a new tag"
    else:
        suffix = "" if service.rows[0].tags else " · untagged head"
    return f"{_plural(len(service.rows), 'change')}{suffix}"


def _not_done(service: Service, issues: dict[str, JiraIssue]) -> str:
    keys: typing.Final = {key.key for row in service.rows for key in row.jira_keys}
    count: typing.Final = sum(1 for key in keys if key in issues and issues[key].status_category != "done")
    return f"{count} not done" if count else ""


def _compare(service: Service, production: str) -> str:
    start: typing.Final = _environment(service, production)
    release: typing.Final = service.release
    tag: typing.Final = release.tag if release else next((tag for row in service.rows for tag in row.tags), None)
    if start is None or tag is None:
        return ""
    base, label = (start.ref, _cell(start.ref)) if start.tag else (start.sha, f"`{start.sha[:8]}`")
    return _link(f"{label}...{_cell(tag.name)}", f"{service.project_url}/-/compare/{quote(base)}...{quote(tag.name)}")


def _summary_row(service: Service, report: Report, environments: list[str]) -> list[str]:
    jira: typing.Final = report.jira
    return [
        _link(_cell(service.project), service.project_url),
        *(_environment_ref(_environment(service, name)) for name in environments),
        _pending(service),
        _compare(service, report.production_environment),
        *([_not_done(service, jira.issues)] if jira else []),
        _failure_counts(service),
    ]


def _job(job: FailedJob) -> str:
    text: str = _link(_cell(job.name), job.url)
    if job.allow_failure:
        text += " (allowed)"
    if job.downstream_pipeline_url:
        text += f" → {_link('child', job.downstream_pipeline_url)}"
    return text


def _jobs(pipeline: PipelineState) -> str:
    return ", ".join(_job(job) for job in pipeline.failed_jobs)


def _main_pipeline(pipeline: PipelineState) -> str:
    text: typing.Final = f"main {_icon(pipeline.status)} {_link(str(pipeline.id), pipeline.url)}"
    return f"{text}: {_jobs(pipeline)}" if pipeline.failed_jobs else text


def _tag(tag: TagRef) -> str:
    if tag.pipeline is None:
        return f"{_link(_cell(tag.name), tag.url)} ⚠️ no pipeline"
    return f"{_link(_cell(tag.name), tag.pipeline.url)} {_icon(tag.pipeline.status)}"


def _reference(label: str, url: str | None, title: str, author: str | None) -> str:
    return f"{_link(label, url)} {_cell(title)}" + (f" · {_cell(author)}" if author else "")


def _merge_requests_or_commits(row: Row) -> str:
    if row.merge_requests:
        return "<br>".join(
            _reference(f"!{item.iid}", item.url, item.title, f"@{item.author}" if item.author else None)
            for item in row.merge_requests
        )
    return "<br>".join(_reference(f"`{item.short_sha}`", item.url, item.title, item.author) for item in row.commits)


def _failed_jobs(row: Row) -> str:
    parts: typing.Final = [_main_pipeline(row.main_pipeline)] if row.main_pipeline else []
    parts.extend(
        f"tag {_cell(tag.name)}: {_jobs(tag.pipeline)}" for tag in row.tags if tag.pipeline and tag.pipeline.failed_jobs
    )
    return "<br>".join(parts)


def _jira_key(key: JiraKeyRef, issues: dict[str, JiraIssue]) -> str:
    text: typing.Final = _link(_cell(key.key), key.url)
    issue: typing.Final = issues.get(key.key)
    return f"{text} {_cell(issue.summary)} · {_cell(issue.status)}" if issue else text


def _related_services(row: Row, project: str, issues: dict[str, JiraIssue]) -> str:
    related: typing.Final = {
        link.project: link.project_url
        for key in row.jira_keys
        if key.key in issues
        for link in issues[key.key].links
        if link.project != project
    }
    return ", ".join(_link(_cell(name), related[name]) for name in sorted(related))


def _row(row: Row, project: str, jira: JiraState | None) -> list[str]:
    issues: typing.Final = jira.issues if jira else {}
    return [
        "<br>".join(_tag(tag) for tag in row.tags),
        f"{_LINKED} {_merge_requests_or_commits(row)}" if row.linked else _merge_requests_or_commits(row),
        "<br>".join(_jira_key(key, issues) for key in row.jira_keys),
        *([_related_services(row, project, issues)] if jira else []),
        ", ".join(_cell(name) for name in row.environments),
        _failed_jobs(row),
    ]


def _counts(service: Service) -> str:
    merge_requests: typing.Final = len({item.iid for row in service.rows for item in row.merge_requests})
    commits: typing.Final = sum(1 for row in service.rows if row.kind == "commit")
    return _nonzero(
        ", ", [(merge_requests, _plural(merge_requests, "merge request")), (commits, _plural(commits, "direct commit"))]
    )


def _rows_section(service: Service, production: str, jira: JiraState | None) -> list[str]:
    ordered: typing.Final = sorted(service.environments, key=lambda item: item.name != production)
    environments: typing.Final = [f"{_cell(item.name)} {_environment_ref(item)}" for item in ordered]
    production_state: typing.Final = _environment(service, production)
    since: typing.Final = f" since {_inline(production_state.ref)}" if production_state else ""
    return [
        " · ".join([*environments, _counts(service)]),
        "",
        *_collapsed(
            f"{_plural(len(service.rows), 'change')}{since}",
            _table(
                ["Tag", "Change", "Jira", *(["Related services"] if jira else []), "Deployed to", "Failed jobs"],
                (_row(row, service.project, jira) for row in service.rows),
            ),
        ),
    ]


def _service_section(service: Service, production: str, jira: JiraState | None) -> list[str]:
    lines: typing.Final = [f"## {_inline(service.project)}", ""]
    if service.error:
        lines.extend([f"❌ {_inline(service.error)}", ""])
    lines.extend(line for warning in service.warnings for line in (f"⚠️ {_inline(warning)}", ""))
    release: typing.Final = service.release
    if release and release.pending_merge_requests:
        waiting: typing.Final = ", ".join(
            _reference(f"!{item.iid}", item.url, item.title, f"@{item.author}" if item.author else None)
            for item in release.pending_merge_requests
        )
        lines.extend([f"⏳ Not merged: {waiting}", ""])
    if release and release.state == "not_found":
        lines.extend(["⚠️ No linked change was found between production and the head of the default branch.", ""])
    if service.rows:
        lines.extend(_rows_section(service, production, jira))
    return lines


def _scope_issue(key: str, jira: JiraState | None) -> str:
    issue: typing.Final = jira.issues.get(key) if jira else None
    if issue is None:
        return f"- {_inline(key)} · not found in Jira"
    return f"- {_link(_inline(key), issue.url)} {_cell(issue.summary)} · {_cell(issue.status)}"


def render_markdown(report: Report) -> str:
    production: typing.Final = report.production_environment
    collected: typing.Final = report.collected_at.astimezone(datetime.UTC).strftime("%Y-%m-%d %H:%M")
    jira: typing.Final = report.jira
    scope: typing.Final = report.jira_scope
    lines: typing.Final = [
        f"# Release scope: {', '.join(_inline(key) for key in scope)}" if scope else "# Release scope",
        "",
        (
            f"Collected {collected} UTC. Changes run from the commit on `{_inline(production)}` "
            + ("to the latest change linked to the issues." if scope else "to the head of the default branch.")
        ),
        "",
    ]
    if scope:
        lines.extend([*(_scope_issue(key, jira) for key in scope), ""])
    lines.extend([f"{_LEGEND} · {_LINKED} linked to the issues" if scope else _LEGEND, ""])
    if jira and jira.error:
        lines.extend([f"❌ {_inline(jira.error)}", ""])
    if not report.services:
        lines.append("No services were collected.")
        return "\n".join(lines) + "\n"

    attention: typing.Final = sorted(
        (service for service in report.services if _state(service) is not None),
        key=lambda service: (_state(service), service.project),
    )
    up_to_date: typing.Final = [service for service in report.services if _state(service) is None]
    environments: typing.Final = _environment_names(report)
    if attention:
        header: typing.Final = [
            "Service",
            *(_cell(name) for name in environments),
            "Pending",
            "Compare",
            *(["Jira"] if jira else []),
            "Failed jobs",
        ]
        lines.extend([*_table(header, (_summary_row(service, report, environments) for service in attention)), ""])
    else:
        lines.extend(["All services are up to date.", ""])
    if up_to_date:
        lines.extend(
            _collapsed(
                f"{_plural(len(up_to_date), 'service')} up to date",
                _table(
                    ["Service", _cell(production)],
                    (
                        [_link(_cell(item.project), item.project_url), _environment_ref(_environment(item, production))]
                        for item in up_to_date
                    ),
                ),
            )
        )
    for service in attention:
        lines.extend(_service_section(service, production, jira))
    return "\n".join(lines).rstrip("\n") + "\n"
