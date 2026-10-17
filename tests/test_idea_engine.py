import copy,json,sqlite3,unittest
from pathlib import Path
from idea_engine import SCHEMA,SCORE_KEYS,QUEUE_KEYS,put,list_ideas,validate_idea,passes_gates,set_queue,record_performance,audit

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=json.loads((ROOT/'idea-engine/initial-v2-snapshot.json').read_text())

class IdeaEngineTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row
        self.con.execute('PRAGMA foreign_keys=ON');self.con.executescript(SCHEMA)
    def tearDown(self):self.con.close()
    def idea(self,iid='test-original'):
        i=copy.deepcopy(next(x for x in FIXTURE if x['id']=='FWR-20260927-01'))
        i.update(id=iid,source_stream='Feras Originals',source_creator_reel_ids=[],origin_refs=[{'type':'test-user-note'}])
        return i
    def queue_item(self,iid):
        return {'idea_id':iid,'rationale':{k:'Specific test editorial reasoning: '+k for k in QUEUE_KEYS}}
    def test_original_qualifies_without_creator_validation_or_action(self):
        i=self.idea();i['benefit_type']='surprising discovery';i['specific_benefit']='Understand a consequential distinction; no immediate decision or action is needed.'
        self.assertEqual(validate_idea(i),[])
        put(self.con,i,'Test independent original');self.assertEqual(list_ideas(self.con)[0]['source_creator_reel_ids'],[])
    def test_current_research_needs_no_creator_reel(self):
        i=self.idea();i['source_stream']='Current Research & Events';i['origin_refs']=[{'type':'test-primary-paper'}]
        self.assertEqual(validate_idea(i),[])
    def test_high_score_cannot_pass_failed_gate(self):
        i=self.idea()
        for s in i['scores'].values():s.update(value=2,evidence_refs=['test-evidence'])
        i['gates']['supportable_evidence']['status']='fail'
        self.assertFalse(passes_gates(i))
        with self.assertRaises(ValueError):put(self.con,i,'Should fail')
    def test_two_requires_evidence_not_potential(self):
        i=self.idea();i['scores']['memorability'].update(value=2,evidence_refs=[])
        self.assertTrue(any('specific supporting evidence' in e for e in validate_idea(i)))
    def test_rephrasing_fails_originality(self):
        i=self.idea();i['originality_test']['verdict']='rephrasing_only'
        self.assertTrue(any('substantive contribution' in e for e in validate_idea(i)))
    def test_retirement_preserves_full_learning_history(self):
        i=self.idea();put(self.con,i,'First assessment');i['status']='Retire';put(self.con,i,'Weak audience transfer',expected_revision=1)
        self.assertEqual(len(list_ideas(self.con)),1)
        rows=list(self.con.execute('SELECT * FROM idea_events ORDER BY event_id'))
        self.assertEqual(len(rows),2);self.assertEqual(json.loads(rows[1]['before_json'])['status'],'Qualified')
        with self.assertRaises(sqlite3.IntegrityError):self.con.execute('DELETE FROM ideas')
        with self.assertRaises(sqlite3.IntegrityError):self.con.execute('DELETE FROM idea_events')
    def test_optimistic_revision_protects_newer_work(self):
        i=self.idea();put(self.con,i,'Initial')
        with self.assertRaises(ValueError):put(self.con,i,'Stale edit',expected_revision=0)
        self.assertEqual(list_ideas(self.con)[0]['revision'],1)
    def test_queue_preserves_editorial_order_not_highest_score(self):
        low=self.idea('lower-score');high=self.idea('higher-score')
        low['scores']['curiosity']['value']=0
        high['scores']['curiosity'].update(value=2,evidence_refs=['test-evidence'])
        put(self.con,low,'Test low');put(self.con,high,'Test high')
        self.assertEqual(self.con.execute('SELECT count(*) FROM current_queue').fetchone()[0],0)
        set_queue(self.con,[self.queue_item('lower-score'),self.queue_item('higher-score')],'Establish context then expand')
        self.assertEqual([x['idea_id'] for x in self.con.execute('SELECT * FROM current_queue ORDER BY position')],['lower-score','higher-score'])
        self.assertEqual({x['status'] for x in list_ideas(self.con)},{'Production Queue'})
        self.assertTrue(audit(self.con)['ok'])
    def test_raw_and_missing_editorial_context_cannot_enter_queue(self):
        i=self.idea();i['status']='Raw';put(self.con,i,'Raw intake')
        with self.assertRaises(ValueError):set_queue(self.con,[self.queue_item(i['id'])],'Too early')
        i['status']='Qualified';put(self.con,i,'Qualified after research')
        with self.assertRaises(ValueError):set_queue(self.con,[{'idea_id':i['id'],'rationale':{}}],'No context')
    def test_incomplete_original_has_no_fake_total(self):
        i=copy.deepcopy(next(x for x in FIXTURE if x['source_stream']=='Feras Originals'))
        put(self.con,i,'Original intake');x=list_ideas(self.con)[0]
        self.assertIsNone(x['score_total']);self.assertEqual(x['assessed_dimensions'],1)
    def test_timely_qualified_idea_requires_durable_question(self):
        i=self.idea();i['timely']=True;i['durable_question']=None
        self.assertTrue(any('durable' in e for e in validate_idea(i)))
    def test_performance_preserves_missing_and_combined_labels(self):
        i=self.idea();put(self.con,i,'Test idea')
        p={'snapshot_id':'p1','idea_id':i['id'],'published_url':'https://www.instagram.com/reel/example/','snapshot_at':'2026-10-01T12:00:00Z','age_hours':24,'metrics':[{'platform_label':'Shares','value':5,'unit':'count','availability':'observed','denominator':None},{'platform_label':'Sends','value':None,'unit':'count','availability':'unavailable','denominator':None}],'metric_source':'test Feras export','production_effort':None,'feras_interest_followup':None,'qualified_comments':None,'repeat_audience_behavior':None}
        record_performance(self.con,p);stored=list_ideas(self.con)[0]['performance_after_publishing'][0]
        self.assertEqual(stored['metrics'][0]['platform_label'],'Shares');self.assertIsNone(stored['metrics'][1]['value'])
        with self.assertRaises(sqlite3.IntegrityError):self.con.execute('DELETE FROM performance_snapshots')
        p['snapshot_id']='p2';p['metrics'][1]['value']=5
        with self.assertRaises(ValueError):record_performance(self.con,p)

if __name__=='__main__':unittest.main()
