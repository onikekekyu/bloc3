import pytest
from data_generator_kscm import generate_products, generate_customers, generate_orders

# 4 models × 5 themes × 3 finishes + 1 édition spéciale (Corentin Nu Gold) = 61
EXPECTED_PRODUCT_COUNT = 61
REQUIRED_PRODUCT_FIELDS = {"product_id", "model_name", "theme", "finish", "base_price", "sku", "stock_quantity", "launch_date"}
REQUIRED_CUSTOMER_FIELDS = {"customer_id", "first_name", "last_name", "email", "registration_date"}
REQUIRED_ORDER_FIELDS = {"order_id", "customer_id", "order_date", "order_status", "sales_channel", "store_id", "order_items"}
REQUIRED_ITEM_FIELDS = {"product_id", "quantity", "price_at_purchase", "rfid"}
VALID_STATUSES = {"shipped", "pending", "delivered", "cancelled"}
VALID_CHANNELS = {"online", "in_person"}


class TestGenerateProducts:
    def test_count(self):
        assert len(generate_products()) == EXPECTED_PRODUCT_COUNT

    def test_required_fields(self):
        for p in generate_products():
            assert REQUIRED_PRODUCT_FIELDS.issubset(p.keys()), f"Missing fields in product: {p}"

    def test_unique_ids(self):
        products = generate_products()
        ids = [p["product_id"] for p in products]
        assert len(ids) == len(set(ids))

    def test_unique_skus(self):
        products = generate_products()
        skus = [p["sku"] for p in products]
        assert len(skus) == len(set(skus))

    def test_prices_are_positive(self):
        for p in generate_products():
            assert p["base_price"] > 0

    def test_special_edition_exists(self):
        products = generate_products()
        special = [p for p in products if p["model_name"] == "Corentin" and p["theme"] == "Nu"]
        assert len(special) == 1


class TestGenerateCustomers:
    def test_count(self):
        assert len(generate_customers(count=50)) == 50

    def test_required_fields(self):
        for c in generate_customers(count=10):
            assert REQUIRED_CUSTOMER_FIELDS.issubset(c.keys()), f"Missing fields in customer: {c}"

    def test_unique_emails(self):
        customers = generate_customers(count=100)
        emails = [c["email"] for c in customers]
        assert len(emails) == len(set(emails))

    def test_unique_ids(self):
        customers = generate_customers(count=50)
        ids = [c["customer_id"] for c in customers]
        assert len(ids) == len(set(ids))


class TestGenerateOrders:
    def setup_method(self):
        self.products = generate_products()
        self.customers = generate_customers(count=20)
        self.orders = generate_orders(self.customers, self.products, count=30)

    def test_count(self):
        assert len(self.orders) == 30

    def test_required_fields(self):
        for o in self.orders:
            assert REQUIRED_ORDER_FIELDS.issubset(o.keys()), f"Missing fields in order: {o}"

    def test_customer_ids_are_valid(self):
        valid_ids = {c["customer_id"] for c in self.customers}
        for o in self.orders:
            assert o["customer_id"] in valid_ids

    def test_status_values(self):
        for o in self.orders:
            assert o["order_status"] in VALID_STATUSES

    def test_sales_channel_values(self):
        for o in self.orders:
            assert o["sales_channel"] in VALID_CHANNELS

    def test_in_person_orders_have_store_id(self):
        for o in self.orders:
            if o["sales_channel"] == "in_person":
                assert o["store_id"] is not None

    def test_online_orders_have_no_store_id(self):
        for o in self.orders:
            if o["sales_channel"] == "online":
                assert o["store_id"] is None

    def test_each_order_has_at_least_one_item(self):
        for o in self.orders:
            assert len(o["order_items"]) >= 1

    def test_order_items_have_required_fields(self):
        for o in self.orders:
            for item in o["order_items"]:
                assert REQUIRED_ITEM_FIELDS.issubset(item.keys()), f"Missing fields in item: {item}"

    def test_order_item_product_ids_are_valid(self):
        valid_ids = {p["product_id"] for p in self.products}
        for o in self.orders:
            for item in o["order_items"]:
                assert item["product_id"] in valid_ids

    def test_order_item_quantities_are_positive(self):
        for o in self.orders:
            for item in o["order_items"]:
                assert item["quantity"] >= 1
