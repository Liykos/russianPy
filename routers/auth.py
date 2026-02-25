from datetime import datetime, timedelta
import secrets

import bcrypt
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db

router = APIRouter(prefix="/auth", tags=["auth"])

SESSION_TTL_DAYS = 30
SESSION_REFRESH_THRESHOLD_DAYS = 7


def _cleanup_expired_sessions(db: Session) -> None:
    db.query(models.AuthSession).filter(models.AuthSession.expiresAt <= datetime.utcnow()).delete(
        synchronize_session=False
    )


def _create_session(db: Session, user_id: int) -> str:
    # 简化客户端逻辑：每个用户只保留一个有效会话
    db.query(models.AuthSession).filter(models.AuthSession.userId == user_id).delete(synchronize_session=False)
    token = secrets.token_urlsafe(48)
    session = models.AuthSession(
        userId=user_id,
        token=token,
        expiresAt=datetime.utcnow() + timedelta(days=SESSION_TTL_DAYS),
    )
    db.add(session)
    return token


def get_current_session(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> models.AuthSession:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或会话已过期。")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的认证头。")

    session = db.query(models.AuthSession).filter(models.AuthSession.token == token).first()
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效会话，请重新登录。")

    if session.expiresAt <= datetime.utcnow():
        db.delete(session)
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="会话过期，请重新登录。")

    remaining = session.expiresAt - datetime.utcnow()
    if remaining <= timedelta(days=SESSION_REFRESH_THRESHOLD_DAYS):
        session.expiresAt = datetime.utcnow() + timedelta(days=SESSION_TTL_DAYS)
        db.commit()
        db.refresh(session)

    return session


def get_current_user(session: models.AuthSession = Depends(get_current_session)) -> models.User:
    return session.user


def _ensure_user_settings(db: Session, user_id: int) -> models.UserSettings:
    settings = db.query(models.UserSettings).filter(models.UserSettings.userId == user_id).first()
    if settings:
        return settings

    settings = models.UserSettings(userId=user_id, dailyTarget=20, currentBookId=None)
    db.add(settings)
    db.commit()
    db.refresh(settings)
    return settings


@router.post("/signup", response_model=schemas.AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(user: schemas.UserCreate, db: Session = Depends(get_db)):
    _cleanup_expired_sessions(db)
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=409, detail="该邮箱已被注册。")

    hashed_password = bcrypt.hashpw(user.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    db_user = models.User(email=user.email, name=user.name, password=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    _ensure_user_settings(db, db_user.id)
    token = _create_session(db, db_user.id)
    db.commit()

    return schemas.AuthResponse(
        message="注册成功！",
        user=schemas.UserOut.model_validate(db_user),
        access_token=token,
    )


@router.post("/signin", response_model=schemas.AuthResponse)
def signin(user: schemas.UserSignin, db: Session = Depends(get_db)):
    _cleanup_expired_sessions(db)
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if not db_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码不正确。")

    if not bcrypt.checkpw(user.password.encode("utf-8"), db_user.password.encode("utf-8")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码不正确。")

    _ensure_user_settings(db, db_user.id)
    token = _create_session(db, db_user.id)
    db.commit()

    return schemas.AuthResponse(
        message="登录成功！",
        user=schemas.UserOut.model_validate(db_user),
        access_token=token,
    )


@router.get("/me", response_model=schemas.UserOut)
def me(current_user: models.User = Depends(get_current_user)):
    return schemas.UserOut.model_validate(current_user)


@router.post("/logout")
def logout(session: models.AuthSession = Depends(get_current_session), db: Session = Depends(get_db)):
    current = db.query(models.AuthSession).filter(models.AuthSession.id == session.id).first()
    if current:
        db.delete(current)
    db.commit()
    return {"message": "已退出登录。"}


@router.get("/settings", response_model=schemas.UserSettingsOut)
def get_settings(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    settings = _ensure_user_settings(db, current_user.id)
    current_book = None
    if settings.currentBook:
        current_book = schemas.WordBookLiteOut(
            id=settings.currentBook.id,
            slug=settings.currentBook.slug,
            title=settings.currentBook.title,
        )
    return schemas.UserSettingsOut(dailyTarget=settings.dailyTarget, currentBook=current_book)


@router.put("/settings", response_model=schemas.UserSettingsOut)
def update_settings(
    payload: schemas.UserSettingsUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = _ensure_user_settings(db, current_user.id)
    settings.dailyTarget = payload.dailyTarget
    settings.updatedAt = datetime.utcnow()
    db.commit()
    current_book = None
    if settings.currentBook:
        current_book = schemas.WordBookLiteOut(
            id=settings.currentBook.id,
            slug=settings.currentBook.slug,
            title=settings.currentBook.title,
        )
    return schemas.UserSettingsOut(dailyTarget=settings.dailyTarget, currentBook=current_book)
