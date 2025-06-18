import streamlit as st
import fitz  # PyMuPDF
import uuid
import os

from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse
from google.generativeai import configure, GenerativeModel

# === Setup ===
gemini_api_key = os.getenv("GEMINI_API_KEY")
if not gemini_api_key:
    st.error("GEMINI_API_KEY environment variable not set. Please set it to proceed.")
    st.stop()

configure(api_key=gemini_api_key)
model = GenerativeModel("gemini-1.5-flash")
embedder = SentenceTransformer("all-MiniLM-L12-v2", device='cpu')

# Initialize Qdrant client
try:
    qdrant = QdrantClient(host="localhost", port=6333)
    qdrant.get_collections() # Test connection
    st.sidebar.success("✅ Connected to Qdrant!")
except Exception as e:
    st.error(f"Failed to connect to Qdrant at localhost:6333. Please ensure Qdrant Docker container is running: {e}")
    st.info("You can usually start Qdrant with `docker run -p 6333:6333 qdrant/qdrant`")
    st.stop()

collection_name = "medical_docs"
vector_dim = embedder.get_sentence_embedding_dimension()
if vector_dim is None:
    st.warning("Could not automatically determine embedding dimension. Defaulting to 384.")
    vector_dim = 384

# --- Function to recreate collection (for initial setup) ---
def recreate_main_collection():
    try:
        qdrant.recreate_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(size=vector_dim, distance=models.Distance.COSINE)
        )
        st.sidebar.success(f"Collection '{collection_name}' recreated successfully.")
    except Exception as create_e:
        st.error(f"Failed to recreate Qdrant collection: {create_e}")
        st.stop()

# === Initial Collection Check/Creation ===
try:
    qdrant.get_collection(collection_name=collection_name)
    st.sidebar.info(f"Collection '{collection_name}' already exists.")
except UnexpectedResponse as e:
    if "Not found" in str(e):
        st.sidebar.info(f"Collection '{collection_name}' not found. Creating it...")
        recreate_main_collection()
    else:
        st.error(f"An unexpected Qdrant error occurred: {e}")
        st.stop()
except Exception as e:
    st.error(f"An error occurred while checking Qdrant collection: {e}")
    st.stop()


# === WHO Indexing (do once on app startup or if data isn't present) ===
WHO_GUIDELINES_PATH = "who_guidelines.txt" # Make sure this file exists in the same directory as app.py

def is_who_data_indexed():
    try:
        results = qdrant.scroll(
            collection_name=collection_name,
            scroll_filter=models.Filter(
                must=[models.FieldCondition(key="source", match=models.MatchValue(value="who"))]
            ),
            limit=1
        )
        return len(results[0]) > 0
    except Exception as e:
        st.error(f"Error checking WHO data index status: {e}")
        return False

def index_who_guidelines():
    if not os.path.exists(WHO_GUIDELINES_PATH):
        st.warning(f"WHO guidelines file not found at: {WHO_GUIDELINES_PATH}. "
                   "Please place 'who_guidelines.txt' in the same directory as this script "
                   "or update the `WHO_GUIDELINES_PATH` variable.")
        return

    with open(WHO_GUIDELINES_PATH, "r", encoding="utf-8") as f:
        text = f.read()

    chunks = [text[i:i+500] for i in range(0, len(text), 500)]
    vectors = [embedder.encode(chunk).tolist() for chunk in chunks]

    points = [
        models.PointStruct(id=str(uuid.uuid4()), vector=v, payload={"text": c, "source": "who"})
        for v, c in zip(vectors, chunks)
    ]

    st.info(f"Indexing {len(points)} WHO guideline chunks...")
    qdrant.upsert(collection_name=collection_name, points=points)
    st.success("✅ WHO guidelines indexed successfully!")


# Only index WHO data if it hasn't been indexed yet on app startup
if not is_who_data_indexed():
    st.sidebar.info("WHO guidelines not found in Qdrant collection. Indexing now...")
    index_who_guidelines()
else:
    st.sidebar.info("WHO guidelines already indexed.")


# === Streamlit UI ===
st.title("🩺 Health Report Assistant")
st.markdown("""
This assistant helps you get answers from your uploaded medical reports
and general WHO guidelines.
""")

uploaded_file = st.file_uploader("Upload your medical report (PDF)", type="pdf")

