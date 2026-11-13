"""Доменный слой: расчёт баллов бонусной программы.
 
Модуль не импортирует aio-pika и SQLAlchemy: он работает только с обычными
объектами Python и поэтому проверяется модульными тестами без брокера и базы.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal
 
ACCRUAL_RATE = Decimal("0.05")        # начисление за покупку: 5 % от суммы чека
REDEEM_LIMIT_RATE = Decimal("0.30")   # оплата баллами: не более 30 % суммы чека
 
PURCHASE = "purchase"
RETURN = "return"
REDEEM = "redeem"
 
APPLIED = "applied"
REJECTED = "rejected"
 
DUPLICATE_PURCHASE = "duplicate_purchase"
PURCHASE_NOT_FOUND = "purchase_not_found"
CUSTOMER_MISMATCH = "customer_mismatch"
ALREADY_RETURNED = "already_returned"
LIMIT_EXCEEDED = "limit_exceeded"
INSUFFICIENT_BALANCE = "insufficient_balance"
 
 
@dataclass(frozen=True)
class Operation:
    """Операция кассы."""
    operation_id: str
    type: str
    customer_id: str
    store_id: str
    check_number: str
    amount: Decimal | None
    points: int | None
    occurred_at: datetime
 
    @classmethod
    def from_message(cls, data: dict) -> "Operation":
        amount = data.get("amount")
        occurred_at = datetime.fromisoformat(data["occurred_at"])
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        return cls(
            operation_id=data["operation_id"],
            type=data["type"],
            customer_id=data["customer_id"],
            store_id=data["store_id"],
            check_number=data["check_number"],
            amount=Decimal(str(amount)) if amount is not None else None,
            points=data.get("points"),
            occurred_at=occurred_at,
        )
 
 
@dataclass(frozen=True)
class AcceptedPurchase:
    """Принятая покупка, найденная по номеру чека.
 
    Номер чека уникален среди всех покупок сети, поэтому покупку ищут только
    по номеру чека, а покупатель из возврата сравнивается с владельцем покупки.
    """
    customer_id: str
    points: int          # сколько баллов начислено за этот чек
 
 
@dataclass(frozen=True)
class Decision:
    """Итог применения операции к балансу."""
    status: str
    points_delta: int
    balance_after: int
    reject_reason: str | None
 
 
def accrual_points(amount: Decimal) -> int:
    """5 % от суммы чека, дробная часть отбрасывается."""
    return int((amount * ACCRUAL_RATE).to_integral_value(rounding=ROUND_DOWN))
 
 
def _applied(balance: int, delta: int) -> Decision:
    return Decision(APPLIED, delta, balance + delta, None)
 
 
def _rejected(balance: int, reason: str) -> Decision:
    return Decision(REJECTED, 0, balance, reason)
 
 
def decide(
    operation: Operation,
    balance: int,
    purchase: AcceptedPurchase | None,
    already_returned: bool,
) -> Decision:
    """Применяет операцию к текущему балансу.
 
    purchase - принятая покупка с номером чека операции (для покупки это
    признак повтора номера, для возврата - покупка, которую возвращают);
    already_returned - по этому номеру чека уже принят возврат.
    Причины отказа проверяются в порядке таблицы из задания.
    """
    if operation.type == PURCHASE:
        if purchase is not None:
            return _rejected(balance, DUPLICATE_PURCHASE)
        return _applied(balance, accrual_points(operation.amount))
 
    if operation.type == RETURN:
        if purchase is None:
            return _rejected(balance, PURCHASE_NOT_FOUND)
        if purchase.customer_id != operation.customer_id:
            return _rejected(balance, CUSTOMER_MISMATCH)
        if already_returned:
            return _rejected(balance, ALREADY_RETURNED)
        return _applied(balance, -purchase.points)
 
    # оплата баллами
    if Decimal(operation.points) > operation.amount * REDEEM_LIMIT_RATE:
        return _rejected(balance, LIMIT_EXCEEDED)
    if operation.points > balance:
        return _rejected(balance, INSUFFICIENT_BALANCE)
    return _applied(balance, -operation.points)
