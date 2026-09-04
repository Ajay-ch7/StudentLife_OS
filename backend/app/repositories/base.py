from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

ModelType = TypeVar("ModelType")


class Repository(Generic[ModelType]):
    def __init__(self, model: type[ModelType]) -> None:
        self.model = model

    def get(self, db: Session, record_id: int) -> ModelType | None:
        return db.get(self.model, record_id)

    def list(self, db: Session, *, limit: int = 100, offset: int = 0) -> Sequence[ModelType]:
        statement = select(self.model).offset(offset).limit(limit)
        return db.scalars(statement).all()

    def create(self, db: Session, **values: Any) -> ModelType:
        record = self.model(**values)
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    def update(self, db: Session, record: ModelType, **values: Any) -> ModelType:
        for field, value in values.items():
            setattr(record, field, value)
        db.commit()
        db.refresh(record)
        return record

    def delete(self, db: Session, record: ModelType) -> None:
        db.delete(record)
        db.commit()
