from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    app_name: str = "enterprise-rag-platform"
    debug: bool = True
    host: str = "0.0.0.0"
    port: int = 8000
    data_dir: Path = Path(__file__).resolve().parents[1] / "data"


settings = Settings()
