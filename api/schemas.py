"""Проверка формата операции кассы (бизнес-правила проверяет worker)."""
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
 
from pydantic import BaseModel, Field, model_validator
 
NonEmpty = Annotated[str, Field(min_length=1)]
Money = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
Points = Annotated[int, Field(gt=0, strict=True)]
 
 
class OperationIn(BaseModel):
    operation_id: NonEmpty
    type: Literal["purchase", "return", "redeem"]
    customer_id: NonEmpty
    store_id: NonEmpty
    check_number: NonEmpty
    amount: Money | None = None
    points: Points | None = None
    occurred_at: datetime
 
    @model_validator(mode="after")
    def check_fields_for_type(self):
        # amount: обязателен у покупки и оплаты баллами, в возврате отсутствует
        if self.type == "return":
            if self.amount is not None:
                raise ValueError("amount must be absent for return")
        elif self.amount is None:
            raise ValueError("amount is required for purchase and redeem")
        # points: обязателен только у оплаты баллами
        if self.type == "redeem":
            if self.points is None:
                raise ValueError("points is required for redeem")
        elif self.points is not None:
            raise ValueError("points must be absent for purchase and return")
        return self
