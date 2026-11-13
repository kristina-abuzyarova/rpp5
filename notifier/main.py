"""notifier: уведомления покупателям по событиям «операция обработана»."""
import asyncio
import json
import logging
import os
import random
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
 
import aio_pika
from fastapi import FastAPI
 
RABBITMQ_URL = os.environ["RABBITMQ_URL"]
MIN_DELAY_MS = int(os.getenv("MIN_DELAY_MS", "200"))
MAX_DELAY_MS = int(os.getenv("MAX_DELAY_MS", "1500"))
UNSUBSCRIBED = {
    item.strip() for item in os.getenv("UNSUBSCRIBED", "").split(",") if item.strip()
}
 
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("notifier")
 
# Данные хранятся в памяти и теряются при перезапуске.
notifications = defaultdict(list)
seen_operations = set()
stats = {"events_received": 0, "notifications_sent": 0}
 
 
def points_word(number: int) -> str:
    number = abs(number)
    if number % 10 == 1 and number % 100 != 11:
        return "балл"
    if number % 10 in (2, 3, 4) and number % 100 not in (12, 13, 14):
        return "балла"
    return "баллов"
 
 
def make_text(event: dict) -> str:
    if event["status"] == "rejected":
        return f"Операция отклонена: {event['reject_reason']}"
    delta = event["points_delta"]
    action = "Списано" if delta < 0 else "Начислено"
    balance = f"{event['balance_after']:,}".replace(",", " ")
    return f"{action} {abs(delta)} {points_word(delta)}, баланс {balance}"
 
 
async def handle(event: dict) -> None:
    if event["operation_id"] in seen_operations:
        return  # повторная доставка того же события
    seen_operations.add(event["operation_id"])
    stats["events_received"] += 1
 
    customer_id = event["customer_id"]
    if customer_id in UNSUBSCRIBED:
        log.info("%s: %s unsubscribed, skipped", event["operation_id"], customer_id)
        return
 
    text = make_text(event)
    # Имитация отправки: случайная задержка и запись в журнал.
    await asyncio.sleep(random.uniform(MIN_DELAY_MS, MAX_DELAY_MS) / 1000)
    notifications[customer_id].append({
        "operation_id": event["operation_id"],
        "customer_id": customer_id,
        "text": text,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    })
    stats["notifications_sent"] += 1
    log.info("%s -> %s: %s", event["operation_id"], customer_id, text)
 
 
async def consume(queue) -> None:
    """Фоновое чтение очереди; работает, пока приложение не остановлено."""
    async with queue.iterator() as messages:
        async for message in messages:
            try:
                event = json.loads(message.body.decode("utf-8"))
            except ValueError:
                log.exception("malformed event dropped")
                await message.reject(requeue=False)
                continue
            try:
                async with message.process(requeue=True):  # ack после обработки
                    await handle(event)
            except Exception:
                log.exception("handling failed, event returned to queue")
                await asyncio.sleep(1)
 
 
@asynccontextmanager
async def lifespan(app: FastAPI):
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=1)
    # Те же параметры, что и в worker: сервис не зависит от порядка запуска.
    events = await channel.declare_exchange(
        "loyalty.events", aio_pika.ExchangeType.FANOUT, durable=True
    )
    queue = await channel.declare_queue(
        "notifier.events", durable=True, arguments={"x-queue-type": "quorum"}
    )
    await queue.bind(events)
    task = asyncio.create_task(consume(queue))
    yield
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await connection.close()
 
 
app = FastAPI(title="Бонусная программа: notifier", lifespan=lifespan)
 
 
@app.get("/notifications")
async def get_notifications(customer_id: str):
    return notifications.get(customer_id, [])
 
 
@app.get("/stats")
async def get_stats():
    return stats
