from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import fitz  # PyMuPDF
import uuid
import os
from dotenv import load_dotenv #
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse
from google.generativeai import configure, GenerativeModel

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
embedder = SentenceTransformer("all-MiniLM-L12-v2", device='cpu')

collection_name = "medical_docs"
vector_dim = embedder.get_sentence_embedding_dimension() or 384

qdrant = QdrantClient(host="localhost", port=6333)
try:
    qdrant.get_collection(collection_name=collection_name)
except UnexpectedResponse as e:
    qdrant.recreate_collection(
        collection_name=collection_name,
        vectors_config=models.VectorParams(size=vector_dim, distance=models.Distance.COSINE)
    )

# === WHO Indexing ===
WHO_GUIDELINES_PATH = "who_guidelines.txt"

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
    except:
        return False

def index_who_guidelines():
    if not os.path.exists(WHO_GUIDELINES_PATH):
        return

    with open(WHO_GUIDELINES_PATH, "r", encoding="utf-8") as f:
        text = f.read()

    chunks = [text[i:i+500] for i in range(0, len(text), 500)]
    vectors = [embedder.encode(chunk).tolist() for chunk in chunks]

    points = [
        models.PointStruct(id=str(uuid.uuid4()), vector=v, payload={"text": c, "source": "who"})
        for v, c in zip(vectors, chunks)
    ]
    qdrant.upsert(collection_name=collection_name, points=points)

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
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[models.FieldCondition(key="source", match=models.MatchValue(value="report"))]
                )
            )
        )
    except:
        pass  # Might not exist initially

    report_points = [
        models.PointStruct(id=str(uuid.uuid4()), vector=v, payload={"text": c, "source": "report"})
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
    try:
        report_results = qdrant.query_points(
            collection_name=collection_name,
            query=q_vec,
            limit=5,
            with_payload=True,
            query_filter=models.Filter(
                must=[models.FieldCondition(key="source", match=models.MatchValue(value="report"))]
            )
        )
        report_context = "\n".join([
            p.payload["text"] for p in report_results.points if "text" in p.payload
        ])
    except:
        report_context = ""

    # --- Query WHO ---
    try:
        who_results = qdrant.query_points(
            collection_name=collection_name,
            query=q_vec,
            limit=5,
            with_payload=True,
            query_filter=models.Filter(
                must=[models.FieldCondition(key="source", match=models.MatchValue(value="who"))]
            )
        )
        who_context = "\n".join([
            p.payload["text"] for p in who_results.points if "text" in p.payload
        ])
    except:
        who_context = ""

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
