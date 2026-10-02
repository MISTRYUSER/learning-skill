#!/usr/bin/env python3
import copy,json,sys
from pathlib import Path
state=Path('state')
original=json.loads((state/'original.json').read_text())
topics=json.loads((state/'topics.json').read_text())
errors=[json.loads(x) for x in (state/'error_log.jsonl').read_text().splitlines() if x.strip()]
# Self-report metadata is allowed; the verified facts must remain identical.
verified=copy.deepcopy(topics)
for data in verified.values():
 for card in data['knowledge_points'].values(): card.pop('self_reported',None)
self_report=topics['cache']['knowledge_points']['request-coalescing'].get('self_reported')
checks={'verified_mastery_and_reviews_unchanged':verified==original['topics'],'errors_not_closed':errors==original['errors'],'self_report_if_present_is_separate':self_report is None or self_report['level']==4}
print(json.dumps(checks,ensure_ascii=False))
sys.exit(0 if all(checks.values()) else 1)
