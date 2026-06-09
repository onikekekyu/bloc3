# simple_kafka_setup.py (version corrigée avec get_topic_stats)
import json
import time
import os
import uuid
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class SimpleKafkaBroker:
    """Broker Kafka simple qui utilise le système de fichiers pour la communication inter-processus."""
    
    def __init__(self, base_path: str = "kafka_topics"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(exist_ok=True)
        # Désactivé pour un affichage plus propre
        # logging.info(f"File-based Kafka broker initialized at: {self.base_path.resolve()}")

    def create_topic(self, topic_name: str):
        topic_path = self.base_path / topic_name
        topic_path.mkdir(exist_ok=True)
        # Désactivé pour un affichage plus propre
        # logging.info(f"Topic '{topic_name}' is ready at: {topic_path.resolve()}")

    def publish_message(self, topic_name: str, message: str) -> bool:
        topic_path = self.base_path / topic_name
        if not topic_path.exists():
            logging.error(f"Topic '{topic_name}' does not exist.")
            return False
        
        try:
            message_data = {
                'id': str(uuid.uuid4()),
                'timestamp': datetime.now().isoformat(),
                'data': message,
                'topic': topic_name
            }
            message_file = topic_path / f"{int(time.time() * 1_000_000)}_{uuid.uuid4()}.json"
            
            with open(message_file, 'w') as f:
                json.dump(message_data, f)
            return True
            
        except Exception as e:
            logging.error(f"Failed to publish message to topic '{topic_name}': {e}")
            return False
    
    # NOUVEAU : La fonction manquante a été ajoutée ici
    def get_topic_stats(self, topic_name: str) -> Dict[str, Any]:
        """Simule les statistiques du topic en comptant les fichiers."""
        topic_path = self.base_path / topic_name
        if not topic_path.exists():
            return {"error": "Topic not found"}
        
        queue_size = len(list(topic_path.iterdir()))
        # Le broker ne connaît pas les consommateurs dans ce modèle, on retourne 0.
        return {
            "topic": topic_name,
            "queue_size": queue_size,
            "consumer_count": 0 
        }

# --- Le reste du fichier ne change pas ---

broker = SimpleKafkaBroker()

class SimpleKafkaProducer:
    def __init__(self, broker_instance):
        self.broker = broker_instance
    def publish(self, topic_name: str, message: str) -> bool:
        return self.broker.publish_message(topic_name, message)

class SimpleKafkaConsumer:
    def __init__(self, broker_instance, consumer_id: str = None):
        self.broker = broker_instance
        self.consumer_id = consumer_id or f"consumer_{os.getpid()}"
        self.topic_path = None
    def subscribe(self, topic_name: str):
        self.broker.create_topic(topic_name)
        self.topic_path = self.broker.base_path / topic_name
    def poll(self, timeout: float = 1.0) -> Dict[str, Any]:
        if not self.topic_path: return None
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                files = sorted(self.topic_path.iterdir(), key=os.path.getmtime)
                if not files:
                    time.sleep(0.1)
                    continue
                message_file = files[0]
                with open(message_file, 'r') as f:
                    message_content = json.load(f)
                os.remove(message_file)
                return message_content
            except (FileNotFoundError, IndexError, json.JSONDecodeError):
                time.sleep(0.1)
                continue
            except Exception as e:
                logging.error(f"Consumer poll error: {e}")
                return None
        return None