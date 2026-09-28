import http
import typing

from release_scope._errors import GitLabError
from release_scope._gitlab import Project


_RESOURCES: typing.Final[dict[str, tuple[str, tuple[str, ...]]]] = {
    "deployments": ("deployments", ("Environments", "CI/CD")),
    "pipelines": ("pipelines", ("CI/CD",)),
    "repository": ("the repository", ("Repository",)),
    "merge_requests": ("merge requests", ("Merge requests",)),
}
_PLURAL_FEATURES: typing.Final = frozenset({"Environments", "Merge requests"})


def _feature_setting(project: Project, feature: str) -> str:
    return f"{project.web_url}/edit#js-shared-permissions → Visibility, project features, permissions → {feature}"


def explain_failure(project: Project, error: GitLabError) -> str:
    name: typing.Final = project.path_with_namespace
    resource, features = _RESOURCES.get(error.resource, ("project data", ()))
    if error.status is None:
        return f"{name}: GitLab request for {resource} failed ({error.reason})."
    if error.status != http.HTTPStatus.FORBIDDEN:
        return f"{name}: GitLab returned {error.status} for {resource}."
    checks: typing.Final = [
        f"- {feature} {'are' if feature in _PLURAL_FEATURES else 'is'} enabled: {_feature_setting(project, feature)}"
        for feature in features
    ]
    checks.append(f"- the token's user has a role that can read them: {project.web_url}/-/project_members")
    return "\n".join([f"{name}: GitLab denied access to {resource} (403). Check that:", *checks])


def skip_reason(project: Project) -> str | None:
    if project.builds_access_level == "disabled":
        return (
            "CI/CD is disabled, so it has no pipelines or deployments. "
            f"Enable it at {_feature_setting(project, 'CI/CD')}."
        )
    if project.environments_access_level == "disabled":
        return (
            "Environments are disabled, so it has no deployments. "
            f"Enable them at {_feature_setting(project, 'Environments')}."
        )
    return None
