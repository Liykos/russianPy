from sqlalchemy import text
from sqlalchemy.engine import Engine


def run_schema_migrations(engine: Engine) -> None:
    """
    Apply lightweight, idempotent schema migrations for legacy PostgreSQL databases.
    This keeps old deployments compatible after new columns/tables are introduced.
    """
    if engine.dialect.name != "postgresql":
        return

    statements = [
        'ALTER TABLE "UserSettings" ADD COLUMN IF NOT EXISTS "currentBookId" INTEGER',
        'ALTER TABLE "Word" ADD COLUMN IF NOT EXISTS "forgottenCount" INTEGER DEFAULT 0',
        'ALTER TABLE "Word" ADD COLUMN IF NOT EXISTS "bookId" INTEGER',
        'UPDATE "Word" SET "forgottenCount" = 0 WHERE "forgottenCount" IS NULL',
        'ALTER TABLE "Word" ALTER COLUMN "forgottenCount" SET DEFAULT 0',
        'ALTER TABLE "Word" ALTER COLUMN "forgottenCount" SET NOT NULL',
        'CREATE INDEX IF NOT EXISTS "ix_Word_bookId" ON "Word" ("bookId")',
        'CREATE INDEX IF NOT EXISTS "ix_UserSettings_currentBookId" ON "UserSettings" ("currentBookId")',
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'fk_word_book_id'
          ) THEN
            ALTER TABLE "Word"
            ADD CONSTRAINT "fk_word_book_id"
            FOREIGN KEY ("bookId") REFERENCES "WordBook"(id);
          END IF;
        END
        $$;
        """,
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'fk_usersettings_current_book_id'
          ) THEN
            ALTER TABLE "UserSettings"
            ADD CONSTRAINT "fk_usersettings_current_book_id"
            FOREIGN KEY ("currentBookId") REFERENCES "WordBook"(id);
          END IF;
        END
        $$;
        """,
    ]

    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
