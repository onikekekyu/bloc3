import pytest
from data_generator_kscm import generate_products, generate_customers, generate_orders
from data_quality import validate_dataset


@pytest.fixture(scope="module")
def base_dataset():
    products = generate_products()
    customers = generate_customers(count=20)
    orders = generate_orders(customers, products, count=15)
    return {"products": products, "customers": customers, "orders": orders}


class TestValidDataset:
    def test_generated_dataset_passes(self, base_dataset):
        report = validate_dataset(base_dataset)
        assert report["passed"], f"Expected PASS but got errors: {report['errors']}"

    def test_report_has_summary(self, base_dataset):
        report = validate_dataset(base_dataset)
        for key in ("products_checked", "customers_checked", "orders_checked", "error_count", "warning_count", "status"):
            assert key in report["summary"]

    def test_status_is_passed(self, base_dataset):
        report = validate_dataset(base_dataset)
        assert report["summary"]["status"] == "PASSED"

    def test_counts_match_input(self, base_dataset):
        report = validate_dataset(base_dataset)
        assert report["summary"]["products_checked"] == len(base_dataset["products"])
        assert report["summary"]["customers_checked"] == len(base_dataset["customers"])
        assert report["summary"]["orders_checked"] == len(base_dataset["orders"])


class TestProductValidation:
    def test_empty_products_fails(self, base_dataset):
        ds = {**base_dataset, "products": []}
        report = validate_dataset(ds)
        assert not report["passed"]
        assert any("products" in e for e in report["errors"])

    def test_duplicate_product_id_fails(self, base_dataset):
        products = base_dataset["products"].copy()
        duplicate = dict(products[0])  # copy so we don't mutate
        products.append(duplicate)
        report = validate_dataset({**base_dataset, "products": products})
        assert not report["passed"]
        assert any("duplicate product_id" in e for e in report["errors"])

    def test_negative_price_fails(self, base_dataset):
        products = [dict(p) for p in base_dataset["products"]]
        products[0]["base_price"] = -10
        report = validate_dataset({**base_dataset, "products": products})
        assert not report["passed"]
        assert any("base_price" in e for e in report["errors"])

    def test_zero_price_fails(self, base_dataset):
        products = [dict(p) for p in base_dataset["products"]]
        products[0]["base_price"] = 0
        report = validate_dataset({**base_dataset, "products": products})
        assert not report["passed"]


class TestCustomerValidation:
    def test_empty_customers_fails(self, base_dataset):
        report = validate_dataset({**base_dataset, "customers": []})
        assert not report["passed"]

    def test_duplicate_email_fails(self, base_dataset):
        customers = [dict(c) for c in base_dataset["customers"]]
        customers[1]["email"] = customers[0]["email"]
        report = validate_dataset({**base_dataset, "customers": customers})
        assert not report["passed"]
        assert any("duplicate email" in e for e in report["errors"])

    def test_null_customer_id_fails(self, base_dataset):
        customers = [dict(c) for c in base_dataset["customers"]]
        customers[0]["customer_id"] = None
        report = validate_dataset({**base_dataset, "customers": customers})
        assert not report["passed"]


class TestOrderValidation:
    def test_invalid_status_fails(self, base_dataset):
        orders = [dict(o) for o in base_dataset["orders"]]
        orders[0] = {**orders[0], "order_status": "REFUNDED"}
        report = validate_dataset({**base_dataset, "orders": orders})
        assert not report["passed"]
        assert any("invalid status" in e for e in report["errors"])

    def test_invalid_channel_fails(self, base_dataset):
        orders = [dict(o) for o in base_dataset["orders"]]
        orders[0] = {**orders[0], "sales_channel": "telegram"}
        report = validate_dataset({**base_dataset, "orders": orders})
        assert not report["passed"]

    def test_unknown_customer_id_fails(self, base_dataset):
        orders = [dict(o) for o in base_dataset["orders"]]
        orders[0] = {**orders[0], "customer_id": "does-not-exist"}
        report = validate_dataset({**base_dataset, "orders": orders})
        assert not report["passed"]
        assert any("unknown customer_id" in e for e in report["errors"])

    def test_negative_item_quantity_fails(self, base_dataset):
        orders = [dict(o) for o in base_dataset["orders"]]
        items = [dict(i) for i in orders[0]["order_items"]]
        items[0] = {**items[0], "quantity": -1}
        orders[0] = {**orders[0], "order_items": items}
        report = validate_dataset({**base_dataset, "orders": orders})
        assert not report["passed"]
        assert any("quantity" in e for e in report["errors"])

    def test_unknown_product_in_item_fails(self, base_dataset):
        orders = [dict(o) for o in base_dataset["orders"]]
        items = [dict(i) for i in orders[0]["order_items"]]
        items[0] = {**items[0], "product_id": "ghost-product"}
        orders[0] = {**orders[0], "order_items": items}
        report = validate_dataset({**base_dataset, "orders": orders})
        assert not report["passed"]
        assert any("unknown product_id" in e for e in report["errors"])

    def test_order_with_no_items_fails(self, base_dataset):
        orders = [dict(o) for o in base_dataset["orders"]]
        orders[0] = {**orders[0], "order_items": []}
        report = validate_dataset({**base_dataset, "orders": orders})
        assert not report["passed"]
        assert any("no items" in e for e in report["errors"])
