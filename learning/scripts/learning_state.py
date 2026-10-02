#!/usr/bin/env python3
"""Small fixed-interval learning store. Python 3.9+, Unix; no dependencies."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import tempfile

INTERVALS = [1, 3, 7, 14, 30]
ERROR_TYPES = {'memory', 'concept', 'reasoning', 'implementation', 'boundary'}
KINDS = {'recall', 'standard', 'application', 'transfer', 'complex'}
ASSISTANCE = {'none', 'hint', 'answer_seen', 'open_book'}


def parse_time(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timestamps must include timezone')
    return result.astimezone(timezone.utc)


def dump(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def lines(values):
    return ''.join(json.dumps(v, ensure_ascii=False) + '\n' for v in values)


def atomic(path, content):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.learning-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def locked(root):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        pending = root / '.pending.json'
        if pending.exists():
            for name, content in json.loads(pending.read_text()).items():
                atomic(root / name, content)
            pending.unlink()
        yield


def read(root):
    topics = json.loads((root / 'topics.json').read_text()) if (root / 'topics.json').exists() else {}
    errors = [json.loads(line) for line in (root / 'error_log.jsonl').read_text().splitlines() if line] if (root / 'error_log.jsonl').exists() else []
    return topics, errors


def candidates(topics, errors, now):
    unresolved = {(e['topic'], e['knowledge_point']) for e in errors if not e.get('resolved_at')}
    found = []
    for topic, data in topics.items():
        for point, card in data['knowledge_points'].items():
            last = parse_time(card['last_review']) if card.get('last_review') else None
            due = parse_time(card['next_review']) if card.get('next_review') else None
            if due and due <= now:
                group = 0
            elif (topic, point) in unresolved:
                # Errors retested today wait until the following day.
                if last and now - last < timedelta(days=1):
                    continue
                group = 1
            elif card['mastery'] < 4 and last and now - last >= timedelta(days=1) and now - last <= timedelta(days=7):
                group = 2
            elif last and now - last >= timedelta(days=30):
                group = 3
            else:
                continue
            found.append({'topic': topic, 'knowledge_point': point, 'mastery': card['mastery'],
                          'next_review': card.get('next_review'), 'priority_group': group,
                          'lapses': card.get('lapses', 0)})
    found.sort(key=lambda x: (x['priority_group'], x['mastery'], -x['lapses'], x['next_review'] or '', x['topic'], x['knowledge_point']))
    # Preserve priority groups; interleave topics inside a group when possible.
    ordered = []
    while found:
        group = found[0]['priority_group']
        index = next((i for i, c in enumerate(found) if c['priority_group'] == group and (not ordered or c['topic'] != ordered[-1]['topic'])), 0)
        ordered.append(found.pop(index))
    return ordered


def commit(root, topics, errors, now):
    payload = {'topics.json': dump(topics), 'error_log.jsonl': lines(errors),
               'review_queue.json': dump({'generated_at': now.isoformat(), 'items': candidates(topics, errors, now)})}
    atomic(root / '.pending.json', dump(payload))
    for name, content in payload.items():
        atomic(root / name, content)
    (root / '.pending.json').unlink()


def new_card(spec):
    if not spec.get('title') or not spec.get('criterion'):
        raise ValueError('point requires title and criterion')
    return {'title': spec['title'], 'criterion': spec['criterion'], 'dependencies': spec.get('dependencies', []),
            'mastery': 0, 'last_review': None, 'next_review': None, 'review_count': 0,
            'schedule_step': 0, 'lapses': 0, 'retention_status': 'unverified', 'evidence': {},
            'history': [], 'fsrs': {'engine': None, 'version': None, 'state': None, 'stability': None,
                                   'difficulty': None, 'desired_retention': 0.9}}


def record(topics, errors, event):
    topic, point = event['topic'], event['knowledge_point']
    card = topics[topic]['knowledge_points'][point]
    if card.get('fsrs', {}).get('engine'):
        raise ValueError('FSRS-managed card requires its actual engine; fixed scheduler cannot overwrite it')
    if event['id'] in {x['id'] for x in card['history']}:
        return False
    now = parse_time(event['timestamp'])
    last = parse_time(card['last_review']) if card['last_review'] else None
    if last and now < last:
        raise ValueError('out-of-order assessment')
    rating = event['rating']
    mastery = event['mastery']
    if type(rating) is not int or rating not in (1, 2, 3, 4) or type(mastery) is not int or not 0 <= mastery <= 5:
        raise ValueError('rating 1..4 and mastery 0..5 required')
    kind, aid = event['kind'], event['assistance']
    if kind not in KINDS or aid not in ASSISTANCE or not event.get('answer_summary') or not event.get('question_id') or not event.get('scenario'):
        raise ValueError('real answer_summary, question_id, scenario, kind and assistance required')
    if event.get('error') and rating != 1:
        raise ValueError('substantive error requires Again rating and error logging')
    if rating == 1:
        err = event.get('error', {})
        if err.get('error_type') not in ERROR_TYPES or not err.get('correct_answer') or not err.get('correction'):
            raise ValueError('failed assessment requires a real error and correction')
        if mastery > 3:
            raise ValueError('failure cannot retain mastery >=4 for this point')
    # A successful hinted answer uses Hard; exposure to the full answer is not a pass.
    if aid != 'none' and rating > 2:
        raise ValueError('assisted answers cannot advance intervals')
    evidence = dict(card['evidence'])
    if rating == 1:
        evidence = {}
    elif aid == 'none' and rating >= 3:
        evidence[kind] = {'id': event['id'], 'question_id': event['question_id'], 'scenario': event['scenario'],
                          'timestamp': event['timestamp'], 'summary': event['answer_summary']}
    if mastery >= 4:
        app, transfer = evidence.get('application'), evidence.get('transfer')
        if not app or not transfer or app['question_id'] == transfer['question_id'] or app['scenario'] == transfer['scenario']:
            raise ValueError('mastery >=4 requires independent application and distinct transfer evidence')
        if mastery == 5 and 'complex' not in evidence:
            raise ValueError('mastery 5 requires complex variation/tradeoff evidence')
    due = parse_time(card['next_review']) if card['next_review'] else None
    was_due = bool(due and due <= now)
    step = card['schedule_step']
    if rating == 1:
        step, interval = 0, 1
        card['lapses'] += 1
        card['retention_status'] = 'unverified'
    elif rating == 2 or aid != 'none':
        interval = 1
        if was_due:
            card['retention_status'] = 'unverified'
    else:
        if was_due:
            step = min(step + 1, len(INTERVALS) - 1)
        interval = INTERVALS[step]
        if was_due:
            card['retention_status'] = 'confirmed'
    # A repeated attempt before due must not push an existing due date back.
    next_due = now + timedelta(days=interval)
    if due and not was_due:
        next_due = min(due, next_due)
    card.update(mastery=mastery, evidence=evidence, last_review=now.isoformat(), next_review=next_due.isoformat(),
                review_count=card['review_count'] + 1, schedule_step=step)
    card['history'].append({k: event[k] for k in ('id', 'timestamp', 'rating', 'kind', 'assistance', 'question_id', 'scenario', 'answer_summary')})
    for error in errors:
        if error['topic'] == topic and error['knowledge_point'] == point and not error.get('resolved_at'):
            error.update(review_count=error['review_count'] + 1, last_review=card['last_review'],
                         next_review=card['next_review'], mastery=mastery)
            if mastery >= 4 and kind == 'transfer' and aid == 'none' and rating >= 3:
                error['resolved_at'] = now.isoformat()
    if rating == 1:
        err = event['error']
        errors.append({'id': event['id'], 'topic': topic, 'knowledge_point': point,
                       'user_answer': event['answer_summary'], 'correct_answer': err['correct_answer'],
                       'error_type': err['error_type'], 'correction': err['correction'], 'timestamp': now.isoformat(),
                       'review_count': 0, 'last_review': now.isoformat(), 'next_review': card['next_review'],
                       'mastery': mastery, 'resolved_at': None})
    return True


def main():
    p = argparse.ArgumentParser(description=__doc__)
    default = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'learning'
    p.add_argument('--root', type=Path, default=default)
    p.add_argument('--now', help='timezone-aware ISO time; omitted = actual UTC time')
    s = p.add_subparsers(dest='command', required=True)
    s.add_parser('init')
    put = s.add_parser('put'); put.add_argument('topic'); put.add_argument('point'); put.add_argument('spec', type=Path)
    rec = s.add_parser('record'); rec.add_argument('event', type=Path)
    queue = s.add_parser('queue'); queue.add_argument('--limit', type=int, default=5)
    reset = s.add_parser('reset'); reset.add_argument('topic')
    a = p.parse_args()
    now = parse_time(a.now) if a.now else datetime.now(timezone.utc)
    with locked(a.root):
        topics, errors = read(a.root)
        if a.command == 'init':
            for name in ('sessions', 'notes'):
                (a.root / name).mkdir(exist_ok=True)
            profile = a.root / 'profile.md'
            if not profile.exists():
                template = Path(__file__).resolve().parent.parent / 'assets/profile.md'
                atomic(profile, template.read_text())
        elif a.command == 'put':
            spec = json.loads(a.spec.read_text())
            cards = topics.setdefault(a.topic, {'knowledge_points': {}})['knowledge_points']
            if a.point in cards:
                raise ValueError('point exists; edit metadata carefully, do not overwrite progress')
            cards[a.point] = new_card(spec)
        elif a.command == 'record':
            event = json.loads(a.event.read_text())
            now = parse_time(event['timestamp'])
            if not record(topics, errors, event):
                print('duplicate assessment: no changes')
                return
        elif a.command == 'reset':
            if a.topic not in topics:
                raise ValueError('unknown topic; nothing reset')
            backup = a.root / 'sessions' / ('reset-' + now.strftime('%Y%m%dT%H%M%S%f') + '.json')
            backup.parent.mkdir(exist_ok=True)
            atomic(backup, dump({'topic': a.topic, 'data': topics[a.topic], 'errors': [e for e in errors if e['topic'] == a.topic]}))
            for key, card in list(topics[a.topic]['knowledge_points'].items()):
                topics[a.topic]['knowledge_points'][key] = new_card(card)
            errors = [e for e in errors if e['topic'] != a.topic]
        elif a.command == 'queue':
            if a.limit < 1:
                raise ValueError('limit must be positive')
            print(dump(candidates(topics, errors, now)[:a.limit]), end='')
            return
        commit(a.root, topics, errors, now)
        print('saved: ' + str(a.root.resolve()))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError) as exc:
        raise SystemExit('learning state error: ' + str(exc))
