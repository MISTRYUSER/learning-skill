import copy
from datetime import timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from test_learning_state import BASE, SKILL, m

class VerifiedMasteryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'state'
        self.root.mkdir()
        self.topics = {'cache': {'knowledge_points': {'coalesce': m.new_card({'title':'scope','criterion':'independent application and transfer'})}}}
        self.topics['cache']['knowledge_points']['coalesce']['mastery'] = 3
        self.errors = [{'id':'old-error','topic':'cache','knowledge_point':'coalesce','user_answer':'one global map across processes','correct_answer':'scope is per process','error_type':'boundary','correction':'identify ownership','timestamp':BASE.isoformat(),'review_count':0,'last_review':BASE.isoformat(),'next_review':(BASE+timedelta(days=1)).isoformat(),'mastery':3,'resolved_at':None}]
        self.save()

    def save(self):
        (self.root/'topics.json').write_text(json.dumps(self.topics))
        (self.root/'error_log.jsonl').write_text(m.lines(self.errors))

    def cli(self,*args):
        return subprocess.run([sys.executable,str(SKILL/'scripts/learning_state.py'),'--root',str(self.root),'--now',BASE.isoformat(),*args],capture_output=True,text=True)

    def event(self,identifier,kind,mastery=3,**kwargs):
        value=dict(id=identifier,topic='cache',knowledge_point='coalesce',timestamp=BASE.isoformat(),question_id='q-'+identifier,scenario='scenario-'+identifier,kind=kind,assistance='none',rating=3,mastery=mastery,answer_summary='fixture answer: independently handles scope and failure')
        value.update(kwargs)
        return value

    def test_self_rating_changes_only_self_report_not_verified_state(self):
        before=copy.deepcopy(self.topics)
        result=self.cli('self-rate','cache','coalesce','4','--note','用户自报懂了')
        self.assertEqual(result.returncode,0,result.stderr)
        after=json.loads((self.root/'topics.json').read_text())
        card=after['cache']['knowledge_points']['coalesce']
        self.assertEqual(card['self_reported']['level'],4)
        card.pop('self_reported')
        self.assertEqual(after,before)
        self.assertEqual([json.loads(x) for x in (self.root/'error_log.jsonl').read_text().splitlines()],self.errors)

    def test_queue_rejects_manual_level_four_without_evidence_and_preserves_file(self):
        self.topics['cache']['knowledge_points']['coalesce']['mastery']=4
        self.save()
        before=(self.root/'topics.json').read_bytes()
        result=self.cli('queue')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('evidence',result.stderr)
        self.assertEqual((self.root/'topics.json').read_bytes(),before)

    def test_queue_rejects_closed_error_without_resolution_evidence(self):
        self.errors[0]['resolved_at']=BASE.isoformat()
        self.errors[0]['mastery']=4
        self.save()
        result=self.cli('queue')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('evidence',result.stderr)

    def test_queue_rejects_forged_evidence_not_supported_by_history(self):
        card=self.topics['cache']['knowledge_points']['coalesce']
        card['mastery']=4
        card['evidence']={'application':{'id':'a','question_id':'q-a','scenario':'s-a'},'transfer':{'id':'t','question_id':'q-t','scenario':'s-t'}}
        self.save()
        self.assertNotEqual(self.cli('queue').returncode,0)

    def test_valid_resolution_remains_valid_after_later_lapse(self):
        m.record(self.topics,self.errors,self.event('a','application'))
        m.record(self.topics,self.errors,self.event('t','transfer',4))
        self.save()
        self.assertEqual(self.cli('validate').returncode,0)
        self.assertIn('resolution_evidence',self.errors[0])
        m.record(self.topics,self.errors,self.event('fail','recall',2,rating=1,error={'error_type':'memory','correct_answer':'per process','correction':'rebuild ownership'}))
        self.save()
        self.assertEqual(self.cli('validate').returncode,0)
        self.assertIsNotNone(self.errors[0]['resolved_at'])
        self.assertIsNone(self.errors[-1]['resolved_at'])

    def test_closed_new_error_cannot_reuse_old_resolution_proof(self):
        m.record(self.topics,self.errors,self.event('a','application'))
        m.record(self.topics,self.errors,self.event('t','transfer',4))
        old_proof=copy.deepcopy(self.errors[0]['resolution_evidence'])
        m.record(self.topics,self.errors,self.event('fail','recall',2,rating=1,error={'error_type':'memory','correct_answer':'per process','correction':'rebuild ownership'}))
        self.errors[-1].update(resolved_at=BASE.isoformat(),mastery=4,resolution_evidence=old_proof)
        self.save()
        self.assertNotEqual(self.cli('queue').returncode,0)

    def test_current_mastery_cannot_reuse_evidence_invalidated_by_lapse(self):
        m.record(self.topics,self.errors,self.event('a','application'))
        m.record(self.topics,self.errors,self.event('t','transfer',4))
        old_evidence=copy.deepcopy(self.topics['cache']['knowledge_points']['coalesce']['evidence'])
        m.record(self.topics,self.errors,self.event('fail','recall',2,rating=1,error={'error_type':'memory','correct_answer':'per process','correction':'rebuild ownership'}))
        self.topics['cache']['knowledge_points']['coalesce'].update(mastery=4,evidence=old_evidence)
        self.save()
        self.assertNotEqual(self.cli('queue').returncode,0)

    def test_resolution_requires_new_application_after_lapse(self):
        m.record(self.topics,self.errors,self.event('a','application'))
        old_application=copy.deepcopy(self.topics['cache']['knowledge_points']['coalesce']['evidence']['application'])
        m.record(self.topics,self.errors,self.event('fail','recall',2,rating=1,error={'error_type':'memory','correct_answer':'per process','correction':'rebuild ownership'}))
        m.record(self.topics,self.errors,self.event('t','transfer',3))
        transfer=self.topics['cache']['knowledge_points']['coalesce']['evidence']['transfer']
        self.errors[-1].update(resolved_at=BASE.isoformat(),mastery=4,resolution_evidence={'application':old_application,'transfer':transfer})
        self.save()
        self.assertNotEqual(self.cli('validate').returncode,0)

    def test_multiple_invalid_legacy_topics_can_be_reset_one_at_a_time(self):
        self.topics['cache']['knowledge_points']['coalesce']['mastery']=4
        self.topics['legacy-other']=copy.deepcopy(self.topics['cache'])
        self.save()
        other_before=copy.deepcopy(self.topics['legacy-other'])
        first=self.cli('reset','cache')
        self.assertEqual(first.returncode,0,first.stderr)
        data=json.loads((self.root/'topics.json').read_text())
        self.assertEqual(data['legacy-other'],other_before)
        self.assertEqual(data['cache']['knowledge_points']['coalesce']['mastery'],0)
        self.assertNotEqual(self.cli('queue').returncode,0)
        self.assertEqual(self.cli('reset','legacy-other').returncode,0)
        self.assertEqual(self.cli('validate').returncode,0)
        self.assertEqual(len(list((self.root/'sessions').glob('reset-*.json'))),2)

    def test_success_history_with_hint_cannot_support_level_four(self):
        m.record(self.topics,self.errors,self.event('a','application'))
        m.record(self.topics,self.errors,self.event('t','transfer',4))
        self.topics['cache']['knowledge_points']['coalesce']['history'][0]['assistance']='hint'
        self.save()
        self.assertNotEqual(self.cli('queue').returncode,0)

if __name__=='__main__':
    unittest.main()
