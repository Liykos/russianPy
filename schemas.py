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


class WordBookLiteOut(BaseModel):
    id: int
    slug: str
    title: str


class UserSettingsOut(BaseModel):
    dailyTarget: int
    currentBook: WordBookLiteOut | None = None


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
    bookId: int | None = None
    bookTitle: str | None = None

    reviewCount: int
    forgottenCount: int
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
    forgottenCount: int


class WordSearchItemOut(BaseModel):
    id: int
    russian: str
    chinese: str
    state: str
    isForgotten: bool
    bookTitle: str | None = None
    pronunciation: str | None = None
    exampleSentence: str | None = None


class TodayStudyPlanOut(BaseModel):
    dailyTarget: int
    newTarget: int
    forgottenTarget: int
    activeBook: WordBookLiteOut | None = None
    words: list[WordOut] = Field(default_factory=list)
    newCount: int = 0
    forgottenCount: int = 0
    reviewCount: int = 0


class WordBookEntryOut(BaseModel):
    id: int
    russian: str
    chinese: str
    pronunciation: str | None = None
    exampleSentence: str | None = None
    derivatives: list[str] = Field(default_factory=list)
    note: str | None = None
    orderIndex: int


class WordBookOut(BaseModel):
    id: int
    slug: str
    title: str
    description: str | None = None
    language: str
    level: str | None = None
    source: str | None = None
    totalWords: int
    isCurrent: bool = False


class WordBookDetailOut(BaseModel):
    id: int
    slug: str
    title: str
    description: str | None = None
    language: str
    level: str | None = None
    source: str | None = None
    totalWords: int
    isCurrent: bool = False
    sampleEntries: list[WordBookEntryOut] = Field(default_factory=list)


class WordBookImportResponse(BaseModel):
    message: str
    imported: int
    updated: int
    currentBook: WordBookLiteOut


class WordBookRestartResponse(BaseModel):
    message: str
    resetCount: int
    currentBook: WordBookLiteOut
