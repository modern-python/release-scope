import collections.abc
import pathlib
import re
import typing

import pytest
import respx
from playwright.sync_api import ConsoleMessage, Error, Locator, Page, expect
from typer.testing import CliRunner

from demo.build import build
from demo.screenshot import capture
from demo.server import serve
from release_scope import ioc
from release_scope.__main__ import MAIN_APP
from tests.payloads import ENDPOINT, JIRA_ENDPOINT


pytestmark = pytest.mark.smoke


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
    with serve(output) as url:
        yield url


@pytest.fixture
def demo_site(tmp_path: pathlib.Path) -> collections.abc.Iterator[str]:
    output: typing.Final = tmp_path / "demo"
    build(output)
    with serve(output) as url:
        yield url


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


def test_demo_lists_its_services_and_picks_tags_for_an_issue(page: Page, demo_site: str, errors: list[str]) -> None:
    page.goto(demo_site)

    expect(page.locator("details.service .name")).to_have_text(["shop/admin", "shop/api", "shop/web", "shop/worker"])
    expect(page.locator(".issue-row code")).to_have_count(6)
    _issue(page, "SHOP-38").check()
    expect(page).to_have_url(re.compile(r"#issues=SHOP-38&shop/api=2\.5\.0&shop/web=1\.9\.0$"))
    assert errors == []


def test_demo_screenshot_shows_an_issue_with_its_picks(
    page: Page, demo_site: str, errors: list[str], tmp_path: pathlib.Path
) -> None:
    output: typing.Final = tmp_path / "screenshot.png"

    capture(page, demo_site, output)

    assert output.read_bytes().startswith(b"\x89PNG")
    expect(page.locator("details.service .chip:visible > span")).to_have_text(["2.5.0", "1.9.0"])
    assert errors == []


def test_clearing_an_issue_pick_unticks_the_issue_and_survives_a_reload(
    page: Page, site: str, errors: list[str]
) -> None:
    page.goto(site)
    _issue(page, "SHOP-12").check()

    page.locator("details.service .chip").get_by_role("button").click()

    expect(_issue(page, "SHOP-12")).not_to_be_checked()
    expect(page.locator("details.service .chip")).to_be_hidden()
    expect(page).not_to_have_url(re.compile("#"))
    page.reload()
    expect(page.locator("details.service .chip")).to_be_hidden()
    assert errors == []


def test_picking_an_older_tag_unticks_the_issues_it_misses(page: Page, site: str, errors: list[str]) -> None:
    page.goto(site)
    _issue(page, "SHOP-12").check()

    page.locator("details.service summary").click()
    page.locator(".tag", has_text="1.1.0").get_by_role("button").click()

    expect(_issue(page, "SHOP-12")).not_to_be_checked()
    expect(page.locator("details.service .chip > span")).to_have_text("1.1.0")
    expect(page).to_have_url(re.compile(r"#team/svc=1\.1\.0$"))
    assert errors == []


def test_an_address_with_an_older_pick_unticks_the_issues_it_misses(page: Page, site: str, errors: list[str]) -> None:
    page.goto(f"{site}#issues=SHOP-12&team/svc=1.1.0")

    expect(_issue(page, "SHOP-12")).not_to_be_checked()
    expect(page.locator("details.service .chip > span")).to_have_text("1.1.0")
    expect(page).to_have_url(re.compile(r"#team/svc=1\.1\.0$"))
    assert errors == []


def _demo_service(page: Page, project: str) -> Locator:
    return page.locator("details.service", has=page.locator(".name", has_text=project))


def test_demo_clearing_one_service_pick_unticks_the_issue_in_every_service(
    page: Page, demo_site: str, errors: list[str]
) -> None:
    page.goto(demo_site)
    _issue(page, "SHOP-38").check()

    _demo_service(page, "shop/api").locator(".chip").get_by_role("button").click()

    expect(_issue(page, "SHOP-38")).not_to_be_checked()
    expect(_demo_service(page, "shop/web").locator(".chip")).to_be_hidden()
    expect(page).not_to_have_url(re.compile("#"))
    assert errors == []


def test_demo_picking_an_older_tag_keeps_it_and_clears_the_other_service(
    page: Page, demo_site: str, errors: list[str]
) -> None:
    page.goto(demo_site)
    _issue(page, "SHOP-38").check()

    api: typing.Final = _demo_service(page, "shop/api")
    api.locator("summary").click()
    api.locator(".tag", has_text="2.4.0").get_by_role("button").click()

    expect(_issue(page, "SHOP-38")).not_to_be_checked()
    expect(api.locator(".chip > span")).to_have_text("2.4.0")
    expect(_demo_service(page, "shop/web").locator(".chip")).to_be_hidden()
    expect(page).to_have_url(re.compile(r"#shop/api=2\.4\.0$"))
    assert errors == []


