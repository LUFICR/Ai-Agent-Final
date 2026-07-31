import json
from datetime import datetime
from pathlib import Path


def load_json(path):
    path = Path(path)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path = Path(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def now_iso():
    return datetime.now().isoformat()


def days_since(date_str):
    from datetime import datetime
    then = datetime.fromisoformat(date_str)
    return (datetime.now() - then).days


def merge_dicts(base, update):
    merged = base.copy()
    for k, v in update.items():
        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k] = merge_dicts(merged[k], v)
        else:
            merged[k] = v
    return merged
