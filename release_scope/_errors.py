import typing


class ReleaseScopeError(Exception):
    exit_code: typing.ClassVar[int] = 1


class ConfigError(ReleaseScopeError):
    exit_code: typing.ClassVar[int] = 2


class AuthError(ReleaseScopeError):
    exit_code: typing.ClassVar[int] = 3


class GitLabError(ReleaseScopeError):
    exit_code: typing.ClassVar[int] = 4
