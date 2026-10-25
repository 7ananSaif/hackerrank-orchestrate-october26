import os, re, sqlite3, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'dataset', 'evidence', 'databases')

for fn in sorted(os.listdir(DB)):
    path = os.path.join(DB, fn)
    sql = open(path, encoding='utf-8').read()
    comments = [l for l in sql.splitlines() if l.startswith('--')]
    con = sqlite3.connect(':memory:')
    try:
        con.executescript(sql)
    except Exception as e:
        print('ERR', fn, e)
        continue
    print('=' * 80)
    print(fn, '|', ' ; '.join(c.strip('- ') for c in comments[:4]))
    for (tname,) in con.execute("select name from sqlite_master where type='table'"):
        cols = [r[1] for r in con.execute(f'PRAGMA table_info("{tname}")')]
        n = con.execute(f'select count(*) from "{tname}"').fetchone()[0]
        print(f'  TABLE {tname}: rows={n} cols={cols}')
        for row in con.execute(f'select * from "{tname}" limit 2'):
            print('     ', row)
