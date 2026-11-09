from dataclasses import dataclass


@dataclass
class Settings:
    app_name: str = "aurelia"
    debug: bool = True
    host: str = "0.0.0.0"
    port: int = 8000


settings = Settings()
