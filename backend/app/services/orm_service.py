from typing import List, Dict, Any
from app.models.orm import FormulaType, ORMNode

def calculate_kpi_score(actual: float, target: float, formula: FormulaType) -> float:
    if target == 0:
        return 0.0
    
    score = 0.0
    if formula == FormulaType.STANDARD:
        score = (actual / target) * 100
    elif formula == FormulaType.REVERSE:
        score = (target / actual) * 100 if actual != 0 else 0.0
    
    # Capped at 100% as per requirements
    return min(100.0, score)

def calculate_weighted_score(score: float, weightage: float) -> float:
    return (score * weightage) / 100.0

def validate_total_weightage(nodes: List[ORMNode], expected_total: float = 100.0) -> bool:
    total = sum(node.weightage for node in nodes)
    return abs(total - expected_total) < 0.01

def flatten_orm_structure(nodes: List[ORMNode], parent_path: str = "") -> List[Dict[str, Any]]:
    """Flatten the recursive structure for easier database storage/retrieval of specific KPIs."""
    flat_list = []
    for node in nodes:
        current_path = f"{parent_path}.{node.name}" if parent_path else node.name
        if not node.children:
            flat_list.append({
                "name": node.name,
                "path": current_path,
                "weightage": node.weightage,
                "formula_type": node.formula_type,
                "target_value": node.target_value,
                "unit": node.unit
            })
        else:
            flat_list.extend(flatten_orm_structure(node.children, current_path))
    return flat_list
