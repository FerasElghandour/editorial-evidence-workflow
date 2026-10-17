"""Offline example using the public implementation; see README for evidence scope."""
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)

import json,sqlite3
from pathlib import Path
from idea_engine import SCHEMA,put,list_ideas,audit
con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
con.execute('PRAGMA foreign_keys=ON');con.executescript(SCHEMA)
idea=json.loads(Path('examples/qualified-idea.json').read_text())
put(con,idea,'Synthetic demonstration')
row=list_ideas(con)[0]
print({'id':row['id'],'status':row['status'],'revision':row['revision'],'score_total':row['score_total'],'audit':audit(con)})
con.close()
