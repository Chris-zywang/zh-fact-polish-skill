"""Select a completed guard snapshot without changing any generated text."""
import json
from pathlib import Path

def select_best(directory, rounds):
    candidates=[]
    for item in rounds:
        number=item["round"]; report=Path(directory)/f"round{number}_guard.json"
        output=Path(directory)/f"SK_round{number}.md"
        ledger=Path(directory)/f"round{number}_ledger.json"
        if not (report.is_file() and output.is_file() and ledger.is_file()):
            continue
        result=json.loads(report.read_text(encoding="utf8"))
        structural=not result.get("structural_passed",False)
        questionable=result.get("questionable_fact_count",0)
        pending=result.get("pending_fact_count",0)+result.get("manual_review_count",0)
        # Structure and explicitly contradictory findings take priority over pending counts.
        candidates.append(((structural,questionable,pending,number),item))
    return min(candidates,key=lambda x:x[0])[1] if candidates else None
