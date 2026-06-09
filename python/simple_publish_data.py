# simple_publish_data.py
import os
import sys
import logging
from simple_kafka_setup import broker, SimpleKafkaProducer

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    # Le nom du topic est défini par une variable d'environnement, avec une valeur par défaut
    topic_name = os.getenv("KAFKA_TOPIC", "figurine_data_topic")
    broker.create_topic(topic_name)
    
    producer = SimpleKafkaProducer(broker)
    
    logging.info(f"🚀 Simple Kafka Publisher")
    logging.info(f"📊 Topic: {topic_name}")
    logging.info("📡 Reading from stdin and publishing messages...")
    
    # Lire l'ensemble des données JSON générées depuis l'entrée standard
    json_data = sys.stdin.read()
    
    if not json_data:
        logging.warning("No data received from stdin. Exiting.")
        sys.exit(1)
        
    # Publier le bloc JSON entier comme un seul message
    success = producer.publish(topic_name, json_data)
    
    if success:
        logging.info("✅ Message published successfully!")
    else:
        logging.error("❌ Failed to publish message.")
        
    stats = broker.get_topic_stats(topic_name)
    logging.info(f"📊 Topic Statistics: Queue size = {stats['queue_size']}, Consumers = {stats['consumer_count']}")