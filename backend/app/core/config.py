from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'JusClipIt API'
    environment: str = 'development'
    database_url: str = "sqlite+aiosqlite:///./jusclipit.db"
    redis_url: str = 'redis://localhost:6379/0'
    s3_bucket: str = 'jusclipit-videos'
    s3_region: str = 'us-east-1'
    openai_api_key: str = ''

    stripe_secret_key: str = ''
    stripe_webhook_secret: str = ''
    stripe_price_pro_monthly: str = ''
    app_base_url: str = 'http://localhost:3000'


settings = Settings()
