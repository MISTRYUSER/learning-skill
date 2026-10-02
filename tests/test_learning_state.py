import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1] / 'learning'
spec = importlib.util.spec_from_file_location('learning_state', SKILL / 'scripts/learning_state.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
BASE = datetime(2026, 10, 2, 2, tzinfo=timezone.utc)

class StateTests(unittest.TestCase):
    def setUp(self):
        self.topics = {'cache': {'knowledge_points': {'coalesce': m.new_card({'title': 'scope', 'criterion': 'independent application + transfer'})}}}
        self.errors = []
        self.number = 0

    def event(self, time=BASE, **overrides):
        self.number += 1
        e = dict(id=str(self.number), topic='cache', knowledge_point='coalesce', timestamp=time.isoformat(),
                 question_id='q'+str(self.number), scenario='scenario'+str(self.number), kind='standard',
                 assistance='none', rating=3, mastery=3, answer_summary='Actual assessed answer summary')
        e.update(overrides)
        return e

    @property
    def card(self):
        return self.topics['cache']['knowledge_points']['coalesce']

    def test_intervals_and_saturation(self):
        now = BASE
        for days in [1, 3, 7, 14, 30, 30]:
            m.record(self.topics, self.errors, self.event(now))
            due = m.parse_time(self.card['next_review'])
            self.assertEqual(due-now, timedelta(days=days))
            now = due
        self.assertEqual(self.card['review_count'], 6)
        self.assertEqual(self.card['retention_status'], 'confirmed')

    def test_immediate_recall_neither_advances_nor_postpones(self):
        m.record(self.topics, self.errors, self.event())
        original_due = self.card['next_review']
        m.record(self.topics, self.errors, self.event(BASE+timedelta(hours=1)))
        self.assertEqual(self.card['schedule_step'], 0)
        self.assertEqual(self.card['next_review'], original_due)
        self.assertEqual(self.card['retention_status'], 'unverified')

    def test_failure_shortens_interval_logs_error_and_invalidates_evidence(self):
        now = BASE
        for _ in range(4):
            m.record(self.topics, self.errors, self.event(now))
            now = m.parse_time(self.card['next_review'])
        error = dict(error_type='boundary', correct_answer='scope is per process', correction='check ownership')
        m.record(self.topics, self.errors, self.event(now, rating=1, mastery=2, error=error))
        self.assertEqual(m.parse_time(self.card['next_review'])-now, timedelta(days=1))
        self.assertEqual(self.card['schedule_step'], 0)
        self.assertEqual(self.card['evidence'], {})
        self.assertEqual(self.errors[0]['review_count'], 0)
        self.assertIsNone(self.errors[0]['resolved_at'])

    def test_duplicate_is_noop(self):
        event = self.event()
        m.record(self.topics, self.errors, event)
        before = copy.deepcopy(self.topics)
        self.assertFalse(m.record(self.topics, self.errors, event))
        self.assertEqual(self.topics, before)

    def test_mastery_requires_distinct_independent_application_transfer(self):
        with self.assertRaises(ValueError):
            m.record(self.topics, self.errors, self.event(mastery=4))
        m.record(self.topics, self.errors, self.event(kind='application'))
        with self.assertRaises(ValueError):
            m.record(self.topics, self.errors, self.event(kind='transfer', mastery=4, scenario=self.card['evidence']['application']['scenario']))
        m.record(self.topics, self.errors, self.event(kind='transfer', mastery=4))
        self.assertEqual(self.card['mastery'], 4)
        with self.assertRaises(ValueError):
            m.record(self.topics, self.errors, self.event(mastery=5))
        m.record(self.topics, self.errors, self.event(kind='complex', mastery=5))
        self.assertEqual(self.card['mastery'], 5)

    def test_assisted_success_cannot_advance_or_make_evidence(self):
        with self.assertRaises(ValueError):
            m.record(self.topics, self.errors, self.event(assistance='hint'))
        m.record(self.topics, self.errors, self.event(assistance='hint', rating=2, mastery=2))
        self.assertEqual(self.card['evidence'], {})
        self.assertEqual(self.card['schedule_step'], 0)

    def test_queue_due_errors_new_old_and_interleaving(self):
        for topic in ['agent', 'rag']:
            self.topics[topic] = {'knowledge_points': {}}
        for topic, point, age in [('cache', 'coalesce', 5), ('cache', 'timeout', 5), ('agent', 'ownership', 5), ('rag', 'old', 40)]:
            card = m.new_card({'title': point, 'criterion': 'testable'})
            card.update(mastery=2, last_review=(BASE-timedelta(days=age)).isoformat(), next_review=(BASE-timedelta(days=1)).isoformat())
            self.topics[topic]['knowledge_points'][point] = card
        queue = m.candidates(self.topics, [], BASE)
        self.assertEqual(len(queue), 4)
        self.assertNotEqual(queue[0]['topic'], queue[1]['topic'])
        self.assertEqual(queue[0]['priority_group'], 0)
        self.card.update(mastery=5, next_review=(BASE+timedelta(days=30)).isoformat(), last_review=BASE.isoformat())
        self.assertFalse(any(c['knowledge_point']=='coalesce' for c in m.candidates(self.topics, [], BASE)))

    def test_fsrs_and_naive_time_rejected(self):
        with self.assertRaises(ValueError):
            m.parse_time('2026-10-02T10:00:00')
        self.card['fsrs']['engine'] = 'external'
        with self.assertRaises(ValueError):
            m.record(self.topics, self.errors, self.event())

    def test_cli_init_record_queue_reset_and_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'state'
            def cli(*args):
                return subprocess.run(['python3', str(SKILL/'scripts/learning_state.py'), '--root', str(root), '--now', BASE.isoformat(), *args], check=True, capture_output=True, text=True)
            cli('init')
            point = Path(directory)/'point.json'
            point.write_text(json.dumps({'title':'scope','criterion':'application and transfer'}))
            cli('put','cache','coalesce',str(point))
            cli('put','agent','ownership',str(point))
            event = Path(directory)/'event.json'
            event.write_text(json.dumps(self.event()))
            cli('record',str(event))
            result = json.loads(cli('queue').stdout)
            self.assertEqual(result, [])
            cli('reset','cache')
            topics = json.loads((root/'topics.json').read_text())
            self.assertEqual(topics['cache']['knowledge_points']['coalesce']['mastery'], 0)
            self.assertIn('agent', topics)
            self.assertEqual(len(list((root/'sessions').glob('reset-*.json'))),1)
            m.atomic(root/'.pending.json',m.dump({'review_queue.json':m.dump({'recovered':True})}))
            cli('queue')
            self.assertEqual(json.loads((root/'review_queue.json').read_text()),{'recovered':True})
            self.assertFalse((root/'.pending.json').exists())

if __name__ == '__main__':
    unittest.main()
