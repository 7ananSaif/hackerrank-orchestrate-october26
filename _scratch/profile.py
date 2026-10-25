import csv, os, collections, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, 'dataset')


def load(name):
    with open(os.path.join(D, name), encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


for name in ['deletion_requests.csv', 'sample_deletion_requests.csv', 'user_identities.csv',
             'user_audit_log.csv', 'system_activity.csv', 'deletion_rules.csv', 'evidence_files.csv']:
    rows = load(name)
    print('=' * 70)
    print(name, 'rows=', len(rows), 'cols=', list(rows[0].keys()) if rows else None)
    for row in rows[:2]:
        print('  ', json.dumps(row, ensure_ascii=False)[:300])

print('=' * 70)
ua = load('user_audit_log.csv')
fields = [k for k in ua[0].keys()]
print('audit cols:', fields)
for k in fields:
    if k in ('audit_id', 'user_id', 'changed_at', 'old_value', 'new_value'):
        continue
    print('--', k, collections.Counter(r[k] for r in ua).most_common(20))
print('sample audit rows:')
for r in ua[:4]:
    print('  ', json.dumps(r, ensure_ascii=False))

print('=' * 70)
sa = load('system_activity.csv')
print('activity cols:', list(sa[0].keys()))
for k in sa[0].keys():
    c = collections.Counter(r[k] for r in sa)
    if len(c) <= 40:
        print(f'-- {k} ({len(c)}):', c.most_common(40))
    else:
        print(f'-- {k} ({len(c)}) top:', c.most_common(8))

print('=' * 70)
dr = load('deletion_requests.csv')
print('reported_status:', collections.Counter(r['reported_status'] for r in dr))
print('audit months:', collections.Counter(r['audit_at'][:7] for r in dr).most_common())
print('first row:', json.dumps(dr[0], ensure_ascii=False))
