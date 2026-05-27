"""Pydantic models for API request/response."""
from pydantic import BaseModel, Field
from typing import Optional, List, Any


# --- Memory ---
class MemoryQuery(BaseModel):
    keyword: str = ""
    domain: str = ""
    limit: int = Field(default=20, ge=1, le=100)


class MemoryAdd(BaseModel):
    name: str
    domain: str = "general"
    pattern: str
    description: str = ""
    source: str = "session"


# --- Session ---
class SessionLog(BaseModel):
    session_id: str
    tool: str  # claude_code / codex
    goal: str
    outcome: str = ""  # success / failure / partial
    changed_files: List[str] = []
    lessons: str = ""
    duration_sec: int = 0
    git_diff: str = ""  # Phase 2: git diff for skill extraction


# --- Skills ---
class SkillRecall(BaseModel):
    scenario: str
    domain: str = ""
    limit: int = Field(default=5, ge=1, le=20)


class SkillUpdate(BaseModel):
    skill_key: str
    success: bool


# --- Patterns ---
class PatternLearn(BaseModel):
    name: str
    domain: str
    description: str
    code_example: str = ""
    source_repo: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


# --- Evolution ---
class EvoApprove(BaseModel):
    approved: bool
    note: str = ""


# --- Generic ---
class ApiResponse(BaseModel):
    ok: bool = True
    message: str = ""
    data: Optional[Any] = None
