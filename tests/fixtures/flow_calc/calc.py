"""Order totals with discount guard, retry, and batching."""
import os

MAX_RETRIES = 3
BATCH = 100


def _rate_for(sku):
    if not sku:
        raise ValueError("sku required")
    return 1.0


def _fetch_price(sku):
    for attempt in range(MAX_RETRIES):
        try:
            return _rate_for(sku)
        except ConnectionError:
            continue
    raise TimeoutError("price service down")


def _discount_rate(coupon):
    if coupon is None:
        return 0.0
    if coupon == "EXPIRED":
        return 0.0
    return 0.1


def compute_total(items, coupon=None):
    rate = _discount_rate(coupon)
    subtotal = sum(_fetch_price(sku) for sku in items)
    return subtotal * (1 - rate)


def total_all(batches):
    totals = []
    for batch in batches:
        chunk = batch[:BATCH]
        totals.append(compute_total(chunk))
    return totals


def _read_limit():
    raw = os.environ.get("ORDER_LIMIT", "")
    return int(raw) if raw else 0
