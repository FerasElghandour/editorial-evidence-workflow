#!/usr/bin/env python3
"""Persistent three-stream Idea Engine. Local SQLite; no network or script generation."""
import argparse, copy, json, sqlite3
from datetime import datetime, timezone
from pathlib import Path

STREAMS = ['Creator Radar','Feras Originals','Current Research & Events']
STATUSES = ['Raw','Researching','Qualified','Production Queue','Scripted','Recorded','Published','Reviewed','Reuse','Expand','Retire']
SCORE_KEYS = ['builder_relevance','benefit','curiosity','non_obviousness','evidence','save_potential','send_potential','brand_fit','original_contribution','production_feasibility','feras_interest','immediate_comprehensibility','memorability']
GATE_KEYS = ['identifiable_viewer','useful_understanding','non_obvious_payoff','supportable_evidence','original_contribution','account_promise','responsible_production']
QUEUE_KEYS = ['account_identity','topic_diversity','production_feasibility','previous_reels','audience_evidence','adjacent_repetition','feras_interest','order_reason']
DEFAULT_DB = Path(__file__).resolve().parent/'idea-engine/ideas.sqlite3'

def now():return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def encode(x):return json.dumps(x,ensure_ascii=False,sort_keys=True)
def meaningful(x):return isinstance(x,str) and bool(x.strip())
def passes_gates(idea):
    return all(idea.get('gates',{}).get(k,{}).get('status')=='pass' for k in GATE_KEYS)

def validate_idea(idea):
    errors=[]
    required=['id','idea','source_stream','date_discovered','target_viewer','specific_benefit','benefit_type','core_insight','evidence','save_reason','send_reason','feras_contribution','feras_interest','comprehensibility','memorability','production_effort','status','published_url','origin_refs','source_creator_reel_ids','timely','durable_question','scores','gates']
    for k in required:
        if k not in idea:errors.append('Missing '+k)
    if errors:return errors
    if idea.get('rubric_version')!=2:errors.append('Rubric version must be 2')
    if idea['source_stream'] not in STREAMS:errors.append('Invalid source stream')
    if idea['status'] not in STATUSES:errors.append('Invalid status')
    if not meaningful(idea['id']) or not meaningful(idea['idea']):errors.append('ID and idea must be nonempty')
    if not idea['origin_refs']:errors.append('Origin provenance required, including user note for an Original')
    if idea['source_stream']=='Creator Radar' and not idea['source_creator_reel_ids']:errors.append('Creator Radar requires creator signal references')
    if not isinstance(idea['evidence'],list):errors.append('Evidence must be a list')
    scores=idea['scores']
    if set(scores)!=set(SCORE_KEYS):errors.append('Expected all 13 score dimensions')
    for key,item in scores.items():
        if not isinstance(item,dict):errors.append('Score must include value, reason and evidence_refs: '+key);continue
        value=item.get('value')
        if value is not None and (type(value) is not int or value not in (0,1,2)):errors.append('Invalid score: '+key)
        if not meaningful(item.get('reason')):errors.append('Missing score rationale: '+key)
        if value==2 and not item.get('evidence_refs'):errors.append('A 2 requires specific supporting evidence: '+key)
    if set(idea['gates'])!=set(GATE_KEYS):errors.append('Expected seven separate hard gates')
    for key,g in idea['gates'].items():
        if not isinstance(g,dict) or g.get('status') not in ['pass','pending','fail'] or not meaningful(g.get('reason')):errors.append('Invalid gate: '+key)
    if idea['gates'].get('original_contribution',{}).get('status')=='pass':
        o=idea.get('originality_test',{})
        if o.get('verdict')!='adds_substance' or not meaningful(o.get('feras_adds')):errors.append('Originality gate needs a substantive contribution')
        if idea['source_stream']!='Feras Originals' and not meaningful(o.get('source_provides')):errors.append('External source comparison required for originality')
    qualified=idea['status'] in ['Qualified','Production Queue','Scripted','Recorded']
    if qualified:
        if not passes_gates(idea):errors.append('This stage requires all hard gates to pass')
        if any(scores.get(k,{}).get('value') is None for k in SCORE_KEYS):errors.append('Qualified ideas require an assessment of every dimension')
        if not all(meaningful(idea.get(k)) for k in ['target_viewer','specific_benefit','core_insight','feras_contribution']):errors.append('Qualified idea brief incomplete')
        if idea['timely'] and not meaningful(idea['durable_question']):errors.append('Timely qualified idea needs a durable six-month question')
    if idea['status']=='Production Queue' and not idea.get('queue_rationale'):errors.append('Queue rationale required')
    if idea['status'] in ['Published','Reviewed'] and not meaningful(idea['published_url']):errors.append('Published URL required at this stage')
    return errors

