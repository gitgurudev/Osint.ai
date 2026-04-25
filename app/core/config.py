import os
from functools import lru_cache
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # Search & scrape
    search_num_results: int = int(os.getenv("SEARCH_NUM_RESULTS", "10"))
    scrape_timeout: int     = int(os.getenv("SCRAPE_TIMEOUT", "10"))
    max_content_chars: int  = int(os.getenv("MAX_CONTENT_CHARS", "4000"))

    # OpenAI
    openai_api_key: str  = os.getenv("OPENAI_API_KEY", "")
    openai_model: str    = os.getenv("OPENAI_MODEL", "gpt-4o")
    llm_content_limit: int = int(os.getenv("LLM_CONTENT_LIMIT", "6000"))

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
