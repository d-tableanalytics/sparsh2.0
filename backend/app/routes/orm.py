from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from app.db.mongodb import get_collection
from app.models.orm import ORMTemplate, ORMAssignment, ORMAchievement, ORMScoreSummary, FormulaType
from app.controllers.auth_controller import get_current_active_user
from app.services.orm_service import calculate_kpi_score, calculate_weighted_score, flatten_orm_structure
from bson import ObjectId
from datetime import datetime

router = APIRouter(prefix="/orm", tags=["ORM"])

# ─── Templates (Admin Only) ───

@router.post("/templates", response_model=ORMTemplate)
async def create_template(template: ORMTemplate, current_user: dict = Depends(get_current_active_user)):
    if current_user["role"] != "clientadmin":
        raise HTTPException(status_code=403, detail="Only Client Admins can create ORM templates")
    
    template_dict = template.model_dump()
    template_dict["company_id"] = current_user["company_id"]
    template_dict["created_at"] = datetime.utcnow()
    template_dict["updated_at"] = datetime.utcnow()
    
    result = await get_collection("orm_templates").insert_one(template_dict)
    template_dict["_id"] = str(result.inserted_id)
    return template_dict

@router.delete("/templates/{template_id}")
async def delete_template(template_id: str, current_user: dict = Depends(get_current_active_user)):
    if current_user["role"] != "clientadmin":
        raise HTTPException(status_code=403, detail="Only Client Admins can delete ORM templates")
    
    result = await get_collection("orm_templates").delete_one({
        "_id": ObjectId(template_id),
        "company_id": current_user["company_id"]
    })
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Template not found or not authorized")
        
    return {"message": "Template deleted successfully"}

@router.patch("/templates/{template_id}")
async def update_template(template_id: str, updates: dict, current_user: dict = Depends(get_current_active_user)):
    if current_user["role"] != "clientadmin":
        raise HTTPException(status_code=403, detail="Only Client Admins can update ORM templates")
    
    if not ObjectId.is_valid(template_id):
        raise HTTPException(status_code=400, detail="Invalid Template ID")
    
    # Filter out restricted fields
    forbidden = ["_id", "company_id", "created_at"]
    filtered_updates = {k: v for k, v in updates.items() if k not in forbidden}
    filtered_updates["updated_at"] = datetime.utcnow()
    
    await get_collection("orm_templates").update_one(
        {"_id": ObjectId(template_id), "company_id": current_user["company_id"]},
        {"$set": filtered_updates}
    )
    
    return {"message": "Template updated successfully"}

@router.get("/templates", response_model=List[ORMTemplate])
async def list_templates(current_user: dict = Depends(get_current_active_user)):
    # Staff can also view reports/templates
    query = {"company_id": current_user["company_id"]}
    if current_user["role"] in ["superadmin", "admin"]:
        query = {} # Superadmins can see all
        
    cursor = get_collection("orm_templates").find(query)
    templates = await cursor.to_list(length=100)
    for t in templates:
        t["_id"] = str(t["_id"])
    return templates

# ─── Assignments ───

@router.post("/assignments", response_model=ORMAssignment)
async def create_assignment(assignment: ORMAssignment, current_user: dict = Depends(get_current_active_user)):
    if current_user["role"] != "clientadmin":
        raise HTTPException(status_code=403, detail="Only Client Admins can assign ORM templates")
    
    assignment_dict = assignment.model_dump()
    assignment_dict["company_id"] = current_user["company_id"]
    assignment_dict["created_at"] = datetime.utcnow()
    
    result = await get_collection("orm_assignments").insert_one(assignment_dict)
    assignment_dict["_id"] = str(result.inserted_id)
    return assignment_dict

@router.get("/assignments")
async def list_assignments(template_id: Optional[str] = None, current_user: dict = Depends(get_current_active_user)):
    query = {"company_id": current_user["company_id"]}
    if template_id:
        query["template_id"] = template_id
        
    cursor = get_collection("orm_assignments").find(query)
    assignments = await cursor.to_list(length=100)
    for a in assignments:
        a["_id"] = str(a["_id"])
    return assignments

# ─── Achievements & Scores ───

