from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import fitz  # PyMuPDF
import uuid
import os
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from sentence_transformers import CrossEncoder
# Fixed imports for Qdrant client version 1.14.3
from qdrant_client.models import (
    Distance, 
    VectorParams, 
    Filter, 
    MatchValue, 
    FilterSelector, 
    PointStruct,
    FieldCondition  # This should be available in 1.14.3
)
from qdrant_client.http.exceptions import UnexpectedResponse
from google.generativeai import configure, GenerativeModel
import time

# === Setup ===
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)
load_dotenv()
gemini_api_key = os.getenv("GEMINI_API_KEY")
if not gemini_api_key:
    raise RuntimeError("❌ GEMINI_API_KEY not set in environment.")

configure(api_key=gemini_api_key)
model = GenerativeModel("gemini-1.5-flash")
# This line loads the SentenceTransformer model on startup, which is memory-intensive
embedder = SentenceTransformer("all-MiniLM-L12-v2", device='cpu')

reranker = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')

collection_name = "medical_docs"
# This dimension is derived from the globally loaded embedder
vector_dim = embedder.get_sentence_embedding_dimension() or 384

# --- Qdrant Client updated to use environment variables and increased timeout ---
qdrant_url = os.getenv("QDRANT_URL")
if not qdrant_url:
    # Raise an error if QDRANT_URL is not set, as it's now required
    raise RuntimeError("❌ QDRANT_URL environment variable not set. Please set it to your Qdrant instance URL (e.g., your Qdrant Cloud URL).")

qdrant_api_key = os.getenv("QDRANT_API_KEY") # Optional, depending on your Qdrant setup

qdrant = QdrantClient(
    url=qdrant_url,
    api_key=qdrant_api_key,
    timeout=60.0 # Increased timeout for potentially long operations like initial indexing
)
# Print client version for debugging
try:
    import qdrant_client
    print(f"Qdrant client version: {qdrant_client.__version__}")
except AttributeError:
    print("Qdrant client version: Unable to determine version")
print("Qdrant client connected successfully")

try:
    # Attempt to get the collection to see if it exists
    qdrant.get_collection(collection_name=collection_name)
    print(f"Qdrant collection '{collection_name}' already exists.")
except UnexpectedResponse as e:
    # If it doesn't exist (e.g., 404 Not Found), recreate it
    print(f"Qdrant collection '{collection_name}' not found, attempting to recreate.")
    qdrant.recreate_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=vector_dim, distance=Distance.COSINE)
    )
    print(f"Qdrant collection '{collection_name}' recreated successfully.")
except Exception as e:
    # Catch any other unexpected errors during collection check/recreation
    raise RuntimeError(f"Error checking/creating Qdrant collection: {e}")

# --- Create payload index for 'source' field ---
# This ensures that filtering by 'source' is efficient and doesn't throw errors
try:
    # Create index using the client method directly (use string instead of enum)
    qdrant.create_payload_index(
        collection_name=collection_name,
        field_name="source",
        field_schema="keyword"  # Use string value instead of FieldType.KEYWORD
    )
    print(f"Payload index for 'source' field created or already exists in collection '{collection_name}'.")
except UnexpectedResponse as e:
    if "already exists" in str(e): # Common error message if index exists
        print(f"Payload index for 'source' field already exists in collection '{collection_name}'.")
    else:
        print(f"Warning: Could not create payload index for 'source' field (UnexpectedResponse): {e}")
except Exception as e:
    # Catch any other general exceptions during index creation
    print(f"Warning: Could not create payload index for 'source' field: {e}")


# === WHO Indexing ===
WHO_GUIDELINES_PATH = "who_data/who_az_guidelines.txt"

def is_who_data_indexed():
    try:
        # Use Qdrant's count method for a more efficient check of existence
        count_result = qdrant.count(
            collection_name=collection_name,
            count_filter=Filter(  # Fixed: use count_filter instead of query_filter
                must=[FieldCondition(key="source", match=MatchValue(value="who"))]
            ),
            exact=True # Request exact count
        )
        return count_result.count > 0
    except Exception as e:
        # Log the error for debugging but return False to trigger indexing if unsure
        print(f"Error checking if WHO data is indexed: {e}")
        return False

