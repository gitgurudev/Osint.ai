from pydantic import BaseModel, Field
from typing import List, Optional


class Entity(BaseModel):
    id: str
    confidence: int = Field(..., ge=0, le=100)
    sources: List[str]


class RankedSource(BaseModel):
    url: str
    credibility_score: float = Field(..., ge=0.0, le=1.0)


class EmailMeta(BaseModel):
    email: str
    username: str
    name_guess: str
    domain: str
    provider: str
    account_type: str   # personal | corporate | educational


class OSINTReport(BaseModel):
    query: str
    llm_enhanced: bool
    summary: Optional[str] = None
    email_meta: Optional[EmailMeta] = None   # populated only when input is an email
    profiles_found: List[str]
    ranked_sources: List[RankedSource]
    entities: List[Entity]
    insights: List[str]
