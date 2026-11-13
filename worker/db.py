"""Таблицы базы данных и запросы worker (SQLAlchemy Core, асинхронно)."""
from sqlalchemy import (
    Column, DateTime, Index, Integer, MetaData, Numeric, String, Table, select,
    text, update,
)
from sqlalchemy.dialects.postgresql import insert
 
from domain import APPLIED, PURCHASE, RETURN, AcceptedPurchase
 
metadata = MetaData()
 
accounts = Table(
    "accounts", metadata,
    Column("customer_id", String, primary_key=True),
    Column("balance", Integer, nullable=False),
)
 
operations = Table(
    "operations", metadata,
    Column("operation_id", String, primary_key=True),
    Column("type", String, nullable=False),
    Column("customer_id", String, nullable=False),
    Column("store_id", String, nullable=False),
    Column("check_number", String, nullable=False),
    Column("amount", Numeric(12, 2)),
    Column("points_delta", Integer, nullable=False),
    Column("balance_after", Integer, nullable=False),
    Column("status", String, nullable=False),
    Column("reject_reason", String),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("processed_at", DateTime(timezone=True), nullable=False),
    Index("operations_customer_idx", "customer_id", "processed_at"),
    # Номер чека един для всей сети: по нему ищут покупку независимо от
    # покупателя. Два частичных уникальных индекса на уровне базы гарантируют,
    # что у одного номера чека не больше одной принятой покупки и одного
    # принятого возврата.
    Index(
        "operations_accepted_purchase_check_uq", "check_number", unique=True,
        postgresql_where=text("type = 'purchase' AND status = 'applied'"),
    ),
    Index(
        "operations_accepted_return_check_uq", "check_number", unique=True,
        postgresql_where=text("type = 'return' AND status = 'applied'"),
    ),
)
 
 
async def get_operation(conn, operation_id):
    query = select(operations).where(operations.c.operation_id == operation_id)
    return (await conn.execute(query)).mappings().first()
 
 
async def lock_balance(conn, customer_id) -> int:
    """Создаёт счёт при первой операции и блокирует строку счёта до конца транзакции."""
    await conn.execute(
        insert(accounts).values(customer_id=customer_id, balance=0)
        .on_conflict_do_nothing()
    )
    query = (
        select(accounts.c.balance)
        .where(accounts.c.customer_id == customer_id)
        .with_for_update()
    )
    return (await conn.execute(query)).scalar_one()
 
 
async def find_purchase(conn, check_number):
    """Принятая покупка с этим номером чека - у любого покупателя."""
    query = select(operations.c.customer_id, operations.c.points_delta).where(
        operations.c.check_number == check_number,
        operations.c.type == PURCHASE,
        operations.c.status == APPLIED,
    )
    row = (await conn.execute(query)).first()
    return AcceptedPurchase(row.customer_id, row.points_delta) if row else None
 
 
async def has_return(conn, check_number) -> bool:
    """Есть ли принятый возврат по этому номеру чека."""
    query = select(operations.c.operation_id).where(
        operations.c.check_number == check_number,
        operations.c.type == RETURN,
        operations.c.status == APPLIED,
    )
    return (await conn.execute(query)).first() is not None
 
 
async def save_result(conn, operation, decision, processed_at):
    await conn.execute(
        operations.insert().values(
            operation_id=operation.operation_id,
            type=operation.type,
            customer_id=operation.customer_id,
            store_id=operation.store_id,
            check_number=operation.check_number,
            amount=operation.amount,
            points_delta=decision.points_delta,
            balance_after=decision.balance_after,
            status=decision.status,
            reject_reason=decision.reject_reason,
            occurred_at=operation.occurred_at,
            processed_at=processed_at,
        )
    )
    await conn.execute(
        update(accounts)
        .where(accounts.c.customer_id == operation.customer_id)
        .values(balance=decision.balance_after)
