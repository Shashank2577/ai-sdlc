import unittest

from pricing.discount import order_total


class OrderTotalTest(unittest.TestCase):
    def test_a_single_item_has_no_discount(self):
        self.assertEqual(order_total(2.00, 1), 2.00)

    def test_nine_items_get_no_discount(self):
        self.assertEqual(order_total(2.00, 9), 18.00)

    def test_ten_items_get_the_bulk_discount(self):
        self.assertEqual(order_total(2.00, 10), 18.00)

    def test_a_large_order_gets_the_bulk_discount(self):
        self.assertEqual(order_total(2.00, 20), 36.00)


if __name__ == "__main__":
    unittest.main()
