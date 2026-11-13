#!/usr/bin/env bash
# Сценарий проверки: docker compose up -d --build && ./scenario.sh
API=http://localhost:8000
T="2026-11-10T14:32:05+07:00"
 
post() {  # post '<json>'
  curl -s -o /dev/null -w "%{http_code}\n" -X POST "$API/operations" \
       -H 'Content-Type: application/json' -d "$1"
}
 
echo "--- 1-13: операции (ожидается 202)"
post '{"operation_id":"OP-01","type":"purchase","customer_id":"C1042","store_id":"S12","check_number":"S12-000154","amount":"2490.00","occurred_at":"'$T'"}'
post '{"operation_id":"OP-02","type":"redeem","customer_id":"C1042","store_id":"S12","check_number":"S12-000160","amount":"1000.00","points":500,"occurred_at":"'$T'"}'
post '{"operation_id":"OP-03","type":"redeem","customer_id":"C1042","store_id":"S12","check_number":"S12-000161","amount":"1000.00","points":200,"occurred_at":"'$T'"}'
post '{"operation_id":"OP-04","type":"redeem","customer_id":"C1042","store_id":"S12","check_number":"S12-000154","amount":"2490.00","points":100,"occurred_at":"'$T'"}'
post '{"operation_id":"OP-05","type":"return","customer_id":"C1042","store_id":"S12","check_number":"S12-000154","occurred_at":"'$T'"}'
post '{"operation_id":"OP-06","type":"return","customer_id":"C1042","store_id":"S12","check_number":"S12-000154","occurred_at":"'$T'"}'
post '{"operation_id":"OP-07","type":"purchase","customer_id":"C1042","store_id":"S12","check_number":"S12-000170","amount":"4000.00","occurred_at":"'$T'"}'
post '{"operation_id":"OP-08","type":"purchase","customer_id":"C1042","store_id":"S12","check_number":"S12-000170","amount":"4000.00","occurred_at":"'$T'"}'
post '{"operation_id":"OP-09","type":"purchase","customer_id":"C2002","store_id":"S07","check_number":"S07-000031","amount":"1500.00","occurred_at":"'$T'"}'
post '{"operation_id":"OP-10","type":"return","customer_id":"C1042","store_id":"S07","check_number":"S07-000031","occurred_at":"'$T'"}'
post '{"operation_id":"OP-11","type":"return","customer_id":"C1042","store_id":"S12","check_number":"S12-999999","occurred_at":"'$T'"}'
post '{"operation_id":"OP-12","type":"purchase","customer_id":"C2002","store_id":"S12","check_number":"S12-000154","amount":"100.00","occurred_at":"'$T'"}'
post '{"operation_id":"OP-13","type":"purchase","customer_id":"C2002","store_id":"S07","check_number":"S07-000032","amount":"999.99","occurred_at":"'$T'"}'
 
echo "--- ошибки формата (ожидается 422)"
post '{"operation_id":"BAD-1","type":"redeem","customer_id":"C1042","store_id":"S12","check_number":"S12-000200","amount":"1000.00","occurred_at":"'$T'"}'
post '{"operation_id":"BAD-2","type":"return","customer_id":"C1042","store_id":"S12","check_number":"S12-000154","amount":"100.00","occurred_at":"'$T'"}'
post '{"operation_id":"BAD-3","type":"gift","customer_id":"C1042","store_id":"S12","check_number":"S12-000201","amount":"100.00","occurred_at":"'$T'"}'
post '{"operation_id":"BAD-4","type":"purchase","customer_id":"C1042","store_id":"S12","check_number":"S12-000202","amount":"-5.00","occurred_at":"'$T'"}'
 
sleep 4
echo "--- результат одной операции"
curl -s $API/operations/OP-10; echo
echo "--- несуществующая операция (404)"
curl -s -o /dev/null -w "%{http_code}\n" $API/operations/NO-SUCH
echo "--- счёт C1042"
curl -s $API/accounts/C1042; echo
echo "--- health"
curl -s $API/health; echo
echo "--- notifier"
curl -s "http://localhost:8001/notifications?customer_id=C1042"; echo
curl -s "http://localhost:8001/notifications?customer_id=C2002"; echo
curl -s http://localhost:8001/stats; echo
echo "--- analytics"
curl -s http://localhost:8002/stores; echo
curl -s http://localhost:8002/stores/S12; echo
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8002/stores/S99
curl -s http://localhost:8002/stats; echo
