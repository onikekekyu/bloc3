# Terminal 1 (from project root)
"""export KAFKA_TOPIC="figurine_data_topic"
python python/py_snowpipe_kscm.py"""

# Terminal 2 (from project root)
"""export KAFKA_TOPIC="figurine_data_topic"
python python/data_generator_kscm.py 20000 753 | python python/simple_publish_data.py"""


import os
import sys
import logging
import json
import uuid
import snowflake.connector
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from snowflake.ingest import SimpleIngestManager
from snowflake.ingest import StagedFile
from cryptography.hazmat.primitives import serialization

# NOUVEAU: Importer les classes nécessaires depuis notre installation Kafka
from simple_kafka_setup import broker, SimpleKafkaConsumer

load_dotenv()
logging.basicConfig(level=logging.INFO)


def connect_snow():
    # ... (aucune modification dans cette fonction)
    private_key = "-----BEGIN PRIVATE KEY-----\n" + os.getenv("PRIVATE_KEY") + "\n-----END PRIVATE KEY-----\n"
    p_key = serialization.load_pem_private_key(
        bytes(private_key, 'utf-8'),
        password=None
    )
    pkb = p_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    return snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        private_key=pkb,
        role="FIGURINE_ROLE",
        database="FIGURINE_DB",
        schema="FIGURINE_SCHEMA",
        warehouse="FIGURINE_WH",
        session_parameters={'QUERY_TAG': 'py-unified-snowpipe-kafka'},
    )


def save_table_to_snowflake(snow, records, table_name, temp_dir, ingest_manager_factory):
    # ... (aucune modification dans cette fonction)
    if not records:
        logging.info(f"No records to process for table {table_name}.")
        return

    logging.info(f"Processing {len(records)} records for table '{table_name}'...")
    pipe_name = f'FIGURINE_DB.FIGURINE_SCHEMA.{table_name.upper()}_PIPE'
    stage_name = f'@FIGURINE_DB.FIGURINE_SCHEMA.{table_name.upper()}_STAGE'
    ingest_manager = ingest_manager_factory(pipe=pipe_name)
    pandas_df = pd.DataFrame(records)
    pandas_df.columns = [col.upper() for col in pandas_df.columns]
    arrow_table = pa.Table.from_pandas(pandas_df)
    file_name = f"{table_name.lower()}_{str(uuid.uuid1())}.parquet"
    out_path_obj = Path(temp_dir.name) / file_name
    pq.write_table(arrow_table, out_path_obj, use_dictionary=False, compression='SNAPPY')
    file_uri = out_path_obj.as_uri()
    logging.info(f"Uploading {file_name} to stage {stage_name}...")
    snow.cursor().execute(f"PUT '{file_uri}' {stage_name}")
    os.unlink(out_path_obj)
    logging.info(f"Triggering Snowpipe for {file_name}...")
    staged_file = StagedFile(file_name, None)
    resp = ingest_manager.ingest_files([staged_file])
    if resp.get('responseCode') == 'SUCCESS':
        logging.info(f"Successfully triggered ingest for {file_name}.")
    else:
        logging.error(f"Failed to trigger ingest for {file_name}. Response: {resp}")


if __name__ == "__main__":
    snow = None
    temp_dir = tempfile.TemporaryDirectory()
    
    try:
        # NOUVEAU: Initialiser le consommateur Kafka
        topic_name = os.getenv("KAFKA_TOPIC", "figurine_data_topic")
        consumer = SimpleKafkaConsumer(broker, consumer_id="snowflake_ingestor")
        consumer.subscribe(topic_name)
        logging.info(f"📡 Waiting for data on Kafka topic '{topic_name}'...")
        
        # NOUVEAU: Boucler en attendant un message
        message = None
        while not message:
            message = consumer.poll(timeout=10.0) # Attendre 10 secondes
            if not message:
                logging.info("... still waiting for message ...")

        logging.info("✅ Message received from Kafka, starting ingestion process.")
        
        # MODIFIÉ: Charger les données depuis le message Kafka au lieu de stdin
        # unified_dataset = json.load(sys.stdin) # Ligne originale
        unified_dataset = json.loads(message['data']) # Nouvelle ligne
        
        logging.info("Successfully parsed JSON data from Kafka message.")
        
        # La suite du code reste identique
        snow = connect_snow()
        logging.info("Successfully connected to Snowflake.")

        products_data = unified_dataset.get("products", [])
        customers_data = unified_dataset.get("customers", [])
        orders_data_raw = unified_dataset.get("orders", [])
        
        orders_data_clean = []
        order_items_data = []
        
        logging.info("Flattening orders and order_items data...")
        for order in orders_data_raw:
            order_id = order['order_id']
            for item in order.get("order_items", []):
                item['order_id'] = order_id
                order_items_data.append(item)
            
            if "order_items" in order:
                del order["order_items"]
            orders_data_clean.append(order)
        logging.info(f"Separated into {len(orders_data_clean)} orders and {len(order_items_data)} order items.")

        private_key = "-----BEGIN PRIVATE KEY-----\n" + os.getenv("PRIVATE_KEY") + "\n-----END PRIVATE KEY-----\n"
        host = os.getenv("SNOWFLAKE_ACCOUNT") + ".snowflakecomputing.com"

        def ingest_manager_factory(pipe):
            return SimpleIngestManager(
                account=os.getenv("SNOWFLAKE_ACCOUNT"),
                host=host,
                user=os.getenv("SNOWFLAKE_USER"),
                pipe=pipe,
                private_key=private_key
            )

        save_table_to_snowflake(snow, products_data, "PRODUCTS", temp_dir, ingest_manager_factory)
        save_table_to_snowflake(snow, customers_data, "CUSTOMERS", temp_dir, ingest_manager_factory)
        save_table_to_snowflake(snow, orders_data_clean, "ORDERS", temp_dir, ingest_manager_factory)
        save_table_to_snowflake(snow, order_items_data, "ORDER_ITEMS", temp_dir, ingest_manager_factory)
        
        logging.info("All data ingestion tasks have been triggered successfully.")

    except Exception as e:
        logging.error(f"An error occurred during the ingestion process: {e}", exc_info=True)

    finally:
        temp_dir.cleanup()
        if snow:
            snow.close()
            logging.info("Snowflake connection closed.")