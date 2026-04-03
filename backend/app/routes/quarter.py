from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from app.db.mongodb import get_collection
from app.models.quarter import QuarterCreate, QuarterUpdate
from app.controllers.auth_controller import get_current_user
from bson import ObjectId
from datetime import datetime

router = APIRouter(prefix="/quarters", tags=["Quarters"])

# ─── Create Quarter ───
@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_quarter(quarter: QuarterCreate, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["superadmin", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    quarters_col = get_collection("quarters")
    batches_col = get_collection("batches")
    
    # Verify batch exists
    if not await batches_col.find_one({"_id": ObjectId(quarter.batch_id)}):
         raise HTTPException(status_code=404, detail="Batch not found")
         
    quarter_dict = quarter.model_dump()
    quarter_dict["status"] = "active"
    quarter_dict["created_at"] = datetime.utcnow()
    
    # Clean empty strings
    for k in ["description", "start_date", "target_end_date"]:
        if not quarter_dict.get(k):
            quarter_dict[k] = None
            
    result = await quarters_col.insert_one(quarter_dict)
    quarter_dict["_id"] = str(result.inserted_id)
    return quarter_dict

# ─── List Quarters for a Batch ───
# ─── List Quarters ───
@router.get("/")
async def list_quarters(batch_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    quarters_col = get_collection("quarters")
    query = {}
    if batch_id:
        query["batch_id"] = batch_id
        
    quarters = await quarters_col.find(query).sort("created_at", 1).to_list(1000)
    for q in quarters:
        q["_id"] = str(q["_id"])
    return quarters

# ─── Get Single Quarter ───
@router.get("/{quarter_id}")
async def get_quarter(quarter_id: str, current_user: dict = Depends(get_current_user)):
    quarters_col = get_collection("quarters")
    quarter = await quarters_col.find_one({"_id": ObjectId(quarter_id)})
    if not quarter:
        raise HTTPException(status_code=404, detail="Quarter not found")
    quarter["_id"] = str(quarter["_id"])
    return quarter

# ─── Update Quarter ───
@router.put("/{quarter_id}")
async def update_quarter(quarter_id: str, updates: QuarterUpdate, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["superadmin", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    quarters_col = get_collection("quarters")
    update_data = {k: v for k, v in updates.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
        
    update_data["updated_at"] = datetime.utcnow()
    result = await quarters_col.update_one({"_id": ObjectId(quarter_id)}, {"$set": update_data})
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Quarter not found")
    return {"message": "Quarter updated"}

# ─── Delete Quarter ───
@router.delete("/{quarter_id}")
async def delete_quarter(quarter_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["superadmin", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    quarters_col = get_collection("quarters")
    result = await quarters_col.delete_one({"_id": ObjectId(quarter_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Quarter not found")
    return {"message": "Quarter deleted"}
