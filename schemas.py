from datetime import datetime

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    email: str
    password: str
    name: str | None = None


class UserSignin(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    name: str | None

    class Config:
        from_attributes = True


class AuthResponse(BaseModel):
    message: str
    user: UserOut
    access_token: str
    token_type: str = "bearer"


class UserSettingsOut(BaseModel):
    dailyTarget: int


class UserSettingsUpdate(BaseModel):
    dailyTarget: int = Field(ge=1, le=200)


class WordImportRequest(BaseModel):
    raw_text: str


class WordOut(BaseModel):
    id: int
    russian: str
    chinese: str
    pronunciation: str | None = None
    exampleSentence: str | None = None
    derivatives: list[str] = Field(default_factory=list)
    note: str | None = None
    reviewType: str = "review"

    reviewCount: int
    easeFactor: float
    interval: int
    lastReviewDate: datetime | None
    nextReviewDate: datetime
    state: str


class WordReviewRequest(BaseModel):
    word_id: int
    quality: int = Field(ge=0, le=5)


class WordReviewResponse(BaseModel):
    message: str
    state: str
    nextReviewDate: datetime
