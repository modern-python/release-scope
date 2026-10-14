import collections.abc
import functools
import http.server
import pathlib
import re
import threading
import typing

import pytest
import respx
from playwright.sync_api import ConsoleMessage, Error, Locator, Page, expect
from typer.testing import CliRunner

from release_scope import ioc
from release_scope.__main__ import MAIN_APP
from tests.payloads import ENDPOINT, JIRA_ENDPOINT


pytestmark = pytest.mark.smoke


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: typing.Any) -> None:  # noqa: A002, ANN401
        pass


@pytest.fixture
def site(jira: respx.Router, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> collections.abc.Iterator[str]:
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-test")
    monkeypatch.setenv("RELEASE_SCOPE_GITLAB__ENDPOINT", ENDPOINT)
    monkeypatch.setenv("RELEASE_SCOPE_ENVIRONMENTS", '["preview"]')
    monkeypatch.setenv("RELEASE_SCOPE_JIRA_ENDPOINT", JIRA_ENDPOINT)
    monkeypatch.setenv("JIRA_TOKEN", "jira-pat")
    output: typing.Final = tmp_path / "public"
    with ioc.container:
        result = CliRunner().invoke(MAIN_APP, ["collect", "-g", "team", "-o", str(output)])
    assert result.exit_code == 0, result.output
    assert jira["jira_search"].called
    server: typing.Final = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(_QuietHandler, directory=str(output))
    )
    thread: typing.Final = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/"
    server.shutdown()
    server.server_close()


@pytest.fixture
def errors(page: Page) -> list[str]:
    collected: list[str] = []

    def console(message: ConsoleMessage) -> None:
        if message.type == "error":
            collected.append(message.text)

    def crash(error: Error) -> None:
        collected.append(str(error))

    page.on("console", console)
    page.on("pageerror", crash)
    return collected


def _issue(page: Page, key: str) -> Locator:
    return page.locator(".issue-row", has=page.locator("code", has_text=key)).get_by_role("checkbox")


def test_page_lists_the_services_without_errors(page: Page, site: str, errors: list[str]) -> None:
    page.goto(site)

    expect(page.locator("details.service .name")).to_have_text(["team/svc"])
    expect(page.locator(".issue-row code")).to_have_text(["SHOP-9", "SHOP-12"])
    assert errors == []


def test_choosing_an_issue_picks_its_release_tag_and_survives_a_reload(
    page: Page, site: str, errors: list[str]
) -> None:
    page.goto(site)

    _issue(page, "SHOP-12").check()

    chip: typing.Final = page.locator("details.service .chip > span")
    expect(chip).to_have_text("1.2.0")
    expect(page.locator(".plan-line")).to_contain_text("for SHOP-12")
    expect(page).to_have_url(re.compile(r"#issues=SHOP-12&team/svc=1\.2\.0$"))
    page.reload()
    expect(chip).to_have_text("1.2.0")
    expect(_issue(page, "SHOP-12")).to_be_checked()
    assert errors == []


def test_picking_a_tag_by_hand_shows_its_chip_and_closes_the_service(page: Page, site: str, errors: list[str]) -> None:
    page.goto(site)

    page.locator("details.service summary").click()
    page.locator(".tag", has_text="1.1.0").get_by_role("button").click()

    expect(page.locator("details.service .chip > span")).to_have_text("1.1.0")
    expect(page.locator("details.service")).not_to_have_attribute("open", re.compile(".*"))
    expect(page).to_have_url(re.compile(r"#team/svc=1\.1\.0$"))
    assert errors == []


def test_russian_page_has_no_untranslated_placeholders(page: Page, site: str, errors: list[str]) -> None:
    page.goto(site)
    _issue(page, "SHOP-12").check()

    page.get_by_role("combobox").first.select_option("ru")

    expect(page.locator("h1")).to_have_text("Состав релиза")
    expect(page.locator("main")).not_to_contain_text(re.compile(r"\{\w+\}"))
    assert errors == []
