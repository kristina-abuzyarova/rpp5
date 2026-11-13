#!/usr/bin/env bash
# Дополнительные проверки. Запускать после scenario.sh.
API=http://localhost:8000
T="2026-11-10T15:10:00+07:00"
post() { curl -s -w " -> HTTP %{http_code}\n" -X POST "$API/operations" -H 'Content-Type: application/json' -d "$1"; }
 
echo "=== 1. Брокер остановлен: api должен отвечать 503"
docker compose stop rabbitmq
post '{"operation_id":"OP-20","type":"purchase","customer_id":"C1042","store_id":"S12","check_number":"S12-000190","amount":"500.00","occurred_at":"'$T'"}'
curl -s -w " -> HTTP %{http_code}\n" $API/health
docker compose start rabbitmq
sleep 20   # ждём готовности брокера и переподключения connect_robust
 
echo "=== 2. notifier остановлен: событие должно дождаться в очереди"
docker compose stop notifier
post '{"operation_id":"OP-21","type":"purchase","customer_id":"C1042","store_id":"S12","check_number":"S12-000180","amount":"300.00","occurred_at":"'$T'"}'
sleep 8   # кворумные очереди обновляют счётчики с небольшой задержкой
docker compose exec rabbitmq rabbitmqctl list_queues name messages_ready messages_unacknowledged
curl -s http://localhost:8002/stats; echo
docker compose start notifier
sleep 6
curl -s "http://localhost:8001/notifications?customer_id=C1042"; echo
