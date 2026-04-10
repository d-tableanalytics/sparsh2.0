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
    
    # If Admin/Staff, return all
    if current_user.get("role") in ["superadmin", "admin", "coach", "staff"]:
        for p in projects:
            p["id"] = str(p["_id"])
            p["locked"] = False
            del p["_id"]
        return projects

    # For Learners: Complex Access Logic
    user_id = str(current_user["_id"])
    company_id = current_user.get("company_id")
    
    # 1. Fetch special permissions
    perm_col = get_collection("gpt_permissions")
    special_perms = await perm_col.find({
        "$or": [
            {"entity_id": user_id, "entity_type": "user"},
            {"entity_id": company_id, "entity_type": "company"}
        ]
    }).to_list(100)
    unlocked_project_ids = {p["project_id"] for p in special_perms}

    # 2. Find linked projects in learner's path
    batch_ids = current_user.get("batch_ids", [current_user.get("batch_id")])
    batch_ids = [ObjectId(bid) for bid in batch_ids if bid]
    
    # Check Batches
    batches = await get_collection("batches").find({"_id": {"$in": batch_ids}}).to_list(100)
    batch_linked = {} # project_id -> is_completed
    for b in batches:
        is_completed = (b.get("status") == "completed")
        # Legacy support
        old_pid = b.get("gpt_project_id")
        if old_pid: batch_linked[old_pid] = batch_linked.get(old_pid, False) or is_completed
        # Multi support
        for p in b.get("gpt_projects", []):
            pid = p.get("id")
            if pid: batch_linked[pid] = batch_linked.get(pid, False) or is_completed

    # Check Quarters
    quarters = await get_collection("quarters").find({"batch_id": {"$in": [str(bid) for bid in batch_ids]}}).to_list(200)
    quarter_linked = {}
    for q in quarters:
        is_completed = (q.get("status") == "completed")
        # Legacy support
        old_pid = q.get("gpt_project_id")
        if old_pid: quarter_linked[old_pid] = quarter_linked.get(old_pid, False) or is_completed
        # Multi support
        for p in q.get("gpt_projects", []):
            pid = p.get("id")
            if pid: quarter_linked[pid] = quarter_linked.get(pid, False) or is_completed

    # Check Sessions
    from app.utils.calendar_utils import CALENDAR_COLLECTIONS
    session_collections = CALENDAR_COLLECTIONS + ["calendar_events"]
    session_linked = {}
    for col_name in session_collections:
        sessions = await get_collection(col_name).find({
            "$or": [
                {"user_id": user_id},
                {"assigned_member_ids": user_id},
                {"coach_ids": user_id}
            ]
        }).to_list(500)
        for s in sessions:
            is_completed = (s.get("status") == "completed")
            # Legacy support
            old_pid = s.get("gpt_project_id")
            if old_pid: session_linked[old_pid] = session_linked.get(old_pid, False) or is_completed
            # Multi support
            for p in s.get("gpt_projects", []):
                pid = p.get("id")
                if pid: session_linked[pid] = session_linked.get(pid, False) or is_completed

    # 3. Assemble Result
    result = []
    seen_ids = set()
    
    for p in projects:
        pid = str(p["_id"])
        # Is it in the learner's path at all?
        is_in_path = (pid in batch_linked) or (pid in quarter_linked) or (pid in session_linked) or (pid in unlocked_project_ids)
        
        if is_in_path:
            p["id"] = pid
            del p["_id"]
            
            # Determine if locked
            is_unlocked = (
                (pid in unlocked_project_ids) or
                batch_linked.get(pid) or
                quarter_linked.get(pid) or
                session_linked.get(pid)
            )
            
            p["locked"] = not is_unlocked
            
            # Metadata about WHY it's locked/available
            if p["locked"]:
                if pid in batch_linked: p["lock_reason"] = "Batch Level Access (Complete Batch to Unlock)"
                elif pid in quarter_linked: p["lock_reason"] = "Quarter Level Access (Complete Quarter to Unlock)"
                elif pid in session_linked: p["lock_reason"] = "Session Level Access (Complete Session to Unlock)"
            
            result.append(p)
            seen_ids.add(pid)
            
    return result

