"""Configuration technique (variables d'environnement / fichier .env).

Les réglages « métier » (critères du bien, seuils, pondérations…) ne sont PAS ici :
ils se modifient dans l'application (page Réglages) — voir app/settings_schema.py.
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Env(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://paradis:paradis@db:5432/paradis"
    data_dir: Path = Path("/data")

    # Clés API (facultatives tant que l'étape correspondante n'est pas atteinte)
    anthropic_api_key: str = ""
    tomtom_api_key: str = ""

    # Identification du robot de collecte (user-agent)
    contact_email: str = ""
    bot_name: str = "NotreParadisBot"

    # Planificateur : désactivable (tests, développement)
    scheduler_enabled: bool = True

    @property
    def user_agent(self) -> str:
        contact = f"; contact: {self.contact_email}" if self.contact_email else ""
        return f"{self.bot_name}/0.1 (outil personnel de recherche immobiliere{contact})"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def public_data_dir(self) -> Path:
        return self.data_dir / "public"

    @property
    def photos_dir(self) -> Path:
        return self.data_dir / "photos"


env = Env()
