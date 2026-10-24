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

    expect(page.locator("details.service .name")).to_have_text(["svc"])
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

    names = page.locator("details.service .name")
    expect(names).to_have_text(["shop/admin", "api", "web", "worker"])
    expect(names.nth(1)).to_have_attribute("title", "shop/api")
    expect(page.locator(".issue-row code")).to_have_count(9)
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
    return page.locator("details.service", has=page.locator(f'.name[title="{project}"]'))


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


def test_demo_only_a_key_the_change_does_not_mention_is_marked_as_via_jira(
    page: Page, demo_site: str, errors: list[str]
) -> None:
    page.goto(demo_site)

    api: typing.Final = _demo_service(page, "shop/api")
    api.locator("summary").click()

    linked: typing.Final = api.locator(".row-key.via-jira")
    expect(linked).to_have_count(1)
    expect(linked.locator("a")).to_have_text("SHOP-33")
    expect(linked.locator(".via")).to_have_text("via Jira")
    expect(linked).to_have_attribute("title", "Not mentioned in !54. SHOP-33 links to it in Jira.")
    expect(api.locator(".row-key", has=page.locator("a", has_text="SHOP-38")).locator(".via")).to_be_hidden()
    assert errors == []


def test_demo_names_a_service_by_its_repo_and_keeps_the_group_only_when_two_share_a_name(
    page: Page, demo_site: str, errors: list[str]
) -> None:
    page.goto(demo_site)

    _issue(page, "SHOP-38").check()

    outside: typing.Final = page.locator(".service.unlisted b")
    expect(outside).to_have_text(["mobile"])
    expect(outside).to_have_attribute("title", "partners/mobile")
    expect(page.locator(".issue-row", has=page.locator("code", has_text="SHOP-44")).locator(".cell")).to_have_text(
        ["shop/admin not merged", "legacy/admin not in this report"]
    )
    assert errors == []


def _pick_by_hand(page: Page, project: str, tag: str) -> None:
    service: typing.Final = _demo_service(page, project)
    service.locator("summary").click()
    service.locator(".tag", has_text=tag).get_by_role("button").click()


def test_demo_a_hand_pick_lists_what_it_leaves_behind_under_each_task(
    page: Page, demo_site: str, errors: list[str]
) -> None:
    page.goto(demo_site)
    tasks: typing.Final = page.locator(".gap-task")

    _pick_by_hand(page, "shop/api", "2.5.0")

    expect(tasks.locator(".gap-head")).to_have_text(
        ["SHOP-38 Export orders as CSV", "SHOP-35 VAT is off by a cent on mixed carts"]
    )
    export: typing.Final = tasks.first
    expect(export.locator(".gap-head a")).to_have_attribute("href", "https://jira.example.com/browse/SHOP-38")
    expect(export.locator(".gap-line")).to_have_text(
        [
            "web needs 1.9.0 Pick 1.9.0",
            "mobile not in this report",
            "shop/admin not merged !15",
            "legacy/admin not in this report",
        ]
    )
    expect(export.locator(".gap-dep-head")).to_have_text(["is blocked by SHOP-44 Only managers may export orders"])
    expect(export.get_by_role("link", name="!15")).to_have_attribute(
        "href", "https://gitlab.example.com/shop/admin/-/merge_requests/15"
    )

    _pick_by_hand(page, "shop/web", "1.9.0")

    expect(tasks.locator(".gap-head")).to_have_text(
        ["SHOP-38 Export orders as CSV", "SHOP-35 VAT is off by a cent on mixed carts", "SHOP-36 Dark mode"]
    )
    expect(tasks.nth(2).locator(".gap-dep-head")).to_have_text(
        [
            "is blocked by SHOP-45 Pick the dark palette with design To Do",
            "has subtask SHOP-46 Dark mode in emails To Do",
        ]
    )
    assert errors == []


def test_demo_picking_the_tag_a_left_behind_line_needs_keeps_the_service_closed(
    page: Page, demo_site: str, errors: list[str]
) -> None:
    page.goto(demo_site)
    _pick_by_hand(page, "shop/api", "2.5.0")

    page.locator(".gap-line", has_text="web").get_by_role("button", name="Pick 1.9.0").click()

    expect(_demo_service(page, "shop/web").locator(".chip > span")).to_have_text("1.9.0")
    expect(page.locator(".gap-line", has_text="web")).to_have_count(0)
    expect(page).to_have_url(re.compile(r"#shop/api=2\.5\.0&shop/web=1\.9\.0$"))
    assert errors == []


def test_demo_picking_every_needed_tag_at_once(page: Page, demo_site: str, errors: list[str]) -> None:
    page.goto(demo_site)
    _pick_by_hand(page, "shop/api", "2.5.0")

    page.get_by_role("button", name="Pick 2 needed tags").click()

    expect(_demo_service(page, "shop/web").locator(".chip > span")).to_have_text("1.9.0")
    expect(_demo_service(page, "shop/worker").locator(".chip > span")).to_have_text("0.15.0")
    assert errors == []


def test_demo_tasks_name_the_changes_that_bring_them(page: Page, demo_site: str, errors: list[str]) -> None:
    page.goto(demo_site)

    _issue(page, "SHOP-38").check()

    task: typing.Final = page.locator(".outputs li", has=page.locator("a", has_text="SHOP-38"))
    expect(task.locator(".sources")).to_have_text("from api !57, web !120")
    expect(page.locator(".outputs li", has=page.locator("a", has_text="SHOP-35")).locator(".sources")).to_have_text(
        "from api !55"
    )
    assert errors == []


def test_demo_related_issues_have_their_own_group_and_relations_show_on_hover(
    page: Page, demo_site: str, errors: list[str]
) -> None:
    page.goto(demo_site)

    expect(page.locator(".issue-group")).to_have_text(["Done · 3", "Not done · 3", "Related · 3"])
    expect(page.locator(".issue-row code", has_text="SHOP-38")).to_have_attribute("title", "is blocked by SHOP-44")
    assert errors == []


def test_demo_left_behind_list_reads_in_russian(page: Page, demo_site: str, errors: list[str]) -> None:
    page.goto(demo_site)
    _pick_by_hand(page, "shop/api", "2.5.0")
    _pick_by_hand(page, "shop/web", "1.9.0")

    page.get_by_role("combobox").first.select_option("ru")

    expect(page.locator(".gaps > p > span")).to_have_text("Не войдёт в релиз с выбранными тегами:")  # noqa: RUF001
    expect(page.locator(".gap-line", has_text="worker")).to_have_text("worker нужен тег 0.15.0 Выбрать 0.15.0")
    expect(page.locator(".gap-dep-head").last).to_have_text("включает подзадачу SHOP-46 Dark mode in emails To Do")
    expect(page.get_by_role("button", name="Выбрать 1 нужный тег")).to_be_visible()
    assert errors == []