# ─── Permissions Endpoints ───
@router.post("/permissions/grant")
async def grant_gpt_permission(payload: dict, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["superadmin", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    perm_col = get_collection("gpt_permissions")
    payload["granted_by"] = str(current_user["_id"])
    payload["granted_at"] = datetime.utcnow()
    
    await perm_col.insert_one(payload)
    return {"message": "Permission granted"}

@router.get("/permissions")
async def list_gpt_permissions(project_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["superadmin", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    perm_col = get_collection("gpt_permissions")
    query = {}
    if project_id: query["project_id"] = project_id
    
    perms = await perm_col.find(query).to_list(500)
    for p in perms: p["id"] = str(p["_id"]); del p["_id"]
    return perms

@router.delete("/permissions/{perm_id}")
async def revoke_gpt_permission(perm_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["superadmin", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    perm_col = get_collection("gpt_permissions")
    await perm_col.delete_one({"_id": ObjectId(perm_id)})
    return {"message": "Permission revoked"}

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
    await get_collection("KnowledgeBase").delete_many({"project_id": project_id})
    return {"message": "Project deleted and KnowledgeBase purged."}

@router.post("/projects/{project_id}/upload-knowledge")
async def upload_project_knowledge(
    project_id: str, 
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...), 
    current_user: dict = Depends(get_current_user)
):
    print(f"--- ATTEMPTING KNOWLEDGE UPLOAD: {file.filename} for project {project_id} ---")
    if current_user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="SuperAdmin only")
        
    col = get_collection("gpt_projects")
    project = await col.find_one({"_id": ObjectId(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Use only the filename, avoiding potential directory traversal or missing folders from webkitdirectory
    safe_filename = os.path.basename(file.filename)
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    tmp_path = os.path.join(tempfile.gettempdir(), f"gpt_kb_{project_id}_{timestamp}_{safe_filename}")
    
    try:
        # 1. Save locally temporarily for processing
        async with aiofiles.open(tmp_path, 'wb') as out_file:
            while chunk := await file.read(1024 * 1024):
                await out_file.write(chunk)
        
        # 2. Insert stub immediately so UI can show progress
        file_id = str(ObjectId())
        file_stub = {
            "id": file_id,
            "name": safe_filename,
            "type": file.content_type,
            "status": "processing",
            "progress": 0,
            "uploaded_at": datetime.utcnow()
        }
        await col.update_one({"_id": ObjectId(project_id)}, {"$push": {"knowledge_files": file_stub}})

        # 3. Define background task for both indexing and S3 upload
        async def process_media_and_index(path, filename, content_type, p_id, f_id):
            proj_col = get_collection("gpt_projects")
            try:
                # Part A: Extract Text & Index (may take time for video)
                from app.services.gpt_service import extract_text_from_file, chunk_text
                print(f"--- Starting background extraction for {filename} ---")
                
                # Mocking progressive updates if it's a known slow file (video/audio)
                # In a real scenario, we'd pass a callback to extract_text_from_file
                await proj_col.update_one(
                    {"_id": ObjectId(p_id), "knowledge_files.id": f_id},
                    {"$set": {"knowledge_files.$.progress": 10}}
                )

                result = await extract_text_from_file(path, filename)
                text = result.get("text", "")
                chunks = chunk_text(text)
                
                await proj_col.update_one(
                    {"_id": ObjectId(p_id), "knowledge_files.id": f_id},
                    {"$set": {"knowledge_files.$.progress": 60}}
                )

                kb_col = get_collection("KnowledgeBase")
                chunk_docs = []
                for idx, c in enumerate(chunks):
                    chunk_docs.append({
                        "project_id": p_id,
                        "file_id": f_id,
                        "filename": filename,
                        "content": c,
                        "created_at": datetime.utcnow()
                    })
                
                if chunk_docs:
                    await kb_col.insert_many(chunk_docs)
                
                await proj_col.update_one(
                    {"_id": ObjectId(p_id), "knowledge_files.id": f_id},
                    {"$set": {"knowledge_files.$.progress": 80}}
                )

                # Part B: S3 Sync
                from app.services.s3_service import upload_file_to_s3
                import functools
                import asyncio
                
                loop = asyncio.get_event_loop()
                with open(path, 'rb') as f:
                    url = await loop.run_in_executor(None, functools.partial(upload_file_to_s3, f, filename, content_type))
                
                update_fields = {
                    "knowledge_files.$.status": "ready",
                    "knowledge_files.$.progress": 100,
                    "knowledge_files.$.url": url
                }
                await proj_col.update_one(
                    {"_id": ObjectId(p_id), "knowledge_files.id": f_id},
                    {"$set": update_fields}
                )
                print(f"--- S3/Knowledge Sync Complete for {filename} ---")
                
            except Exception as e:
                print(f"!!! Error in background knowledge task for {filename}: {str(e)} !!!")
                await proj_col.update_one(
                    {"_id": ObjectId(p_id), "knowledge_files.id": f_id},
                    {"$set": {"knowledge_files.$.status": "failed", "knowledge_files.$.error": str(e)}}
                )
            finally:
                if os.path.exists(path):
                    try: os.remove(path)
                    except: pass

        # Dispatch background task
        background_tasks.add_task(process_media_and_index, tmp_path, safe_filename, file.content_type, project_id, file_id)

        return {
            "message": "Upload successful. Neural processing started.", 
            "file_id": file_id,
            "filename": safe_filename
        }
    except Exception as e:
        print(f"!!! Knowledge processing CRITICAL ERROR: {str(e)} !!!")
        if os.path.exists(tmp_path): os.remove(tmp_path)
        raise HTTPException(status_code=500, detail=f"Knowledge processing failed: {str(e)}")

@router.delete("/projects/{project_id}/knowledge/{file_id}")
async def delete_project_knowledge(project_id: str, file_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="SuperAdmin only")
        
    col = get_collection("gpt_projects")
    # 1. Remove from GPT project knowledge_files array
    await col.update_one(
        {"_id": ObjectId(project_id)},
        {"$pull": {"knowledge_files": {"id": file_id}}}
    )
    
    # 2. Remove all chunks from KnowledgeBase
    await get_collection("KnowledgeBase").delete_many({"project_id": project_id, "file_id": file_id})
    
    return {"message": "Knowledge file removed successfully"}

@router.get("/chat/{project_id}/sessions", response_model=List[dict])
async def get_gpt_sessions(project_id: str, current_user: dict = Depends(get_current_user)):
    col = get_collection("gpt_conversations")
    sessions = await col.find({"project_id": project_id, "user_id": str(current_user["_id"])}).sort("updated_at", -1).to_list(100)
    for s in sessions:
        s["id"] = str(s["_id"])
        del s["_id"]
        # Create a preview title from the first message
        if s.get("messages") and len(s["messages"]) > 0:
            s["title"] = s["messages"][0]["content"][:30] + "..."
        else:
            s["title"] = "New Chat Session"
    return sessions

@router.post("/chat/{project_id}/session", response_model=dict)
async def create_new_gpt_session(project_id: str, current_user: dict = Depends(get_current_user)):
    col = get_collection("gpt_conversations")
    new_session = {
        "project_id": project_id,
        "user_id": str(current_user["_id"]),
        "messages": [],
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    res = await col.insert_one(new_session)
    return {"id": str(res.inserted_id)}

@router.post("/chat/sessions/{session_id}/respond")
async def gpt_session_respond(session_id: str, payload: dict, current_user: dict = Depends(get_current_user)):
    user_message = payload.get("message")
    if not user_message:
        raise HTTPException(status_code=400, detail="Message required")
        
    conv_col = get_collection("gpt_conversations")
    conv = await conv_col.find_one({"_id": ObjectId(session_id), "user_id": str(current_user["_id"])})
    if not conv:
        raise HTTPException(status_code=404, detail="Session not found")

    project_id = conv["project_id"]

    # 1. Fetch relevant knowledge (RAG)
    from app.services.gpt_service import get_relevant_context, generate_ai_response
    
    # Combined knowledge: Project RAG + Session Knowledge
    context = await get_relevant_context(project_id, user_message)
    session_images = []
    if conv.get("session_knowledge"):
        for sk in conv["session_knowledge"]:
            if sk["content"].startswith("[IMAGE_BASE64]"):
                session_images.append(sk["content"].replace("[IMAGE_BASE64]", "", 1))
            else:
                context += f"\n\n[Session Context - {sk['name']}]:\n{sk['content']}"

    # Get project instructions
    proj_col = get_collection("gpt_projects")
    project = await proj_col.find_one({"_id": ObjectId(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="GPT Project not found")
    instructions = project.get("instruction", "You are a helpful assistant.")
    
    # 2. Generate AI Response
    ai_msg = await generate_ai_response(instructions, context, user_message, conv["messages"], images=session_images if session_images else None)
    
    # 3. Save to History
    new_messages = conv["messages"]
    new_messages.append({"role": "user", "content": user_message, "timestamp": datetime.utcnow()})
    new_messages.append({"role": "assistant", "content": ai_msg, "timestamp": datetime.utcnow()})
    
    await conv_col.update_one(
        {"_id": conv["_id"]}, 
        {"$set": {"messages": new_messages, "updated_at": datetime.utcnow()}}
    )
    
    return {"answer": ai_msg}

@router.get("/chat/sessions/{session_id}/history")
async def get_session_history(session_id: str, current_user: dict = Depends(get_current_user)):
    conv_col = get_collection("gpt_conversations")
    # Strict privacy: filter by user_id
    conv = await conv_col.find_one({"_id": ObjectId(session_id), "user_id": str(current_user["_id"])})
    if not conv:
        raise HTTPException(status_code=404, detail="Session not found or access denied")
    return {"messages": conv["messages"]}

@router.delete("/chat/sessions/{session_id}")
async def delete_gpt_session(session_id: str, current_user: dict = Depends(get_current_user)):
    conv_col = get_collection("gpt_conversations")
    # Strict privacy check
    res = await conv_col.delete_one({"_id": ObjectId(session_id), "user_id": str(current_user["_id"])})
    if res.deleted_count == 0:
         raise HTTPException(status_code=404, detail="Session not found or access denied")
    return {"message": "Session deleted"}

@router.patch("/chat/sessions/{session_id}/rethink")
async def rethink_gpt_session(session_id: str, payload: dict, current_user: dict = Depends(get_current_user)):
    message_idx = payload.get("index") # Index of the message to rethink from
    new_content = payload.get("content")
    if message_idx is None or new_content is None:
        raise HTTPException(status_code=400, detail="Index and content required")

    conv_col = get_collection("gpt_conversations")
    conv = await conv_col.find_one({"_id": ObjectId(session_id), "user_id": str(current_user["_id"])})
    if not conv:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = conv["messages"]
    if message_idx >= len(messages):
        raise HTTPException(status_code=400, detail="Invalid message index")

    # Truncate conversation from the edited message
    truncated_messages = messages[:message_idx]
    
    # 1. RAG and AI generation with the NEW content
    from app.services.gpt_service import get_relevant_context, generate_ai_response
    context = await get_relevant_context(conv["project_id"], new_content)
    session_images = []
    if conv.get("session_knowledge"):
        for sk in conv["session_knowledge"]:
            if sk["content"].startswith("[IMAGE_BASE64]"):
                session_images.append(sk["content"].replace("[IMAGE_BASE64]", "", 1))
            else:
                context += f"\n\n[Session Context - {sk['name']}]:\n{sk['content']}"
    
    # Get project instructions
    proj_col = get_collection("gpt_projects")
    project = await proj_col.find_one({"_id": ObjectId(conv["project_id"])})
    instructions = project.get("instruction", "You are a helpful assistant.")
    
    # 2. Generate new response
    ai_msg = await generate_ai_response(instructions, context, new_content, truncated_messages, images=session_images if session_images else None)
    
    # Update messages
    truncated_messages.append({"role": "user", "content": new_content, "timestamp": datetime.utcnow()})
    truncated_messages.append({"role": "assistant", "content": ai_msg, "timestamp": datetime.utcnow()})
    
    await conv_col.update_one(
        {"_id": conv["_id"]}, 
        {"$set": {"messages": truncated_messages, "updated_at": datetime.utcnow()}}
    )
    
    return {"answer": ai_msg, "messages": truncated_messages}

@router.post("/chat/sessions/{session_id}/upload")
async def upload_session_context(
    session_id: str, 
    file: UploadFile = File(...), 
    current_user: dict = Depends(get_current_user)
):
    # Enforce session ownership
    conv_col = get_collection("gpt_conversations")
    conv = await conv_col.find_one({"_id": ObjectId(session_id), "user_id": str(current_user["_id"])})
    if not conv:
         raise HTTPException(status_code=404, detail="Session access denied")

    # This file is temporary and scoped ONLY to this chat conversation
    # We'll extract text and append it to the chat as a system context or hidden message 
    # Or store it in a temporary session knowledge base.
    
    tmp_path = os.path.join(tempfile.gettempdir(), f"session_kb_{session_id}_{file.filename}")
    try:
        async with aiofiles.open(tmp_path, 'wb') as out_file:
            while chunk := await file.read():
                await out_file.write(chunk)
                
        from app.services.gpt_service import extract_text_from_file
        result = await extract_text_from_file(tmp_path, file.filename)
        
        knowledge_entries = []
        
        # Store text content if available
        if result["text"]:
            knowledge_entries.append({
                "name": file.filename, 
                "content": result["text"], 
                "uploaded_at": datetime.utcnow()
            })
        
        # Store each image as a separate entry with IMAGE_BASE64 tag
        for i, img_data in enumerate(result["images"]):
            knowledge_entries.append({
                "name": f"{file.filename} (image {i+1})",
                "content": f"[IMAGE_BASE64]{img_data}",
                "uploaded_at": datetime.utcnow()
            })
        
        if knowledge_entries:
            await conv_col.update_one(
                {"_id": conv["_id"]},
                {"$push": {"session_knowledge": {"$each": knowledge_entries}}}
            )
        
        img_count = len(result["images"])
        msg = f"File {file.filename} is now available in this chat engine session."
        if img_count:
            msg += f" ({img_count} embedded image{'s' if img_count > 1 else ''} also extracted)"
        
        if os.path.exists(tmp_path): os.remove(tmp_path)
        return {"message": msg}
    except Exception as e:
        if os.path.exists(tmp_path): os.remove(tmp_path)
        raise HTTPException(status_code=500, detail=str(e))
