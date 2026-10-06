"""Настройки из окружения. Секреты приходят из /opt/sunscrypt/.env через
Docker Compose и наружу не отдаются: SecretStr не печатается в логах."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    database_url: str = "postgresql+psycopg://sunscrypt:sunscrypt@localhost:5432/sunscrypt"
    redis_url: str = "redis://localhost:6379/0"
    git_commit: str = "dev"
    # Тесты: без пула соединений (у каждого TestClient свой цикл событий).
    db_nullpool: bool = False
    # Адрес сайта — для ссылок в письмах.
    public_url: str = "http://localhost:3000"

    master_key: SecretStr | None = None
    session_secret: SecretStr | None = None

    # Владелец: создаётся при запуске, если его ещё нет (секреты
    # SUNSCRYPT_OWNER_EMAIL / SUNSCRYPT_OWNER_PASSWORD). Пароль потом не
    # перезаписывается — его можно сменить в кабинете.
    owner_email: str | None = None
    owner_password: SecretStr | None = None

    session_days: int = 30
    cookie_secure: bool = True

    # Почта. Без SMTP_HOST письма копятся в outbox_emails и не уходят.
    smtp_host: str | None = None
    smtp_port: int = 465
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str = "SUNSCRYPT <noreply@localhost>"


@lru_cache
def get_settings() -> Settings:
    return Settings()