def index_who_guidelines():
    if not os.path.exists(WHO_GUIDELINES_PATH):
        print(f"Error: WHO guidelines file not found at {WHO_GUIDELINES_PATH}.")
        return

    print("Starting WHO guidelines indexing...")
    with open(WHO_GUIDELINES_PATH, "r", encoding="utf-8") as f:
        text = f.read()

    chunks = [text[i:i+500] for i in range(0, len(text), 500)]
    print(f"Generated {len(chunks)} chunks for WHO data.")

    # This encoding happens on startup, contributing to high memory usage
    vectors = [embedder.encode(chunk).tolist() for chunk in chunks]
    print("Encoded WHO chunks into vectors.")

    points = [
        PointStruct(id=str(uuid.uuid4()), vector=v, payload={"text": c, "source": "who"})
        for v, c in zip(vectors, chunks)
    ]
    
    # Upsert in batches
    batch_size = 50 # Reduced batch size for upserts to reduce load on Qdrant
    for i in range(0, len(points), batch_size):
        batch = points[i:i+batch_size]
        try:
            qdrant.upsert(collection_name=collection_name, points=batch)
            print(f"Indexed {min(i + batch_size, len(points))} / {len(points)} WHO chunks...")
        except Exception as upsert_e:
            print(f"Error upserting batch {i//batch_size + 1}: {upsert_e}")
            # Decide how to handle this - retry, skip, or re-raise
            # For now, we'll just log and continue, but in production, you might want more robust retry logic
        time.sleep(0.1) # Add a small delay to relieve pressure on Qdrant Cloud (if free tier/rate limited)

    print("WHO guidelines indexing complete!")

def rerank_chunks(question: str, chunks: list[str], top_k=3) -> list[str]:
    if not chunks:
        return []

    pairs = [(question, chunk) for chunk in chunks]
    scores = reranker.predict(pairs)

    # Sort chunks based on scores descending
    ranked = sorted(zip(chunks, scores), key=lambda x: x[1], reverse=True)
    top_chunks = [chunk for chunk, _ in ranked[:top_k]]
    
    return top_chunks


# This block runs on every application startup, causing repeated memory spikes and processing
if not is_who_data_indexed():
    index_who_guidelines()


# === Upload Report Endpoint ===
@app.post("/upload")
async def upload_report(file: UploadFile = File(...)):
    try:
        doc = fitz.open(stream=await file.read(), filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"Error reading PDF: {e}"})

    chunks = [text[i:i+500] for i in range(0, len(text), 500)]
    vectors = [embedder.encode(chunk).tolist() for chunk in chunks]

    # Clear old report data
    try:
        qdrant.delete(
            collection_name=collection_name,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[FieldCondition(key="source", match=MatchValue(value="report"))]
                )
            )
        )
        print("Old report data cleared from Qdrant.")
    except UnexpectedResponse as e:
        # This can happen if the filter doesn't match any points, which is fine
        print(f"No old report data to clear or unexpected response during delete: {e}")
    except Exception as e:
        print(f"Error clearing old report data: {e}")
        pass  # Continue even if there's an error clearing old data

    report_points = [
        PointStruct(id=str(uuid.uuid4()), vector=v, payload={"text": c, "source": "report"})
        for v, c in zip(vectors, chunks)
    ]

    try:
        qdrant.upsert(collection_name=collection_name, points=report_points)
        return {"message": "✅ Report uploaded and indexed successfully!"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to index report: {e}"})


# === Ask Question Endpoint ===
class QuestionRequest(BaseModel):
    question: str

@app.post("/ask")
async def ask_question(data: QuestionRequest):
    q_vec = embedder.encode(data.question).tolist()

    # --- Query Report ---
    report_context = ""
    try:
        report_results = qdrant.query_points(
            collection_name=collection_name,
            query=q_vec,
            limit=5,
            with_payload=True,
            query_filter=Filter(
                must=[FieldCondition(key="source", match=MatchValue(value="report"))]
            )
        )
        report_chunks = [p.payload["text"] for p in report_results.points if p.payload and "text" in p.payload]
        report_context = "\n".join(rerank_chunks(data.question, report_chunks, top_k=3))
        print(type(report_chunks))
    except Exception as e:
        print(f"Error querying report context from Qdrant: {e}")
        report_context = ""

    # --- Query WHO ---
    who_context = ""
    try:
        who_results = qdrant.query_points(
            collection_name=collection_name,
            query=q_vec,
            limit=5,
            with_payload=True,
            query_filter=Filter(
                must=[FieldCondition(key="source", match=MatchValue(value="who"))]
            )
        )
        who_chunks = [p.payload["text"] for p in who_results.points if p.payload and "text" in p.payload]
        who_context = "\n".join(rerank_chunks(data.question, who_chunks, top_k=3))

    except Exception as e:
        print(f"Error querying WHO context from Qdrant: {e}")
        who_context = ""
    print(report_context)
    print(who_context)
    # --- Prompt ---
    prompt = f"""You are a helpful health assistant.

The user asked: "{data.question}"

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
    try:
        response = model.generate_content(prompt)
        return {"answer": response.text}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Gemini error: {e}"})