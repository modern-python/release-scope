import dataclasses
import http
import typing

from release_scope._errors import AuthError, GitLabError, ReleaseScopeError
from release_scope._gitlab import GitLabApi
from release_scope._settings import Settings


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class Published:
    url: str
    updated: bool


def _wiki_error(error: GitLabError, *, project: str, slug: str, size: int | None) -> ReleaseScopeError:
    if error.status == http.HTTPStatus.FORBIDDEN:
        return AuthError(
            f"GitLab denied access to the wiki of project '{project}' (403). Check that the token has the 'api' "
            "scope and that its user has at least the Developer role there."
        )
    if error.status == http.HTTPStatus.NOT_FOUND:
        return GitLabError(
            f"Wiki page '{slug}' does not exist in project '{project}', or the token cannot see it. "
            "Create the page in GitLab first.",
            resource="wiki",
            status=error.status,
        )
    if size is None:
        return error
    return GitLabError(f"{error} The page is {size} bytes.", resource="wiki", status=error.status, reason=error.reason)


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class PublishUseCase:
    api: GitLabApi
    settings: Settings

    def __call__(self, *, project: str, slug: str, content: str) -> Published:
        url: typing.Final = f"{self.settings.gitlab.endpoint.rstrip('/')}/{project}/-/wikis/{slug}"
        try:
            page = self.api.get_wiki_page(project, slug)
        except GitLabError as exc:
            raise _wiki_error(exc, project=project, slug=slug, size=None) from exc
        if page.content == content:
            return Published(url=url, updated=False)
        try:
            self.api.update_wiki_page(project, slug, content=content)
        except GitLabError as exc:
            raise _wiki_error(exc, project=project, slug=slug, size=len(content.encode())) from exc
        return Published(url=url, updated=True)
