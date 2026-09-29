import typing


class ReleaseScopeError(Exception):
    exit_code: typing.ClassVar[int] = 1


class ConfigError(ReleaseScopeError):
    exit_code: typing.ClassVar[int] = 2


class AuthError(ReleaseScopeError):
    exit_code: typing.ClassVar[int] = 3


class GitLabError(ReleaseScopeError):
    exit_code: typing.ClassVar[int] = 4

    def __init__(self, message: str, *, resource: str, status: int | None = None, reason: str = "") -> None:
        super().__init__(message)
        self.resource = resource
        self.status = status
        self.reason = reason


class JiraError(ReleaseScopeError):
    pass
