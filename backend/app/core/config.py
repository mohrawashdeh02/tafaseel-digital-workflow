from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./backend/tafaseel.db"
    environment: str = "development"
    jwt_secret: str = "development-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 480
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
