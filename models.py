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
    createdAt = Column("createdAt", DateTime, nullable=False, default=datetime.utcnow)
    updatedAt = Column("updatedAt", DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("User", back_populates="settings")


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
    easeFactor = Column("easeFactor", Float, default=2.5)
    interval = Column(Integer, default=0)
    lastReviewDate = Column("lastReviewDate", DateTime, nullable=True)
    nextReviewDate = Column("nextReviewDate", DateTime, nullable=False)
    state = Column(String, default="new", nullable=False)

    userId = Column("userId", Integer, ForeignKey("User.id"), nullable=False)
    user = relationship("User", back_populates="words")
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
