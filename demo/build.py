import datetime as dt
import json
import os
import pathlib
import sys
import typing
from unittest import mock

import pytest_httpx2  # noqa: F401  registers the httpcore2 mocker with respx
import respx
from typer.testing import CliRunner

from demo import scenario
from release_scope import ioc
from release_scope.__main__ import MAIN_APP


_ENV: typing.Final = {
    "GITLAB_TOKEN": "demo",
    "RELEASE_SCOPE_GITLAB__ENDPOINT": scenario.ENDPOINT,
    "RELEASE_SCOPE_ENVIRONMENTS": json.dumps(scenario.ENVIRONMENTS),
    "RELEASE_SCOPE_JIRA_ENDPOINT": scenario.JIRA_ENDPOINT,
    "JIRA_TOKEN": "demo",
}


def build(output: pathlib.Path) -> None:
    now: typing.Final = dt.datetime.now(dt.UTC).replace(minute=0, second=0, microsecond=0)
    with (
        mock.patch.dict(os.environ, _ENV),
        respx.mock(using="httpcore2", assert_all_called=False) as router,
        ioc.container,
    ):
        scenario.mock(router, now)
        result: typing.Final = CliRunner().invoke(MAIN_APP, ["collect", "-g", scenario.GROUP, "-o", str(output)])
    if result.exit_code != 0:
        msg = f"collect exited with {result.exit_code}:\n{result.output}"
        raise RuntimeError(msg)


if __name__ == "__main__":
    build(pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "site"))
