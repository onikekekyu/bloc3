import sys
import rapidjson as json
import uuid
import random
from faker import Faker
from datetime import datetime

# --- Configuration ---
# Using Faker for generating realistic mock data.
fake = Faker()

# --- Deconstructed Inventory for a Structured Product Catalog ---
# This defines the components of each product for a clean 'products' table.
MODEL_NAMES = ["Kirsten", "Matteo", "Sasha", "Corentin"]
THEMES = ["Policier", "Vampire", "Super-heros", "Pirate", "Astronaute"]
FINISHES = {
    # Finish type maps to a base price
    "Gold": 299.99,
    "Silver": 199.99,
    "Regular": 99.99
}

# --- Point of Sale Stores ---
# This data helps differentiate online vs. in-person sales channels.
STORES = ["BOUTIQUE-PARIS-01", "BOUTIQUE-LYON-01", "POPUP-MARSEILLE-01"]


# --- Generator Functions for the 3 Core Tables ---

def generate_products():
    """Generates the master product catalog. (Table 1)"""
    products = []
    for model in MODEL_NAMES:
        for theme in THEMES:
            for finish, price in FINISHES.items():
                product = {
                    "product_id": str(uuid.uuid4()),
                    "model_name": model,
                    "theme": theme,
                    "finish": finish,
                    "base_price": price,
                    "sku": f"{model[:3].upper()}-{theme[:4].upper()}-{finish[:3].upper()}",
                    "stock_quantity": fake.random_int(min=0, max=200),
                    "launch_date": fake.date_this_decade().isoformat()
                }
                products.append(product)
    # Add the special item from the original list
    products.append({
        "product_id": str(uuid.uuid4()), "model_name": "Corentin", "theme": "Nu", "finish": "Gold",
        "base_price": 499.99, "sku": "COR-NU-GLD", "stock_quantity": fake.random_int(min=0, max=50),
        "launch_date": fake.date_this_decade().isoformat()
    })
    return products

def generate_customers(count=150):
    """Generates a list of unique customers. (Table 2)"""
    customers = []
    for _ in range(count):
        customer = {
            "customer_id": str(uuid.uuid4()),
            "first_name": fake.first_name(),
            "last_name": fake.last_name(),
            "email": fake.unique.email(),
            "registration_date": fake.date_time_this_year().isoformat()
        }
        customers.append(customer)
    return customers

def generate_orders(customers, products, count=250):
    """
    Generates a list of orders, with order items nested inside. (Table 3)
    This links customers and products together.
    """
    orders = []
    for _ in range(count):
        customer = random.choice(customers)
        order_date = fake.date_time_this_year()
        
        # Determine the sales channel and associated details
        channel = random.choice(['online', 'in_person'])
        store_id = random.choice(STORES) if channel == 'in_person' else None

        # Build the list of items for this specific order
        order_items = []
        for _ in range(random.randint(1, 3)):
            product = random.choice(products)
            item = {
                "product_id": product['product_id'],
                "quantity": random.randint(1, 2),
                "price_at_purchase": product['base_price'],
                "rfid": hex(random.getrandbits(96))
            }
            order_items.append(item)

        order = {
            "order_id": str(uuid.uuid4()),
            "customer_id": customer['customer_id'],
            "order_date": order_date.isoformat(),
            "order_status": random.choice(['shipped', 'pending', 'delivered', 'cancelled']),
            "sales_channel": channel,
            "store_id": store_id,
            "order_items": order_items  # Nested list of items
        }
        orders.append(order)
            
    return orders


# --- Main Execution Block ---
if __name__ == "__main__":
    # Default values for data generation
    num_orders = 250
    num_customers = 150

    # Read counts from command-line arguments if provided
    if len(sys.argv) > 1:
        try:
            num_orders = int(sys.argv[1])
        except ValueError:
            print("Error: The first argument (num_orders) must be an integer.", file=sys.stderr)
            sys.exit(1)
    
    if len(sys.argv) > 2:
        try:
            num_customers = int(sys.argv[2])
        except ValueError:
            print("Error: The second argument (num_customers) must be an integer.", file=sys.stderr)
            sys.exit(1)

    print("--- Generating a simplified 3-table dataset for the figurine business ---", file=sys.stderr)

    # 1. Generate the master data tables first, using the specified counts.
    master_products = generate_products()
    master_customers = generate_customers(count=num_customers)

    # 2. Generate the transactional data that links the master tables.
    all_orders = generate_orders(master_customers, master_products, count=num_orders)

    # 3. Bundle the three tables into a single dictionary.
    unified_dataset = {
        "products": master_products,
        "customers": master_customers,
        "orders": all_orders,
    }

    print(f"Generated data for {len(unified_dataset.keys())} tables.", file=sys.stderr)
    print(f"-> {len(master_products)} products", file=sys.stderr)
    print(f"-> {len(master_customers)} customers", file=sys.stderr)
    print(f"-> {len(all_orders)} orders", file=sys.stderr)
    
    # 4. Dump the entire unified structure to standard output as a single JSON object.
    json_output = json.dumps(unified_dataset, indent=4) + '\n'
    sys.stdout.write(json_output)
