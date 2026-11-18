"""权限和客户端的稳定契约；无需数据库即可检查错误路径与输入不变性。"""

import copy
import unittest
from unittest.mock import patch

from security import policy
from security.database import DemoError
from tools import query_sales


class PolicyContracts(unittest.TestCase):
    def test_months_reject_invalid_or_discontinuous_periods(self):
        for months in (None, [], ["0000-01"], ["2026-13"], ["2026-01", "2026-03"]):
            with self.subTest(months=months), self.assertRaises(DemoError):
                policy.normalize_months(months)
        self.assertEqual(policy.normalize_months(["2026-02", "2026-01"]), ["2026-01", "2026-02"])

    def test_reversed_dates_within_same_month_are_rejected(self):
        cube_query = {
            "timeDimensions": [
                {
                    "dimension": "Sales.sales_date",
                    "dateRange": ["2026-01-31", "2026-01-01"],
                }
            ]
        }
        with self.assertRaises(DemoError):
            policy._months_from_query(cube_query)

    def test_rewrite_preserves_user_or_and_input(self):
        cube_query = {
            "measures": ["Sales.total_amount"],
            "timeDimensions": [{"dimension": "Sales.sales_date", "dateRange": ["2026-01-01", "2026-01-31"]}],
            "filters": [
                {
                    "or": [
                        {"member": "Sales.hospital_code", "operator": "equals", "values": ["H1"]},
                        {"member": "Sales.product_code", "operator": "equals", "values": ["P2"]},
                    ]
                }
            ],
        }
        context = {"viewerEmployeeCode": "M001", "months": ["2026-01"]}
        original = copy.deepcopy((cube_query, context))
        scope = {"units": [("2026-01", "H1", "P1")]}
        with (
            patch("security.database.connect"),
            patch.object(policy, "_require_active_user"),
            patch.object(policy, "_resolve_sales_scope", return_value=scope),
        ):
            rewritten = policy.rewrite_query(cube_query, context)
        self.assertEqual((cube_query, context), original)
        self.assertEqual(rewritten["filters"][0]["and"][0], cube_query["filters"][0])
        self.assertEqual(rewritten["filters"][0]["and"][1]["values"], ['["2026-01", "H1", "P1"]'])

    def test_database_failure_never_returns_unfiltered_query(self):
        with (
            patch("security.database.connect"),
            patch.object(policy, "_require_active_user", side_effect=RuntimeError("database unavailable")),
        ):
            with self.assertRaises(RuntimeError):
                policy.rewrite_query({"measures": ["Sales.total_amount"]}, {"viewerEmployeeCode": "M001"})

    def test_truncated_sales_result_is_not_reported_as_complete(self):
        response = (200, {"data": [{"Sales.total_amount": "1"}] * 1000})
        with patch("tools.cube_request", return_value=response), self.assertRaises(DemoError):
            query_sales("M001", ["M001"], ["2026-01"])


if __name__ == "__main__":
    unittest.main()
