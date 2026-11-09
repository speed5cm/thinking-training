#!/usr/bin/env python3
"""Maintain one existing human-reviewed card record under the publication lock."""
import argparse
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile

import coach


def maintain(action, qid, actor, note):
    if not actor.strip() or not note.strip():
        raise coach.Stop('须提供执行人的身份和操作原因')
    card_path = coach.card_path(qid)
    with (coach.ROOT / '.publication.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        card = coach.json_read(card_path)
        version = card.get('version', '')
        if not isinstance(version, str) or not coach.re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', version) or '..' in version:
            raise coach.Stop('题卡版本无效')
        review_path = coach.ROOT / 'reviews' / (qid + '@' + version + '.json')
        review = coach.json_read(review_path)
        states = [x.get('state') for x in review.get('transitions', [])]
        if action == 'publish':
            if states != ['verified', 'approved']:
                raise coach.Stop('仅可发布已验证和人工批准、尚未发布的版本')
        elif states != ['verified', 'approved', 'published']:
            raise coach.Stop('仅可撤销当前已发布版本')
        transition = {'state':'published' if action == 'publish' else 'revoked', 'actor_type':'human',
                      'actor':actor, 'time':dt.datetime.now(dt.timezone.utc).isoformat(), 'note':note}
        if action == 'revoke':
            coach.load_card(qid)
        else:
            # Apply the exact existing card gate to the proposed complete review before writing.
            proposed = {**review, 'transitions':review['transitions'] + [transition]}
            original_read = coach.json_read
            def read_with_proposal(path):
                return proposed if Path(path) == review_path else original_read(path)
            coach.json_read = read_with_proposal
            try: coach.load_card(qid)
            finally: coach.json_read = original_read
        review['transitions'].append(transition)
        fd, temporary = tempfile.mkstemp(dir=review_path.parent, prefix='.review-')
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(review, f, ensure_ascii=False, indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
            os.replace(temporary, review_path)
            fd = os.open(review_path.parent, os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
        return {'card_id':qid, 'version':version, 'status':transition['state'], 'sha256':review['content_sha256']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('publish', 'revoke'))
    p.add_argument('--card', required=True)
    args = p.parse_args()
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict) or set(data) != {'actor', 'note'} or any(not isinstance(data[k], str) for k in data):
            raise coach.Stop('标准输入须提供 actor 和 note')
        print(json.dumps(maintain(args.action, args.card, data['actor'], data['note']), ensure_ascii=False))
    except (coach.Stop, OSError, ValueError, KeyError, TypeError) as exc:
        print('停止：' + str(exc), file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
