from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT / ".env", Path(".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""
    groq_api_key: str = ""
    groq_llm_model: str = "openai/gpt-oss-20b"
    groq_stt_model: str = "whisper-large-v3-turbo"
    tts_provider: str = "edge"
    edge_tts_voice: str = "en-US-AvaNeural"
    openai_llm_model: str = "gpt-4o-mini"
    openai_tts_model: str = "tts-1"
    openai_tts_voice: str = "nova"


def get_settings() -> Settings:
    return Settings()


def keys_status() -> dict[str, bool]:
    s = get_settings()
    return {
        "groq": bool(s.groq_api_key),
        "openai": bool(s.openai_api_key),
    }
