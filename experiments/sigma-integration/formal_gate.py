#!/usr/bin/env python3
"""Prototype for isolated verification only; not an atomic authorization boundary."""
import argparse
import fcntl
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import learning_evidence as e

def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['check'])
    p.add_argument('--learner', required=True)
    p.add_argument('--concept', required=True)
    a = p.parse_args()
    try:
        import concept_authorization as authorization
        if not authorization.synthetic_learner(a.learner):
            print('BLOCKED: 仅允许隔离合成数据', file=sys.stderr); return 1
        folder = e.get_folder(a.learner)
        with (e.coach.ROOT / '.publication.lock').open('a') as pub, (folder / '.lock').open('a') as lock:
            fcntl.flock(pub, fcntl.LOCK_SH); fcntl.flock(lock, fcntl.LOCK_SH)
            e.authorize_concept_locked(a.learner, a.concept)
        print('ALLOWED: synthetic precheck; session commit rechecks at use'); return 0
    except (e.EvidenceError, e.coach.Stop, e.roadmap.Invalid, OSError, ValueError, KeyError, TypeError) as exc:
        print('BLOCKED: ' + str(exc), file=sys.stderr); return 1

if __name__ == '__main__': sys.exit(main())
