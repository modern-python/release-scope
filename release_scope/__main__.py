import functools
import importlib.metadata
import pathlib
import typing

import modern_di_typer
import typer

from release_scope import ioc
from release_scope._cache import Cache
from release_scope._errors import ConfigError, ReleaseScopeError
from release_scope._files import write_site
from release_scope._jira_keys import JIRA_KEY_PATTERN
from release_scope._report import Report
from release_scope._use_case import CollectUseCase


_PACKAGE_NAME: typing.Final = "release-scope"


MAIN_APP: typing.Final = typer.Typer(
    name="release-scope",
    help="Collect what sits between production and the default branch across GitLab services.",
    no_args_is_help=True,
    add_completion=False,
)

modern_di_typer.setup_di(MAIN_APP, ioc.container)


def _version_callback(value: bool) -> None:
    if not value:
        return
    typer.echo(importlib.metadata.version(_PACKAGE_NAME))
    raise typer.Exit


@MAIN_APP.callback()
def _main_callback(
    _version: typing.Annotated[
        bool | None,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version and exit."),
    ] = None,
) -> None:
    pass


_P = typing.ParamSpec("_P")


def _exit_on_error(func: typing.Callable[_P, None]) -> typing.Callable[_P, None]:
    @functools.wraps(func)
    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> None:
        try:
            func(*args, **kwargs)
        except ReleaseScopeError as err:
            typer.echo(f"Error: {err}", err=True)
            raise typer.Exit(code=err.exit_code) from err

    return wrapper


@MAIN_APP.command("collect", help="Collect pending changes per service into a static site with a JSON report.")
@_exit_on_error
@modern_di_typer.inject
def _collect_command(  # noqa: PLR0913, PLR0917
    use_case: typing.Annotated[CollectUseCase, modern_di_typer.FromDI(CollectUseCase)],
    output: typing.Annotated[
        pathlib.Path, typer.Option("--output", "-o", help="Directory for the site: index.html and report.json.")
    ],
    group: typing.Annotated[
        list[str] | None, typer.Option("--group", "-g", help="GitLab group path; repeatable.")
    ] = None,
    project: typing.Annotated[
        list[str] | None, typer.Option("--project", "-p", help="GitLab project path; repeatable.")
    ] = None,
    include_subgroups: typing.Annotated[
        bool, typer.Option("--include-subgroups", help="Also collect projects in subgroups of each --group.")
    ] = False,
    cache_path: typing.Annotated[
        pathlib.Path | None,
        typer.Option("--cache", help="Cache JSON; read if present, rewritten in place after the run."),
    ] = None,
    jira: typing.Annotated[
        list[str] | None,
        typer.Option("--jira", "-j", help="Jira issue key; collect only the services it links to. Repeatable."),
    ] = None,
) -> None:
    _check_selection(groups=group or [], projects=project or [], keys=jira or [])
    cache, cache_warning = Cache.load(cache_path) if cache_path else (Cache(), None)
    if cache_warning:
        typer.echo(f"Warning: {cache_warning}", err=True)
    if jira:
        report = use_case.for_issues(keys=list(dict.fromkeys(jira)), cache=cache)
    else:
        report = use_case(groups=group or [], projects=project or [], include_subgroups=include_subgroups, cache=cache)
    write_site(output, report.model_dump_json(indent=2))
    if cache_path:
        cache.save(cache_path)
    failed: typing.Final = [service for service in report.services if service.error]
    rows: typing.Final = sum(len(service.rows) for service in report.services)
    typer.echo(f"{len(report.services)} services, {rows} rows, {len(failed)} failed -> {output}", err=True)
    for service in failed:
        typer.echo(f"Error: {service.error}", err=True)
    jira_errors: typing.Final = _jira_errors(report)
    for message in jira_errors:
        typer.echo(f"Error: {message}", err=True)
    if failed or jira_errors:
        raise typer.Exit(code=1)


def _check_selection(
    *, groups: typing.Sequence[str], projects: typing.Sequence[str], keys: typing.Sequence[str]
) -> None:
    if keys and (groups or projects):
        msg = "Pass either --jira or --group/--project, not both."
        raise ConfigError(msg)
    if not keys and not groups and not projects:
        msg = "Pass --jira, or at least one --group or --project."
        raise ConfigError(msg)
    for key in keys:
        if not JIRA_KEY_PATTERN.fullmatch(key):
            msg = f"Not a Jira issue key: {key}."
            raise ConfigError(msg)


def _jira_errors(report: Report) -> list[str]:
    if report.jira is None:
        return []
    errors: typing.Final = [f"Jira has no issue {key}." for key in report.jira_scope if key in report.jira.missing]
    if report.jira.error:
        errors.append(report.jira.error)
    return errors


def main() -> None:
    with ioc.container:
        MAIN_APP()


if __name__ == "__main__":
    main()
