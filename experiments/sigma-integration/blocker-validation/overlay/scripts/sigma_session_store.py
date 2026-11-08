#!/usr/bin/env python3
"""Experimental single-snapshot Sigma session store; not a teaching gate."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile

import learning_evidence as evidence

class Invalid(ValueError):
    pass

def read(path):
    if not path.exists():
        return {'schema_version': 1, 'revision': 0, 'state': {}, 'session': '', 'turns': []}
    obj = json.loads(path.read_text(encoding='utf-8'))
    validate(obj)
    return obj

def validate(obj):
    if (not isinstance(obj, dict) or set(obj) != {'schema_version', 'revision', 'state', 'session', 'turns'}
        or type(obj['schema_version']) is not int or obj['schema_version'] != 1
        or type(obj['revision']) is not int or obj['revision'] < 0
        or not isinstance(obj['state'], dict) or not isinstance(obj['session'], str)
        or not isinstance(obj['turns'], list) or any(not isinstance(t, dict) for t in obj['turns'])):
        raise Invalid('会话快照格式无效')

def operate(learner, proposed=None, expected=None):
    folder = evidence.get_folder(learner)
    dest = folder / 'sigma'
    dest.mkdir(mode=0o700, exist_ok=True)
    path = dest / 'session-snapshot.json'
    with (folder / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = read(path)
        if proposed is None:
            return previous
        if type(expected) is not int or expected != previous['revision']:
            raise Invalid('会话已被更新，请重新读取后重试')
        if not isinstance(proposed, dict) or set(proposed) != {'state', 'session', 'turns'}:
            raise Invalid('提交须同时包含 state、session、turns')
        current = {'schema_version': 1, 'revision': expected + 1, **proposed}
        validate(current)
        # Previously committed turns must remain byte-for-byte equivalent in JSON data.
        if current['turns'][:len(previous['turns'])] != previous['turns']:
            raise Invalid('不能覆盖已提交的逐轮记录')
        fd, temp = tempfile.mkstemp(dir=dest, prefix='.session-')
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(current, f, ensure_ascii=False, indent=2)
                f.write('\n'); f.flush(); os.fsync(f.fileno())
            os.replace(temp, path)
            directory = os.open(dest, os.O_RDONLY)
            try: os.fsync(directory)
            finally: os.close(directory)
        finally:
            if os.path.exists(temp): os.unlink(temp)
        return current

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('read', 'commit'))
    parser.add_argument('--learner', required=True)
    parser.add_argument('--expected-revision', type=int)
    args = parser.parse_args()
    try:
        result = operate(args.learner, json.load(sys.stdin), args.expected_revision) if args.action == 'commit' else operate(args.learner)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (Invalid, evidence.EvidenceError, evidence.coach.Stop, OSError, ValueError, TypeError) as exc:
        print('停止：' + str(exc), file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
