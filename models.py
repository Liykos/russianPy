from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "User"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True)
    password = Column(String, nullable=False)

    words = relationship("Word", back_populates="user")
    sessions = relationship("AuthSession", back_populates="user")
    settings = relationship("UserSettings", back_populates="user", uselist=False)


class UserSettings(Base):
    __tablename__ = "UserSettings"

    id = Column(Integer, primary_key=True, index=True)
    userId = Column("userId", Integer, ForeignKey("User.id"), unique=True, nullable=False)
    dailyTarget = Column("dailyTarget", Integer, nullable=False, default=20)
    currentBookId = Column("currentBookId", Integer, ForeignKey("WordBook.id"), nullable=True)
    createdAt = Column("createdAt", DateTime, nullable=False, default=datetime.utcnow)
    updatedAt = Column("updatedAt", DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("User", back_populates="settings")
    currentBook = relationship("WordBook", foreign_keys=[currentBookId])


class AuthSession(Base):
    __tablename__ = "AuthSession"

    id = Column(Integer, primary_key=True, index=True)
    userId = Column("userId", Integer, ForeignKey("User.id"), nullable=False, index=True)
    token = Column(String, unique=True, index=True, nullable=False)
    createdAt = Column("createdAt", DateTime, nullable=False, default=datetime.utcnow)
    expiresAt = Column("expiresAt", DateTime, nullable=False, index=True)

    user = relationship("User", back_populates="sessions")


class Word(Base):
    __tablename__ = "Word"

    id = Column(Integer, primary_key=True, index=True)
    russian = Column(String, nullable=False)
    chinese = Column(String, nullable=False)

    reviewCount = Column("reviewCount", Integer, default=0)
    forgottenCount = Column("forgottenCount", Integer, default=0, nullable=False)
    easeFactor = Column("easeFactor", Float, default=2.5)
    interval = Column(Integer, default=0)
    lastReviewDate = Column("lastReviewDate", DateTime, nullable=True)
    nextReviewDate = Column("nextReviewDate", DateTime, nullable=False)
    state = Column(String, default="new", nullable=False)

    userId = Column("userId", Integer, ForeignKey("User.id"), nullable=False)
    bookId = Column("bookId", Integer, ForeignKey("WordBook.id"), nullable=True)
    user = relationship("User", back_populates="words")
    book = relationship("WordBook", foreign_keys=[bookId])
    detail = relationship("WordDetail", back_populates="word", uselist=False)

    __table_args__ = (
        UniqueConstraint("userId", "russian", name="_user_russian_uc"),
    )


class WordDetail(Base):
    __tablename__ = "WordDetail"

    id = Column(Integer, primary_key=True, index=True)
    wordId = Column("wordId", Integer, ForeignKey("Word.id"), unique=True, nullable=False, index=True)
    pronunciation = Column(String, nullable=True)
    exampleSentence = Column("exampleSentence", Text, nullable=True)
    derivatives = Column(Text, nullable=True)
    note = Column(Text, nullable=True)

    word = relationship("Word", back_populates="detail")


class WordBook(Base):
    __tablename__ = "WordBook"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String, unique=True, nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    language = Column(String, nullable=False, default="ru")
    level = Column(String, nullable=True)
    source = Column(String, nullable=True)
    createdAt = Column("createdAt", DateTime, nullable=False, default=datetime.utcnow)
    updatedAt = Column("updatedAt", DateTime, nullable=False, default=datetime.utcnow)

    entries = relationship("WordBookEntry", back_populates="book", cascade="all, delete-orphan")


class WordBookEntry(Base):
    __tablename__ = "WordBookEntry"

    id = Column(Integer, primary_key=True, index=True)
    bookId = Column("bookId", Integer, ForeignKey("WordBook.id"), nullable=False, index=True)
    russian = Column(String, nullable=False)
    chinese = Column(String, nullable=False)
    pronunciation = Column(String, nullable=True)
    exampleSentence = Column("exampleSentence", Text, nullable=True)
    derivatives = Column(Text, nullable=True)
    note = Column(Text, nullable=True)
    orderIndex = Column("orderIndex", Integer, nullable=False, default=0)

    book = relationship("WordBook", back_populates="entries")

    __table_args__ = (
        UniqueConstraint("bookId", "russian", name="_book_russian_uc"),
    )
