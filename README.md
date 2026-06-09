# KSCM Figurine — Data Pipeline

End-to-end real-time data pipeline for the KSCM figurine business: synthetic data generation → data quality validation → message queue → Snowflake ingestion via Snowpipe → Business Intelligence dashboard.

![Pipeline Architecture](use_case_pipeline.png)

## Architecture

```
pipeline_scheduler.py  (orchestration + scheduling)
        │
        ├─ 1. data_generator_kscm.py   generate synthetic data
        │
        ├─ 2. data_quality.py          validate before ingestion
        │         (nulls · uniqueness · referential integrity · ranges)
        │
        └─ 3. simple_publish_data.py ──► File-based Kafka broker ──► py_snowpipe_kscm.py
                                           (kafka_topics/)                  │
                                                                     data_quality.py
                                                                     (second gate)
                                                                            │
                                                                     Snowpipe (async)
                                                                            │
                                                                   Snowflake FIGURINE_DB
                                                                  ┌─────────┴──────────┐
                                                               PRODUCTS           CUSTOMERS
                                                               ORDERS          ORDER_ITEMS
                                                                            │
                                                                    streamkscm.py
                                                                 (Streamlit dashboard)
```

**Tech stack:** Python · File-based message queue · Snowflake + Snowpipe · Streamlit · Anthropic Claude API

## Project Structure

```
bloc3/
├── dags/
│   └── pipeline_scheduler.py    # Orchestrator: schedules generate → DQ → publish
├── sql/
│   └── setup_snowflake.sql      # Snowflake DDL: warehouse, roles, tables, stages, pipes
├── python/
│   ├── data_generator_kscm.py   # Generates synthetic products / customers / orders
│   ├── data_quality.py          # DQ validation: nulls, uniqueness, referential integrity
│   ├── simple_kafka_setup.py    # File-based message broker (Kafka-like, no external deps)
│   ├── simple_publish_data.py   # Producer: stdin → broker topic
│   ├── simple_consume_data.py   # Consumer (test/debug)
│   ├── py_snowpipe_kscm.py      # Ingestor: broker → DQ → Parquet → Snowpipe → Snowflake
│   └── streamkscm.py            # Streamlit BI dashboard
├── tests/
│   ├── conftest.py              # sys.path setup for pytest
│   ├── test_data_generator.py  # Unit tests — data generation
│   └── test_data_quality.py    # Unit tests — DQ validation (17 cases)
├── screenshots/                 # Dashboard screenshots
├── .env.example                 # Environment variable template
├── requirements.txt
└── README.md
```

## Data Model

| Table | Description |
|---|---|
| `PRODUCTS` | Master catalog — model, theme, finish, price, SKU |
| `CUSTOMERS` | Registered buyers |
| `ORDERS` | Transactions with channel (online / in_person) and status |
| `ORDER_ITEMS` | Line items linking orders to products with quantity and price |

## Setup

### 1. Snowflake

Run `sql/setup_snowflake.sql` in your Snowflake account as `ACCOUNTADMIN`.  
It creates: warehouse `FIGURINE_WH`, role `FIGURINE_ROLE`, database `FIGURINE_DB`, schema `FIGURINE_SCHEMA`, all tables, internal stages, and Snowpipe definitions.

Generate an RSA key pair and link the public key to `FIGURINE_USER`:

```bash
openssl genrsa 4096 | openssl pkcs8 -topk8 -inform PEM -out rsa_key.p8 -nocrypt
openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub
# Copy the ALTER USER command from sql/setup_snowflake.sql and run it in Snowflake
```

### 2. Python environment

```bash
pip install -r requirements.txt
```

### 3. Environment variables

```bash
cp .env.example .env
# Fill in SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD,
# PRIVATE_KEY, and ANTHROPIC_API_KEY (see .env.example for details)
```

