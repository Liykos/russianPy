import math
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import exc as sqlalchemy_exc, or_
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from routers.auth import get_current_user

router = APIRouter(prefix="/words", tags=["words"])

NEW_WORD_RATIO = 0.7
MIN_FORGOTTEN_RATIO = 0.2


def _start_of_today() -> datetime:
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


def _ensure_word_detail(db: Session, word: models.Word) -> models.WordDetail:
    detail = db.query(models.WordDetail).filter(models.WordDetail.wordId == word.id).first()
    if detail:
        return detail
    detail = models.WordDetail(wordId=word.id)
    db.add(detail)
    db.flush()
    return detail


def _split_derivatives(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _word_review_type(word: models.Word) -> str:
    if word.state == "new":
        return "new"
    if word.state in {"forgotten", "learning"}:
        return "forgotten"
    return "review"


def _serialize_word(word: models.Word) -> schemas.WordOut:
    return schemas.WordOut(
        id=word.id,
        russian=word.russian,
        chinese=word.chinese,
        pronunciation=word.detail.pronunciation if word.detail else None,
        exampleSentence=word.detail.exampleSentence if word.detail else None,
        derivatives=_split_derivatives(word.detail.derivatives if word.detail else None),
        note=word.detail.note if word.detail else None,
        reviewType=_word_review_type(word),
        bookId=word.bookId,
        bookTitle=word.book.title if word.book else None,
        reviewCount=word.reviewCount,
        forgottenCount=word.forgottenCount,
        easeFactor=word.easeFactor,
        interval=word.interval,
        lastReviewDate=word.lastReviewDate,
        nextReviewDate=word.nextReviewDate,
        state=word.state,
    )


def _mix_words(new_words: list[models.Word], forgotten_words: list[models.Word], review_words: list[models.Word]) -> list[models.Word]:
    mixed: list[models.Word] = []
    new_idx = 0
    forgot_idx = 0

    while new_idx < len(new_words) or forgot_idx < len(forgotten_words):
        for _ in range(2):
            if new_idx < len(new_words):
                mixed.append(new_words[new_idx])
                new_idx += 1
        if forgot_idx < len(forgotten_words):
            mixed.append(forgotten_words[forgot_idx])
            forgot_idx += 1

        if new_idx >= len(new_words) and forgot_idx < len(forgotten_words):
            mixed.extend(forgotten_words[forgot_idx:])
            break
        if forgot_idx >= len(forgotten_words) and new_idx < len(new_words):
            mixed.extend(new_words[new_idx:])
            break

    mixed.extend(review_words)
    return mixed


def _build_forgotten_queue(words: list[models.Word]) -> list[models.Word]:
    """
    Build a dynamic forgotten queue:
    1) group by due date (oldest day first),
    2) inside the same day, prioritize older review timestamps.
    """
    buckets: dict[date, list[models.Word]] = {}
    for word in words:
        due_base = word.nextReviewDate or datetime.min
        due_date = due_base.date()
        buckets.setdefault(due_date, []).append(word)

    queue: list[models.Word] = []
    for due_date in sorted(buckets.keys()):
        bucket = sorted(
            buckets[due_date],
            key=lambda item: (
                item.lastReviewDate or datetime.min,
                item.id,
            ),
        )
        queue.extend(bucket)
    return queue


def _build_today_plan(current_user: models.User, db: Session) -> schemas.TodayStudyPlanOut:
    settings = _ensure_user_settings(db, current_user.id)
    daily_target = max(1, settings.dailyTarget)
    today = _start_of_today()

    new_candidates_query = db.query(models.Word).filter(
        models.Word.userId == current_user.id,
        models.Word.state == "new",
        models.Word.nextReviewDate <= today,
    )
    if settings.currentBookId:
        new_candidates_query = new_candidates_query.filter(models.Word.bookId == settings.currentBookId)

    new_candidates = new_candidates_query.order_by(models.Word.id.asc()).all()
    forgotten_raw_candidates = db.query(models.Word).filter(
        models.Word.userId == current_user.id,
        models.Word.state == "forgotten",
        models.Word.nextReviewDate <= today,
    ).order_by(models.Word.nextReviewDate.asc(), models.Word.lastReviewDate.asc(), models.Word.id.asc()).all()
    review_candidates = db.query(models.Word).filter(
        models.Word.userId == current_user.id,
        models.Word.state.notin_(["new", "forgotten"]),
        models.Word.nextReviewDate <= today,
    ).order_by(models.Word.nextReviewDate.asc()).all()
    forgotten_candidates = _build_forgotten_queue(forgotten_raw_candidates)

    new_target = math.ceil(daily_target * NEW_WORD_RATIO)
    forgotten_target = max(0, math.floor(daily_target * MIN_FORGOTTEN_RATIO))

    new_quota = min(len(new_candidates), new_target)
    forgotten_quota = min(len(forgotten_candidates), forgotten_target)

    # 有遗忘词时保证每天至少复习 1 个遗忘词
    if daily_target >= 2 and forgotten_candidates and forgotten_quota == 0:
        forgotten_quota = 1
        if new_quota + forgotten_quota > daily_target:
            new_quota = max(0, daily_target - forgotten_quota)

    remaining = daily_target - new_quota - forgotten_quota
    # 优先补新词，确保“新词占主导”
    if remaining > 0:
        extra_new = min(len(new_candidates) - new_quota, remaining)
        new_quota += extra_new
        remaining -= extra_new
    # 再补遗忘词，按最老日期队列推进
    if remaining > 0:
        extra_forgotten = min(len(forgotten_candidates) - forgotten_quota, remaining)
        forgotten_quota += extra_forgotten
        remaining -= extra_forgotten

    review_quota = max(0, remaining)
    review_selected = review_candidates[:review_quota]
    new_selected = new_candidates[:new_quota]
    forgotten_selected = forgotten_candidates[:forgotten_quota]

    mixed = _mix_words(new_selected, forgotten_selected, review_selected)

    active_book = None
    if settings.currentBook:
        active_book = schemas.WordBookLiteOut(
            id=settings.currentBook.id,
            slug=settings.currentBook.slug,
            title=settings.currentBook.title,
        )

    return schemas.TodayStudyPlanOut(
        dailyTarget=daily_target,
        newTarget=new_target,
        forgottenTarget=forgotten_target,
        activeBook=active_book,
        words=[_serialize_word(word) for word in mixed],
        newCount=len(new_selected),
        forgottenCount=len(forgotten_selected),
        reviewCount=len(review_selected),
    )


@router.post("/import", status_code=status.HTTP_201_CREATED)
def import_words(
    data: schemas.WordImportRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    new_words_count = 0
    updated_words_count = 0
    lines = data.raw_text.strip().split("\n")
    today = _start_of_today()

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        parts = line.split(" - ", 1)
        if len(parts) != 2:
            continue

        russian_word = parts[0].strip()
        payload = [segment.strip() for segment in parts[1].split("|")]
        chinese_meaning = payload[0] if payload else ""
        example_sentence = payload[1] if len(payload) > 1 else None
        derivatives = payload[2] if len(payload) > 2 else None
        pronunciation = payload[3] if len(payload) > 3 else None
        note = payload[4] if len(payload) > 4 else None

        if not russian_word or not chinese_meaning:
            continue

        word = db.query(models.Word).filter(
            models.Word.userId == current_user.id,
            models.Word.russian == russian_word,
        ).first()

        if not word:
            word = models.Word(
                russian=russian_word,
                chinese=chinese_meaning,
                userId=current_user.id,
                bookId=None,
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
            new_words_count += 1
        else:
            word.chinese = chinese_meaning
            updated_words_count += 1

        detail = _ensure_word_detail(db, word)
        if example_sentence:
            detail.exampleSentence = example_sentence
        if derivatives:
            detail.derivatives = derivatives
        if pronunciation:
            detail.pronunciation = pronunciation
        if note:
            detail.note = note

    try:
        db.commit()
    except sqlalchemy_exc.IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="导入过程中发生数据库冲突。")

    return {
        "message": f"成功导入 {new_words_count} 个新词，更新 {updated_words_count} 个已有词。",
        "imported": new_words_count,
        "updated": updated_words_count,
    }


@router.get("/review/today-plan", response_model=schemas.TodayStudyPlanOut)
def get_today_plan(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _build_today_plan(current_user, db)


@router.get("/review/today", response_model=list[schemas.WordOut])
def get_today_words(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plan = _build_today_plan(current_user, db)
    return plan.words


@router.get("/search", response_model=list[schemas.WordSearchItemOut])
def search_words(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pattern = f"%{q.strip()}%"
    words = db.query(models.Word).filter(
        models.Word.userId == current_user.id,
        or_(
            models.Word.russian.ilike(pattern),
            models.Word.chinese.ilike(pattern),
        ),
    ).order_by(models.Word.id.asc()).limit(limit).all()

    return [
        schemas.WordSearchItemOut(
            id=word.id,
            russian=word.russian,
            chinese=word.chinese,
            state=word.state,
            isForgotten=(word.state == "forgotten" or word.forgottenCount > 0),
            bookTitle=word.book.title if word.book else None,
            pronunciation=word.detail.pronunciation if word.detail else None,
            exampleSentence=word.detail.exampleSentence if word.detail else None,
        )
        for word in words
    ]


@router.get("/forgotten", response_model=list[schemas.WordOut])
def get_forgotten_words(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    words = db.query(models.Word).filter(
        models.Word.userId == current_user.id,
        models.Word.forgottenCount > 0,
    ).order_by(models.Word.lastReviewDate.desc(), models.Word.id.desc()).all()
    return [_serialize_word(word) for word in words]


@router.post("/{word_id}/mark-forgotten", response_model=schemas.WordReviewResponse)
def mark_word_forgotten(
    word_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    word = db.query(models.Word).filter(
        models.Word.id == word_id,
        models.Word.userId == current_user.id,
    ).first()
    if not word:
        raise HTTPException(status_code=404, detail="单词不存在。")

    word.state = "forgotten"
    word.reviewCount = 0
    word.interval = 0
    word.forgottenCount += 1
    word.lastReviewDate = datetime.utcnow()
    word.nextReviewDate = _start_of_today()
    db.commit()
    db.refresh(word)

    return schemas.WordReviewResponse(
        message="已加入遗忘词。",
        state=word.state,
        nextReviewDate=word.nextReviewDate,
        forgottenCount=word.forgottenCount,
    )


@router.get("/{word_id}", response_model=schemas.WordOut)
def get_word_detail(
    word_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    word = db.query(models.Word).filter(
        models.Word.id == word_id,
        models.Word.userId == current_user.id,
    ).first()
    if not word:
        raise HTTPException(status_code=404, detail="单词不存在。")
    return _serialize_word(word)


@router.post("/review", response_model=schemas.WordReviewResponse, status_code=status.HTTP_200_OK)
def submit_review(
    data: schemas.WordReviewRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    word = db.query(models.Word).filter(
        models.Word.id == data.word_id,
        models.Word.userId == current_user.id,
    ).first()
    if not word:
        raise HTTPException(status_code=404, detail="Word not found or unauthorized.")

    quality = data.quality
    new_ef = word.easeFactor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    word.easeFactor = max(1.3, new_ef)
    word.lastReviewDate = datetime.utcnow()

    if quality < 3:
        word.reviewCount = 0
        word.interval = 0
        word.state = "forgotten"
        word.forgottenCount += 1
        word.nextReviewDate = _start_of_today()
    else:
        word.reviewCount += 1
        if word.reviewCount == 1:
            new_interval = 1
        elif word.reviewCount == 2:
            new_interval = 6
        else:
            new_interval = max(1, round(word.interval * word.easeFactor))
        word.interval = round(new_interval)
        word.state = "mastered"
        word.nextReviewDate = _start_of_today() + timedelta(days=word.interval)

    try:
        db.commit()
        db.refresh(word)
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update review status.")

    return schemas.WordReviewResponse(
        message="Review status updated successfully.",
        state=word.state,
        nextReviewDate=word.nextReviewDate,
        forgottenCount=word.forgottenCount,
    )
