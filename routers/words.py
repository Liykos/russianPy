from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import exc as sqlalchemy_exc
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from routers.auth import get_current_user

router = APIRouter(prefix="/words", tags=["words"])


def _start_of_today() -> datetime:
    return datetime.combine(date.today(), datetime.min.time())


def _ensure_word_detail(db: Session, word: models.Word) -> models.WordDetail:
    detail = db.query(models.WordDetail).filter(models.WordDetail.wordId == word.id).first()
    if detail:
        return detail
    detail = models.WordDetail(wordId=word.id)
    db.add(detail)
    db.flush()
    return detail


def _serialize_word(word: models.Word, review_type: str) -> schemas.WordOut:
    derivatives = []
    if word.detail and word.detail.derivatives:
        derivatives = [item.strip() for item in word.detail.derivatives.split(",") if item.strip()]

    return schemas.WordOut(
        id=word.id,
        russian=word.russian,
        chinese=word.chinese,
        pronunciation=word.detail.pronunciation if word.detail else None,
        exampleSentence=word.detail.exampleSentence if word.detail else None,
        derivatives=derivatives,
        note=word.detail.note if word.detail else None,
        reviewType=review_type,
        reviewCount=word.reviewCount,
        easeFactor=word.easeFactor,
        interval=word.interval,
        lastReviewDate=word.lastReviewDate,
        nextReviewDate=word.nextReviewDate,
        state=word.state,
    )


def _load_user_daily_target(db: Session, user_id: int) -> int:
    settings = db.query(models.UserSettings).filter(models.UserSettings.userId == user_id).first()
    return settings.dailyTarget if settings else 20


def _interleave_words(review_words: list[models.Word], new_words: list[models.Word]) -> list[tuple[models.Word, str]]:
    mixed: list[tuple[models.Word, str]] = []
    max_len = max(len(review_words), len(new_words))
    for idx in range(max_len):
        if idx < len(review_words):
            current = review_words[idx]
            review_type = "forgotten" if current.state in {"forgotten", "learning"} else "review"
            mixed.append((current, review_type))
        if idx < len(new_words):
            mixed.append((new_words[idx], "new"))
    return mixed


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
                reviewCount=0,
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


@router.get("/review/today", response_model=list[schemas.WordOut])
def get_review_words(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    today = _start_of_today()
    daily_target = _load_user_daily_target(db, current_user.id)

    due_words = db.query(models.Word).filter(
        models.Word.userId == current_user.id,
        models.Word.nextReviewDate <= today,
        models.Word.state != "new",
    ).order_by(models.Word.nextReviewDate.asc()).all()

    new_candidates = db.query(models.Word).filter(
        models.Word.userId == current_user.id,
        models.Word.state == "new",
        models.Word.nextReviewDate <= today,
    ).order_by(models.Word.id.asc()).all()

    due_quota = min(len(due_words), daily_target)
    new_quota = min(len(new_candidates), daily_target - due_quota)

    # 当天既有遗忘/复习词，也有新词时，尽量保证两类都出现（目标>=2）
    if daily_target >= 2 and due_words and new_candidates and new_quota == 0:
        due_quota = max(0, daily_target - 1)
        new_quota = 1

    remaining_slots = daily_target - due_quota - new_quota
    if remaining_slots > 0:
        due_quota = min(len(due_words), due_quota + remaining_slots)
        remaining_slots = daily_target - due_quota - new_quota
        if remaining_slots > 0:
            new_quota = min(len(new_candidates), new_quota + remaining_slots)

    due_selected = due_words[:due_quota]
    new_words = new_candidates[:new_quota]

    mixed = _interleave_words(due_selected, new_words)
    return [_serialize_word(word, review_type) for word, review_type in mixed]


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

    review_type = "forgotten" if word.state in {"forgotten", "learning"} else ("new" if word.state == "new" else "review")
    return _serialize_word(word, review_type)


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
    )
