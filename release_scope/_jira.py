import collections.abc
import dataclasses
import typing

import httpware
import pydantic

from release_scope._errors import JiraError


_SEARCH: typing.Final = "/rest/api/2/search"
_ISSUE: typing.Final = "/rest/api/2/issue"
_BATCH_SIZE: typing.Final = 100
_FIELDS: typing.Final = ("summary", "status", "issuetype")


class StatusCategory(pydantic.BaseModel):
    key: str | None = None


class Status(pydantic.BaseModel):
    name: str
    category: StatusCategory | None = pydantic.Field(default=None, alias="statusCategory")


class IssueType(pydantic.BaseModel):
    name: str


class IssueFields(pydantic.BaseModel):
    summary: str
    status: Status
    issuetype: IssueType | None = None


class Issue(pydantic.BaseModel):
    key: str
    fields: IssueFields


class _SearchResults(pydantic.BaseModel):
    total: int
    issues: list[Issue]


class RemoteObject(pydantic.BaseModel):
    url: str | None = None


class RemoteLink(pydantic.BaseModel):
    target: RemoteObject | None = pydantic.Field(default=None, alias="object")


class _RemoteLinks(pydantic.RootModel[list[RemoteLink]]):
    pass


def _error_messages(exc: httpware.StatusError) -> str:
    try:
        payload: typing.Final = exc.response.json()
    except ValueError:
        return ""
    messages: typing.Final = payload.get("errorMessages") if isinstance(payload, dict) else None
    if not isinstance(messages, list):
        return ""
    return " ".join(str(message) for message in messages)


def _translate(exc: httpware.ClientError, *, target: str) -> JiraError:
    if isinstance(exc, httpware.UnauthorizedError):
        return JiraError("Jira rejected the token (401). Check that it is valid and not expired.")
    if isinstance(exc, httpware.StatusError):
        status: typing.Final = exc.response.status_code
        details: typing.Final = _error_messages(exc)
        suffix: typing.Final = f": {details.rstrip('.')}." if details else "."
        return JiraError(f"Jira returned {status} for {target}{suffix}")
    return JiraError(f"Jira request for {target} failed: {type(exc).__name__}.")


def _batches(keys: collections.abc.Sequence[str]) -> collections.abc.Iterator[collections.abc.Sequence[str]]:
    for start in range(0, len(keys), _BATCH_SIZE):
        yield keys[start : start + _BATCH_SIZE]


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class JiraApi:
    http: httpware.Client

    def search_issues(self, keys: collections.abc.Sequence[str]) -> list[Issue]:
        issues: typing.Final[list[Issue]] = []
        for batch in _batches(keys):
            quoted = ", ".join(f'"{key}"' for key in batch)
            issues.extend(self._search(f"key in ({quoted})"))
        return issues

    def _search(self, jql: str) -> list[Issue]:
        issues: typing.Final[list[Issue]] = []
        while True:
            body = {
                "jql": jql,
                "fields": list(_FIELDS),
                "startAt": len(issues),
                "maxResults": _BATCH_SIZE,
                "validateQuery": False,
            }
            try:
                page = self.http.post(_SEARCH, json=body, response_model=_SearchResults)
            except httpware.ClientError as exc:
                raise _translate(exc, target="the issue search") from exc
            issues.extend(page.issues)
            if not page.issues or len(issues) >= page.total:
                return issues

    def remote_links(self, key: str) -> list[RemoteLink]:
        try:
            return self.http.get(f"{_ISSUE}/{key}/remotelink", response_model=_RemoteLinks).root
        except httpware.ClientError as exc:
            raise _translate(exc, target=f"the remote links of {key}") from exc