> **Two auth methods are used intentionally:**  
> - `py_snowpipe_kscm.py` uses RSA key-pair auth (required by Snowpipe's JWT mechanism)  
> - `streamkscm.py` uses password auth via SQLAlchemy (simpler for read-only queries)

## Running the Pipeline

### Option A — Automated (recommended)

The scheduler handles generation, DQ validation, and publishing on a configurable interval.  
Keep the ingestor running in a separate terminal to consume the queue and load into Snowflake.

**Terminal 1 — ingestor (long-running consumer):**

```bash
python python/py_snowpipe_kscm.py
```

**Terminal 2 — scheduler (orchestrator):**

```bash
# Runs immediately then every 30 minutes
python dags/pipeline_scheduler.py

# Custom interval and volume
PIPELINE_INTERVAL_MIN=60 PIPELINE_NUM_ORDERS=1000 python dags/pipeline_scheduler.py
```

### Option B — Manual (one-shot)

**Terminal 1 — ingestor:**

```bash
export KAFKA_TOPIC="figurine_data_topic"
python python/py_snowpipe_kscm.py
```

**Terminal 2 — generate and publish:**

```bash
export KAFKA_TOPIC="figurine_data_topic"
python python/data_generator_kscm.py 20000 753 | python python/simple_publish_data.py
# args: <num_orders> <num_customers>
```

The ingestor runs a DQ validation gate before connecting to Snowflake. If any check fails the batch is rejected and logged — the Snowflake connection is never opened. On success, each table is converted to Parquet, uploaded to its internal stage, and Snowpipe is triggered. Records appear in Snowflake within ~1 minute.

## Data Quality

DQ validation runs at two points in the pipeline:

| Stage | Where | What is checked |
|---|---|---|
| Pre-publish | `dags/pipeline_scheduler.py` | Full dataset before entering the queue |
| Pre-ingest | `python/py_snowpipe_kscm.py` | Consumed message before Snowflake connection |

**Checks performed:**

| Category | Rules |
|---|---|
| Null / empty | Required fields on every record across all 4 tables |
| Uniqueness | `product_id`, `sku`, `customer_id`, `email`, `order_id` |
| Referential integrity | `customer_id` in orders → customers; `product_id` in items → products |
| Enum validation | `order_status` ∈ {shipped, pending, delivered, cancelled} |
| | `sales_channel` ∈ {online, in_person} |
| Range checks | `base_price > 0`, `quantity ≥ 1`, `price_at_purchase > 0` |
| Structural | Each order must contain at least one item |

Errors (blocking) abort the run and are logged as `[DQ ERROR]`.  
Warnings (non-blocking) are logged as `[DQ WARN]` and execution continues.

## Orchestration

`dags/pipeline_scheduler.py` is the entry point for automated execution.

| Variable | Default | Description |
|---|---|---|
| `PIPELINE_INTERVAL_MIN` | `30` | Minutes between runs |
| `PIPELINE_NUM_ORDERS` | `500` | Orders generated per run |
| `PIPELINE_NUM_CUSTOMERS` | `150` | Customers generated per run |
| `PIPELINE_MAX_RETRIES` | `3` | Retry attempts with exponential back-off |
| `KAFKA_TOPIC` | `figurine_data_topic` | Target topic name |

Execution logs are written to `pipeline.log` and to stdout.

## Dashboard

```bash
streamlit run python/streamkscm.py
```

The dashboard connects to Snowflake and provides 9 tabs:

| Tab | Content |
|---|---|
| Synthèse Exécutive | KPIs, revenue, top products |
| Analyse des Ventes | Sales by channel, theme, finish |
| Segmentation Client | RFM K-Means clustering (4 segments) |
| Prévisions & Science des Données | SARIMA 30-day sales forecast |
| Rétention & CLV | Cohort retention heatmap |
| Chat Interactif IA | Natural language → SQL → results (Claude) |
| Assistant Stratégique IA | C-level executive report generated by Claude |
| Data Quality Monitoring | Null rates, duplicate detection, anomalies |
| R&D Experimental | Market basket analysis, cross-sell opportunities |

> **Anthropic API key:** set `ANTHROPIC_API_KEY` in `.env` before launching.  
> If omitted, the dashboard will prompt for the key in the sidebar at runtime — AI tabs will not function without it.

## Tests

```bash
pytest tests/ -v
```

**38 tests — no external dependencies required (no Snowflake, no API keys).**

| File | Covers | Count |
|---|---|---|
| `test_data_generator.py` | Product count/structure, customer uniqueness, order–product–customer referential integrity | 21 |
| `test_data_quality.py` | Valid dataset passes, empty tables, duplicates, invalid enums, unknown foreign keys, range violations | 17 |

## Verify ingestion in Snowflake

```sql
USE ROLE FIGURINE_ROLE;
USE SCHEMA FIGURINE_DB.FIGURINE_SCHEMA;

SELECT 'PRODUCTS', COUNT(*) FROM PRODUCTS
UNION ALL SELECT 'CUSTOMERS', COUNT(*) FROM CUSTOMERS
UNION ALL SELECT 'ORDERS', COUNT(*) FROM ORDERS
UNION ALL SELECT 'ORDER_ITEMS', COUNT(*) FROM ORDER_ITEMS;

-- Snowpipe copy history (last hour)
SELECT * FROM TABLE(INFORMATION_SCHEMA.COPY_HISTORY(
    TABLE_NAME => 'ORDERS',
    START_TIME => DATEADD(hours, -1, CURRENT_TIMESTAMP())
));
```
