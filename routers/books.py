import json
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from routers.auth import get_current_user

router = APIRouter(prefix="/books", tags=["books"])

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "wordbooks"


def _today_start() -> datetime:
    return datetime.combine(date.today(), datetime.min.time())


def _ensure_user_settings(db: Session, user_id: int) -> models.UserSettings:
    settings = db.query(models.UserSettings).filter(models.UserSettings.userId == user_id).first()
    if settings:
        return settings
    settings = models.UserSettings(userId=user_id, dailyTarget=20, currentBookId=None)
    db.add(settings)
    db.commit()
    db.refresh(settings)
    return settings


def _ensure_seed_books(db: Session) -> None:
    if not DATA_DIR.exists():
        return

    seed_files = sorted(DATA_DIR.glob("*.json"))
    if not seed_files:
        return

    existing_slugs = {
        item.slug
        for item in db.query(models.WordBook.slug).all()
    }

    created = 0
    for seed_file in seed_files:
        payload = json.loads(seed_file.read_text(encoding="utf-8"))
        slug = (payload.get("slug") or "").strip()
        title = (payload.get("title") or "").strip()
        if not slug or not title or slug in existing_slugs:
            continue

        book = models.WordBook(
            slug=slug,
            title=title,
            description=payload.get("description"),
            language=payload.get("language", "ru"),
            level=payload.get("level"),
            source=payload.get("source"),
        )
        db.add(book)
        db.flush()

        entries = payload.get("entries", [])
        for idx, entry in enumerate(entries):
            russian = (entry.get("russian") or "").strip()
            chinese = (entry.get("chinese") or "").strip()
            if not russian or not chinese:
                continue
            db.add(
                models.WordBookEntry(
                    bookId=book.id,
                    russian=russian,
                    chinese=chinese,
                    pronunciation=(entry.get("pronunciation") or "").strip() or None,
                    exampleSentence=(entry.get("exampleSentence") or "").strip() or None,
                    derivatives=(entry.get("derivatives") or "").strip() or None,
                    note=(entry.get("note") or "").strip() or None,
                    orderIndex=idx,
                )
            )
        existing_slugs.add(slug)
        created += 1

    if created > 0:
        db.commit()


def _split_derivatives(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _book_lite(book: models.WordBook) -> schemas.WordBookLiteOut:
    return schemas.WordBookLiteOut(id=book.id, slug=book.slug, title=book.title)


def _book_out(book: models.WordBook, current_book_id: int | None) -> schemas.WordBookOut:
    return schemas.WordBookOut(
        id=book.id,
        slug=book.slug,
        title=book.title,
        description=book.description,
        language=book.language,
        level=book.level,
        source=book.source,
        totalWords=len(book.entries),
        isCurrent=(current_book_id == book.id),
    )


def _entry_out(entry: models.WordBookEntry) -> schemas.WordBookEntryOut:
    return schemas.WordBookEntryOut(
        id=entry.id,
        russian=entry.russian,
        chinese=entry.chinese,
        pronunciation=entry.pronunciation,
        exampleSentence=entry.exampleSentence,
        derivatives=_split_derivatives(entry.derivatives),
        note=entry.note,
        orderIndex=entry.orderIndex,
    )


@router.get("", response_model=list[schemas.WordBookOut])
def list_books(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_seed_books(db)
    settings = _ensure_user_settings(db, current_user.id)
    books = db.query(models.WordBook).order_by(models.WordBook.id.asc()).all()
    return [_book_out(book, settings.currentBookId) for book in books]


@router.get("/{book_id}", response_model=schemas.WordBookDetailOut)
def get_book(
    book_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_seed_books(db)
    settings = _ensure_user_settings(db, current_user.id)
    book = db.query(models.WordBook).filter(models.WordBook.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="词书不存在。")

    sample_entries = sorted(book.entries, key=lambda item: item.orderIndex)[:20]
    return schemas.WordBookDetailOut(
        id=book.id,
        slug=book.slug,
        title=book.title,
        description=book.description,
        language=book.language,
        level=book.level,
        source=book.source,
        totalWords=len(book.entries),
        isCurrent=(settings.currentBookId == book.id),
        sampleEntries=[_entry_out(item) for item in sample_entries],
    )


@router.post("/{book_id}/import", response_model=schemas.WordBookImportResponse, status_code=status.HTTP_201_CREATED)
def import_book_to_user(
    book_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_seed_books(db)
    book = db.query(models.WordBook).filter(models.WordBook.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="词书不存在。")

    entries = sorted(book.entries, key=lambda item: item.orderIndex)
    imported = 0
    updated = 0
    today = _today_start()

    for entry in entries:
        word = db.query(models.Word).filter(
            models.Word.userId == current_user.id,
            models.Word.russian == entry.russian,
        ).first()

        if not word:
            word = models.Word(
                russian=entry.russian,
                chinese=entry.chinese,
                userId=current_user.id,
                bookId=book.id,
                reviewCount=0,
                forgottenCount=0,
                easeFactor=2.5,
                interval=0,
                state="new",
                lastReviewDate=None,
                nextReviewDate=today,
            )
            db.add(word)
            db.flush()
            imported += 1
        else:
            word.chinese = entry.chinese
            word.bookId = book.id
            updated += 1

        detail = db.query(models.WordDetail).filter(models.WordDetail.wordId == word.id).first()
        if not detail:
            detail = models.WordDetail(wordId=word.id)
            db.add(detail)

        detail.pronunciation = entry.pronunciation
        detail.exampleSentence = entry.exampleSentence
        detail.derivatives = entry.derivatives
        detail.note = entry.note

    settings = _ensure_user_settings(db, current_user.id)
    settings.currentBookId = book.id
    settings.updatedAt = datetime.utcnow()
    db.commit()

    return schemas.WordBookImportResponse(
        message=f"词书《{book.title}》已设为在学并完成一键导入。",
        imported=imported,
        updated=updated,
        currentBook=_book_lite(book),
    )


@router.post("/{book_id}/restart", response_model=schemas.WordBookRestartResponse)
def restart_book_for_user(
    book_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_seed_books(db)
    book = db.query(models.WordBook).filter(models.WordBook.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="词书不存在。")

    words = db.query(models.Word).filter(
        models.Word.userId == current_user.id,
        models.Word.bookId == book.id,
    ).all()
    if not words:
        raise HTTPException(status_code=400, detail="请先导入该词书，再使用重新学习。")

    today = _today_start()
    for word in words:
        word.reviewCount = 0
        word.forgottenCount = 0
        word.easeFactor = 2.5
        word.interval = 0
        word.state = "new"
        word.lastReviewDate = None
        word.nextReviewDate = today

    settings = _ensure_user_settings(db, current_user.id)
    settings.currentBookId = book.id
    settings.updatedAt = datetime.utcnow()
    db.commit()

    return schemas.WordBookRestartResponse(
        message=f"词书《{book.title}》已重置为重新学习状态。",
        resetCount=len(words),
        currentBook=_book_lite(book),
    )
