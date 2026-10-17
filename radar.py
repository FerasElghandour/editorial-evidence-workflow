#!/usr/bin/env python3
"""Local research calculations. No Instagram network access or account mutations."""
import argparse, csv, hashlib, json, statistics
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from idea_engine import validate_idea as validate_v2_idea

TZ = ZoneInfo('America/Toronto')
SCORE_KEYS = ['builder_relevance','benefit','curiosity','non_obviousness','evidence','save_potential','send_potential','brand_fit','original_contribution','production_feasibility']
GATE_KEYS = ['identifiable_viewer','clear_benefit','non_obvious_payoff','supportable_evidence','original_contribution','account_promise','responsible_production']

def timestamp(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('An explicit timezone is required')
    return dt

def iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace('+00:00','Z')

def complete_window(as_of):
    local = timestamp(as_of).astimezone(TZ)
    end = datetime.combine(local.date(), time.min, TZ)
    start = datetime.combine(local.date() - timedelta(days=7), time.min, TZ)
    return {'timezone':str(TZ), 'execution_local_date':str(local.date()),
            'start_inclusive':iso(start), 'end_exclusive':iso(end)}

def parse_count(value):
    if value is None or str(value).strip() in ('','?','-'):
        return None
    value = str(value).strip().replace(',','').upper()
    multiplier = {'K':1000, 'M':1000000}.get(value[-1], 1)
    number = float(value[:-1] if multiplier != 1 else value) * multiplier
    if number < 0:
        raise ValueError('Counts cannot be negative')
    return number

def summarize(values):
    values = [v for v in values if v is not None]
    if not values:
        return {'n':0,'median':None,'q1':None,'q3':None}
    qs = statistics.quantiles(values,n=4,method='inclusive') if len(values)>1 else [values[0]]*3
    return {'n':len(values),'median':statistics.median(values),'q1':qs[0],'q3':qs[2]}

def comparable_baseline(samples, start, min_n=10):
    """Strict cohort. Caller must verify comparability rather than infer it from views."""
    seen=set(); kept=[]; rejected=[]
    for s in samples:
        sid=s['reel_id']
        if sid in seen:
            raise ValueError('Duplicate shortcode in baseline: '+sid)
        seen.add(sid)
        reason=None
        if s.get('views_approx') is None: reason='views unavailable'
        elif s.get('pinned'): reason='pinned'
        elif s.get('cohort_exclusion'): reason='excluded distribution/format'
        elif not s.get('date_verified'): reason='date not verified'
        elif not s.get('comparability_confirmed'): reason='comparability not confirmed'
        elif not s.get('published_at'): reason='publication date unavailable'
        elif timestamp(s['published_at']) >= timestamp(start): reason='not pre-window'
        if reason: rejected.append({'reel_id':sid,'reason':reason})
        else: kept.append(s)
    result=summarize([s['views_approx'] for s in kept])
    result.update(sample_reel_ids=[s['reel_id'] for s in kept],rejected=rejected,
                  eligible=result['n']>=min_n,age_adjusted=False)
    if not result['eligible']:
        result['sample_median']=result['median'];result['median']=None
    return result

def outlier_multiple(views, baseline):
    if views is None or not baseline.get('eligible') or not baseline.get('median'):
        return None
    return views / baseline['median']

def passes_gates(idea):
    return all(idea.get('gates',{}).get(k) is True for k in GATE_KEYS)

def write_new(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as f:
        json.dump(value,f,indent=2,ensure_ascii=False)
        f.write('\n')

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def audit(run):
    errors=[]; warnings=[]
    required=['weekly_reels.json','weekly_reels.csv','view_samples.csv','creator_baselines.json','creator_panel.json','opportunities.json','access_and_coverage.json','report.md']
    missing=[n for n in required if not (run/n).exists()]
    if missing:return {'ok':False,'errors':['Missing '+', '.join(missing)],'warnings':[]}
    read=lambda n:json.loads((run/n).read_text())
    reels=read('weekly_reels.json'); panel=read('creator_panel.json'); bases=read('creator_baselines.json'); ideas=read('opportunities.json');coverage=read('access_and_coverage.json')
    ids=[r['reel_id'] for r in reels]
    if len(ids)!=len(set(ids)):errors.append('Duplicate weekly shortcode')
    if len(panel)!=len({p['creator'] for p in panel}):errors.append('Duplicate creator')
    if len(panel)<30 or len(panel)>50:warnings.append('Panel outside requested 30–50 range')
    with (run/'view_samples.csv').open() as f:samples=list(csv.DictReader(f))
    with (run/'weekly_reels.csv').open() as f:csvreels=list(csv.DictReader(f))
    if len(csvreels)!=len(reels):errors.append('CSV and JSON weekly counts differ')
    confirmed=sum(r['weekly_confirmed'] for r in reels)
    if confirmed!=coverage['confirmed_weekly_reels']:errors.append('Coverage count differs')
    start=timestamp(coverage['window_start_inclusive']);end=timestamp(coverage['window_end_exclusive'])
    for r in reels:
        times=[timestamp(r[k]) for k in ['publication_time_display','alternate_caption_time'] if r.get(k)]
        if r['weekly_confirmed'] and not all(start<=d<end for d in times):errors.append('Window conflict incorrectly included: '+r['reel_id'])
        if any(r.get(k) is not None for k in ['saves','sends','shares']):errors.append('Competitor private metric populated: '+r['reel_id'])
        if r.get('first_spoken_sentence') and not r.get('spoken_sentence_verified'):errors.append('Unverified spoken quote: '+r['reel_id'])
        if r['creator'] not in {p['creator'] for p in panel}:errors.append('Unknown creator: '+r['creator'])
    for b in bases:
        cohort=[s for s in samples if s['creator']==b['creator']]
        summary=summarize([parse_count(s['views_label']) for s in cohort])
        if summary['median']!=b['screening_median_views'] or summary['n']!=b['n']:errors.append('Baseline mismatch: '+b['creator'])
        if b['matched_median_views'] is not None:
            match=summarize([parse_count(s['views_label']) for s in cohort if not s['cohort_exclusion']])
            if match['median']!=b['matched_median_views'] or match['n']!=b['matched_n']:errors.append('Matched subset mismatch: '+b['creator'])
        for r in [r for r in reels if r['creator']==b['creator']]:
            if abs(r['screening_multiple']-r['views_approx']/b['screening_median_views'])>.0001:errors.append('Ratio mismatch: '+r['reel_id'])
            if r.get('outlier_multiple') is not None:
                if b['matched_median_views'] is None or abs(r['outlier_multiple']-r['views_approx']/b['matched_median_views'])>.0001:errors.append('Matched ratio mismatch: '+r['reel_id'])
    config=read('run_config.json') if (run/'run_config.json').exists() else {}
    for idea in ideas:
        if idea.get('rubric_version') == 2:
            errors.extend(idea['id']+': '+e for e in validate_v2_idea(idea))
            continue
        if config.get('rubric_version') == 2:
            errors.append('Future run contains an unversioned legacy idea: '+idea.get('id','unknown'))
            continue
        scores=idea.get('scores',{})
        if set(scores)!=set(SCORE_KEYS) or any(v not in [0,1,2] for v in scores.values()):errors.append('Invalid scores: '+idea['id'])
        if sum(scores.values())!=idea.get('score_total'):errors.append('Score total mismatch: '+idea['id'])
        if idea['status'] in ['recommend','wildcard'] and not passes_gates(idea):errors.append('Recommended idea fails gate: '+idea['id'])
        if not set(idea['source_signal']).issubset(set(ids)):errors.append('Missing source signal: '+idea['id'])
    warnings.append(f"{sum(r.get('first_spoken_sentence') is None for r in reels)} candidate spoken openings unavailable")
    warnings.append(f"{sum(b['n']<10 for b in bases)} creator baseline samples below 10")
    warnings.append('Initial matched subsets are provisional; audiovisual comparability and age controls incomplete')
    manifest=run/'MANIFEST.json'
    if manifest.exists():
        m=json.loads(manifest.read_text())
        for name,sha in m['sha256'].items():
            p=run/name
            if not p.exists() or digest(p)!=sha:errors.append('Sealed file changed or missing: '+name)
        actual={str(p.relative_to(run)) for p in run.rglob('*') if p.is_file() and p.name!='MANIFEST.json'}
        if actual!=set(m['sha256']):errors.append('Sealed file set changed')
    return {'ok':not errors,'errors':errors,'warnings':warnings,'confirmed_reels':confirmed,'candidate_reels':len(reels),'panel':len(panel),'baseline_sample_rows':len(samples)}

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    for c in ['window','new-run']:
        p=sub.add_parser(c);p.add_argument('--as-of',required=True)
        if c=='new-run':p.add_argument('--root',type=Path,default=Path(__file__).resolve().parent)
    for c in ['audit','seal']:
        p=sub.add_parser(c);p.add_argument('run',type=Path)
    args=parser.parse_args()
    if args.command=='window':result=complete_window(args.as_of)
    elif args.command=='new-run':
        window=complete_window(args.as_of);rid='run-'+timestamp(args.as_of).astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        run=args.root/'weeks'/window['execution_local_date']/rid
        run.mkdir(parents=True,exist_ok=False)
        write_new(run/'run_config.json',dict(window=window,execution_as_of=args.as_of,status='awaiting read-only research',rules='See weekly_prompt.md and policies/idea-engine-v2.md; no inferred metrics, automatic account actions or automatic scripts',strategy_version=2,rubric_version=2,idea_engine_database='idea-engine/ideas.sqlite3',source_streams=['Creator Radar','Feras Originals','Current Research & Events'],output_stages=['signals','opportunities','qualified ideas','recommended production queue']))
        result={'created':str(run),'window':window}
    elif args.command=='audit':result=audit(args.run)
    else:
        result=audit(args.run)
        if not result['ok']:raise SystemExit(json.dumps(result,indent=2))
        write_new(args.run/'MANIFEST.json',{'sealed_at':iso(datetime.now(timezone.utc)),'status':json.loads((args.run/'access_and_coverage.json').read_text()).get('status','research snapshot'),'sha256':{str(p.relative_to(args.run)):digest(p) for p in sorted(args.run.rglob('*')) if p.is_file() and p.name!='MANIFEST.json'}})
        result['sealed']=True
    print(json.dumps(result,indent=2))
    if result.get('ok') is False:raise SystemExit(1)

if __name__=='__main__':main()
