import pathlib
import typing

import httpware
import httpx2
import pydantic
import pytest

from release_scope import ioc
from release_scope._cache import Cache, CacheData, CachedPipeline
from release_scope._errors import ConfigError, GitLabError
from release_scope._gitlab import GitLabApi
from release_scope._jira_keys import extract_jira_keys
from release_scope._settings import GitLabConfig, Settings, load_settings


@pytest.mark.parametrize(
    ("text", "keys"),
    [
        ("SHOP-123 fix", ["SHOP-123"]),
        ("feature/SHOP-123_fix", ["SHOP-123"]),
        ("feat_SHOP-123", ["SHOP-123"]),
        ("[SHOP-1] and SHOP-2, SHOP-1 again", ["SHOP-1", "SHOP-2"]),
        ("abcSHOP-12", []),
        ("https://jira/browse/SHOP-5", ["SHOP-5"]),
        ("shop-5 lower", []),
    ],
)
def test_jira_keys_are_found_in_text(text: str, keys: list[str]) -> None:
    assert extract_jira_keys([text]) == keys


def test_jira_keys_respect_the_project_allowlist() -> None:
    assert extract_jira_keys(["UTF-8 SHOP-1", None, ""], allowed_projects=["SHOP"]) == ["SHOP-1"]


def test_production_environment_is_always_collected() -> None:
    settings: typing.Final = Settings(environments=["preview"], production_environment="prod")

    assert settings.environments == ["prod", "preview"]


def test_settings_read_nested_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RELEASE_SCOPE_GITLAB__TOKEN", "abc")
    monkeypatch.setenv("RELEASE_SCOPE_JIRA_PROJECT_KEYS", '["SHOP","OPS"]')

    settings: typing.Final = load_settings({})

    assert settings.gitlab.token.get_secret_value() == "abc"
    assert settings.jira_project_keys == ["SHOP", "OPS"]


def test_invalid_settings_raise_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITLAB_TOKEN", "abc")

    with pytest.raises(ConfigError, match="Invalid configuration"):
        load_settings({"max_commits": "many"})


def test_cache_round_trips_through_a_file(tmp_path: pathlib.Path) -> None:
    path: typing.Final = tmp_path / "nested" / "cache.json"
    cache: typing.Final = Cache()
    cache.put_failed_jobs(1, 5, CachedPipeline(updated_at="u", failed_jobs=[]))
    cache.save(path)

    loaded, warning = Cache.load(path)

    assert warning is None
    assert loaded.get_failed_jobs(1, 5, "u") == []
    assert loaded.get_failed_jobs(1, 5, "other") is None
    assert [item.name for item in tmp_path.joinpath("nested").iterdir()] == ["cache.json"]


def test_missing_cache_starts_empty(tmp_path: pathlib.Path) -> None:
    loaded, warning = Cache.load(tmp_path / "absent.json")

    assert warning is None
    assert loaded.previous == CacheData()


def test_cache_keeps_only_entries_used_by_the_run() -> None:
    previous: typing.Final = CacheData()
    previous.pipelines["1"] = {"5": CachedPipeline(updated_at="u", failed_jobs=[])}
    previous.pipelines["2"] = {"6": CachedPipeline(updated_at="u", failed_jobs=[])}
    cache: typing.Final = Cache(previous=previous)

    cache.get_failed_jobs(1, 5, "u")

    assert set(cache.current.pipelines) == {"1"}


def test_keep_project_merges_old_and_new_entries() -> None:
    previous: typing.Final = CacheData()
    previous.pipelines["1"] = {"5": CachedPipeline(updated_at="old", failed_jobs=[])}
    cache: typing.Final = Cache(previous=previous)
    cache.put_failed_jobs(1, 6, CachedPipeline(updated_at="new", failed_jobs=[]))

    cache.keep_project(1)
    cache.keep_project(3)

    assert set(cache.current.pipelines["1"]) == {"5", "6"}
    assert cache.current.commit_merge_requests["3"] == {}


def test_transport_failure_becomes_gitlab_error() -> None:
    def broken(request: httpx2.Request) -> httpx2.Response:
        msg = "down"
        raise httpx2.ConnectError(msg, request=request)

    api: typing.Final = GitLabApi(
        http=httpware.Client(httpx2_client=httpx2.Client(transport=httpx2.MockTransport(broken), base_url="http://x"))
    )

    with pytest.raises(GitLabError, match="failed: NetworkError"):
        api.get_project("team/svc")
    with pytest.raises(GitLabError, match="failed: NetworkError"):
        api.list_tags(1)


def test_container_builds_a_real_client_from_settings() -> None:
    settings: typing.Final = Settings(
        gitlab=GitLabConfig(endpoint="https://gitlab.test", token=pydantic.SecretStr("t"))
    )

    with ioc.container:
        ioc.container.set_context(Settings, settings)
        api: typing.Final = ioc.container.resolve(GitLabApi)

    assert isinstance(api.http, httpware.Client)
