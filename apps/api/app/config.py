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

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


settings = Settings()