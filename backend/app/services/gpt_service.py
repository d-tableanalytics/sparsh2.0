import os
import pypdf
import docx
import json
import pandas as pd
from datetime import datetime
from bson import ObjectId
from app.db.mongodb import get_collection
from app.config.settings import settings
from openai import AsyncOpenAI
import numpy as np

async def extract_text_from_file(file_path: str, filename: str) -> str:
    ext = filename.split('.')[-1].lower()
    text = ""
    try:
        if ext == 'pdf':
            with open(file_path, 'rb') as f:
                reader = pypdf.PdfReader(f)
                for page in reader.pages:
                    text += (page.extract_text() or "") + "\n"
        elif ext in ['doc', 'docx']:
            doc = docx.Document(file_path)
            for para in doc.paragraphs:
                text += para.text + "\n"
        elif ext == 'txt':
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
        elif ext in ['csv', 'xls', 'xlsx']:
            df = pd.read_excel(file_path) if ext.startswith('xls') else pd.read_csv(file_path)
            text = df.to_string()
    except Exception as e:
        print(f"Extraction Error for {filename}: {e}")
    return text

def chunk_text(text: str, chunk_size=800, overlap=150) -> list:
    chunks = []
    if not text: return chunks
    words = text.split()
    for i in range(0, len(words), chunk_size - overlap):
        chunk = " ".join(words[i:i + chunk_size])
        chunks.append(chunk)
    return chunks

async def process_knowledge_base(project_id: str, file_id: str, local_path: str, filename: str):
    """
    Background Task to index the knowledge base.
    """
    text = await extract_text_from_file(local_path, filename)
    chunks = chunk_text(text)
    
    col = get_collection("KnowledgeBase")
    chunk_docs = []
    for c in chunks:
        chunk_docs.append({
            "project_id": project_id,
            "file_id": file_id,
            "filename": filename,
            "content": c,
            "created_at": datetime.utcnow()
        })
    
    if chunk_docs:
        await col.insert_many(chunk_docs)
    
    # Cleanup local file
    if os.path.exists(local_path):
        os.remove(local_path)

async def get_relevant_context(project_id: str, query: str, limit=5) -> str:
    """
    Simple keyword-based context retrieval (Mocking RAG for modularity).
    In a full production version, this would use vector embeddings.
    """
    col = get_collection("KnowledgeBase")
    # Simple search for chunks containing any of the keywords from query
    keywords = [k for k in query.lower().split() if len(k) > 3]
    
    # Using regex for case-insensitive keyword search
    if keywords:
        search_query = {"project_id": project_id, "content": {"$regex": "|".join(keywords), "$options": "i"}}
    else:
        search_query = {"project_id": project_id}
        
    chunks = await col.find(search_query).limit(limit).to_list(limit)
    context = "\n\n---\n\n".join([c["content"] for c in chunks])
    return context

async def generate_ai_response(instructions: str, context: str, user_message: str, history: list):
    try:
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        
        system_prompt = f"""### SYSTEM INSTRUCTION
{instructions}

### KNOWLEDGE CONTEXT
The following snippets are extracted from your dedicated knowledge base. Prioritize this information above your general knowledge for project-specific queries.

---
{context}
---

### RESPONSE PROTOCOL
1. **Accuracy**: If the answer is in the provided context, use it. If not, state clearly that the specific information isn't in your knowledge base before using general AI knowledge.
2. **Detail**: Provide comprehensive, structured, and descriptive answers.
3. **Adherence**: Follow the exact instructions provided in the SYSTEM INSTRUCTION section above.
4. **Tone**: Maintain a professional, executive, and coaching-oriented tone.
5. **Efficiency**: Answer fast and focus on actionable insights.
"""
        messages = [{"role": "system", "content": system_prompt}]
        # Add basic context from history
        for h in history[-5:]: # Last 5 messages for history
            messages.append({"role": h["role"], "content": h["content"]})
            
        messages.append({"role": "user", "content": user_message})
        
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"GPT Generation Error: {e}")
        return f"I'm sorry, I encountered an error: {str(e)}"

async def grade_descriptive_answer(question: str, user_answer: str, keywords: str, checker_instructions: str, max_marks: float):
    try:
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        
        prompt = f"""You are an Expert Academic Evaluator. Your task is to grade a student's answer based on the following criteria:

### QUESTION
{question}

### STUDENT'S ANSWER
{user_answer}

### EXPECTED CORE KEYWORDS / CONCEPTS
{keywords}

### SPECIAL INSTRUCTIONS FOR CHECKER
{checker_instructions}

### GRADING PROTOCOL
1. Assign a numeric score from 0 to {max_marks}.
2. Compare the student's answer against the keywords and question context.
3. Be fair but strict according to the special instructions.
4. Provide constructive feedback, explaining the REASON for the marks given and offering SUGGESTIONS for improvement.
5. If the answer is blank or irrelevant, assign 0.
6. Return ONLY a valid JSON object.

### OUTPUT FORMAT (JSON ONLY)
{{
  "score": <number>,
  "feedback": "<string>"
}}
"""
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            response_format={ "type": "json_object" },
            temperature=0.3
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"AI Grading Error: {e}")
        return {"score": 0, "feedback": f"AI Grading Engine Error: {str(e)}"}
