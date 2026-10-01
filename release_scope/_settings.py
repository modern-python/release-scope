import typing

import pydantic
import pydantic_settings

from release_scope._errors import ConfigError


class GitLabConfig(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(
        env_prefix="RELEASE_SCOPE_GITLAB__",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    endpoint: str = "https://gitlab.com"
    token: pydantic.SecretStr = pydantic.Field(
        default=pydantic.SecretStr(""),
        validation_alias=pydantic.AliasChoices("RELEASE_SCOPE_GITLAB__TOKEN", "GITLAB_TOKEN"),
    )


class Settings(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(
        env_prefix="RELEASE_SCOPE_",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    gitlab: GitLabConfig = pydantic.Field(default_factory=GitLabConfig)
    jira_endpoint: str | None = None
    jira_token: pydantic.SecretStr = pydantic.Field(
        default=pydantic.SecretStr(""),
        validation_alias=pydantic.AliasChoices("RELEASE_SCOPE_JIRA_TOKEN", "JIRA_TOKEN"),
    )
    jira_project_keys: list[str] = pydantic.Field(default_factory=list)
    environments: list[str] = pydantic.Field(default_factory=lambda: ["production"])
    production_environment: str = "production"
    request_timeout: float = 10.0
    max_commits: int = 1000

    @pydantic.model_validator(mode="after")
    def _production_is_listed(self) -> typing.Self:
        if self.production_environment not in self.environments:
            self.environments = [self.production_environment, *self.environments]
        return self


def load_settings() -> Settings:
    try:
        settings: typing.Final = Settings()
    except pydantic.ValidationError as exc:
        msg = f"Invalid configuration: {exc}"
        raise ConfigError(msg) from exc
    if not settings.gitlab.token.get_secret_value():
        msg = "GitLab token is missing. Set RELEASE_SCOPE_GITLAB__TOKEN or GITLAB_TOKEN."
        raise ConfigError(msg)
    if settings.jira_token.get_secret_value() and not settings.jira_endpoint:
        msg = "Jira token is set but RELEASE_SCOPE_JIRA_ENDPOINT is not."
        raise ConfigError(msg)
    return settings
