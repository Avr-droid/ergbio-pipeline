import os

def validate_file(file_path: str) -> dict:
    """
    Validates that a file exists and is readable.
    Returns a dict with valid=True/False and a reason.
    """
    if not os.path.exists(file_path):
        return {"valid": False, "reason": "File does not exist"}
    
    if not file_path.endswith(('.xlsx', '.csv')):
        return {"valid": False, "reason": "File must be .xlsx or .csv"}
    
    if os.path.getsize(file_path) == 0:
        return {"valid": False, "reason": "File is empty"}
    
    return {"valid": True, "reason": "File looks good"}
