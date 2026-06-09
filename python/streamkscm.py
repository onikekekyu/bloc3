import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine
from datetime import datetime
from sklearn.cluster import KMeans
from statsmodels.tsa.statespace.sarimax import SARIMAX
from itertools import combinations
from collections import Counter
import anthropic

# --- Page Configuration ---
st.set_page_config(
    page_title="Figurine Business Intelligence",
    page_icon="👑",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Custom CSS for Aesthetics ---
st.markdown("""
<style>
    /* Main titles */
    .st-emotion-cache-18ni7ap, .st-emotion-cache-10trblm {
        color: #1a5276; /* Darker blue */
    }
    /* Metric labels */
    .st-emotion-cache-1g8sfyr, .st-emotion-cache-d8Jz4L {
        color: #21618c;
    }
    /* Use a more professional font */
    html, body, [class*="st-"] {
        font-family: 'Helvetica Neue', sans-serif;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 24px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        background-color: #f0f2f6;
        border-radius: 4px 4px 0px 0px;
        gap: 1px;
        padding-top: 10px;
        padding-bottom: 10px;
    }
    .stTabs [aria-selected="true"] {
        background-color: #eaf2f8;
    }
    /* Fix expander arrow display issues */
    .stExpander svg {
        width: 1rem;
        height: 1rem;
    }
    details summary {
        cursor: pointer;
    }
    /* Ensure expander icons render properly */
    [data-testid="stExpander"] details summary svg {
        display: inline-block;
        vertical-align: middle;
    }
    /* Masque le texte des icônes Material si la police est bloquée */
    [data-testid="stIconMaterial"] {
        font-size: 0px; /* Rend le texte de l'icône invisible */
    }
</style>
""", unsafe_allow_html=True)


# --- Load Environment Variables ---
load_dotenv()

# --- Snowflake Connection ---
@st.cache_resource
def get_snowflake_connection():
    """Establishes a connection to the Snowflake database using SQLAlchemy."""
    try:
        connection_url = (
            f"snowflake://{os.getenv('SNOWFLAKE_USER')}:{os.getenv('SNOWFLAKE_PASSWORD')}"
            f"@{os.getenv('SNOWFLAKE_ACCOUNT')}/FIGURINE_DB/FIGURINE_SCHEMA"
            f"?warehouse=FIGURINE_WH&role=FIGURINE_ROLE"
        )
        engine = create_engine(connection_url)
        return engine
    except Exception as e:
        st.error(f"Error connecting to Snowflake: {e}")
        return None

# --- Data Loading Function ---
@st.cache_data(ttl=600)
def load_data(_engine):
    """Loads and preprocesses data from Snowflake."""
    main_query = """
    SELECT
        O.ORDER_ID, O.ORDER_DATE, O.SALES_CHANNEL,
        C.CUSTOMER_ID, C.FIRST_NAME, C.LAST_NAME,
        P.PRODUCT_ID, P.MODEL_NAME, P.THEME, P.FINISH,
        OI.QUANTITY, OI.PRICE_AT_PURCHASE,
        (OI.QUANTITY * OI.PRICE_AT_PURCHASE) AS TOTAL_SALE
    FROM ORDERS AS O
    INNER JOIN CUSTOMERS AS C ON O.CUSTOMER_ID = C.CUSTOMER_ID
    INNER JOIN ORDER_ITEMS AS OI ON O.ORDER_ID = OI.ORDER_ID
    INNER JOIN PRODUCTS AS P ON OI.PRODUCT_ID = P.PRODUCT_ID
    WHERE O.ORDER_STATUS != 'cancelled'
    AND OI.PRODUCT_ID IS NOT NULL
    AND P.PRODUCT_ID IS NOT NULL;
    """
    try:
        df = pd.read_sql(main_query, _engine)
        df.columns = [col.upper() for col in df.columns]
        df['ORDER_DATE'] = pd.to_datetime(df['ORDER_DATE'])
        return df
    except Exception as e:
        st.error(f"Error executing query: {e}")
        return pd.DataFrame()

# --- Data Science & AI Functions ---
@st.cache_data(ttl=3600)
def get_sales_forecast(_daily_sales):
    """Trains a SARIMA model and forecasts future sales."""
    if len(_daily_sales) < 14:
        return None
    try:
        model = SARIMAX(_daily_sales, order=(1, 1, 1), seasonal_order=(1, 1, 1, 7),
                       enforce_stationarity=False, enforce_invertibility=False).fit(disp=False)
        return model.get_forecast(steps=30).summary_frame(alpha=0.05)
    except Exception as e:
        st.warning(f"Erreur lors de la prévision: {e}")
        return None

@st.cache_data(ttl=3600)
def get_customer_clusters(_rfm_data):
    """Performs K-Means clustering on RFM data."""
    if _rfm_data.empty or len(_rfm_data) < 4:
        return None
    try:
        rfm_copy = _rfm_data.copy()
        kmeans = KMeans(n_clusters=4, init='k-means++', random_state=42, n_init=10)
        rfm_copy['Cluster'] = kmeans.fit_predict(rfm_copy[['Recency', 'Frequency', 'Monetary']])
        cluster_centers = kmeans.cluster_centers_

        # Improved cluster mapping logic
        cluster_map = {}
        for i, center in enumerate(cluster_centers):
            if center[2] > rfm_copy['Monetary'].mean() and center[0] < rfm_copy['Recency'].mean():
                cluster_map[i] = "Champions"
            elif center[0] > rfm_copy['Recency'].mean() * 1.5:
                cluster_map[i] = "À Risque"
            elif center[1] > rfm_copy['Frequency'].mean():
                cluster_map[i] = "Clients Loyaux"
            else:
                cluster_map[i] = "Standard"

        rfm_copy['Cluster'] = rfm_copy['Cluster'].map(cluster_map)
        return rfm_copy
    except Exception as e:
        st.warning(f"Erreur lors du clustering: {e}")
        return None

@st.cache_data(ttl=3600)
def calculate_cohort_data(_df):
    """Calculates customer retention cohorts."""
    try:
        df_copy = _df.copy()
        df_copy['OrderMonth'] = df_copy['ORDER_DATE'].dt.to_period('M')
        df_copy['CohortMonth'] = df_copy.groupby('CUSTOMER_ID')['OrderMonth'].transform('min')
        df_copy['CohortIndex'] = (df_copy['OrderMonth'].dt.year - df_copy['CohortMonth'].dt.year) * 12 + \
                                  (df_copy['OrderMonth'].dt.month - df_copy['CohortMonth'].dt.month)
        cohort_data = df_copy.groupby(['CohortMonth', 'CohortIndex'])['CUSTOMER_ID'].nunique().reset_index()
        cohort_counts = cohort_data.pivot_table(index='CohortMonth', columns='CohortIndex', values='CUSTOMER_ID')
        return cohort_counts.divide(cohort_counts.iloc[:, 0], axis=0) * 100
    except Exception as e:
        st.warning(f"Erreur lors du calcul des cohortes: {e}")
        return pd.DataFrame()

def get_ai_strategic_summary(api_key, data_context):
    """Generates a strategic summary using Anthropic's Claude."""
    try:
        client = anthropic.Anthropic(api_key=api_key)
        prompt = f"""
        Human: Tu es un consultant en stratégie de niveau C-Level pour une entreprise qui vend des figurines de collection.
        Analyse les données suivantes et rédige un rapport exécutif concis.
        Le rapport doit inclure :
        1.  Une synthèse de la performance actuelle.
        2.  Trois insights clés basés sur les données.
        3.  Trois recommandations stratégiques et actionnables pour la direction.

        Voici les données :
        {data_context}

        Assistant:
        """
        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text
    except Exception as e:
        return f"Erreur lors de la génération de l'analyse IA : {e}"

def generate_sql_from_question(api_key, question, conversation_history):
    """Generates SQL query from natural language question using Claude."""
    try:
        client = anthropic.Anthropic(api_key=api_key)

        schema_context = """
        Base de données Snowflake - Schéma FIGURINE_SCHEMA:

        Tables disponibles:
        1. ORDERS (ORDER_ID, ORDER_DATE, CUSTOMER_ID, SALES_CHANNEL, ORDER_STATUS)
        2. CUSTOMERS (CUSTOMER_ID, FIRST_NAME, LAST_NAME, EMAIL, CITY, COUNTRY)
        3. PRODUCTS (PRODUCT_ID, MODEL_NAME, THEME, FINISH, PRICE)
        4. ORDER_ITEMS (ORDER_ITEM_ID, ORDER_ID, PRODUCT_ID, QUANTITY, PRICE_AT_PURCHASE)

        Règles:
        - Utilise uniquement les tables et colonnes listées ci-dessus
        - Exclure les commandes avec ORDER_STATUS = 'cancelled'
        - Retourne UNIQUEMENT la requête SQL, sans explications ni markdown
        - Utilise des alias clairs pour les jointures
        """

        context = "\n".join([f"Q: {h['question']}\nR: {h['answer']}" for h in conversation_history[-3:]])

        prompt = f"""
        {schema_context}

        Historique de conversation:
        {context}

        Question de l'utilisateur: {question}

        Génère une requête SQL Snowflake pour répondre à cette question. Réponds UNIQUEMENT avec la requête SQL, sans explications.
        """

        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}]
        )

        sql_query = message.content[0].text.strip()
        # Nettoyage du SQL si markdown est présent
        sql_query = sql_query.replace("```sql", "").replace("```", "").strip()
        return sql_query
    except Exception as e:
        return f"Erreur: {e}"

