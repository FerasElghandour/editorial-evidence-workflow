import unittest
from radar import complete_window,parse_count,summarize,comparable_baseline,outlier_multiple,passes_gates,GATE_KEYS

class RadarTests(unittest.TestCase):
    def test_complete_calendar_days(self):
        w=complete_window('2026-09-27T22:02:38-04:00')
        self.assertEqual(w['start_inclusive'],'2026-09-20T04:00:00Z')
        self.assertEqual(w['end_exclusive'],'2026-09-27T04:00:00Z')
    def test_dst_calendar_window_not_168_hours(self):
        w=complete_window('2026-03-09T12:00:00-04:00')
        self.assertEqual(w['start_inclusive'],'2026-03-02T05:00:00Z')
        self.assertEqual(w['end_exclusive'],'2026-03-09T04:00:00Z')
    def test_missing_count_is_not_zero(self):
        self.assertIsNone(parse_count(None));self.assertIsNone(parse_count('?'))
        self.assertEqual(parse_count('0'),0);self.assertEqual(parse_count('1.4K'),1400)
    def test_median_resists_large_post(self):
        self.assertEqual(summarize([10,11,12,13,1000,None])['median'],12)
    def samples(self,n=10):
        return [dict(reel_id=str(i),views_approx=100+i,pinned=False,date_verified=True,comparability_confirmed=True,published_at='2026-09-10T10:00:00Z') for i in range(n)]
    def test_exclude_current_window_and_pins(self):
        s=self.samples(12);s[0]['pinned']=True;s[1]['published_at']='2026-09-20T04:00:00Z'
        b=comparable_baseline(s,'2026-09-20T04:00:00Z')
        self.assertTrue(b['eligible']);self.assertEqual(b['n'],10);self.assertNotIn('0',b['sample_reel_ids']);self.assertNotIn('1',b['sample_reel_ids'])
    def test_insufficient_or_unverified_not_certified(self):
        b=comparable_baseline(self.samples(9),'2026-09-20T04:00:00Z')
        self.assertIsNone(b['median']);self.assertIsNone(outlier_multiple(1000,b))
        s=self.samples();s[0]['comparability_confirmed']=False
        self.assertFalse(comparable_baseline(s,'2026-09-20T04:00:00Z')['eligible'])
    def test_duplicate_collaboration_not_independent_sample(self):
        s=self.samples();s.append(s[0].copy())
        with self.assertRaises(ValueError):comparable_baseline(s,'2026-09-20T04:00:00Z')
    def test_high_score_does_not_override_failed_gate(self):
        i={'score_total':20,'gates':dict.fromkeys(GATE_KEYS,True)}
        i['gates']['supportable_evidence']=False
        self.assertFalse(passes_gates(i))
    def test_valid_ratio_and_missing_views(self):
        b=comparable_baseline(self.samples(),'2026-09-20T04:00:00Z')
        self.assertEqual(outlier_multiple(209,b),2)
        self.assertIsNone(outlier_multiple(None,b))

if __name__=='__main__':unittest.main()
