import pathlib
import typing

import httpcore2
import httpware
import pydantic
import pytest
import respx

from release_scope import ioc
from release_scope._cache import Cache, CacheData, CachedPipeline
from release_scope._errors import ConfigError, GitLabError
from release_scope._gitlab import GitLabApi, MergeRequest
from release_scope._jira_keys import extract_jira_keys
from release_scope._links import parse_gitlab_link
from release_scope._settings import GitLabConfig, Settings, load_settings
from tests.payloads import merge_request


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

    settings: typing.Final = load_settings()

    assert settings.gitlab.token.get_secret_value() == "abc"
    assert settings.jira_project_keys == ["SHOP", "OPS"]


def test_jira_token_falls_back_to_the_shared_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITLAB_TOKEN", "abc")
    monkeypatch.setenv("RELEASE_SCOPE_JIRA_ENDPOINT", "https://jira.example.test")
    monkeypatch.setenv("JIRA_TOKEN", "jira-pat")

    assert load_settings().jira_token.get_secret_value() == "jira-pat"


def test_invalid_settings_raise_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITLAB_TOKEN", "abc")
    monkeypatch.setenv("RELEASE_SCOPE_MAX_COMMITS", "many")

    with pytest.raises(ConfigError, match="Invalid configuration"):
        load_settings()


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


def test_cache_prunes_only_the_projects_the_run_visited() -> None:
    previous: typing.Final = CacheData()
    previous.pipelines["1"] = {
        "5": CachedPipeline(updated_at="u", failed_jobs=[]),
        "7": CachedPipeline(updated_at="u", failed_jobs=[]),
    }
    previous.pipelines["2"] = {"6": CachedPipeline(updated_at="u", failed_jobs=[])}
    previous.merge_requests["2"] = {"4": MergeRequest.model_validate(merge_request(4, "Kept"))}
    cache: typing.Final = Cache(previous=previous)

    cache.visit(1)
    cache.get_failed_jobs(1, 5, "u")
    pruned: typing.Final = cache.pruned()

    assert {project: set(entries) for project, entries in pruned.pipelines.items()} == {"1": {"5"}, "2": {"6"}}
    assert set(pruned.merge_requests["2"]) == {"4"}


def test_cache_holds_merged_merge_requests() -> None:
    previous: typing.Final = CacheData()
    previous.merge_requests["1"] = {"4": MergeRequest.model_validate(merge_request(4, "Done"))}
    cache: typing.Final = Cache(previous=previous)

    cached: typing.Final = cache.get_merge_request(1, 4)

    assert cached is not None
    assert cached.title == "Done"
    assert cache.get_merge_request(1, 5) is None
    assert set(cache.current.merge_requests["1"]) == {"4"}


def test_keep_project_merges_old_and_new_entries() -> None:
    previous: typing.Final = CacheData()
    previous.pipelines["1"] = {"5": CachedPipeline(updated_at="old", failed_jobs=[])}
    cache: typing.Final = Cache(previous=previous)
    cache.put_failed_jobs(1, 6, CachedPipeline(updated_at="new", failed_jobs=[]))

    cache.keep_project(1)
    cache.keep_project(3)

    assert set(cache.current.pipelines["1"]) == {"5", "6"}
    assert cache.current.commit_merge_requests["3"] == {}
    assert cache.current.merge_requests["3"] == {}


def test_transport_failure_becomes_gitlab_error(httpx2_mock: respx.Router) -> None:
    httpx2_mock.route(host="gitlab.test").mock(side_effect=httpcore2.ConnectError("down"))
    api: typing.Final = GitLabApi(http=httpware.Client(base_url="https://gitlab.test"))

    with pytest.raises(GitLabError, match="failed: NetworkError"):
        api.get_project("team/svc")
    with pytest.raises(GitLabError, match="failed: NetworkError"):
        api.list_tags(1)


def test_container_builds_a_real_client_from_settings() -> None:
    settings: typing.Final = Settings(
        gitlab=GitLabConfig(endpoint="https://gitlab.test", token=pydantic.SecretStr("t"))
    )

    with ioc.container:
        ioc.container.override(ioc.SettingsGroup.settings, settings)
        api: typing.Final = ioc.container.resolve(GitLabApi)

    assert isinstance(api.http, httpware.Client)


def test_container_graph_is_valid() -> None:
    ioc.container.validate()


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://g.test/a/b/-/merge_requests/7", ("merge_request", "a/b", "https://g.test/a/b", 7, None)),
        ("https://g.test/a/b/-/merge_requests/7#note_1", ("merge_request", "a/b", "https://g.test/a/b", 7, None)),
        ("https://g.test/a/b/-/merge_requests/7/diffs", ("merge_request", "a/b", "https://g.test/a/b", 7, None)),
        ("https://g.test/a/-/commit/0123abcd", ("commit", "a", "https://g.test/a", None, "0123abcd")),
        ("https://g.test/a/b/-/issues/3", None),
        ("https://g.test/a/b", None),
        ("https://g.testing/a/b/-/merge_requests/7", None),
        ("https://other.test/a/b/-/merge_requests/7", None),
        (None, None),
    ],
)
def test_gitlab_links_are_parsed_against_the_endpoint(url: str | None, expected: tuple[typing.Any, ...] | None) -> None:
    change: typing.Final = parse_gitlab_link(url, "https://g.test/")

    actual: typing.Final = (change.kind, change.project, change.project_url, change.iid, change.sha) if change else None
    assert actual == expected