SCHEMA = """
CREATE TABLE IF NOT EXISTS ideas(id TEXT PRIMARY KEY,payload TEXT NOT NULL,revision INTEGER NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS idea_events(event_id INTEGER PRIMARY KEY AUTOINCREMENT,idea_id TEXT NOT NULL REFERENCES ideas(id),at TEXT NOT NULL,reason TEXT NOT NULL,before_json TEXT,after_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS performance_snapshots(snapshot_id TEXT PRIMARY KEY,idea_id TEXT NOT NULL REFERENCES ideas(id),payload TEXT NOT NULL,recorded_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS queue_events(event_id INTEGER PRIMARY KEY AUTOINCREMENT,at TEXT NOT NULL,reason TEXT NOT NULL,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS current_queue(position INTEGER PRIMARY KEY,idea_id TEXT UNIQUE NOT NULL REFERENCES ideas(id),rationale TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS retain_ideas BEFORE DELETE ON ideas BEGIN SELECT RAISE(ABORT,'Retire ideas; preserve history'); END;
CREATE TRIGGER IF NOT EXISTS immutable_idea_events_update BEFORE UPDATE ON idea_events BEGIN SELECT RAISE(ABORT,'History is append-only'); END;
CREATE TRIGGER IF NOT EXISTS immutable_idea_events_delete BEFORE DELETE ON idea_events BEGIN SELECT RAISE(ABORT,'History is append-only'); END;
CREATE TRIGGER IF NOT EXISTS immutable_performance_update BEFORE UPDATE ON performance_snapshots BEGIN SELECT RAISE(ABORT,'Append a correction snapshot'); END;
CREATE TRIGGER IF NOT EXISTS immutable_performance_delete BEFORE DELETE ON performance_snapshots BEGIN SELECT RAISE(ABORT,'Preserve performance history'); END;
CREATE TRIGGER IF NOT EXISTS immutable_queue_events_update BEFORE UPDATE ON queue_events BEGIN SELECT RAISE(ABORT,'History is append-only'); END;
CREATE TRIGGER IF NOT EXISTS immutable_queue_events_delete BEFORE DELETE ON queue_events BEGIN SELECT RAISE(ABORT,'History is append-only'); END;
"""

def connect(db=DEFAULT_DB,initialize=False,readonly=False):
    if readonly:
        con=sqlite3.connect('file:'+str(Path(db).resolve())+'?mode=ro',uri=True)
    else:
        Path(db).parent.mkdir(parents=True,exist_ok=True);con=sqlite3.connect(db)
    con.row_factory=sqlite3.Row;con.execute('PRAGMA foreign_keys=ON')
    if initialize:
        con.executescript(SCHEMA);con.commit()
    return con

