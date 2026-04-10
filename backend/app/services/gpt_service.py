import os
import pypdf
import docx
import json
import pandas as pd
import base64
from datetime import datetime
from bson import ObjectId
from app.db.mongodb import get_collection
from app.config.settings import settings
from openai import AsyncOpenAI
import numpy as np
from app.services.transcription_service import transcribe_media_file

async def extract_text_from_file(file_path: str, filename: str) -> dict:
    """
    Returns {"text": str, "images": list[str]}
    Images are base64 data URIs: "data:image/png;base64,..."
    """
    ext = filename.split('.')[-1].lower()
    text = ""
    images = []
    try:
        if ext in ['jpg', 'jpeg', 'png', 'webp', 'gif']:
            with open(file_path, "rb") as image_file:
                base64_data = base64.b64encode(image_file.read()).decode('utf-8')
                mime_type = "image/jpeg" if ext in ['jpg', 'jpeg'] else f"image/{ext}"
                images.append(f"data:{mime_type};base64,{base64_data}")
        elif ext == 'pdf':
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
            if ext == 'csv':
                df = pd.read_csv(file_path)
                text = df.to_string()
            else:
                # Read all sheets for text
                xls = pd.ExcelFile(file_path)
                sheet_texts = []
                for sheet_name in xls.sheet_names:
                    df = pd.read_excel(file_path, sheet_name=sheet_name)
                    sheet_texts.append(f"[Sheet: {sheet_name}]\n{df.to_string()}")
                text = "\n\n".join(sheet_texts)
                
                # Extract embedded images from Excel using openpyxl
                try:
                    from openpyxl import load_workbook
                    from io import BytesIO
                    wb = load_workbook(file_path)
                    for ws in wb.worksheets:
                        for img in ws._images:
                            try:
                                img_data = None
                                if hasattr(img, '_data'):
                                    img_data = img._data()
                                elif hasattr(img, 'ref'):
                                    img_data = img.ref.getvalue() if hasattr(img.ref, 'getvalue') else img.ref.read()
                                
                                if img_data:
                                    b64 = base64.b64encode(img_data).decode('utf-8')
                                    images.append(f"data:image/png;base64,{b64}")
                            except Exception as img_err:
                                print(f"Skipping image extraction: {img_err}")
                    wb.close()
                except Exception as excel_img_err:
                    print(f"Excel image extraction warning: {excel_img_err}")
        elif ext in ['mp3', 'wav', 'm4a', 'aac', 'flac', 'mp4', 'mov', 'avi', 'mkv', 'webm']:
            print(f"--- Transcribing Media Knowledge: {filename} ---")
            text = await transcribe_media_file(file_path)
            if not text:
                text = f"[Media File: {filename} - No speech detected or readable]"
    except Exception as e:
        print(f"Extraction Error for {filename}: {e}")
    return {"text": text, "images": images}

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
    result = await extract_text_from_file(local_path, filename)
    text = result["text"]
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

async def generate_ai_response(instructions: str, context: str, user_message: str, history: list, images: list = None):
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
            
        user_content = [{"type": "text", "text": user_message}]
        
        if images:
            for img_url in images:
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": img_url, "detail": "low"}
                })
                
        messages.append({"role": "user", "content": user_content})
        
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
