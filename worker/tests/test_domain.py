import os
import sys
import unittest
from decimal import Decimal
 
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
 
from domain import accrual_points  # noqa: E402
from ledger import Ledger  # noqa: E402
from scenario import T, op, run  # noqa: E402
 
 
class AccrualTests(unittest.TestCase):
    def test_five_percent_fraction_dropped(self):
        self.assertEqual(accrual_points(Decimal("2490.00")), 124)   # 124.5 -> 124
        self.assertEqual(accrual_points(Decimal("999.99")), 49)     # 49.9995 -> 49
        self.assertEqual(accrual_points(Decimal("19.99")), 0)       # 0.9995 -> 0
        self.assertEqual(accrual_points(Decimal("100.00")), 5)
 
 
class RedeemTests(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger()
        self.ledger.apply(op(1, "purchase", "C1", "S1", "CH-1", "10000.00"))  # 500 баллов
 
    def test_exactly_thirty_percent_allowed(self):
        d = self.ledger.apply(op(2, "redeem", "C1", "S1", "CH-2", "1000.00", 300))
        self.assertEqual((d.status, d.points_delta, d.balance_after), ("applied", -300, 200))
 
    def test_over_limit(self):
        d = self.ledger.apply(op(2, "redeem", "C1", "S1", "CH-2", "1000.00", 301))
        self.assertEqual(d.reject_reason, "limit_exceeded")
        self.assertEqual(d.balance_after, 500)
 
    def test_limit_reason_comes_first(self):
        d = self.ledger.apply(op(2, "redeem", "C1", "S1", "CH-2", "1000.00", 800))
        self.assertEqual(d.reject_reason, "limit_exceeded")   # и лимит, и нехватка
 
    def test_insufficient_balance(self):
        d = self.ledger.apply(op(2, "redeem", "C1", "S1", "CH-2", "5000.00", 501))
        self.assertEqual(d.reject_reason, "insufficient_balance")
 
 
class CheckNumberTests(unittest.TestCase):
    """Возврат и повтор покупки определяются по номеру чека всей сети."""
 
    def setUp(self):
        self.ledger = Ledger()
        self.ledger.apply(op(1, "purchase", "C1", "S1", "CH-1", "2000.00"))  # 100 баллов
 
    def test_return_by_check_number(self):
        d = self.ledger.apply(op(2, "return", "C1", "S1", "CH-1"))
        self.assertEqual((d.status, d.points_delta, d.balance_after), ("applied", -100, 0))
 
    def test_return_of_other_customers_check_is_mismatch_not_not_found(self):
        self.ledger.apply(op(2, "purchase", "C2", "S2", "CH-2", "1000.00"))
        d = self.ledger.apply(op(3, "return", "C1", "S2", "CH-2"))
        self.assertEqual(d.reject_reason, "customer_mismatch")
 
    def test_return_without_purchase(self):
        d = self.ledger.apply(op(2, "return", "C1", "S1", "CH-404"))
        self.assertEqual(d.reject_reason, "purchase_not_found")
 
    def test_second_return(self):
        self.ledger.apply(op(2, "return", "C1", "S1", "CH-1"))
        d = self.ledger.apply(op(3, "return", "C1", "S1", "CH-1"))
        self.assertEqual(d.reject_reason, "already_returned")
 
    def test_check_number_is_unique_across_customers(self):
        d = self.ledger.apply(op(2, "purchase", "C2", "S2", "CH-1", "500.00"))
        self.assertEqual(d.reject_reason, "duplicate_purchase")
        self.assertEqual(self.ledger.balances["C2"], 0)
 
    def test_redeem_may_share_check_number_with_purchase(self):
        d = self.ledger.apply(op(2, "redeem", "C1", "S1", "CH-1", "2000.00", 50))
        self.assertEqual(d.status, "applied")
 
    def test_rejected_purchase_does_not_block_check_number(self):
        # отклонённая покупка не считается принятой, номер остаётся свободным
        self.ledger.apply(op(2, "return", "C1", "S1", "CH-9"))           # отклонён
        d = self.ledger.apply(op(3, "purchase", "C1", "S1", "CH-9", "1000.00"))
        self.assertEqual(d.status, "applied")
 
 
class DebtTests(unittest.TestCase):
    def test_negative_balance_and_repayment(self):
        ledger = Ledger()
        ledger.apply(op(1, "purchase", "C1", "S1", "CH-1", "2490.00"))       # 124
        ledger.apply(op(2, "redeem", "C1", "S1", "CH-1", "2490.00", 100))    # 24
        d = ledger.apply(op(3, "return", "C1", "S1", "CH-1"))
        self.assertEqual(d.balance_after, -100)
        d = ledger.apply(op(4, "purchase", "C1", "S1", "CH-2", "4000.00"))   # +200
        self.assertEqual(d.balance_after, 100)
        d = ledger.apply(op(5, "redeem", "C1", "S1", "CH-3", "10000.00", 300))
        self.assertEqual(d.reject_reason, "insufficient_balance")
 
    def test_negative_balance_blocks_redeem(self):
        ledger = Ledger()
        ledger.balances["C1"] = -10
        d = ledger.apply(op(1, "redeem", "C1", "S1", "CH-1", "1000.00", 1))
        self.assertEqual(d.reject_reason, "insufficient_balance")
 
 
class ScenarioTests(unittest.TestCase):
    def test_full_scenario(self):
        rows, ledger = run()
        got = [(d.status, d.points_delta, d.balance_after, d.reject_reason) for _, _, d in rows]
        self.assertEqual(got, [
            ("applied", 124, 124, None),
            ("rejected", 0, 124, "limit_exceeded"),
            ("rejected", 0, 124, "insufficient_balance"),
            ("applied", -100, 24, None),
            ("applied", -124, -100, None),
            ("rejected", 0, -100, "already_returned"),
            ("applied", 200, 100, None),
            ("rejected", 0, 100, "duplicate_purchase"),
            ("applied", 75, 75, None),
            ("rejected", 0, 100, "customer_mismatch"),
            ("rejected", 0, 100, "purchase_not_found"),
            ("rejected", 0, 75, "duplicate_purchase"),
            ("applied", 49, 124, None),
        ])
        self.assertEqual(ledger.balances, {"C1042": 100, "C2002": 124})
 
 
class MessageParsingTests(unittest.TestCase):
    def test_amount_is_decimal(self):
        o = op(1, "purchase", "C1", "S1", "CH-1", "2490.00")
        self.assertIsInstance(o.amount, Decimal)
 
    def test_naive_time_gets_utc(self):
        from domain import Operation
        o = Operation.from_message({
            "operation_id": "X", "type": "return", "customer_id": "C", "store_id": "S",
            "check_number": "N", "occurred_at": "2026-11-10T14:32:05"})
        self.assertIsNotNone(o.occurred_at.tzinfo)
 
 
if __name__ == "__main__":
    unittest.main(verbosity=2)