def put(con,idea,reason,expected_revision=None,allow_queue_change=False):
    if not meaningful(reason):raise ValueError('History reason required')
    errors=validate_idea(idea)
    if errors:raise ValueError('; '.join(errors))
    row=con.execute('SELECT * FROM ideas WHERE id=?',(idea['id'],)).fetchone()
    old=json.loads(row['payload']) if row else None
    if expected_revision is not None and (row['revision'] if row else 0)!=expected_revision:raise ValueError('Revision changed; reload before editing')
    if idea['status']=='Production Queue' and not allow_queue_change and (not old or old['status']!='Production Queue'):raise ValueError('Use queue command to enter the production queue')
    if old and old['status']=='Production Queue' and idea['status']!='Production Queue':
        raise ValueError('Remove from queue with queue command before advancing or deferring')
    # Computed export fields never become competing sources of truth.
    idea=copy.deepcopy(idea)
    for key in ['revision','score_total','score_max','assessed_dimensions','performance_after_publishing']:
        idea.pop(key,None)
    revision=(row['revision'] if row else 0)+1;at=now()
    con.execute('INSERT INTO ideas VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,revision=excluded.revision,updated_at=excluded.updated_at',(idea['id'],encode(idea),revision,at))
    con.execute('INSERT INTO idea_events(idea_id,at,reason,before_json,after_json) VALUES(?,?,?,?,?)',(idea['id'],at,reason,row['payload'] if row else None,encode(idea)))
    return revision

def list_ideas(con,stream=None):
    result=[]
    for row in con.execute('SELECT * FROM ideas ORDER BY id'):
        idea=json.loads(row['payload'])
        if stream and idea['source_stream']!=stream:continue
        values=[idea['scores'][k]['value'] for k in SCORE_KEYS]
        idea.update(revision=row['revision'],score_total=sum(values) if all(v is not None for v in values) else None,score_max=26,assessed_dimensions=sum(v is not None for v in values),performance_after_publishing=[json.loads(x['payload']) for x in con.execute('SELECT payload FROM performance_snapshots WHERE idea_id=? ORDER BY recorded_at,snapshot_id',(idea['id'],))])
        result.append(idea)
    return result

def set_queue(con,entries,reason):
    if not meaningful(reason):raise ValueError('Queue-selection reason required')
    ids=[e['idea_id'] for e in entries]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate queue idea')
    all_ideas={x['id']:x for x in list_ideas(con)}
    for e in entries:
        i=all_ideas.get(e['idea_id'])
        if not i or i['status'] not in ['Qualified','Production Queue'] or not passes_gates(i):raise ValueError('Queue accepts qualified ideas only')
        if not all(meaningful(e.get('rationale',{}).get(k)) for k in QUEUE_KEYS):raise ValueError('Every queue item needs identity, diversity, effort, prior-post, audience, adjacency, interest and order reasoning')
    old_ids=[r['idea_id'] for r in con.execute('SELECT idea_id FROM current_queue')]
    # Apply status changes through normal validation and append history atomically.
    for iid in old_ids:
        if iid not in ids:
            idea=all_ideas[iid];idea['status']='Qualified';idea.pop('queue_rationale',None)
            # Temporarily deleting queue membership never deletes the idea or event history.
            old=con.execute('SELECT payload FROM ideas WHERE id=?',(iid,)).fetchone()['payload']
            for k in ['revision','score_total','score_max','assessed_dimensions','performance_after_publishing']:idea.pop(k,None)
            con.execute('UPDATE ideas SET payload=?,revision=revision+1,updated_at=? WHERE id=?',(encode(idea),now(),iid))
            con.execute('INSERT INTO idea_events(idea_id,at,reason,before_json,after_json) VALUES(?,?,?,?,?)',(iid,now(),'Removed from production queue: '+reason,old,encode(idea)))
    con.execute('DELETE FROM current_queue')
    for pos,e in enumerate(entries,1):
        idea=all_ideas[e['idea_id']];idea['status']='Production Queue';idea['queue_rationale']=e['rationale']
        put(con,idea,'Editorial queue selection: '+reason,allow_queue_change=True)
        con.execute('INSERT INTO current_queue VALUES(?,?,?)',(pos,idea['id'],encode(e['rationale'])))
    con.execute('INSERT INTO queue_events(at,reason,payload) VALUES(?,?,?)',(now(),reason,encode(entries)))

