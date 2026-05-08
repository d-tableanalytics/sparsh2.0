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

def flatten_orm_structure(nodes: List[Any], parent_path: str = "") -> List[Dict[str, Any]]:
    """Flatten the recursive structure for easier database storage/retrieval of specific KPIs."""
    flat_list = []
    for node in nodes:
        # Handle both Pydantic objects and raw MongoDB dictionaries
        is_dict = isinstance(node, dict)
        name = node["name"] if is_dict else node.name
        children = node.get("children", []) if is_dict else node.children
        weightage = node.get("weightage", 0) if is_dict else node.weightage
        formula_type = node.get("formula_type", "standard") if is_dict else node.formula_type
        target_value = node.get("target_value", 0) if is_dict else node.target_value
        unit = node.get("unit") if is_dict else node.unit
        allowed_fillers = node.get("allowed_fillers", []) if is_dict else node.allowed_fillers
        
        current_path = f"{parent_path}.{name}" if parent_path else name
        if not children:
            flat_list.append({
                "name": name,
                "path": current_path,
                "weightage": weightage,
                "formula_type": formula_type,
                "target_value": target_value,
                "unit": unit,
                "allowed_fillers": allowed_fillers
            })
        else:
            flat_list.extend(flatten_orm_structure(children, current_path))
    return flat_list
