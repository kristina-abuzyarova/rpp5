api/main.py
"""api: принимает операции касс, публикует их в RabbitMQ, отдаёт результаты из БД."""
import logging
import os
from contextlib import asynccontextmanager
 
import aio_pika
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine
 
from schemas import OperationIn
from tables import accounts, operations
 
DATABASE_URL = os.environ["DATABASE_URL"]
RABBITMQ_URL = os.environ["RABBITMQ_URL"]
PUBLISH_TIMEOUT_S = 5
 
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("api")
 
 
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.engine = create_async_engine(DATABASE_URL)
    app.state.connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await app.state.connection.channel(
        publisher_confirms=True, on_return_raises=True
    )
    app.state.channel = channel
    # Те же параметры, что и в worker: иначе брокер вернёт PRECONDITION_FAILED.
    app.state.exchange = await channel.declare_exchange(
        "loyalty", aio_pika.ExchangeType.DIRECT, durable=True
    )
    queue = await channel.declare_queue(
        "operations", durable=True, arguments={"x-queue-type": "quorum"}
    )
    await queue.bind(app.state.exchange, routing_key="operation")
    yield
    await app.state.connection.close()
    await app.state.engine.dispose()
 
 
app = FastAPI(title="Бонусная программа: api", lifespan=lifespan)
 
 
def to_result(row) -> dict:
    return {
        "operation_id": row["operation_id"],
        "type": row["type"],
        "customer_id": row["customer_id"],
        "store_id": row["store_id"],
        "status": row["status"],
        "points_delta": row["points_delta"],
        "balance_after": row["balance_after"],
        "reject_reason": row["reject_reason"],
        "processed_at": row["processed_at"].isoformat(),
    }
 
 
@app.post("/operations", status_code=202)
async def create_operation(operation: OperationIn, request: Request):
    # Здесь проверяется только формат. Баллы и баланс считает worker.
    message = aio_pika.Message(
        body=operation.model_dump_json(exclude_none=True).encode("utf-8"),
        content_type="application/json",
        message_id=operation.operation_id,
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
    )
    try:
        # С publisher_confirms await ждёт подтверждения брокера.
        await request.app.state.exchange.publish(
            message, routing_key="operation", mandatory=True,
            timeout=PUBLISH_TIMEOUT_S,
        )
    except Exception:
        log.exception("publish of %s was not confirmed", operation.operation_id)
        raise HTTPException(status_code=503, detail="Брокер не подтвердил публикацию")
    return {"operation_id": operation.operation_id}
 
 
@app.get("/operations/{operation_id}")
async def get_operation(operation_id: str, request: Request):
    query = select(operations).where(operations.c.operation_id == operation_id)
    async with request.app.state.engine.connect() as conn:
        row = (await conn.execute(query)).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Операция ещё не обработана")
    return to_result(row)
 
 
@app.get("/accounts/{customer_id}")
async def get_account(customer_id: str, request: Request):
    async with request.app.state.engine.connect() as conn:
        balance = (await conn.execute(
            select(accounts.c.balance).where(accounts.c.customer_id == customer_id)
        )).scalar_one_or_none()
        if balance is None:
            raise HTTPException(status_code=404, detail="Счёт не найден")
        rows = (await conn.execute(
            select(operations)
            .where(operations.c.customer_id == customer_id)
            .order_by(operations.c.processed_at.desc())
            .limit(20)
        )).mappings().all()
    return {
        "customer_id": customer_id,
        "balance": balance,
        "operations": [to_result(row) for row in rows],
    }
 
 
@app.get("/health")
async def health(request: Request):
    checks = {"database": "ok", "broker": "ok"}
    try:
        async with request.app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        checks["database"] = "unavailable"
    if (request.app.state.connection.is_closed or request.app.state.channel.is_closed):
        code = 200 if all(value == "ok" for value in checks.values()) else 503
    return JSONResponse(checks, status_code=code)
