from sqlalchemy import text

from app.database import engine


def run() -> None:
    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE message_citations ADD COLUMN IF NOT EXISTS source_details JSONB"
        ))


if __name__ == "__main__":
    run()