def generate_natural_language_response(api_key, question, sql_query, data_result):
    """Generates natural language response from query results."""
    try:
        client = anthropic.Anthropic(api_key=api_key)

        prompt = f"""
        Tu es un analyste de données expert. L'utilisateur a posé la question suivante:
        "{question}"

        J'ai exécuté cette requête SQL:
        {sql_query}

        Voici les résultats (limités aux 100 premières lignes):
        {data_result.head(100).to_string() if not data_result.empty else "Aucun résultat"}

        Résume ces résultats en langage naturel de manière claire et concise, comme le ferait un analyste professionnel.
        Inclus des chiffres clés et des insights pertinents.
        """

        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text
    except Exception as e:
        return f"Erreur lors de la génération de la réponse : {e}"


# --- Main Dashboard Application ---
def main():
    engine = get_snowflake_connection()
    if engine is None: return

    df = load_data(engine)
    if df.empty:
        st.warning("Aucune donnée trouvée.")
        return

    # --- Sidebar ---
    st.sidebar.image(str(Path(__file__).parent.parent / "shrek.png"), width=80)
    st.sidebar.title("👑 Filtres du Dashboard")

    # Get Anthropic API key from .env or allow override
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not anthropic_api_key:
        anthropic_api_key = st.sidebar.text_input("Clé API Anthropic (Claude)", type="password", help="Nécessaire pour l'assistant stratégique IA")
    else:
        st.sidebar.success("✅ Clé API Anthropic chargée depuis .env")
    
    min_date, max_date = df['ORDER_DATE'].min(), df['ORDER_DATE'].max()
    date_range = st.sidebar.date_input("Plage de dates", (min_date, max_date) if min_date != max_date else (min_date, max_date), disabled=(min_date == max_date))
    
    selected_themes = st.sidebar.multiselect("Thèmes", options=df['THEME'].unique(), default=df['THEME'].unique())
    selected_models = st.sidebar.multiselect("Modèles", options=df['MODEL_NAME'].unique(), default=df['MODEL_NAME'].unique())

    start_date, end_date = (pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])) if len(date_range) == 2 else (min_date, max_date)
    filtered_df = df[(df['ORDER_DATE'] >= start_date) & (df['ORDER_DATE'] <= end_date) & (df['THEME'].isin(selected_themes)) & (df['MODEL_NAME'].isin(selected_models))]

    # --- Main Panel ---
    st.title("🗿 Dashboard de Vente des Figurines")
    st.markdown("Votre centre de commandement pour piloter la performance de votre entreprise.")

    # Initialize session state for chat history
    if 'chat_history' not in st.session_state:
        st.session_state.chat_history = []
    if 'last_query_result' not in st.session_state:
        st.session_state.last_query_result = None

    tabs = st.tabs(["📊 Synthèse Exécutive", "💎 Analyse des Ventes", "👥 Segmentation Client", "🚀 Prévisions & Science des Données", "📈 Rétention & CLV", "💬 Chat Interactif IA", "🧠 Assistant Stratégique IA", "🔍 Data Quality Monitoring", "🧪 R&D Experimental"])

    with tabs[0]: # Executive Summary
        st.header("Indicateurs Clés de Performance (KPIs)")
        total_revenue = filtered_df['TOTAL_SALE'].sum()
        total_orders = filtered_df['ORDER_ID'].nunique()
        unique_customers = filtered_df['CUSTOMER_ID'].nunique()
        col1, col2, col3 = st.columns(3)
        col1.metric("Chiffre d'affaires", f"{total_revenue:,.2f} €")
        col2.metric("Commandes", f"{total_orders:,}")
        col3.metric("Clients Uniques", f"{unique_customers:,}")
        
        st.markdown("---")
        st.subheader("Tendance du Chiffre d'Affaires")
        daily_sales_summary = filtered_df.set_index('ORDER_DATE').resample('D')['TOTAL_SALE'].sum().reset_index()
        daily_sales_summary['MA_7'] = daily_sales_summary['TOTAL_SALE'].rolling(window=7).mean()
        
        fig_summary = go.Figure()
        fig_summary.add_trace(go.Scatter(x=daily_sales_summary['ORDER_DATE'], y=daily_sales_summary['TOTAL_SALE'], mode='lines', name='Ventes Journalières', line=dict(color='royalblue', width=1)))
        fig_summary.add_trace(go.Scatter(x=daily_sales_summary['ORDER_DATE'], y=daily_sales_summary['MA_7'], mode='lines', name='Moyenne Mobile (7 jours)', line=dict(color='crimson', width=2, dash='dot')))
        fig_summary.update_layout(title="Évolution des Ventes Journalières et Tendance", template="plotly_white", height=400)
        st.plotly_chart(fig_summary, width='stretch')

    with tabs[1]: # Sales & Product Analysis
        st.header("Analyse Approfondie des Produits")
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Top 10 Produits par Chiffre d'Affaires")
            top_products = filtered_df.groupby(['MODEL_NAME', 'THEME', 'FINISH'])['TOTAL_SALE'].sum().nlargest(10).reset_index()
            fig_top_prod = px.bar(top_products.sort_values('TOTAL_SALE'), x='TOTAL_SALE', y='MODEL_NAME', color='THEME', orientation='h', template="plotly_white", height=400)
            st.plotly_chart(fig_top_prod, width='stretch')

        with col2:
            st.subheader("Produits Souvent Achetés Ensemble")
            if filtered_df['ORDER_ID'].nunique() > 1:
                baskets = filtered_df.groupby('ORDER_ID')['MODEL_NAME'].apply(list).reset_index()
                co_occurrence = Counter()
                for basket in baskets['MODEL_NAME']:
                    if len(basket) > 1:
                        for pair in combinations(sorted(set(basket)), 2):
                            co_occurrence[pair] += 1
                if co_occurrence:
                    affinity_df = pd.DataFrame(co_occurrence.most_common(5), columns=['product_pair', 'count'])
                    affinity_df['product_pair'] = affinity_df['product_pair'].apply(lambda x: f"{x[0]} & {x[1]}")
                    st.dataframe(affinity_df.set_index('product_pair'), width='stretch')
                else: st.info("Aucune paire de produits trouvée.")
            else: st.info("Pas assez de données pour l'analyse d'affinité.")

    with tabs[2]: # Customer Segmentation
        st.header("Segmentation Clientèle (RFM)")
        if not filtered_df.empty:
            snapshot_date = filtered_df['ORDER_DATE'].max() + pd.Timedelta(days=1)
            rfm = filtered_df.groupby('CUSTOMER_ID').agg({'ORDER_DATE': lambda d: (snapshot_date - d.max()).days, 'ORDER_ID': 'nunique', 'TOTAL_SALE': 'sum'}).rename(columns={'ORDER_DATE': 'Recency', 'ORDER_ID': 'Frequency', 'TOTAL_SALE': 'Monetary'})
            if not rfm.empty:
                col1_rfm, col2_rfm = st.columns([1, 2])
                with col1_rfm:
                    st.subheader("Distribution des Segments")
                    try:
                        rfm['R_Score'] = pd.qcut(rfm['Recency'], 4, labels=[4, 3, 2, 1], duplicates='drop')
                    except Exception:
                        rfm['R_Score'] = 1
                    try:
                        rfm['F_Score'] = pd.qcut(rfm['Frequency'].rank(method='first'), 4, labels=[1, 2, 3, 4], duplicates='drop')
                    except Exception:
                        rfm['F_Score'] = 1
                    try:
                        rfm['M_Score'] = pd.qcut(rfm['Monetary'], 4, labels=[1, 2, 3, 4], duplicates='drop')
                    except Exception:
                        rfm['M_Score'] = 1
                    rfm['Segment'] = rfm.apply(lambda r: 'Champions' if r['R_Score'] >= 4 and r['F_Score'] >= 4 else 'Clients Loyaux' if r['F_Score'] >= 4 else 'Clients à Risque' if r['R_Score'] <= 2 and r['F_Score'] <= 2 else 'Standard', axis=1)
                    segment_counts = rfm['Segment'].value_counts()
                    fig_pie = px.pie(names=segment_counts.index, values=segment_counts.values, hole=0.4, title="Segments RFM")
                    st.plotly_chart(fig_pie, width='stretch')
                with col2_rfm:
                    st.subheader("Détail des Segments Clients")
                    st.dataframe(rfm.sort_values(by=['Monetary'], ascending=False), width='stretch')
            else: st.warning("Aucun client trouvé.")
        else: st.warning("Aucune donnée disponible.")

    with tabs[3]: # Forecasts & Data Science
        st.header("🔮 Prévisions des Ventes et Clustering")
        daily_sales_fc = filtered_df.set_index('ORDER_DATE').resample('D')['TOTAL_SALE'].sum()
        forecast_df = get_sales_forecast(daily_sales_fc)
        if forecast_df is not None:
            fig_fc = go.Figure()
            fig_fc.add_trace(go.Scatter(x=daily_sales_fc.index, y=daily_sales_fc.values, mode='lines', name='Ventes Historiques', line=dict(color='#2980b9')))
            fig_fc.add_trace(go.Scatter(x=forecast_df.index, y=forecast_df['mean'], mode='lines', name='Prévision', line=dict(color='#e74c3c', dash='dot')))
            fig_fc.add_trace(go.Scatter(x=forecast_df.index, y=forecast_df['mean_ci_lower'], fill=None, mode='lines', line_color='#f1c40f', name='Intervalle de Confiance'))
            fig_fc.add_trace(go.Scatter(x=forecast_df.index, y=forecast_df['mean_ci_upper'], fill='tonexty', mode='lines', line_color='#f1c40f'))
            fig_fc.update_layout(title="Prévision du Chiffre d'Affaires (30 jours)", template="plotly_white", height=450)
            st.plotly_chart(fig_fc, width='stretch')
        else: st.warning("Pas assez de données pour une prévision fiable.")

        st.markdown("---")
        st.header("🧠 Clustering Client par Comportement d'Achat (K-Means)")
        rfm_for_cluster = filtered_df.groupby('CUSTOMER_ID').agg({'ORDER_DATE': lambda d: (datetime.now() - d.max()).days, 'ORDER_ID': 'nunique', 'TOTAL_SALE': 'sum'}).rename(columns={'ORDER_DATE': 'Recency', 'ORDER_ID': 'Frequency', 'TOTAL_SALE': 'Monetary'})
        rfm_clustered = get_customer_clusters(rfm_for_cluster)
        if rfm_clustered is not None:
            fig_cluster = px.scatter(rfm_clustered, x='Recency', y='Frequency', size='Monetary', color='Cluster', hover_name=rfm_clustered.index, title="Visualisation des Clusters Clients", size_max=60, template="plotly_white")
            st.plotly_chart(fig_cluster, width='stretch')
        else: st.warning("Pas assez de données pour le clustering.")

    with tabs[4]: # Retention & CLV
        st.header("Analyse de la Rétention et Valeur Client")
        cohort_retention = calculate_cohort_data(filtered_df.copy())
        if not cohort_retention.empty:
            fig_cohort = go.Figure(data=go.Heatmap(z=cohort_retention.values, x=[f"Mois {i}" for i in cohort_retention.columns], y=[str(i) for i in cohort_retention.index], colorscale='Blues'))
            fig_cohort.update_layout(title='Taux de Rétention Mensuel (%) par Cohorte d\'Acquisition')
            st.plotly_chart(fig_cohort, width='stretch')
        else: st.warning("Pas assez de données pour l'analyse de cohorte.")
        
        st.markdown("---")
        st.header("Valeur Vie Client (CLV) par Segment")
        rfm_for_clv = filtered_df.groupby('CUSTOMER_ID').agg({'ORDER_DATE': lambda d: (datetime.now() - d.max()).days, 'ORDER_ID': 'nunique', 'TOTAL_SALE': 'sum'}).rename(columns={'ORDER_DATE': 'Recency', 'ORDER_ID': 'Frequency', 'TOTAL_SALE': 'Monetary'})
        rfm_clustered_clv = get_customer_clusters(rfm_for_clv)
        if rfm_clustered_clv is not None:
            clv_by_segment = rfm_clustered_clv.groupby('Cluster')['Monetary'].mean().sort_values(ascending=False).reset_index()
            fig_clv = px.bar(clv_by_segment, x='Cluster', y='Monetary', title="Valeur Moyenne d'un Client par Segment", labels={'Cluster': 'Segment Client', 'Monetary': 'Dépenses Moyennes (€)'})
            st.plotly_chart(fig_clv, width='stretch')
        else: st.warning("Pas assez de données pour la CLV.")

    with tabs[5]: # Interactive AI Chat
        st.header("💬 Assistant de Données Interactif")
        st.markdown("Posez des questions en langage naturel sur vos données. L'IA génère automatiquement les requêtes SQL et analyse les résultats.")

        # Example questions
        with st.expander("💡 Exemples de questions"):
            st.markdown("""
            - Quel a été notre meilleur mois en termes de chiffre d'affaires ?
            - Montre-moi les 5 clients les plus fidèles
            - Quels sont les produits les plus vendus par thème ?
            - Quel est le panier moyen par canal de vente ?
            - Combien de nouveaux clients avons-nous acquis ce trimestre ?
            - Quelle est la répartition géographique de nos clients ?
            """)

        # Chat interface with form to prevent page reload
        with st.form(key="chat_form", clear_on_submit=True):
            user_question = st.text_input("Posez votre question:", placeholder="Ex: Quel a été notre meilleur mois en termes de chiffre d'affaires ?")
            submit_button = st.form_submit_button("🔍 Analyser")

        if submit_button and user_question:
            if not anthropic_api_key:
                st.error("⚠️ Veuillez entrer votre clé API Anthropic dans la barre latérale.")
            else:
                # Create placeholder for results
                result_container = st.container()

                with result_container:
                    with st.spinner("🤖 L'IA analyse votre question et génère la requête SQL..."):
                        # Generate SQL query
                        sql_query = generate_sql_from_question(anthropic_api_key, user_question, st.session_state.chat_history)

                        if sql_query.startswith("Erreur"):
                            st.error(sql_query)
                        else:
                            # Display generated SQL
                            with st.expander("📝 Requête SQL générée", expanded=True):
                                st.code(sql_query, language="sql")

                            # Execute SQL query
                            try:
                                with st.spinner("⚙️ Exécution de la requête sur Snowflake..."):
                                    result_df = pd.read_sql(sql_query, engine)

                                if result_df.empty:
                                    st.warning("Aucun résultat trouvé pour cette question.")
                                else:
                                    # Generate natural language response
                                    with st.spinner("📊 L'IA analyse les résultats..."):
                                        nl_response = generate_natural_language_response(
                                            anthropic_api_key,
                                            user_question,
                                            sql_query,
                                            result_df
                                        )

                                    # Display response
                                    st.success("✅ Analyse terminée")
                                    st.markdown("### 📈 Réponse")
                                    st.markdown(nl_response)

                                    # Show data table
                                    with st.expander("📊 Voir les données brutes", expanded=True):
                                        st.dataframe(result_df, width='stretch')

                                    # Save to chat history
                                    st.session_state.chat_history.append({
                                        "question": user_question,
                                        "sql": sql_query,
                                        "answer": nl_response,
                                        "data": result_df
                                    })

                            except Exception as e:
                                st.error(f"❌ Erreur lors de l'exécution de la requête: {e}")
                                st.code(sql_query, language="sql")

        # Display chat history
        if st.session_state.chat_history:
            st.markdown("---")
            col_hist_title, col_hist_clear = st.columns([3, 1])
            with col_hist_title:
                st.subheader("📜 Historique de conversation")
            with col_hist_clear:
                if st.button("🗑️ Effacer", key="clear_history"):
                    st.session_state.chat_history = []
                    st.success("Historique effacé !")

            for idx, chat in enumerate(reversed(st.session_state.chat_history)):
                with st.expander(f"💬 {chat['question']}", expanded=(idx == 0)):
                    st.markdown(f"**Réponse:** {chat['answer']}")
                    with st.expander("Voir la requête SQL"):
                        st.code(chat['sql'], language="sql")
                    with st.expander("Voir les données"):
                        st.dataframe(chat['data'], width='stretch')

    with tabs[6]: # AI Strategic Assistant
        st.header("Assistant Stratégique IA (propulsé par Claude 3)")
        st.markdown("Obtenez une synthèse et des recommandations stratégiques générées par l'IA sur la base des données filtrées.")

        if st.button("🤖 Générer l'Analyse Stratégique"):
            if not anthropic_api_key:
                st.error("Veuillez entrer votre clé API Anthropic dans la barre latérale pour continuer.")
            else:
                with st.spinner("L'IA analyse les données et rédige son rapport..."):
                    kpis = {"Chiffre d'affaires": total_revenue, "Commandes": total_orders, "Clients uniques": unique_customers}
                    top_products_ai = filtered_df.groupby(['MODEL_NAME', 'THEME'])['TOTAL_SALE'].sum().nlargest(5).to_dict()
                    rfm_ai = filtered_df.groupby('CUSTOMER_ID').agg({'ORDER_DATE': lambda d: (datetime.now() - d.max()).days, 'ORDER_ID': 'nunique', 'TOTAL_SALE': 'sum'})
                    rfm_summary_ai = rfm_ai.describe().to_dict()

                    data_context = f"- KPIs: {kpis}\n- Top 5 Produits par CA: {top_products_ai}\n- Résumé des segments clients (RFM): {rfm_summary_ai}"
                    
                    summary = get_ai_strategic_summary(anthropic_api_key, data_context)
                    st.markdown(summary)

    with tabs[7]: # Data Quality Monitoring
        st.header("🔍 Monitoring de la Qualité des Données")
        st.markdown("Surveillance et validation de la qualité des données de votre pipeline ETL.")

        # First, get raw counts from each table to diagnose the issue
        st.subheader("📊 Vérification des Tables Sources")

        try:
            # Count records in each table directly
            orders_count_query = "SELECT COUNT(*) as cnt FROM ORDERS"
            order_items_count_query = "SELECT COUNT(*) as cnt FROM ORDER_ITEMS"
            customers_count_query = "SELECT COUNT(*) as cnt FROM CUSTOMERS"
            products_count_query = "SELECT COUNT(*) as cnt FROM PRODUCTS"

            orders_count_result = pd.read_sql(orders_count_query, engine)
            orders_count = int(orders_count_result.iloc[0, 0])

            order_items_count_result = pd.read_sql(order_items_count_query, engine)
            order_items_count = int(order_items_count_result.iloc[0, 0])

            customers_count_result = pd.read_sql(customers_count_query, engine)
            customers_count = int(customers_count_result.iloc[0, 0])

            products_count_result = pd.read_sql(products_count_query, engine)
            products_count = int(products_count_result.iloc[0, 0])

            col_tbl1, col_tbl2, col_tbl3, col_tbl4 = st.columns(4)
            col_tbl1.metric("📦 ORDERS (brut)", f"{orders_count:,}")
            col_tbl2.metric("📝 ORDER_ITEMS (brut)", f"{order_items_count:,}")
            col_tbl3.metric("👥 CUSTOMERS (brut)", f"{customers_count:,}")
            col_tbl4.metric("🎨 PRODUCTS (brut)", f"{products_count:,}")

        except Exception as e:
            st.error(f"Erreur lors du comptage des tables sources: {e}")

        st.markdown("---")

        # Load complete data without filters for quality checks
        complete_df_query = """
        SELECT
            O.ORDER_ID, O.ORDER_DATE, O.SALES_CHANNEL, O.ORDER_STATUS,
            C.CUSTOMER_ID, C.FIRST_NAME, C.LAST_NAME, C.EMAIL,
            P.PRODUCT_ID, P.MODEL_NAME, P.THEME, P.FINISH, P.BASE_PRICE,
            OI.QUANTITY, OI.PRICE_AT_PURCHASE,
            (OI.QUANTITY * OI.PRICE_AT_PURCHASE) AS TOTAL_SALE
        FROM ORDERS AS O
        LEFT JOIN CUSTOMERS AS C ON O.CUSTOMER_ID = C.CUSTOMER_ID
        LEFT JOIN ORDER_ITEMS AS OI ON O.ORDER_ID = OI.ORDER_ID
        LEFT JOIN PRODUCTS AS P ON OI.PRODUCT_ID = P.PRODUCT_ID;
        """

        try:
            complete_df = pd.read_sql(complete_df_query, engine)
            complete_df.columns = [col.upper() for col in complete_df.columns]
        except Exception as e:
            st.error(f"Erreur lors du chargement des données complètes: {e}")
            complete_df = df.copy()

        # Data Quality Metrics
        col1_dq, col2_dq, col3_dq, col4_dq = st.columns(4)

        # Calculate quality metrics on complete dataset
        total_records = len(complete_df)
        total_orders = complete_df['ORDER_ID'].nunique()
        total_order_items = len(complete_df)
        null_counts = complete_df.isnull().sum()

        # Check for duplicates based on combination of ORDER_ID + PRODUCT_ID
        duplicate_order_items = complete_df.duplicated(subset=['ORDER_ID', 'PRODUCT_ID']).sum()

        with col1_dq:
            st.metric("Commandes Totales (JOIN)", f"{total_orders:,}")
        with col2_dq:
            completeness = ((total_records * len(complete_df.columns) - null_counts.sum()) / (total_records * len(complete_df.columns)) * 100)
            st.metric("Complétude", f"{completeness:.2f}%", delta=None)
        with col3_dq:
            # Query specifically for cancelled orders from ORDERS table
            cancelled_query = "SELECT COUNT(*) as cnt FROM ORDERS WHERE ORDER_STATUS = 'cancelled'"
            try:
                cancelled_result = pd.read_sql(cancelled_query, engine)
                cancelled_orders = int(cancelled_result.iloc[0, 0])
                pct_cancelled = (cancelled_orders / orders_count * 100) if orders_count > 0 else 0
                st.metric("Commandes annulées", f"{cancelled_orders:,}", delta=f"{pct_cancelled:.1f}%")
            except Exception as e:
                st.metric("Commandes annulées", f"Error: {str(e)[:50]}")
        with col4_dq:
            validity_rate = ((complete_df['TOTAL_SALE'] > 0).sum() / len(complete_df) * 100) if len(complete_df) > 0 else 0
            st.metric("Taux de validité", f"{validity_rate:.2f}%")

        st.markdown("---")

        # Diagnostic: Check for referential integrity issues
        st.subheader("🔗 Diagnostic d'Intégrité Référentielle")

        try:
            # Check orphan order_items (order_id not in orders)
            orphan_items_query = """
            SELECT COUNT(*) as cnt
            FROM ORDER_ITEMS OI
            LEFT JOIN ORDERS O ON OI.ORDER_ID = O.ORDER_ID
            WHERE O.ORDER_ID IS NULL
            """
            orphan_items_result = pd.read_sql(orphan_items_query, engine)
            orphan_items = int(orphan_items_result.iloc[0, 0])

            # Check orders without items
            orders_no_items_query = """
            SELECT COUNT(*) as cnt
            FROM ORDERS O
            LEFT JOIN ORDER_ITEMS OI ON O.ORDER_ID = OI.ORDER_ID
            WHERE OI.ORDER_ID IS NULL
            """
            orders_no_items_result = pd.read_sql(orders_no_items_query, engine)
            orders_no_items = int(orders_no_items_result.iloc[0, 0])

            # Check orphan customers (order references customer that doesn't exist)
            orphan_customers_query = """
            SELECT COUNT(DISTINCT O.CUSTOMER_ID) as cnt
            FROM ORDERS O
            LEFT JOIN CUSTOMERS C ON O.CUSTOMER_ID = C.CUSTOMER_ID
            WHERE C.CUSTOMER_ID IS NULL
            """
            orphan_customers_result = pd.read_sql(orphan_customers_query, engine)
            orphan_customers = int(orphan_customers_result.iloc[0, 0])

            # Check orphan products
            orphan_products_query = """
            SELECT COUNT(*) as cnt
            FROM ORDER_ITEMS OI
            LEFT JOIN PRODUCTS P ON OI.PRODUCT_ID = P.PRODUCT_ID
            WHERE P.PRODUCT_ID IS NULL
            """
            orphan_products_result = pd.read_sql(orphan_products_query, engine)
            orphan_products = int(orphan_products_result.iloc[0, 0])

            col_diag1, col_diag2, col_diag3, col_diag4 = st.columns(4)
            col_diag1.metric("🔴 Items orphelins", f"{orphan_items:,}",
                           delta="❌ Problème" if orphan_items > 0 else "✅ OK",
                           delta_color="inverse" if orphan_items > 0 else "normal")
            col_diag2.metric("🔴 Orders sans items", f"{orders_no_items:,}",
                           delta="⚠️ Attention" if orders_no_items > 0 else "✅ OK",
                           delta_color="inverse" if orders_no_items > 0 else "normal")
            col_diag3.metric("🔴 Customers orphelins", f"{orphan_customers:,}",
                           delta="❌ Problème" if orphan_customers > 0 else "✅ OK",
                           delta_color="inverse" if orphan_customers > 0 else "normal")
            col_diag4.metric("🔴 Produits orphelins", f"{orphan_products:,}",
                           delta="❌ Problème" if orphan_products > 0 else "✅ OK",
                           delta_color="inverse" if orphan_products > 0 else "normal")

            # Calculate expected vs actual after joins
            if orphan_items == 0 and orders_no_items == 0 and orphan_customers == 0 and orphan_products == 0:
                st.success("✅ Aucun problème d'intégrité référentielle détecté !")
            else:
                cancelled_count = pd.read_sql("SELECT COUNT(*) as cnt FROM ORDERS WHERE ORDER_STATUS = 'cancelled'", engine).iloc[0, 0]
                active_orders = orders_count - cancelled_count

                st.warning(f"⚠️ Problèmes d'intégrité détectés !")
                st.info(f"""
                📊 **Analyse des pertes de données** :
                - ORDERS total : **{orders_count:,}**
                - ORDERS cancelled : **{cancelled_count:,}**
                - ORDERS actives (attendues) : **{active_orders:,}**
                - ORDERS après JOIN : **{total_orders:,}**
                - **Perte due aux orphelins : {active_orders - total_orders:,} commandes** ({(active_orders - total_orders)/active_orders*100:.1f}%)
                """)

                if orphan_customers > 0:
                    st.error(f"🔴 **Problème critique**: {orphan_customers} CUSTOMER_ID référencés dans ORDERS n'existent pas dans CUSTOMERS")
                if orders_no_items > 0:
                    st.warning(f"⚠️ {orders_no_items} commandes n'ont aucun item associé dans ORDER_ITEMS")
                if orphan_products > 0:
                    st.error(f"""
                    🔴 **Problème critique**: {orphan_products} lignes dans ORDER_ITEMS référencent des PRODUCT_ID qui n'existent pas dans PRODUCTS

                    **Impact** : Ces {orphan_products} items orphelins affectent probablement plusieurs commandes, causant leur exclusion des analyses.

                    **Action requise** :
                    1. Vérifier la génération des données (`data_generator2.py`)
                    2. Vérifier l'ingestion Snowpipe (`snowpipekscm.py`)
                    3. S'assurer que tous les PRODUCT_ID dans ORDER_ITEMS existent dans PRODUCTS
                    """)

        except Exception as e:
            st.error(f"Erreur lors du diagnostic d'intégrité: {e}")

        st.markdown("---")

        # Additional Metrics Row
        col_add1, col_add2, col_add3, col_add4 = st.columns(4)
        with col_add1:
            st.metric("Items de commande", f"{total_order_items:,}")
        with col_add2:
            st.metric("Clients uniques", f"{complete_df['CUSTOMER_ID'].nunique():,}")
        with col_add3:
            st.metric("Produits uniques", f"{complete_df['PRODUCT_ID'].nunique():,}")
        with col_add4:
            if duplicate_order_items > 0:
                st.metric("Doublons d'items", f"{duplicate_order_items:,}", delta="❌", delta_color="inverse")
            else:
                st.metric("Doublons d'items", "0", delta="✅")

        st.markdown("---")

        # Detailed Quality Checks
        col_left, col_right = st.columns(2)

        with col_left:
            st.subheader("📋 Valeurs Manquantes par Colonne")
            missing_data = pd.DataFrame({
                'Colonne': null_counts.index,
                'Valeurs Manquantes': null_counts.values,
                '% Manquant': (null_counts.values / total_records * 100).round(2)
            })
            missing_data = missing_data[missing_data['Valeurs Manquantes'] > 0].sort_values('Valeurs Manquantes', ascending=False)

            if missing_data.empty:
                st.success("✅ Aucune valeur manquante détectée !")
            else:
                fig_missing = px.bar(missing_data, x='% Manquant', y='Colonne', orientation='h',
                                    title="Pourcentage de valeurs manquantes", template="plotly_white")
                st.plotly_chart(fig_missing, width='stretch')

        with col_right:
            st.subheader("🔢 Distribution des Montants de Vente")
            # Check for outliers and anomalies
            if not complete_df.empty:
                Q1 = complete_df['TOTAL_SALE'].quantile(0.25)
                Q3 = complete_df['TOTAL_SALE'].quantile(0.75)
                IQR = Q3 - Q1
                outliers = complete_df[(complete_df['TOTAL_SALE'] < Q1 - 1.5 * IQR) |
                                      (complete_df['TOTAL_SALE'] > Q3 + 1.5 * IQR)]

                fig_box = px.box(complete_df, y='TOTAL_SALE', title=f"Outliers détectés: {len(outliers)}",
                                template="plotly_white")
                st.plotly_chart(fig_box, width='stretch')

                if len(outliers) > 0:
                    st.warning(f"⚠️ {len(outliers)} transactions suspectes détectées ({len(outliers)/len(complete_df)*100:.2f}%)")

        st.markdown("---")

        # Data Freshness
        st.subheader("🕐 Fraîcheur des Données")
        col_fresh1, col_fresh2, col_fresh3 = st.columns(3)

        with col_fresh1:
            most_recent = complete_df['ORDER_DATE'].max()
            st.metric("Dernière commande", most_recent.strftime("%Y-%m-%d"))

        with col_fresh2:
            days_since = (datetime.now() - most_recent).days
            st.metric("Jours depuis MAJ", f"{days_since}", delta=f"-{days_since}" if days_since > 7 else None)

        with col_fresh3:
            oldest = complete_df['ORDER_DATE'].min()
            st.metric("Première commande", oldest.strftime("%Y-%m-%d"))

        st.markdown("---")

        # Data Consistency Checks
        st.subheader("✔️ Vérifications de Cohérence")

        consistency_checks = []

        # Check 1: Price consistency
        price_check = complete_df['PRICE_AT_PURCHASE'] > 0
        consistency_checks.append({
            "Vérification": "Prix > 0",
            "Statut": "✅ Passed" if price_check.all() else "❌ Failed",
            "Taux de réussite": f"{price_check.sum() / len(complete_df) * 100:.2f}%"
        })

        # Check 2: Quantity consistency
        qty_check = complete_df['QUANTITY'] > 0
        consistency_checks.append({
            "Vérification": "Quantité > 0",
            "Statut": "✅ Passed" if qty_check.all() else "❌ Failed",
            "Taux de réussite": f"{qty_check.sum() / len(complete_df) * 100:.2f}%"
        })

        # Check 3: Date validity
        date_check = complete_df['ORDER_DATE'] <= pd.Timestamp.now()
        consistency_checks.append({
            "Vérification": "Date ≤ Aujourd'hui",
            "Statut": "✅ Passed" if date_check.all() else "❌ Failed",
            "Taux de réussite": f"{date_check.sum() / len(complete_df) * 100:.2f}%"
        })

        # Check 4: Total sale calculation
        calc_total = (complete_df['QUANTITY'] * complete_df['PRICE_AT_PURCHASE']).round(2)
        total_check = (calc_total == complete_df['TOTAL_SALE'].round(2))
        consistency_checks.append({
            "Vérification": "TOTAL_SALE = QTY × PRICE",
            "Statut": "✅ Passed" if total_check.sum() / len(complete_df) > 0.99 else "❌ Failed",
            "Taux de réussite": f"{total_check.sum() / len(complete_df) * 100:.2f}%"
        })

        consistency_df = pd.DataFrame(consistency_checks)
        st.dataframe(consistency_df, width='stretch', hide_index=True)

        # Data Quality Score
        st.markdown("---")
        st.subheader("🎯 Score Global de Qualité")

        quality_score = (
            completeness * 0.3 +
            (100 - (duplicate_order_items / total_records * 100)) * 0.2 +
            validity_rate * 0.2 +
            (consistency_df['Taux de réussite'].str.rstrip('%').astype(float).mean()) * 0.3
        )

        col_score, col_gauge = st.columns([1, 2])
        with col_score:
            st.metric("Score de Qualité", f"{quality_score:.1f}/100")
            if quality_score >= 95:
                st.success("🟢 Excellente qualité des données")
            elif quality_score >= 80:
                st.info("🟡 Bonne qualité, quelques améliorations possibles")
            else:
                st.warning("🔴 Qualité insuffisante, action requise")

        with col_gauge:
            fig_gauge = go.Figure(go.Indicator(
                mode="gauge+number+delta",
                value=quality_score,
                domain={'x': [0, 1], 'y': [0, 1]},
                title={'text': "Score de Qualité"},
                delta={'reference': 95},
                gauge={
                    'axis': {'range': [None, 100]},
                    'bar': {'color': "darkblue"},
                    'steps': [
                        {'range': [0, 60], 'color': "lightcoral"},
                        {'range': [60, 80], 'color': "lightyellow"},
                        {'range': [80, 100], 'color': "lightgreen"}
                    ],
                    'threshold': {
                        'line': {'color': "red", 'width': 4},
                        'thickness': 0.75,
                        'value': 95
                    }
                }
            ))
            fig_gauge.update_layout(height=300)
            st.plotly_chart(fig_gauge, width='stretch')

    with tabs[8]: # R&D Experimental
        st.header("🧪 Laboratoire R&D - Visualisations Expérimentales")
        st.markdown("**Bienvenue dans le laboratoire d'innovation !** Découvrez des analyses ultra-avancées et des visualisations next-gen.")

        # Section selector
        rd_section = st.selectbox(
            "Choisissez une expérience :",
            ["🌐 Network Graph - Univers des Produits",
             "🎯 3D Customer Universe",
             "🌊 Sankey Flow - Parcours Client",
             "☀️ Sunburst - Hiérarchie des Ventes",
             "🏎️ Racing Bar - Top Clients",
             "📅 Calendar Heatmap",
             "💰 Simulateur d'Élasticité Prix",
             "🤖 Next Best Action IA"]
        )

        st.markdown("---")

        # 1. NETWORK GRAPH - PRODUITS LIÉS
        if rd_section == "🌐 Network Graph - Univers des Produits":
            st.subheader("🌐 Graphe de Réseau : Produits Achetés Ensemble")
            st.markdown("**Chaque produit est un nœud. Les liens montrent les co-achats. Plus le lien est épais, plus ils sont achetés ensemble.**")

            if not filtered_df.empty:
                # Build co-occurrence matrix
                baskets = filtered_df.groupby('ORDER_ID')['MODEL_NAME'].apply(list).reset_index()
                product_pairs = {}

                for basket in baskets['MODEL_NAME']:
                    if len(basket) > 1:
                        for i in range(len(basket)):
                            for j in range(i+1, len(basket)):
                                pair = tuple(sorted([basket[i], basket[j]]))
                                product_pairs[pair] = product_pairs.get(pair, 0) + 1

                if product_pairs:
                    # Create network visualization with plotly
                    import numpy as np

                    # Get unique products
                    products = list(set([p for pair in product_pairs.keys() for p in pair]))
                    product_to_idx = {p: i for i, p in enumerate(products)}

                    # Calculate positions in a circle
                    n = len(products)
                    angles = np.linspace(0, 2*np.pi, n, endpoint=False)
                    x_pos = np.cos(angles)
                    y_pos = np.sin(angles)

                    # Create edges
                    edge_x = []
                    edge_y = []
                    edge_weights = []

                    for (prod1, prod2), weight in product_pairs.items():
                        idx1, idx2 = product_to_idx[prod1], product_to_idx[prod2]
                        edge_x.extend([x_pos[idx1], x_pos[idx2], None])
                        edge_y.extend([y_pos[idx1], y_pos[idx2], None])
                        edge_weights.append(weight)

                    # Normalize weights for line width
                    max_weight = max(edge_weights)

                    # Create figure
                    fig_network = go.Figure()

                    # Add edges
                    for i, ((prod1, prod2), weight) in enumerate(product_pairs.items()):
                        idx1, idx2 = product_to_idx[prod1], product_to_idx[prod2]
                        fig_network.add_trace(go.Scatter(
                            x=[x_pos[idx1], x_pos[idx2]],
                            y=[y_pos[idx1], y_pos[idx2]],
                            mode='lines',
                            line=dict(width=weight/max_weight*10, color='rgba(125,125,125,0.5)'),
                            hoverinfo='text',
                            hovertext=f'{prod1} ↔ {prod2}: {weight} co-achats',
                            showlegend=False
                        ))

                    # Add nodes
                    node_sizes = [sum(1 for pair, w in product_pairs.items() if p in pair) * 20 for p in products]

                    fig_network.add_trace(go.Scatter(
                        x=x_pos,
                        y=y_pos,
                        mode='markers+text',
                        marker=dict(size=node_sizes, color='lightblue', line=dict(width=2, color='darkblue')),
                        text=products,
                        textposition="top center",
                        hoverinfo='text',
                        hovertext=[f'{p}<br>Connexions: {node_sizes[i]//20}' for i, p in enumerate(products)],
                        showlegend=False
                    ))

                    fig_network.update_layout(
                        title="Réseau de Co-Achats des Produits",
                        showlegend=False,
                        hovermode='closest',
                        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                        height=700,
                        template='plotly_white'
                    )

                    st.plotly_chart(fig_network, width='stretch')

                    # Stats
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Produits dans le réseau", len(products))
                    col2.metric("Connexions totales", len(product_pairs))
                    col3.metric("Co-achat le plus fort", max(edge_weights))
                else:
                    st.info("Pas assez de co-achats pour créer le réseau.")
            else:
                st.warning("Aucune donnée disponible.")

        # 2. 3D CUSTOMER UNIVERSE
        elif rd_section == "🎯 3D Customer Universe":
            st.subheader("🎯 Univers 3D des Clients (RFM)")
            st.markdown("**Explorez vos clients dans un espace 3D : Recency, Frequency, Monetary. Faites pivoter avec la souris !**")

            if not filtered_df.empty:
                # Calculate RFM
                snapshot_date = filtered_df['ORDER_DATE'].max() + pd.Timedelta(days=1)
                rfm_3d = filtered_df.groupby('CUSTOMER_ID').agg({
                    'ORDER_DATE': lambda d: (snapshot_date - d.max()).days,
                    'ORDER_ID': 'nunique',
                    'TOTAL_SALE': 'sum',
                    'FIRST_NAME': 'first',
                    'LAST_NAME': 'first'
                }).rename(columns={
                    'ORDER_DATE': 'Recency',
                    'ORDER_ID': 'Frequency',
                    'TOTAL_SALE': 'Monetary'
                })

                # Segment assignment
                rfm_3d['Segment'] = 'Standard'
                rfm_3d.loc[(rfm_3d['Monetary'] > rfm_3d['Monetary'].quantile(0.75)) &
                          (rfm_3d['Recency'] < rfm_3d['Recency'].quantile(0.25)), 'Segment'] = 'Champions'
                rfm_3d.loc[rfm_3d['Frequency'] > rfm_3d['Frequency'].quantile(0.75), 'Segment'] = 'Loyaux'
                rfm_3d.loc[rfm_3d['Recency'] > rfm_3d['Recency'].quantile(0.75), 'Segment'] = 'À Risque'

                rfm_3d['Customer'] = rfm_3d['FIRST_NAME'] + ' ' + rfm_3d['LAST_NAME']

                # Create 3D scatter
                fig_3d = px.scatter_3d(
                    rfm_3d,
                    x='Recency',
                    y='Frequency',
                    z='Monetary',
                    color='Segment',
                    size='Monetary',
                    hover_name='Customer',
                    hover_data={'Recency': True, 'Frequency': True, 'Monetary': ':.2f'},
                    title="Univers 3D des Clients",
                    color_discrete_map={
                        'Champions': '#FFD700',
                        'Loyaux': '#4169E1',
                        'À Risque': '#FF6347',
                        'Standard': '#90EE90'
                    }
                )

                fig_3d.update_layout(
                    scene=dict(
                        xaxis_title='Recency (jours)',
                        yaxis_title='Frequency (commandes)',
                        zaxis_title='Monetary (€)',
                        camera=dict(eye=dict(x=1.5, y=1.5, z=1.3))
                    ),
                    height=700
                )

                st.plotly_chart(fig_3d, width='stretch')

                # Segment stats
                st.subheader("📊 Distribution des Segments")
                segment_stats = rfm_3d.groupby('Segment').agg({
                    'Customer': 'count',
                    'Monetary': 'mean'
                }).round(2)
                segment_stats.columns = ['Nb Clients', 'CA Moyen (€)']
                st.dataframe(segment_stats, width='stretch')
            else:
                st.warning("Aucune donnée disponible.")

        # 3. SANKEY FLOW DIAGRAM
        elif rd_section == "🌊 Sankey Flow - Parcours Client":
            st.subheader("🌊 Diagramme de Sankey : Flux du Parcours Client")
            st.markdown("**Suivez le flux : Canal de Vente → Thème → Finition**")

            if not filtered_df.empty:
                # Prepare data for Sankey
                df_sankey = filtered_df[['SALES_CHANNEL', 'THEME', 'FINISH']].copy()

                # Create unique labels
                all_labels = (
                    ['Canal: ' + x for x in df_sankey['SALES_CHANNEL'].unique()] +
                    ['Thème: ' + x for x in df_sankey['THEME'].unique()] +
                    ['Finish: ' + x for x in df_sankey['FINISH'].unique()]
                )

                label_to_idx = {label: i for i, label in enumerate(all_labels)}

                # Create flows
                flows = []

                # Channel → Theme
                for (channel, theme), count in df_sankey.groupby(['SALES_CHANNEL', 'THEME']).size().items():
                    flows.append({
                        'source': label_to_idx['Canal: ' + channel],
                        'target': label_to_idx['Thème: ' + theme],
                        'value': count
                    })

                # Theme → Finish
                for (theme, finish), count in df_sankey.groupby(['THEME', 'FINISH']).size().items():
                    flows.append({
                        'source': label_to_idx['Thème: ' + theme],
                        'target': label_to_idx['Finish: ' + finish],
                        'value': count
                    })

                # Create Sankey diagram
                fig_sankey = go.Figure(data=[go.Sankey(
                    node=dict(
                        pad=15,
                        thickness=20,
                        line=dict(color="black", width=0.5),
                        label=all_labels,
                        color=['#FF6B6B', '#4ECDC4', '#45B7D1', '#FFA07A', '#98D8C8', '#F7DC6F',
                               '#BB8FCE', '#85C1E2', '#F8B739', '#52B788', '#FF85A1', '#FFB3BA']
                    ),
                    link=dict(
                        source=[f['source'] for f in flows],
                        target=[f['target'] for f in flows],
                        value=[f['value'] for f in flows]
                    )
                )])

                fig_sankey.update_layout(
                    title="Flux du Parcours Client : Canal → Thème → Finition",
                    font_size=12,
                    height=600
                )

                st.plotly_chart(fig_sankey, width='stretch')

                st.info("💡 **Interprétation** : La largeur des flux indique le volume de ventes. Vous pouvez voir quels canaux mènent à quels thèmes, et quelles finitions sont préférées.")
            else:
                st.warning("Aucune donnée disponible.")

        # 4. SUNBURST HIERARCHIQUE
        elif rd_section == "☀️ Sunburst - Hiérarchie des Ventes":
            st.subheader("☀️ Sunburst : Explorez la Hiérarchie des Ventes")
            st.markdown("**Cliquez sur les segments pour zoomer ! Centre → Modèle → Thème → Finition**")

            if not filtered_df.empty:
                # Prepare hierarchical data
                df_sun = filtered_df.groupby(['MODEL_NAME', 'THEME', 'FINISH'])['TOTAL_SALE'].sum().reset_index()

                # Create sunburst
                fig_sunburst = px.sunburst(
                    df_sun,
                    path=['MODEL_NAME', 'THEME', 'FINISH'],
                    values='TOTAL_SALE',
                    title='Hiérarchie des Ventes : Modèle → Thème → Finition',
                    color='TOTAL_SALE',
                    color_continuous_scale='Viridis',
                    height=700
                )

                fig_sunburst.update_layout(
                    font_size=11
                )

                st.plotly_chart(fig_sunburst, width='stretch')

                st.success("💡 **Astuce** : Cliquez sur un segment pour zoomer. Cliquez au centre pour revenir en arrière.")
            else:
                st.warning("Aucune donnée disponible.")

        # 5. RACING BAR CHART (simulé avec animation)
        elif rd_section == "🏎️ Racing Bar - Top Clients":
            st.subheader("🏎️ Course des Top Clients dans le Temps")
            st.markdown("**Regardez les clients 'courir' pour le classement mois par mois !**")

            if not filtered_df.empty:
                # Prepare monthly cumulative data
                df_race = filtered_df.copy()
                df_race['YearMonth'] = df_race['ORDER_DATE'].dt.to_period('M').astype(str)
                df_race['Customer'] = df_race['FIRST_NAME'] + ' ' + df_race['LAST_NAME']

                # Cumulative sales by customer by month
                monthly_sales = df_race.groupby(['YearMonth', 'Customer'])['TOTAL_SALE'].sum().reset_index()
                monthly_sales = monthly_sales.sort_values('YearMonth')
                monthly_sales['Cumulative'] = monthly_sales.groupby('Customer')['TOTAL_SALE'].cumsum()

                # Get top 10 customers overall
                top_customers = monthly_sales.groupby('Customer')['Cumulative'].max().nlargest(10).index
                monthly_sales_top = monthly_sales[monthly_sales['Customer'].isin(top_customers)]

                # Create animated bar chart
                fig_race = px.bar(
                    monthly_sales_top,
                    x='Cumulative',
                    y='Customer',
                    animation_frame='YearMonth',
                    orientation='h',
                    range_x=[0, monthly_sales_top['Cumulative'].max() * 1.1],
                    title='Course des Top 10 Clients (CA Cumulé)',
                    labels={'Cumulative': 'Chiffre d\'Affaires Cumulé (€)'},
                    color='Customer',
                    height=600
                )

                fig_race.update_layout(
                    xaxis_title='CA Cumulé (€)',
                    yaxis_title='',
                    showlegend=False
                )

                st.plotly_chart(fig_race, width='stretch')

                st.info("▶️ **Appuyez sur Play** pour voir l'animation de la course dans le temps !")
            else:
                st.warning("Aucune donnée disponible.")

        # 6. CALENDAR HEATMAP
        elif rd_section == "📅 Calendar Heatmap":
            st.subheader("📅 Heatmap Calendrier : Ventes Quotidiennes")
            st.markdown("**Style GitHub Contributions : chaque jour est une case colorée selon l'intensité des ventes**")

            if not filtered_df.empty:
                # Prepare daily sales
                daily_sales_cal = filtered_df.groupby(filtered_df['ORDER_DATE'].dt.date)['TOTAL_SALE'].sum().reset_index()
                daily_sales_cal.columns = ['Date', 'Sales']
                daily_sales_cal['Date'] = pd.to_datetime(daily_sales_cal['Date'])
                daily_sales_cal['Week'] = daily_sales_cal['Date'].dt.isocalendar().week
                daily_sales_cal['DayOfWeek'] = daily_sales_cal['Date'].dt.dayofweek
                daily_sales_cal['Year'] = daily_sales_cal['Date'].dt.year

                # Create heatmap
                fig_calendar = px.density_heatmap(
                    daily_sales_cal,
                    x='Week',
                    y='DayOfWeek',
                    z='Sales',
                    title='Heatmap des Ventes Quotidiennes (semaine × jour)',
                    labels={'Week': 'Semaine de l\'année', 'DayOfWeek': 'Jour (0=Lundi)', 'Sales': 'Ventes (€)'},
                    color_continuous_scale='YlOrRd',
                    height=400
                )

                st.plotly_chart(fig_calendar, width='stretch')

                # Alternative: Simple heatmap by date
                daily_sales_cal['DateStr'] = daily_sales_cal['Date'].dt.strftime('%Y-%m-%d')

                fig_calendar2 = go.Figure(data=go.Scatter(
                    x=daily_sales_cal['Date'],
                    y=daily_sales_cal['Sales'],
                    mode='markers',
                    marker=dict(
                        size=daily_sales_cal['Sales']/daily_sales_cal['Sales'].max()*50,
                        color=daily_sales_cal['Sales'],
                        colorscale='Viridis',
                        showscale=True,
                        colorbar=dict(title="Ventes (€)")
                    ),
                    text=daily_sales_cal['DateStr'],
                    hovertemplate='<b>%{text}</b><br>Ventes: %{y:,.2f}€<extra></extra>'
                ))

                fig_calendar2.update_layout(
                    title='Timeline des Ventes Quotidiennes',
                    xaxis_title='Date',
                    yaxis_title='Ventes (€)',
                    height=400,
                    hovermode='closest'
                )

                st.plotly_chart(fig_calendar2, width='stretch')
            else:
                st.warning("Aucune donnée disponible.")

        # 7. PRICE ELASTICITY SIMULATOR
        elif rd_section == "💰 Simulateur d'Élasticité Prix":
            st.subheader("💰 Simulateur d'Élasticité des Prix")
            st.markdown("**Testez l'impact d'un changement de prix sur vos ventes**")

            if not filtered_df.empty:
                # Select a product
                products_list = filtered_df['MODEL_NAME'].unique()
                selected_product = st.selectbox("Choisissez un produit", products_list)

                # Get current metrics
                product_data = filtered_df[filtered_df['MODEL_NAME'] == selected_product]
                current_price = product_data['PRICE_AT_PURCHASE'].mean()
                current_quantity = len(product_data)
                current_revenue = product_data['TOTAL_SALE'].sum()

                col1, col2, col3 = st.columns(3)
                col1.metric("Prix Moyen Actuel", f"{current_price:.2f}€")
                col2.metric("Unités Vendues", current_quantity)
                col3.metric("Revenu Total", f"{current_revenue:.2f}€")

                st.markdown("---")

                # Price adjuster
                price_change = st.slider(
                    "Ajustement du Prix (%)",
                    min_value=-50,
                    max_value=50,
                    value=0,
                    step=5,
                    help="Simulez une variation de prix de -50% à +50%"
                )

                new_price = current_price * (1 + price_change/100)

                # Simple elasticity model (assuming elasticity of -1.5)
                elasticity = -1.5
                quantity_change = elasticity * price_change
                new_quantity = int(current_quantity * (1 + quantity_change/100))
                new_revenue = new_price * new_quantity

                revenue_change = ((new_revenue - current_revenue) / current_revenue * 100)

                st.markdown("### 📊 Résultats de la Simulation")

                col1, col2, col3 = st.columns(3)
                col1.metric(
                    "Nouveau Prix",
                    f"{new_price:.2f}€",
                    delta=f"{price_change:+}%"
                )
                col2.metric(
                    "Unités Vendues (estimées)",
                    new_quantity,
                    delta=f"{quantity_change:+.1f}%",
                    delta_color="inverse" if quantity_change < 0 else "normal"
                )
                col3.metric(
                    "Revenu Estimé",
                    f"{new_revenue:.2f}€",
                    delta=f"{revenue_change:+.1f}%"
                )

                # Visualization
                scenarios = pd.DataFrame({
                    'Scenario': ['Actuel', 'Simulé'],
                    'Prix': [current_price, new_price],
                    'Quantité': [current_quantity, new_quantity],
                    'Revenu': [current_revenue, new_revenue]
                })

                fig_sim = go.Figure()
                fig_sim.add_trace(go.Bar(
                    name='Prix (€)',
                    x=scenarios['Scenario'],
                    y=scenarios['Prix'],
                    yaxis='y',
                    marker_color='lightblue'
                ))
                fig_sim.add_trace(go.Bar(
                    name='Quantité',
                    x=scenarios['Scenario'],
                    y=scenarios['Quantité'],
                    yaxis='y2',
                    marker_color='lightgreen'
                ))
                fig_sim.add_trace(go.Scatter(
                    name='Revenu (€)',
                    x=scenarios['Scenario'],
                    y=scenarios['Revenu'],
                    yaxis='y3',
                    mode='lines+markers',
                    line=dict(color='red', width=3),
                    marker=dict(size=12)
                ))

                fig_sim.update_layout(
                    title='Comparaison : Actuel vs Simulé',
                    yaxis=dict(title='Prix (€)', side='left'),
                    yaxis2=dict(title='Quantité', overlaying='y', side='right'),
                    yaxis3=dict(title='Revenu (€)', overlaying='y', side='right', position=0.85),
                    legend=dict(x=0.1, y=1.1, orientation='h'),
                    height=500
                )

                st.plotly_chart(fig_sim, width='stretch')

                st.info(f"""
                💡 **Hypothèses** :
                - Élasticité-prix de la demande : {elasticity} (typique pour des produits de luxe/collection)
                - Un changement de prix de 1% entraîne un changement de quantité de {elasticity}%
                - Modèle simplifié à des fins illustratives
                """)
            else:
                st.warning("Aucune donnée disponible.")

        # 8. NEXT BEST ACTION IA
        elif rd_section == "🤖 Next Best Action IA":
            st.subheader("🤖 Recommandation Personnalisée : Next Best Action")
            st.markdown("**L'IA analyse un client et recommande la meilleure action commerciale**")

            if not filtered_df.empty and anthropic_api_key:
                # Select customer
                customers_list = filtered_df.groupby('CUSTOMER_ID').agg({
                    'FIRST_NAME': 'first',
                    'LAST_NAME': 'first'
                }).reset_index()
                customers_list['Display'] = customers_list['FIRST_NAME'] + ' ' + customers_list['LAST_NAME']

                selected_customer_display = st.selectbox(
                    "Choisissez un client",
                    customers_list['Display'].values
                )

                selected_customer_id = customers_list[customers_list['Display'] == selected_customer_display]['CUSTOMER_ID'].values[0]

                # Get customer data
                customer_orders = filtered_df[filtered_df['CUSTOMER_ID'] == selected_customer_id]

                customer_stats = {
                    'Nom': selected_customer_display,
                    'Nombre de commandes': len(customer_orders),
                    'CA total': customer_orders['TOTAL_SALE'].sum(),
                    'Panier moyen': customer_orders['TOTAL_SALE'].mean(),
                    'Dernière commande': customer_orders['ORDER_DATE'].max().strftime('%Y-%m-%d'),
                    'Produits préférés': customer_orders['MODEL_NAME'].value_counts().head(3).to_dict(),
                    'Thèmes préférés': customer_orders['THEME'].value_counts().head(3).to_dict(),
                    'Canal préféré': customer_orders['SALES_CHANNEL'].mode()[0] if len(customer_orders['SALES_CHANNEL'].mode()) > 0 else 'N/A'
                }

                # Display stats
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Commandes", customer_stats['Nombre de commandes'])
                col2.metric("CA Total", f"{customer_stats['CA total']:.2f}€")
                col3.metric("Panier Moyen", f"{customer_stats['Panier moyen']:.2f}€")
                col4.metric("Dernière Commande", customer_stats['Dernière commande'])

                st.markdown("---")

                if st.button("🤖 Générer la Recommandation IA"):
                    with st.spinner("🧠 L'IA analyse le profil du client..."):
                        # Prepare context for AI
                        context = f"""
                        Profil Client :
                        - Nom : {customer_stats['Nom']}
                        - Nombre de commandes : {customer_stats['Nombre de commandes']}
                        - Chiffre d'affaires total : {customer_stats['CA total']:.2f}€
                        - Panier moyen : {customer_stats['Panier moyen']:.2f}€
                        - Dernière commande : {customer_stats['Dernière commande']}
                        - Produits préférés : {customer_stats['Produits préférés']}
                        - Thèmes préférés : {customer_stats['Thèmes préférés']}
                        - Canal préféré : {customer_stats['Canal préféré']}
                        """

                        prompt = f"""
                        Tu es un expert en marketing et relation client pour une entreprise de figurines de collection.

                        Analyse ce profil client et génère une recommandation "Next Best Action" structurée :

                        {context}

                        Fournis :
                        1. **Segment Client** : (Champion / Loyal / Standard / À Risque)
                        2. **Produit à Recommander** : (avec justification basée sur l'historique)
                        3. **Meilleur Moment de Contact** : (timing optimal)
                        4. **Canal Recommandé** : (email, in-store, phone)
                        5. **Message Personnalisé** : (un court message marketing à envoyer)
                        6. **Probabilité d'Achat Estimée** : (%)

                        Sois concis et actionnable.
                        """

                        try:
                            client = anthropic.Anthropic(api_key=anthropic_api_key)
                            message = client.messages.create(
                                model="claude-sonnet-4-5-20250929",
                                max_tokens=1500,
                                messages=[{"role": "user", "content": prompt}]
                            )

                            recommendation = message.content[0].text

                            st.success("✅ Recommandation générée !")
                            st.markdown("### 🎯 Next Best Action")
                            st.markdown(recommendation)

                        except Exception as e:
                            st.error(f"Erreur lors de la génération : {e}")

            elif not anthropic_api_key:
                st.warning("⚠️ Veuillez entrer votre clé API Anthropic dans la barre latérale.")
            else:
                st.warning("Aucune donnée disponible.")

if __name__ == "__main__":
    main()

