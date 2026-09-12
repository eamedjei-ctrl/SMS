from __future__ import annotations

import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class BaseConfig:
    ENV_NAME = os.environ.get("FLASK_ENV", "development")
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-secret")
    APP_BASE_DOMAIN = os.environ.get("APP_BASE_DOMAIN", "schoolos.com")
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://schoolos:schoolos@localhost:5432/schoolos"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_size": _int("DB_POOL_SIZE", 10),
        "max_overflow": _int("DB_MAX_OVERFLOW", 20),
        "pool_pre_ping": True,
    }

    REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
    REDIS_CACHE_DB = _int("REDIS_CACHE_DB", 0)
    REDIS_SESSION_DB = _int("REDIS_SESSION_DB", 1)
    REDIS_QUEUE_DB = _int("REDIS_QUEUE_DB", 2)
    REDIS_RATELIMIT_DB = _int("REDIS_RATELIMIT_DB", 3)

    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", SECRET_KEY)
    JWT_ACCESS_TOKEN_MINUTES = _int("JWT_ACCESS_TOKEN_MINUTES", 30)
    JWT_REFRESH_TOKEN_DAYS = _int("JWT_REFRESH_TOKEN_DAYS", 7)
    JWT_ALGORITHM = "HS256"

    LOGIN_MAX_ATTEMPTS = _int("LOGIN_MAX_ATTEMPTS", 5)
    LOGIN_LOCKOUT_MINUTES = _int("LOGIN_LOCKOUT_MINUTES", 15)
    PASSWORD_MIN_LENGTH = _int("PASSWORD_MIN_LENGTH", 8)

    DEFAULT_PAGE_SIZE = _int("DEFAULT_PAGE_SIZE", 25)
    MAX_PAGE_SIZE = _int("MAX_PAGE_SIZE", 100)

    STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "local")
    STORAGE_LOCAL_PATH = os.environ.get("STORAGE_LOCAL_PATH", "/var/lib/schoolos/storage")

    CORS_ORIGINS = [o for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o]


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class TestingConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    SQLALCHEMY_ENGINE_OPTIONS: dict = {}
    JWT_SECRET_KEY = "testing-secret"
    STORAGE_LOCAL_PATH = os.environ.get("TEST_STORAGE_PATH", "")


class ProductionConfig(BaseConfig):
    DEBUG = False


CONFIGS = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "staging": ProductionConfig,
    "production": ProductionConfig,
}


def get_config(name: str | None = None):
    return CONFIGS.get(name or os.environ.get("FLASK_ENV", "development"), DevelopmentConfig)
