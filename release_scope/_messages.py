import http
import typing

from release_scope._errors import GitLabError
from release_scope._gitlab import Project
from release_scope._report import Message, MessageCode


_RESOURCES: typing.Final[dict[str, tuple[str, tuple[str, ...]]]] = {
    "project": ("the project", ()),
    "deployments": ("deployments", ("Environments", "CI/CD")),
    "pipelines": ("pipelines", ("CI/CD",)),
    "repository": ("the repository", ("Repository",)),
    "merge_requests": ("merge requests", ("Merge requests",)),
}
_PLURAL_FEATURES: typing.Final = frozenset({"Environments", "Merge requests"})
_PERMISSIONS: typing.Final = "Visibility, project features, permissions"


def _settings_url(web_url: str) -> str:
    return f"{web_url}/edit#js-shared-permissions"


def explain_failure(name: str, web_url: str, error: GitLabError) -> Message:
    label, features = _RESOURCES.get(error.resource, ("project data", ()))
    if error.status is None:
        return Message(
            code=MessageCode.GITLAB_UNREACHABLE,
            params={"project": name, "resource": error.resource, "reason": error.reason},
            text=f"{name}: GitLab request for {label} failed ({error.reason}).",
        )
    if error.status != http.HTTPStatus.FORBIDDEN:
        return Message(
            code=MessageCode.GITLAB_STATUS,
            params={"project": name, "resource": error.resource, "status": error.status},
            text=f"{name}: GitLab returned {error.status} for {label}.",
        )
    settings: typing.Final = _settings_url(web_url)
    members: typing.Final = f"{web_url}/-/project_members"
    checks: typing.Final = [
        f"- {feature} {'are' if feature in _PLURAL_FEATURES else 'is'} enabled: {settings} → {_PERMISSIONS} → {feature}"
        for feature in features
    ]
    checks.append(f"- the token's user has a role that can read them: {members}")
    return Message(
        code=MessageCode.GITLAB_DENIED,
        params={
            "project": name,
            "resource": error.resource,
            "features": list(features),
            "settings_url": settings,
            "members_url": members,
        },
        text="\n".join([f"{name}: GitLab denied access to {label} (403). Check that:", *checks]),
    )


def skip_reason(project: Project) -> Message | None:
    settings: typing.Final = _settings_url(project.web_url)
    if project.builds_access_level == "disabled":
        return Message(
            code=MessageCode.CI_DISABLED,
            params={"settings_url": settings},
            text="CI/CD is disabled, so it has no pipelines or deployments. "
            f"Enable it at {settings} → {_PERMISSIONS} → CI/CD.",
        )
    if project.environments_access_level == "disabled":
        return Message(
            code=MessageCode.ENVIRONMENTS_DISABLED,
            params={"settings_url": settings},
            text="Environments are disabled, so it has no deployments. "
            f"Enable them at {settings} → {_PERMISSIONS} → Environments.",
        )
    return None


def no_default_branch() -> Message:
    return Message(code=MessageCode.NO_DEFAULT_BRANCH, text="Project has no default branch.")


def no_production(environment: str, branch: str) -> Message:
    return Message(
        code=MessageCode.NO_PRODUCTION,
        params={"environment": environment, "branch": branch},
        text=f"No successful deployment to '{environment}'; rows run from the first commit of {branch}.",
    )


def commits_truncated(max_commits: int) -> Message:
    return Message(
        code=MessageCode.COMMITS_TRUNCATED,
        params={"max_commits": max_commits},
        text=f"Stopped after {max_commits} commits; older changes are omitted.",
    )


def tags_truncated() -> Message:
    return Message(code=MessageCode.TAGS_TRUNCATED, text="Tag list was truncated; some tags may be missing from rows.")


def deployments_truncated(environment: str) -> Message:
    return Message(
        code=MessageCode.DEPLOYMENTS_TRUNCATED,
        params={"environment": environment},
        text=f"Deployment history of {environment} was truncated; newer rows may miss when they reached it.",
    )


def merged_elsewhere(iid: int, target_branch: str, default_branch: str) -> Message:
    return Message(
        code=MessageCode.MERGED_ELSEWHERE,
        params={"iid": iid, "target_branch": target_branch, "default_branch": default_branch},
        text=f"!{iid} was merged into {target_branch}, not {default_branch}.",
    )


def _jira_target(issue: str | None) -> tuple[dict[str, str], str]:
    if issue is None:
        return {}, "the issue search"
    return {"issue": issue}, f"the remote links of {issue}"


def jira_token_rejected() -> Message:
    return Message(
        code=MessageCode.JIRA_TOKEN_REJECTED,
        text="Jira rejected the token (401). Check that it is valid and not expired.",
    )


def jira_status(status: int, detail: str, issue: str | None) -> Message:
    params, target = _jira_target(issue)
    suffix: typing.Final = f": {detail}." if detail else "."
    return Message(
        code=MessageCode.JIRA_STATUS,
        params={"status": status, "detail": detail, **params},
        text=f"Jira returned {status} for {target}{suffix}",
    )


def jira_unreachable(reason: str, issue: str | None) -> Message:
    params, target = _jira_target(issue)
    return Message(
        code=MessageCode.JIRA_UNREACHABLE,
        params={"reason": reason, **params},
        text=f"Jira request for {target} failed: {reason}.",
    )
