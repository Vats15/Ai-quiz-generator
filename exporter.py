# exporter.py
from io import BytesIO
import pandas as pd
from typing import List, Dict, Any
import json

def questions_to_dataframe(qs: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    Convert list of question dicts into a pandas DataFrame.
    Options (list) are joined into a single string with '|' as separator.
    """
    rows = []
    for q in qs:
        row = {
            "id": q.get("id"),
            "type": q.get("type"),
            "question": q.get("question"),
            "options": "|".join(q.get("options")) if q.get("options") else None,
            "answer": q.get("answer"),
            "explanation": q.get("explanation"),
            "difficulty": q.get("difficulty"),
        }
        rows.append(row)
    return pd.DataFrame(rows)

def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    """
    Convert DataFrame to CSV bytes for Streamlit download button.
    """
    buf = BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    return buf.read()

def questions_to_json_bytes(qs: List[Dict[str, Any]]) -> bytes:
    """
    Convert question list to pretty JSON bytes for download.
    """
    b = json.dumps(qs, indent=2, ensure_ascii=False).encode("utf-8")
    return b