if uploaded_file:
    st.info("Processing your medical report...")
    # === PDF to Text ===
    try:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
    except Exception as e:
        st.error(f"Error reading PDF file: {e}")
        st.stop()

    # === Chunk & Embed ===
    chunks = [text[i:i+500] for i in range(0, len(text), 500)] # Chunk size 500
    vectors = [embedder.encode(chunk).tolist() for chunk in chunks]

    # === Clear old patient report data before indexing new one ===
    st.info("Clearing old patient report data from Qdrant...")
    try:
        qdrant.delete(
            collection_name=collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[models.FieldCondition(key="source", match=models.MatchValue(value="report"))]
                )
            )
        )
        st.success("✅ Old patient report data cleared successfully.")
    except Exception as e:
        st.warning(f"Could not clear old patient report data (may not exist): {e}")


    # Each chunk gets a unique ID and is marked as 'report' source
    report_points = [
        models.PointStruct(
            id=str(uuid.uuid4()),
            vector=v,
            payload={
                "text": c,
                "source": "report"
            }
        ) for v, c in zip(vectors, chunks)
    ]

    try:
        st.info(f"Indexing {len(report_points)} chunks from the report...")
        qdrant.upsert(collection_name=collection_name, points=report_points)
        st.success("✅ Report uploaded and indexed successfully!")
    except Exception as e:
        st.error(f"Failed to index patient report in Qdrant: {e}")
        st.info("Please ensure Qdrant is running and the collection exists.")


    # === Ask a Question ===
    question = st.text_input("Ask a question about your health or report:")

    if question:
        st.info("Searching for answers...")
        q_vec = embedder.encode(question).tolist()

        # --- Query Patient Report Context ---
        report_context = ""
        try:
            report_results = qdrant.query_points(
                collection_name=collection_name,
                query=q_vec,
                limit=5, # Retrieving top 5 relevant chunks
                with_payload=True,
                query_filter=models.Filter(
                    must=[models.FieldCondition(key="source", match=models.MatchValue(value="report"))]
                )
            )
            report_context = "\n".join([
                p.payload["text"] for p in report_results.points if "text" in p.payload
            ])

        except Exception as e:
            st.error(f"Error querying patient report from Qdrant: {e}")
            report_context = ""


        # --- Query WHO Guidelines Context ---
        who_context = ""
        try:
            who_results = qdrant.query_points(
                collection_name=collection_name,
                query=q_vec,
                limit=5, # Retrieving top 5 relevant chunks
                with_payload=True,
                query_filter=models.Filter(
                    must=[models.FieldCondition(key="source", match=models.MatchValue(value="who"))]
                )
            )
            who_context = "\n".join([
                p.payload["text"] for p in who_results.points if "text" in p.payload
            ])

        except Exception as e:
            st.error(f"Error querying WHO guidelines from Qdrant: {e}")
            who_context = ""

        # --- Construct Prompt ---
        prompt = f"""You are a helpful health assistant.

The user asked: "{question}"

=== Context from Patient Report ===
{report_context if report_context else "No relevant information found in patient report."}

=== Context from WHO Guidelines ===
{who_context if who_context else "No relevant information found in WHO guidelines."}

Please answer the question based only on the provided context. Follow these guidelines:
1.  **Prioritize Relevance:** Use information from the "Context from Patient Report" for questions specifically about the patient's individual health, diagnosis, medications, or personal data.
2.  **General Health Information:** Use information from "Context from WHO Guidelines" for general medical advice, disease information, lifestyle recommendations, or broader health concepts.
3.  **Combined Use:** If the question requires both personal details and general health advice, use information from both contexts synergistically.
4.  **Context Availability:**
    * If only "Context from Patient Report" is relevant or available, answer using that.
    * If only "Context from WHO Guidelines" is relevant or available, answer using that.
    * If relevant information is found in neither context, or if the question cannot be answered from the provided specific contexts, clearly state that.

If the answer cannot be found in the provided relevant context from either the patient report or WHO guidelines,
reply: "Sorry, I couldn't find relevant information in the available context to answer that specific question."
"""
        st.markdown("### 💡 Generating Answer...")
        try:
            response = model.generate_content(prompt)
            st.markdown("### 💡 Answer:")
            st.write(response.text)
        except Exception as e:
            st.error(f"Error generating answer from Gemini: {e}")
            st.write("Sorry, I encountered an issue while trying to answer. Please try again.")