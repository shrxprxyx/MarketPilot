from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../../.env", ".env"), extra="ignore")

    app_name: str = "MarketPilot API"
    database_url: str
    database_url_direct: str
    redis_url: str
    jwt_secret: str
    fernet_keys: str
    allowed_origins: str = "http://localhost:3000"
    app_user_db_password: str = "app_user_dev_password"
    # Model-provider base URLs (Ollama, OpenAI-compatible) pointing at loopback or private
    # networks are refused unless this is on. Turn it on for a self-hosted or local setup.
    allow_private_base_urls: bool = False
    # Multiplies every per-user and per-tenant rate limit (app.core.rate_limit). Leave at 1 in
    # production; the test suite raises it so unrelated tests that share a tenant never trip it.
    rate_limit_scale: float = 1.0

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


settings = Settings()