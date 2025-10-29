from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from ..config import settings

engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class AtomicProcessor:
    def __init__(self, db_session):
        self.db = db_session

    def process_with_rollback(self, operations: list) -> bool:
        try:
            self.db.begin()

            for operation in operations:
                pass

            self.db.commit()
            return True

        except Exception as e:
            self.db.rollback()
            raise e