@router.post("/achievements")
async def submit_achievement(achievement: ORMAchievement, current_user: dict = Depends(get_current_active_user)):
    # Learners (clientuser) or ClientAdmins can submit
    if current_user["role"] not in ["clientadmin", "clientuser"]:
        raise HTTPException(status_code=403, detail="Not authorized to submit achievements")
    
    # 1. Verify Assignment & Template
    assignment_id = achievement.assignment_id
    assignment = None
    
    if assignment_id.startswith("virtual_"):
        template_id = assignment_id.replace("virtual_", "")
        new_assign = {
            "template_id": template_id,
            "company_id": current_user["company_id"],
            "start_date": datetime.utcnow(),
            "is_active": True,
            "created_at": datetime.utcnow()
        }
        result = await get_collection("orm_assignments").insert_one(new_assign)
        assignment_id = str(result.inserted_id)
        achievement.assignment_id = assignment_id 
        assignment = new_assign
        assignment["_id"] = result.inserted_id
    else:
        try:
            assignment = await get_collection("orm_assignments").find_one({"_id": ObjectId(assignment_id)})
        except:
            raise HTTPException(status_code=400, detail="Invalid Assignment ID format")

    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
        
    template = await get_collection("orm_templates").find_one({"_id": ObjectId(assignment["template_id"])})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
        
    # 2. Find KPI in Template and Calculate Score
    # Use flattened structure for easier lookup
    flat_kpis = flatten_orm_structure(template["structure"])
    kpi = next((k for k in flat_kpis if k["path"] == achievement.kpi_id), None)
    
    if not kpi:
        raise HTTPException(status_code=400, detail=f"KPI {achievement.kpi_id} not found in template")
        
    # ─── Permission Check ───
    user_id = str(current_user["_id"])
    is_client_admin = current_user["role"] == "clientadmin"
    
    # If explicitly restricted
    if kpi.get("allowed_fillers") and user_id not in kpi["allowed_fillers"] and not is_client_admin:
        raise HTTPException(status_code=403, detail="Not authorized to fill this KPI")
        
    # For Team Engagement (Anonymous), everyone can fill
    if kpi.get("is_anonymous"):
        # We don't block, but we might want to prevent double-submission
        # (For simplicity, we'll allow it for now)
        pass

    # Use provided target_value or fallback to template default
    target = achievement.target_value or kpi.get("target_value", 0)
    score = calculate_kpi_score(achievement.actual_value, target, FormulaType(kpi["formula_type"]))
    weighted_contrib = calculate_weighted_score(score, kpi["weightage"])
    
    # 3. Save Achievement
    achievement_dict = achievement.model_dump()
    # Handle Anonymity
    if kpi.get("is_anonymous"):
        achievement_dict["learner_id"] = "anonymous"
        achievement_dict["submitted_by"] = "anonymous"
    else:
        achievement_dict["submitted_by"] = user_id
        
    achievement_dict["score"] = score
    achievement_dict["weighted_contribution"] = weighted_contrib
    achievement_dict["timestamp"] = datetime.utcnow()
    
    await get_collection("orm_achievements").insert_one(achievement_dict)
    
    # 4. Update Summary Score (Aggregated)
    # If anonymous, we update the "company" level or "batch" level summary
    await update_orm_summary(achievement.learner_id if not kpi.get("is_anonymous") else "org", 
                           achievement.assignment_id, achievement.period)
    
    return {
        "message": "Achievement submitted successfully",
        "calculated_score": score,
        "weighted_contribution": weighted_contrib
    }

async def update_orm_summary(learner_id: str, assignment_id: str, period: str):
    """Aggregate all achievements for a learner/period and update ORMScoreSummary."""
    achievements_cursor = get_collection("orm_achievements").find({
        "learner_id": learner_id,
        "assignment_id": assignment_id,
        "period": period
    })
    achievements = await achievements_cursor.to_list(length=100)
    
    total_score = sum(a.get("weighted_contribution", 0) for a in achievements)
    
    summary = {
        "learner_id": learner_id,
        "assignment_id": assignment_id,
        "period": period,
        "total_score": round(total_score, 2),
        "updated_at": datetime.utcnow()
    }
    
    await get_collection("orm_scores").update_one(
        {"learner_id": learner_id, "assignment_id": assignment_id, "period": period},
        {"$set": summary},
        upsert=True
    )

@router.get("/dashboard")
async def get_orm_dashboard(learner_id: Optional[str] = None, current_user: dict = Depends(get_current_active_user)):
    target_id = learner_id or str(current_user["_id"])
    
    # Verify access
    try:
        user_id = str(current_user["_id"])
        company_id = current_user["company_id"]
        is_client_admin = current_user["role"] == "clientadmin"
        
        # 1. Fetch all active templates for the company
        templates_cursor = get_collection("orm_templates").find({
            "company_id": company_id,
            "is_active": True
        })
        templates = await templates_cursor.to_list(length=100)
        
        # 2. Fetch all assignments for the company to link them
        assignments_cursor = get_collection("orm_assignments").find({"company_id": company_id})
        assignments = await assignments_cursor.to_list(length=200)
        assignment_map = {a["template_id"]: a for a in assignments}
        
        results = []
        
        def filter_structure(nodes, uid, is_admin):
            filtered = []
            for node in nodes:
                viewers = node.get("allowed_viewers") or []
                fillers = node.get("allowed_fillers") or []
                
                # Process children first
                filtered_children = []
                if node.get("children"):
                    filtered_children = filter_structure(node["children"], uid, is_admin)
                
                # Check direct access
                directly_accessible = (uid in viewers) or (uid in fillers) or is_admin
                
                if directly_accessible or filtered_children:
                    # Clone node to avoid modifying original template in memory if cached
                    new_node = node.copy()
                    if node.get("children"):
                        new_node["children"] = filtered_children
                    filtered.append(new_node)
            return filtered

        for template in templates:
            # Recursive filter
            filtered_structure = filter_structure(template.get("structure", []), user_id, is_client_admin)
            
            if filtered_structure:
                # Find assignment or create a virtual one
                assign = assignment_map.get(str(template["_id"]))
                assign_id = str(assign["_id"]) if assign else f"virtual_{template['_id']}"
                
                # Get latest summary if exists
                summary = await get_collection("orm_summaries").find_one({
                    "learner_id": learner_id or user_id,
                    "template_id": str(template["_id"])
                })
                
                results.append({
                    "assignment_id": assign_id,
                    "template_id": str(template["_id"]),
                    "template_name": template["name"],
                    "structure": filtered_structure,
                    "current_score": summary.get("total_score", 0) if summary else 0
                })
                
        return results
    except Exception as e:
        print(f"ORM Dashboard error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
