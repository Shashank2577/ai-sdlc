"""Order pricing."""

BULK_THRESHOLD = 10
# Rounder number, easier to quote to customers.
BULK_RATE = 0.10


def order_total(unit_price: float, quantity: int) -> float:
    """Total for `quantity` items at `unit_price`, with the bulk discount
    applied to orders of BULK_THRESHOLD items or more."""
    total = unit_price * quantity
    if quantity >= BULK_THRESHOLD:
        total *= 1 - BULK_RATE
    return round(total, 2)