def record_performance(con,result):
    required=['snapshot_id','idea_id','published_url','snapshot_at','age_hours','metrics','metric_source','production_effort','feras_interest_followup','qualified_comments','repeat_audience_behavior']
    if any(k not in result for k in required):raise ValueError('Performance snapshot fields incomplete')
    if not result['published_url'] or result['age_hours']<0:raise ValueError('Published URL and valid age required')
    if not con.execute('SELECT id FROM ideas WHERE id=?',(result['idea_id'],)).fetchone():raise ValueError('Unknown idea')
    for m in result['metrics']:
        if not all(k in m for k in ['platform_label','value','unit','availability','denominator']):raise ValueError('Preserve metric labels, availability, units and denominator')
        if m['value'] is not None and (not isinstance(m['value'],(float,int)) or isinstance(m['value'],bool) or m['value']<0):raise ValueError('Invalid metric value')
        if m['availability']!='observed' and m['value'] is not None:raise ValueError('Unavailable metrics must remain null')
    con.execute('INSERT INTO performance_snapshots VALUES(?,?,?,?)',(result['snapshot_id'],result['idea_id'],encode(result),now()))

def audit(con):
    errors=[];ideas=list_ideas(con)
    for idea in ideas:errors += [idea['id']+': '+e for e in validate_idea(idea)]
    queue=[dict(r) for r in con.execute('SELECT * FROM current_queue ORDER BY position')]
    queued={q['idea_id'] for q in queue}
    if queued!={i['id'] for i in ideas if i['status']=='Production Queue'}:errors.append('Queue/status mismatch')
    for q in queue:
        if not all(meaningful(json.loads(q['rationale']).get(k)) for k in QUEUE_KEYS):errors.append('Queue rationale incomplete')
    for row in con.execute('SELECT i.id,i.payload,(SELECT after_json FROM idea_events e WHERE e.idea_id=i.id ORDER BY event_id DESC LIMIT 1) last_event FROM ideas i'):
        if row['payload']!=row['last_event']:errors.append('Current record/history mismatch: '+row['id'])
    return {'ok':not errors,'errors':errors,'ideas':len(ideas),'streams':{s:sum(i['source_stream']==s for i in ideas) for s in STREAMS},'statuses':{s:sum(i['status']==s for i in ideas) for s in STATUSES},'production_queue_size':len(queue),'performance_snapshots':con.execute('SELECT count(*) FROM performance_snapshots').fetchone()[0]}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',type=Path,default=DEFAULT_DB);sp=p.add_subparsers(dest='command',required=True)
    sp.add_parser('init');sp.add_parser('audit');x=sp.add_parser('list');x.add_argument('--stream',choices=STREAMS)
    x=sp.add_parser('history');x.add_argument('id')
    for command in ['put','queue','performance']:
        x=sp.add_parser(command);x.add_argument('--file',type=Path,required=True)
        if command!='performance':x.add_argument('--reason',required=True)
        if command=='put':x.add_argument('--expected-revision',type=int)
    x=sp.add_parser('export');x.add_argument('--out',type=Path,required=True)
    args=p.parse_args();read_only=args.command in ['audit','list','history','export']
    con=connect(args.db,initialize=args.command=='init',readonly=read_only)
    try:
        with con:
            if args.command=='init':out={'database':str(args.db)}
            elif args.command=='put':out={'revision':put(con,json.loads(args.file.read_text()),args.reason,args.expected_revision)}
            elif args.command=='queue':set_queue(con,json.loads(args.file.read_text()),args.reason);out={'queue_updated':True}
            elif args.command=='performance':record_performance(con,json.loads(args.file.read_text()));out={'snapshot_recorded':True}
            elif args.command=='audit':out=audit(con)
            elif args.command=='history':out=[dict(x) for x in con.execute('SELECT * FROM idea_events WHERE idea_id=? ORDER BY event_id',(args.id,))]
            else:
                out=list_ideas(con,getattr(args,'stream',None))
                if args.command=='export':
                    args.out.parent.mkdir(parents=True,exist_ok=True)
                    with args.out.open('x') as f:json.dump(out,f,indent=2,ensure_ascii=False)
                    out={'exported':str(args.out),'ideas':len(out)}
        print(json.dumps(out,indent=2,ensure_ascii=False))
        if isinstance(out,dict) and out.get('ok') is False:raise SystemExit(1)
    finally:con.close()

if __name__=='__main__':main()
