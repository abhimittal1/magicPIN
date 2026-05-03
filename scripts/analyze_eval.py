import json
from collections import defaultdict

with open("expanded-evaluation.jsonl") as f:
    rows = [json.loads(line) for line in f if line.strip()]

by_kind = defaultdict(list)
for r in rows:
    kind = r.get("trigger_kind", "unknown")
    by_kind[kind].append(r)

print("Trigger kind summary:")
for kind, cases in sorted(by_kind.items()):
    non_empty = sum(1 for c in cases if c.get("actions"))
    print(f"  {kind}: {non_empty}/{len(cases)} non-empty actions")

empty = [r for r in rows if not r.get("actions")]
print(f"\nTotal rows with empty actions: {len(empty)}")
for r in empty[:10]:
    err = str(r.get("error", ""))[:120]
    print(f"  trigger_kind={r.get('trigger_kind')}, merchant={r.get('merchant_id')}, error={err}")
