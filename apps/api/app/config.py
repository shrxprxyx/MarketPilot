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

    # The API sits behind the web app's proxy, so request.client is the proxy. When this is on,
    # the last X-Forwarded-For entry (the address the proxy saw) is the caller's address, which
    # the login lockout and the audit log use. Leave it off if the API is reachable directly,
    # because then any caller could set the header.
    trust_forwarded_for: bool = False

    # Google PageSpeed Insights key (free, from Google Cloud). Without it audits skip the page
    # speed step and still finish.
    pagespeed_api_key: str = ""

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


settings = Settings()