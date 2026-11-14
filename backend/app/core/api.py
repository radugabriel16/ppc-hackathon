"""Shared JSON serialization and capped, zero-based pagination."""
from typing import Annotated, TypeVar

from fastapi import Query
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

T = TypeVar("T", bound=BaseModel)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, from_attributes=True
    )


class Pagination:
    def __init__(
        self,
        page: Annotated[int, Query(ge=0)] = 0,
        size: Annotated[int, Query(ge=1)] = 20,
    ):
        self.page = page
        self.size = min(size, 100)


def paginate(
    db: Session, statement: Select, pagination: Pagination, schema: type[T],
    *, mappings: bool = False,
) -> dict:
    total = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    result = db.execute(
        statement.offset(pagination.page * pagination.size).limit(pagination.size)
    )
    rows = result.mappings().all() if mappings else result.scalars().all()
    return {
        "items": [schema.model_validate(row) for row in rows],
        "page": pagination.page,
        "size": pagination.size,
        "totalElements": total,
        "totalPages": (total + pagination.size - 1) // pagination.size,
    }
