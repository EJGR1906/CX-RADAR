import json
from pathlib import Path

brains = [
    ("probe_developer", "e02213d9-5750-4474-bb88-5f8d160f6398"),
    ("utility_developer", "3b6b6e8a-29aa-4a18-a686-fc6f7d6ff7d1"),
    ("qa_orchestration_developer", "cd5b4138-9760-4515-ab32-097cdac058e4")
]

for name, cid in brains:
    path = Path(rf"C:\Users\Eduar\.gemini\antigravity\brain\{cid}\.system_generated\logs\transcript.jsonl")
    print("=" * 60)
    print(f"Subagent: {name} ({cid})")
    if not path.exists():
        print("Does not exist")
        continue
    
    lines = path.read_text(encoding="utf-8").splitlines()
    print(f"Total steps: {len(lines)}")
    
    # Check if there are any lines with status ERROR or system notifications
    for idx, line in enumerate(lines):
        try:
            step = json.loads(line)
            if step.get('status') == 'ERROR' or step.get('source') == 'SYSTEM' or 'error' in line.lower():
                print(f"  Step {step.get('step_index')} | Source: {step.get('source')} | Type: {step.get('type')} | Status: {step.get('status')}")
                print(f"    Raw content snippet: {line[:200]}")
        except Exception as e:
            pass
