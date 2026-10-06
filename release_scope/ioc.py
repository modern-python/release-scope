import typing

import httpware
import modern_di
from modern_di import Scope, providers

from release_scope._gitlab import GitLabApi
from release_scope._jira import JiraApi
from release_scope._settings import Settings, load_settings
from release_scope._use_case import CollectUseCase


_RETRY_STATUS_CODES: typing.Final = frozenset({408, 429, 500, 502, 503, 504})
_MAX_RESPONSE_BODY_BYTES: typing.Final = 16 * 1024 * 1024
_JIRA_RETRY_METHODS: typing.Final = frozenset({"GET", "POST"})


def _build_gitlab_client(settings: Settings) -> httpware.Client:
    return httpware.Client(
        base_url=settings.gitlab.endpoint,
        timeout=settings.request_timeout,
        headers={"PRIVATE-TOKEN": settings.gitlab.token.get_secret_value()},
        middleware=[httpware.Retry(retry_status_codes=_RETRY_STATUS_CODES)],
        max_response_body_bytes=_MAX_RESPONSE_BODY_BYTES,
    )


def _build_jira_client(settings: Settings) -> httpware.Client | None:
    if not settings.jira_endpoint or not settings.jira_token.get_secret_value():
        return None
    return httpware.Client(
        base_url=settings.jira_endpoint,
        timeout=settings.request_timeout,
        headers={"Authorization": f"Bearer {settings.jira_token.get_secret_value()}"},
        middleware=[httpware.Retry(retry_status_codes=_RETRY_STATUS_CODES, retry_methods=_JIRA_RETRY_METHODS)],
        max_response_body_bytes=_MAX_RESPONSE_BODY_BYTES,
    )


def _build_jira_api(http: httpware.Client | None) -> JiraApi | None:
    return JiraApi(http=http) if http else None


def _close_client(client: httpware.Client | None) -> None:
    if client is not None:
        client.close()


class SettingsGroup(modern_di.Group):
    settings = providers.Factory(scope=Scope.APP, creator=load_settings, cache=True)


class ClientsGroup(modern_di.Group):
    gitlab_client = providers.Factory(
        scope=Scope.APP,
        creator=_build_gitlab_client,
        bound_type=None,
        cache=providers.CacheSettings(finalizer=_close_client),
    )
    gitlab_api = providers.Factory(scope=Scope.APP, creator=GitLabApi, kwargs={"http": gitlab_client})
    jira_client = providers.Factory(
        scope=Scope.APP,
        creator=_build_jira_client,
        bound_type=None,
        cache=providers.CacheSettings(finalizer=_close_client),
    )
    jira_api = providers.Factory(
        scope=Scope.APP, creator=_build_jira_api, bound_type=None, kwargs={"http": jira_client}
    )


class UseCasesGroup(modern_di.Group):
    collect_use_case = providers.Factory(
        scope=Scope.APP, creator=CollectUseCase, kwargs={"jira": ClientsGroup.jira_api}
    )


ALL_GROUPS: typing.Final[list[type[modern_di.Group]]] = [SettingsGroup, ClientsGroup, UseCasesGroup]


container: typing.Final = modern_di.Container(groups=ALL_GROUPS)
