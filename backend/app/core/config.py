from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://aussiinvest:password@db:5432/aussiinvest"
    REDIS_URL: str = "redis://redis:6379/0"
    SECRET_KEY: str = "dev-secret-change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24h
    
    TELEGRAM_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    
    ALPACA_API_KEY: str = ""
    ALPACA_SECRET_KEY: str = ""
    ALPACA_BASE_URL: str = "https://paper-api.alpaca.markets"
    
    T212_API_KEY: str = ""
    
    class Config:
        env_file = ".env"

settings = Settings()
