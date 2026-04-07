from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from typing import List, Optional
from datetime import datetime
from bson import ObjectId
from app.db.mongodb import get_collection
from app.controllers.auth_controller import get_current_user
from app.services.s3_service import upload_file_to_s3, get_signed_url
from app.models.gpt import GptProjectCreate, GptProjectUpdate, GptProjectResponse
import os
import tempfile
import aiofiles

router = APIRouter(prefix="/gpt", tags=["gpt"])

@router.get("/projects", response_model=List[dict])
async def get_gpt_projects(current_user: dict = Depends(get_current_user)):
    col = get_collection("gpt_projects")
    projects = await col.find({}).to_list(100)
    for p in projects:
        p["id"] = str(p["_id"])
        del p["_id"]
    return projects

@router.post("/projects", response_model=dict)
async def create_gpt_project(project: GptProjectCreate, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="SuperAdmin only")
    
    col = get_collection("gpt_projects")
    project_dict = project.model_dump()
    project_dict["created_by"] = str(current_user["_id"])
    project_dict["created_at"] = datetime.utcnow()
    
    res = await col.insert_one(project_dict)
    return {"id": str(res.inserted_id), "message": "Project created successfully"}

@router.get("/projects/{project_id}", response_model=dict)
async def get_gpt_project(project_id: str, current_user: dict = Depends(get_current_user)):
    col = get_collection("gpt_projects")
    project = await col.find_one({"_id": ObjectId(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project["id"] = str(project["_id"])
    del project["_id"]
    return project

@router.patch("/projects/{project_id}")
async def update_gpt_project(project_id: str, project_update: GptProjectUpdate, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="SuperAdmin only")
    
    col = get_collection("gpt_projects")
    upd = {k: v for k, v in project_update.model_dump().items() if v is not None}
    await col.update_one({"_id": ObjectId(project_id)}, {"$set": upd})
    return {"message": "Project updated"}

@router.delete("/projects/{project_id}")
async def delete_gpt_project(project_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="SuperAdmin only")
    
    await get_collection("gpt_projects").delete_one({"_id": ObjectId(project_id)})
    # Clean up knowledge chunks too
    await get_collection("gpt_knowledge_chunks").delete_many({"project_id": project_id})
    return {"message": "Project deleted"}

@router.post("/projects/{project_id}/upload-knowledge")
async def upload_project_knowledge(
    project_id: str, 
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...), 
    current_user: dict = Depends(get_current_user)
):
    if current_user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="SuperAdmin only")
        
    col = get_collection("gpt_projects")
    project = await col.find_one({"_id": ObjectId(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # 1. Save locally temporarily for processing
    tmp_path = os.path.join(tempfile.gettempdir(), f"gpt_kb_{project_id}_{file.filename}")
    try:
        async with aiofiles.open(tmp_path, 'wb') as out_file:
            while chunk := await file.read(1024 * 1024):
                await out_file.write(chunk)
                
        # 2. Extract Text and Save to DB IMMEDIATELY (for fast response)
        from app.services.gpt_service import extract_text_from_file, chunk_text
        text = await extract_text_from_file(tmp_path, file.filename)
        chunks = chunk_text(text)
        
        chunk_col = get_collection("gpt_knowledge_chunks")
        file_id = str(ObjectId())
        chunk_docs = []
        for c in chunks:
            chunk_docs.append({
                "project_id": project_id,
                "file_id": file_id,
                "content": c,
                "created_at": datetime.utcnow()
            })
        
        if chunk_docs:
            await chunk_col.insert_many(chunk_docs)

        # 3. Handle S3 Upload in BACKGROUND
        def s3_upload_task(path, filename, content_type, p_id, f_id):
            from app.services.s3_service import upload_file_to_s3
            with open(path, 'rb') as f:
                url = upload_file_to_s3(f, filename, content_type)
            
            # Update project with the final S3 URL
            import asyncio
            from app.db.mongodb import get_collection
            async def update_url():
                col = get_collection("gpt_projects")
                file_doc = {
                    "id": f_id,
                    "name": filename,
                    "type": content_type,
                    "url": url,
                    "uploaded_at": datetime.utcnow()
                }
                await col.update_one({"_id": ObjectId(p_id)}, {"$push": {"knowledge_files": file_doc}})
                if os.path.exists(path):
                    os.remove(path)
            
            # Since this is a sync background task, we need a way to run async DB update or use sync driver.
            # But FastAPI background tasks can be async. Let's make it more robust.
            pass

        # Let's use a better approach: background task for S3 only
        async def finalize_upload(path, filename, content_type, p_id, f_id):
            from app.services.s3_service import upload_file_to_s3
            # s3 is usually sync client, but we can wrap it
            import functools
            import asyncio
            loop = asyncio.get_event_loop()
            with open(path, 'rb') as f:
                url = await loop.run_in_executor(None, functools.partial(upload_file_to_s3, f, filename, content_type))
            
            proj_col = get_collection("gpt_projects")
            file_doc = {
                "id": f_id,
                "name": filename,
                "type": content_type,
                "url": url,
                "uploaded_at": datetime.utcnow()
            }
            await proj_col.update_one({"_id": ObjectId(p_id)}, {"$push": {"knowledge_files": file_doc}})
            if os.path.exists(path):
                os.remove(path)

        background_tasks.add_task(finalize_upload, tmp_path, file.filename, file.content_type, project_id, file_id)

        return {"message": "Knowledge indexed and saved to database. S3 sync in progress...", "file_id": file_id}
    except Exception as e:
        if os.path.exists(tmp_path): os.remove(tmp_path)
        raise HTTPException(status_code=500, detail=f"Knowledge processing failed: {str(e)}")

@router.post("/chat/{project_id}/respond")
async def gpt_chat_respond(project_id: str, payload: dict, current_user: dict = Depends(get_current_user)):
    user_message = payload.get("message")
    if not user_message:
        raise HTTPException(status_code=400, detail="Message required")
        
    # Get conversation history or create new
    conv_col = get_collection("gpt_conversations")
    conv = await conv_col.find_one({"project_id": project_id, "user_id": str(current_user["_id"])})
    if not conv:
        conv = {
            "project_id": project_id,
            "user_id": str(current_user["_id"]),
            "messages": [],
            "updated_at": datetime.utcnow()
        }
        res = await conv_col.insert_one(conv)
        conv["_id"] = res.inserted_id

    # 1. Fetch relevant knowledge (RAG)
    from app.services.gpt_service import get_relevant_context, generate_ai_response
    
    context = await get_relevant_context(project_id, user_message)
    
    # Get project instructions
    proj_col = get_collection("gpt_projects")
    project = await proj_col.find_one({"_id": ObjectId(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="GPT Project not found")
    instructions = project.get("instruction", "You are a helpful assistant.")
    
    # 2. Generate AI Response
    ai_msg = await generate_ai_response(instructions, context, user_message, conv["messages"])
    
    # 3. Save to History
    new_messages = conv["messages"]
    new_messages.append({"role": "user", "content": user_message, "timestamp": datetime.utcnow()})
    new_messages.append({"role": "assistant", "content": ai_msg, "timestamp": datetime.utcnow()})
    
    await conv_col.update_one(
        {"_id": conv["_id"]}, 
        {"$set": {"messages": new_messages, "updated_at": datetime.utcnow()}}
    )
    
    return {"answer": ai_msg}

@router.get("/chat/{project_id}/history")
async def get_gpt_chat_history(project_id: str, current_user: dict = Depends(get_current_user)):
    conv_col = get_collection("gpt_conversations")
    conv = await conv_col.find_one({"project_id": project_id, "user_id": str(current_user["_id"])})
    if not conv:
        return {"messages": []}
    return {"messages": conv["messages"]}
