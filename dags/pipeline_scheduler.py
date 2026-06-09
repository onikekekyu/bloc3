"""
Pipeline orchestrator.
Schedules periodic runs of the full ingestion pipeline:
  1. Generate synthetic figurine data
  2. Validate data quality
  3. Publish to the Kafka topic (consumed by python/py_snowpipe_kscm.py)

Usage (from project root):
    python dags/pipeline_scheduler.py

Configuration via environment variables (or .env):
    KAFKA_TOPIC            Topic name          (default: figurine_data_topic)
    PIPELINE_NUM_ORDERS    Orders per run      (default: 500)
    PIPELINE_NUM_CUSTOMERS Customers per run   (default: 150)
    PIPELINE_INTERVAL_MIN  Schedule interval   (default: 30 minutes)
    PIPELINE_MAX_RETRIES   Retries on failure  (default: 3)
"""
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import schedule
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

import data_generator_kscm as gen
from data_quality import validate_dataset
from simple_kafka_setup import broker, SimpleKafkaProducer

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("pipeline.log"),
    ],
)

TOPIC = os.getenv("KAFKA_TOPIC", "figurine_data_topic")
NUM_ORDERS = int(os.getenv("PIPELINE_NUM_ORDERS", "500"))
NUM_CUSTOMERS = int(os.getenv("PIPELINE_NUM_CUSTOMERS", "150"))
INTERVAL_MIN = int(os.getenv("PIPELINE_INTERVAL_MIN", "30"))
MAX_RETRIES = int(os.getenv("PIPELINE_MAX_RETRIES", "3"))


def run_pipeline() -> bool:
    """
    Executes one complete pipeline cycle.
    Returns True on success, False on any failure.
    """
    run_id = datetime.now().strftime("%Y%m%dT%H%M%S")
    logging.info("─── Pipeline run %s started ───", run_id)

    try:
        # Step 1 — Data generation
        logging.info("Generating %d orders for %d customers...", NUM_ORDERS, NUM_CUSTOMERS)
        products = gen.generate_products()
        customers = gen.generate_customers(count=NUM_CUSTOMERS)
        orders = gen.generate_orders(customers, products, count=NUM_ORDERS)
        dataset = {"products": products, "customers": customers, "orders": orders}
        logging.info(
            "Generated: %d products | %d customers | %d orders",
            len(products), len(customers), len(orders),
        )

        # Step 2 — Data quality validation
        logging.info("Running data quality checks...")
        dq_report = validate_dataset(dataset)
        if not dq_report["passed"]:
            logging.error(
                "DQ validation FAILED (%d error(s)) — aborting run %s.",
                dq_report["summary"]["error_count"], run_id,
            )
            return False
        logging.info(
            "DQ validation PASSED — %d warning(s).",
            dq_report["summary"]["warning_count"],
        )

        # Step 3 — Publish to Kafka broker
        logging.info("Publishing dataset to Kafka topic '%s'...", TOPIC)
        broker.create_topic(TOPIC)
        producer = SimpleKafkaProducer(broker)
        success = producer.publish(TOPIC, json.dumps(dataset))
        if not success:
            logging.error("Failed to publish message — aborting run %s.", run_id)
            return False

        stats = broker.get_topic_stats(TOPIC)
        logging.info(
            "Published successfully. Queue depth: %d message(s).",
            stats.get("queue_size", "?"),
        )
        logging.info("─── Pipeline run %s completed ✓ ───", run_id)
        return True

    except Exception as exc:
        logging.error("Unexpected error in run %s: %s", run_id, exc, exc_info=True)
        return False


def run_with_retry() -> None:
    """Wraps run_pipeline() with configurable retry logic and exponential back-off."""
    for attempt in range(1, MAX_RETRIES + 1):
        logging.info("Attempt %d/%d", attempt, MAX_RETRIES)
        if run_pipeline():
            return
        if attempt < MAX_RETRIES:
            wait = attempt * 60
            logging.warning("Run failed — retrying in %ds...", wait)
            time.sleep(wait)
    logging.error("All %d attempt(s) failed for this scheduled run.", MAX_RETRIES)


if __name__ == "__main__":
    logging.info(
        "Scheduler started — pipeline runs every %d minute(s) | "
        "orders=%d | customers=%d | topic='%s'",
        INTERVAL_MIN, NUM_ORDERS, NUM_CUSTOMERS, TOPIC,
    )

    run_with_retry()  # immediate first run on startup
    schedule.every(INTERVAL_MIN).minutes.do(run_with_retry)

    while True:
        schedule.run_pending()
        time.sleep(30)
