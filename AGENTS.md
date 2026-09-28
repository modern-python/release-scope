# AGENTS.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`release-scope` reports, per GitLab service, every change between production and the default branch as one JSON
report. [`CONTEXT.md`](CONTEXT.md) owns the vocabulary; read it before naming a concept in code, a test name, or an
issue title.

## Commands

`just` (task runner) and `uv` (package manager). The [`justfile`](justfile) is the source of truth —
`just --list`, or read it. Never run bare `ruff check`: `[tool.ruff]` sets `fix = true` and `unsafe-fixes = true`.

## Architecture

`_use_case.py` drives one run; `_gitlab.py` is the only module that speaks HTTP; `_rows.py` is pure and turns the
range plus merge requests into rows. Tests mock GitLab only with respx routes (pytest-httpx2): the `gitlab` fixture in
`tests/conftest.py` declares one named static route per call of the scenario in `tests/payloads.py`. A test changes
a response by re-mocking a named route; add no fakes, callbacks, or stubs.

The package must stay free of any company's hostnames, group paths, job names, or Jira project keys: every such value
comes from settings. The repo is public.

## Workflow

Every link in `README.md` must be absolute: `https://github.com/modern-python/<repo>/blob/main/<path>`,
or `.../tree/main/<path>` for a directory. Never a relative path: `README.md` is also the PyPI long
description, and PyPI does not rewrite relative links, so a relative one 404s on the package page.

## Agent skills

### Issue tracker

GitHub issues on `modern-python/release-scope`, via `gh`. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles, each label string equal to its name. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
