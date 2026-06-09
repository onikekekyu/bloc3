# simple_consume_data.py
import os
import time
import logging
import json
from simple_kafka_setup import broker, SimpleKafkaConsumer

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    topic_name = os.getenv("KAFKA_TOPIC", "figurine_data_topic")
    consumer = SimpleKafkaConsumer(broker, consumer_id="test_consumer")
    consumer.subscribe(topic_name)

    logging.info(f"🚀 Simple Kafka Consumer")
    logging.info(f"📊 Topic: {topic_name}")
    logging.info("📡 Waiting for messages... (Press Ctrl+C to stop)")
    
    try:
        while True:
            message = consumer.poll(timeout=5.0) # Attendre jusqu'à 5 secondes
            if message:
                logging.info("📦 Message received!")
                # Affiche un extrait des données pour confirmation
                data = json.loads(message['data'])
                logging.info(f"   -> Contains {len(data.keys())} tables: {list(data.keys())}")
                logging.info(f"   -> {len(data.get('products', []))} products")
                logging.info(f"   -> {len(data.get('customers', []))} customers")
                logging.info(f"   -> {len(data.get('orders', []))} orders")
            else:
                logging.info("... still waiting ...")
    except KeyboardInterrupt:
        logging.info("🛑 Consumer stopped.")