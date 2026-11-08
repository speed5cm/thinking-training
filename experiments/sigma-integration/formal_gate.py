#!/usr/bin/env python3
"""Prototype for isolated verification only; not an atomic authorization boundary."""
import argparse
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import learning_evidence as e

def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['check', 'start'])
    p.add_argument('--learner', required=True)
    p.add_argument('--concept', required=True, choices=['C01', 'C02'])
    a = p.parse_args()
    try:
        rec = e.recommend(a.learner)
        if rec['concept'] != a.concept or rec['action'] not in ('collect_or_reinforce', 'consider_next'):
            print('BLOCKED: ' + rec['reason'], file=sys.stderr); return 1
        e.coach.gate(a.concept)
        e.coach.load_card(e.coach.MODES[a.concept][0], a.concept)
        if a.action == 'check':
            print('ALLOWED: formal gate checked; recheck at point of use'); return 0
        # Separate processes introduce a race; direct coach calls can bypass this wrapper.
        return subprocess.call([sys.executable, str(ROOT / 'pilot-c01-c02/scripts/coach.py'), 'start', '--learner', a.learner, '--mode', a.concept])
    except (e.EvidenceError, e.coach.Stop, e.roadmap.Invalid, OSError, ValueError, KeyError, TypeError) as exc:
        print('BLOCKED: ' + str(exc), file=sys.stderr); return 1

if __name__ == '__main__': sys.exit(main())
