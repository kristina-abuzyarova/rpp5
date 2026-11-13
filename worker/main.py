"""worker: берёт операции из очереди, считает баллы, пишет в БД, публикует события."""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
 
import aio_pika
from sqlalchemy.ext.asyncio import create_async_engine
 
import db
from domain import Operation, decide
 
DATABASE_URL = os.environ["DATABASE_URL"]
RABBITMQ_URL = os.environ["RABBITMQ_URL"]
 
QUORUM = {"x-queue-type": "quorum"}
SUBSCRIBER_QUEUES = ("notifier.events", "analytics.events")
RETRY_PAUSE_S = 2
 
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("worker")
 
 
def build_event(row) -> dict:
    """Событие «операция обработана» по сохранённой операции."""
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
 
 
async def process_operation(engine, operation: Operation) -> dict:
    """Вся обработка операции - в одной транзакции. Возвращает событие."""
    async with engine.begin() as conn:
        saved = await db.get_operation(conn, operation.operation_id)
        if saved is not None:
            # Повторная доставка: транзакция уже была зафиксирована,
            # баланс второй раз не меняем, берём сохранённый результат.
            return build_event(saved)
 
        balance = await db.lock_balance(conn, operation.customer_id)
        # Покупку и возврат ищем по номеру чека среди всех покупок сети.
        purchase = await db.find_purchase(conn, operation.check_number)
        returned = await db.has_return(conn, operation.check_number)
        decision = decide(operation, balance, purchase, returned)
 
        processed_at = datetime.now(timezone.utc)
        await db.save_result(conn, operation, decision, processed_at)
 
    return build_event({
        "operation_id": operation.operation_id,
        "type": operation.type,
        "customer_id": operation.customer_id,
        "store_id": operation.store_id,
        "status": decision.status,
        "points_delta": decision.points_delta,
        "balance_after": decision.balance_after,
        "reject_reason": decision.reject_reason,
        "processed_at": processed_at,
    })
 
 
async def declare_topology(channel):
    """Объявляет всё, что нужно приложению, до начала обработки."""
    loyalty = await channel.declare_exchange(
        "loyalty", aio_pika.ExchangeType.DIRECT, durable=True
    )
    operations_queue = await channel.declare_queue(
        "operations", durable=True, arguments=QUORUM
    )
    await operations_queue.bind(loyalty, routing_key="operation")
 
    events = await channel.declare_exchange(
        "loyalty.events", aio_pika.ExchangeType.FANOUT, durable=True
    )
    for name in SUBSCRIBER_QUEUES:
        queue = await channel.declare_queue(name, durable=True, arguments=QUORUM)
        await queue.bind(events)
    return operations_queue, events
 
 
async def publish_event(events, event: dict) -> None:
    message = aio_pika.Message(
        body=json.dumps(event, ensure_ascii=False).encode("utf-8"),
        content_type="application/json",
        message_id=event["operation_id"],
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
    )
    # Канал открыт с publisher_confirms: await возвращается после подтверждения.
    await events.publish(message, routing_key="", mandatory=True)
 
 
async def handle_message(engine, events, message) -> None:
    try:
        operation = Operation.from_message(json.loads(message.body.decode("utf-8")))
    except (ValueError, KeyError, TypeError, ArithmeticError):
        log.exception("message %s is malformed, dropped", message.message_id)
        await message.reject(requeue=False)
        return
 
    # ack отправляется при выходе из блока, то есть после фиксации транзакции
    # и подтверждения брокером публикации события.
    async with message.process(requeue=True):
        event = await process_operation(engine, operation)
        await publish_event(events, event)
    log.info(
        "%s %s %s %+d balance=%d %s",
        event["operation_id"], event["type"], event["status"],
        event["points_delta"], event["balance_after"], event["reject_reason"] or "",
    )
 
 
async def main() -> None:
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(db.metadata.create_all)
 
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    async with connection:
        channel = await connection.channel(
            publisher_confirms=True, on_return_raises=True
        )
        await channel.set_qos(prefetch_count=1)
        operations_queue, events = await declare_topology(channel)
 
        log.info("waiting for operations")
        async with operations_queue.iterator() as messages:
            async for message in messages:
                try:
                    await handle_message(engine, events, message)
                except Exception:
                    # Сообщение уже возвращено в очередь блоком process().
                    log.exception("processing failed, will retry")
                    await asyncio.sleep(RETRY_PAUSE_S)
    await engine.dispose()
 
 
if __name__ == "__main__":
    asyncio.run(main())
