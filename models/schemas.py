"""
Schemas Pydantic
Define a estrutura de dados para a API.
"""
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional, List
from datetime import datetime
import uuid


# ====================================================================
#                       USER SCHEMAS
# ====================================================================

class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None


class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=128)


class User(UserBase):
    id: uuid.UUID

    # Novos campos: Planos e Limites
    plan: Optional[str] = "basic"
    messages_limit: Optional[int] = 100
    messages_used: Optional[int] = 0

    # Novos campos: APIs Pessoais
    github_token: Optional[str] = None
    use_own_apis: Optional[bool] = False

    created_at: datetime

    class Config:
        from_attributes = True


# ====================================================================
#                       TOKEN SCHEMAS
# ====================================================================

class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    email: Optional[str] = None


# ====================================================================
#                       NOTE SCHEMAS
# ====================================================================

class NoteBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1, max_length=50000)
    tags: Optional[List[str]] = []


class NoteCreate(NoteBase):
    pass


class Note(NoteBase):
    id: int
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None


# ============================================
# SPEC #4: Chat Schemas
# ============================================

class Conversation(BaseModel):
    id: str
    user_id: str
    title: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConversationCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class Message(BaseModel):
    id: int
    conversation_id: str
    role: str  # 'user' | 'assistant' | 'system'
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class ChatMessage(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        """Strip whitespace and reject empty messages."""
        return v.strip()


# ============================================
# SPEC #7: Workspace + Git Schemas
# ============================================

class GitInitRequest(BaseModel):
    project_name: str


class GitCommitRequest(BaseModel):
    project_name: str
    message: str
    files: Optional[List[str]] = None


class Project(BaseModel):
    id: str
    user_id: str
    name: str
    description: Optional[str] = None
    template_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CreateProjectRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)


# ============================================
# SPEC #8: Git Remote Schemas
# ============================================

class GitCloneRequest(BaseModel):
    repo_url: str = Field(..., pattern=r"^https?://")  # ex: https://github.com/user/repo.git


class GitRemoteRequest(BaseModel):
    remote_url: str
    remote_name: str = "origin"


class GitPushRequest(BaseModel):
    remote_name: str = "origin"
    branch_name: Optional[str] = None  # Se None, usa o branch ativo
