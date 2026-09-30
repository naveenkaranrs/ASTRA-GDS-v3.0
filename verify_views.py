import os

with open('static/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

checks = {
    'view-mission-console exists': 'id="view-mission-console"' in html,
    'view-hardware-testbed exists': 'id="view-hardware-testbed"' in html,
    'view-payload-ops exists': 'id="view-payload-ops"' in html,
    'print-flight-sheet exists': 'id="print-flight-sheet"' in html,
    'src-btn-twin exists': 'id="src-btn-twin"' in html,
    'src-btn-hil exists': 'id="src-btn-hil"' in html,
    'src-btn-tle exists': 'id="src-btn-tle"' in html,
    'p3-view-validation exists': 'id="p3-view-validation"' in html,
    'p3-view-sustainability exists': 'id="p3-view-sustainability"' in html,
    'btn-test-hil-closed-loop exists': 'id="btn-test-hil-closed-loop"' in html,
    'row-maneuver-a exists': 'id="row-maneuver-a"' in html,
    'row-maneuver-b exists': 'id="row-maneuver-b"' in html,
    'row-maneuver-c exists': 'id="row-maneuver-c"' in html,
    'val-cm-tp exists': 'id="val-cm-tp"' in html,
    'sust-decay-years exists': 'id="sust-decay-years"' in html,
    'engine label updated': 'PREDICTIVE HEALTH & DECISION ENGINE v3.0 (ML-ENHANCED)' in html,
}

all_passed = True
for name, res in checks.items():
    print(f"[{'PASS' if res else 'FAIL'}] {name}")
    if not res:
        all_passed = False

if all_passed:
    print("\n>>> ALL 16 VIEW & ELEMENT CHECKS PASSED! <<<")
else:
    print("\n>>> SOME CHECKS FAILED! <<<")
