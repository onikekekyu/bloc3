"""
Data quality validation module.
Called before every Snowpipe ingestion to catch structural and referential errors early.
"""
import logging
import re
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

VALID_STATUSES = {"shipped", "pending", "delivered", "cancelled"}
VALID_CHANNELS = {"online", "in_person"}
_EMAIL_RE = re.compile(r"[^@]+@[^@]+\.[^@]+")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _check_nulls(records: List[dict], required_fields: List[str], entity: str) -> List[str]:
    errors = []
    for i, rec in enumerate(records):
        for field in required_fields:
            val = rec.get(field)
            if val is None or val == "":
                errors.append(f"{entity}[{i}]: null or empty required field '{field}'")
    return errors


def _check_uniqueness(records: List[dict], field: str, entity: str) -> List[str]:
    seen: set = set()
    errors = []
    for rec in records:
        val = rec.get(field)
        if val is not None and val in seen:
            errors.append(f"{entity}: duplicate {field} '{val}'")
        seen.add(val)
    return errors


# ── Per-table validators ──────────────────────────────────────────────────────

def validate_products(products: List[dict]) -> Tuple[List[str], List[str]]:
    errors, warnings = [], []

    if not products:
        errors.append("products: dataset is empty")
        return errors, warnings

    errors += _check_nulls(
        products,
        ["product_id", "model_name", "theme", "finish", "base_price", "sku"],
        "products",
    )
    errors += _check_uniqueness(products, "product_id", "products")
    errors += _check_uniqueness(products, "sku", "products")

    for i, p in enumerate(products):
        price = p.get("base_price")
        if price is not None and price <= 0:
            errors.append(f"products[{i}]: base_price must be positive, got {price}")
        qty = p.get("stock_quantity")
        if qty is not None and qty < 0:
            warnings.append(f"products[{i}]: negative stock_quantity ({qty})")

    return errors, warnings


def validate_customers(customers: List[dict]) -> Tuple[List[str], List[str]]:
    errors, warnings = [], []

    if not customers:
        errors.append("customers: dataset is empty")
        return errors, warnings

    errors += _check_nulls(
        customers,
        ["customer_id", "first_name", "last_name", "email"],
        "customers",
    )
    errors += _check_uniqueness(customers, "customer_id", "customers")
    errors += _check_uniqueness(customers, "email", "customers")

    for i, c in enumerate(customers):
        email = c.get("email", "")
        if email and not _EMAIL_RE.match(email):
            warnings.append(f"customers[{i}]: malformed email '{email}'")

    return errors, warnings


def validate_orders(
    orders: List[dict],
    valid_customer_ids: set,
    valid_product_ids: set,
) -> Tuple[List[str], List[str]]:
    errors, warnings = [], []

    if not orders:
        errors.append("orders: dataset is empty")
        return errors, warnings

    errors += _check_nulls(
        orders,
        ["order_id", "customer_id", "order_date", "order_status", "sales_channel"],
        "orders",
    )
    errors += _check_uniqueness(orders, "order_id", "orders")

    for i, o in enumerate(orders):
        status = o.get("order_status")
        if status and status not in VALID_STATUSES:
            errors.append(
                f"orders[{i}]: invalid status '{status}', expected one of {VALID_STATUSES}"
            )

        channel = o.get("sales_channel")
        if channel and channel not in VALID_CHANNELS:
            errors.append(
                f"orders[{i}]: invalid channel '{channel}', expected one of {VALID_CHANNELS}"
            )

        cid = o.get("customer_id")
        if cid and valid_customer_ids and cid not in valid_customer_ids:
            errors.append(f"orders[{i}]: unknown customer_id '{cid}'")

        if channel == "in_person" and not o.get("store_id"):
            warnings.append(f"orders[{i}]: in_person order has no store_id")

        items = o.get("order_items", [])
        if not items:
            errors.append(f"orders[{i}]: order has no items")
            continue

        for j, item in enumerate(items):
            pid = item.get("product_id")
            if pid and valid_product_ids and pid not in valid_product_ids:
                errors.append(
                    f"orders[{i}].items[{j}]: unknown product_id '{pid}'"
                )
            qty = item.get("quantity")
            if qty is not None and qty < 1:
                errors.append(
                    f"orders[{i}].items[{j}]: quantity must be >= 1, got {qty}"
                )
            price = item.get("price_at_purchase")
            if price is not None and price <= 0:
                errors.append(
                    f"orders[{i}].items[{j}]: price_at_purchase must be positive, got {price}"
                )

    return errors, warnings


# ── Public API ────────────────────────────────────────────────────────────────

def validate_dataset(dataset: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validates the unified dataset before ingestion into Snowflake.

    Returns a report dict:
      - passed   : bool
      - errors   : list of blocking issues
      - warnings : list of non-blocking anomalies
      - summary  : counts and status string
    """
    products = dataset.get("products", [])
    customers = dataset.get("customers", [])
    orders = dataset.get("orders", [])

    p_errors, p_warnings = validate_products(products)
    c_errors, c_warnings = validate_customers(customers)

    valid_product_ids = {p["product_id"] for p in products if p.get("product_id")}
    valid_customer_ids = {c["customer_id"] for c in customers if c.get("customer_id")}
    o_errors, o_warnings = validate_orders(orders, valid_customer_ids, valid_product_ids)

    all_errors = p_errors + c_errors + o_errors
    all_warnings = p_warnings + c_warnings + o_warnings

    for err in all_errors:
        logger.error("[DQ ERROR] %s", err)
    for warn in all_warnings:
        logger.warning("[DQ WARN]  %s", warn)

    passed = len(all_errors) == 0
    summary = {
        "products_checked": len(products),
        "customers_checked": len(customers),
        "orders_checked": len(orders),
        "error_count": len(all_errors),
        "warning_count": len(all_warnings),
        "status": "PASSED" if passed else "FAILED",
    }
    logger.info("[DQ SUMMARY] %s", summary)

    return {"passed": passed, "errors": all_errors, "warnings": all_warnings, "summary": summary}
