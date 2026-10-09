import importlib.resources
import re
import typing

from release_scope._report import MessageCode


_PAGE: typing.Final = importlib.resources.files("release_scope").joinpath("_static/index.html").read_text()


def _block(start: str, end: str) -> str:
    return _PAGE[_PAGE.index(start) : _PAGE.index(end)]


def _keys(block: str, indent: int) -> set[str]:
    return set(re.findall(rf"^ {{{indent}}}(\w+):", block, re.MULTILINE))


def test_every_translation_key_exists_in_both_languages() -> None:
    strings: typing.Final = _block("const STRINGS = {", "const PERMISSIONS")
    english, russian = strings.split("\n    ru: {")
    used: typing.Final = set(re.findall(r"(?<!\w)t\([\"'](\w+)[\"']", _PAGE))

    assert used
    assert used <= _keys(english, 6)
    assert _keys(english, 6) == _keys(russian, 6)


def test_every_message_code_has_a_russian_rendering() -> None:
    russian: typing.Final = _block("const MESSAGES = {", "const PLURALS")

    assert _keys(russian, 6) == {code.value for code in MessageCode}