def test_demo_a_shared_pick_stays_while_another_chosen_issue_needs_it(
    page: Page, demo_site: str, errors: list[str]
) -> None:
    page.goto(demo_site)
    _issue(page, "SHOP-38").check()
    _issue(page, "SHOP-36").check()

    _demo_service(page, "shop/api").locator(".chip").get_by_role("button").click()

    expect(_issue(page, "SHOP-38")).not_to_be_checked()
    expect(_issue(page, "SHOP-36")).to_be_checked()
    expect(_demo_service(page, "shop/web").locator(".chip > span")).to_have_text("1.9.0")
    expect(page).to_have_url(re.compile(r"#issues=SHOP-36&shop/web=1\.9\.0$"))
    assert errors == []


def test_demo_a_hand_pick_survives_when_the_issue_is_unticked(page: Page, demo_site: str, errors: list[str]) -> None:
    page.goto(demo_site)
    _issue(page, "SHOP-38").check()

    web: typing.Final = _demo_service(page, "shop/web")
    web.locator("summary").click()
    web.locator(".tag", has_text="1.9.1").get_by_role("button").click()
    expect(_issue(page, "SHOP-38")).to_be_checked()
    _demo_service(page, "shop/api").locator(".chip").get_by_role("button").click()

    expect(_issue(page, "SHOP-38")).not_to_be_checked()
    expect(web.locator(".chip > span")).to_have_text("1.9.1")
    expect(page).to_have_url(re.compile(r"#shop/web=1\.9\.1$"))
    assert errors == []


_SHOWN_COLOR_JS: typing.Final = """element => {
    let alpha = 1;
    for (let node = element; node; node = node.parentElement) alpha *= Number(getComputedStyle(node).opacity);
    return [getComputedStyle(element).color, getComputedStyle(document.body).backgroundColor, alpha];
}"""


def _luminance(color: str) -> float:
    channels: typing.Final = [int(value) / 255 for value in re.findall(r"\d+", color)[:3]]
    linear: typing.Final = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(element: Locator) -> float:
    color, background, alpha = element.evaluate(_SHOWN_COLOR_JS)
    text, ground = _luminance(color), _luminance(background)
    shown: typing.Final = alpha * text + (1 - alpha) * ground
    return (max(shown, ground) + 0.05) / (min(shown, ground) + 0.05)


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_demo_an_idle_service_keeps_readable_text(
    page: Page, demo_site: str, errors: list[str], scheme: typing.Literal["light", "dark"]
) -> None:
    page.emulate_media(color_scheme=scheme)
    page.goto(demo_site)
    _issue(page, "SHOP-38").check()

    worker: typing.Final = _demo_service(page, "shop/worker")
    expect(worker).to_have_class(re.compile(r"\bidle\b"))
    for text in worker.locator("summary span:visible").all():
        assert _contrast(text) >= 4.5, text.inner_text()
    assert errors == []


def test_demo_the_side_column_takes_two_fifths_of_a_wide_window(page: Page, demo_site: str, errors: list[str]) -> None:
    page.set_viewport_size({"width": 1920, "height": 900})
    page.goto(demo_site)

    layout: typing.Final = page.locator(".layout").bounding_box()
    box: typing.Final = page.locator(".layout > aside").bounding_box()

    assert layout is not None
    assert box is not None
    assert box["width"] == pytest.approx((layout["width"] - 24) * 0.4, abs=1)
    assert errors == []


def _left(element: Locator) -> float:
    box: typing.Final = element.bounding_box()
    assert box is not None
    return box["x"]


def test_demo_service_rows_line_up_with_and_without_a_pick(page: Page, demo_site: str, errors: list[str]) -> None:
    page.goto(f"{demo_site}#shop/web=1.9.0")
    expect(_demo_service(page, "shop/web").locator(".chip")).to_be_visible()

    names: typing.Final = [
        _left(_demo_service(page, project).locator(".name")) for project in ("shop/admin", "shop/api")
    ]
    states: typing.Final = [
        _left(_demo_service(page, project).locator("summary .warn").first)
        for project in ("shop/api", "shop/web", "shop/worker")
    ]

    assert names[0] == pytest.approx(names[1], abs=0.5)
    assert max(states) - min(states) < 0.5, states
    assert errors == []
