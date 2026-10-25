import csv, os, json, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, 'dataset')
EV = os.path.join(D, 'evidence')


def load(n):
    with open(os.path.join(D, n), encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


ident = {r['user_id']: r for r in load('user_identities.csv')}
audit = load('user_audit_log.csv')
reqs = load('sample_deletion_requests.csv')

# text corpus of evidence
corpus = {}
for base, _, files in os.walk(EV):
    for fn in files:
        if fn.endswith(('.sql', '.log', '.json', '.txt')):
            p = os.path.join(base, fn)
            corpus[os.path.relpath(p, D)] = open(p, encoding='utf-8', errors='replace').read()

for req in reqs:
    email = req['email'].lower()
    name = None
    print('=' * 70)
    print(req['case_id'], req['email'], 'audit', req['audit_at'])
    # find identity
    hits = [u for u, r in ident.items() if r['email'].lower() == email]
    if not hits:
        audits = [a for a in audit if a['new_value'] and a['new_value'].lower() == email]
        print('  not current identity; audit old->new matches:', [(a['user_id'], a['event_time'], a['field_name']) for a in audits])
    for u in hits:
        print('  user_id', u, ident[u]['name'], ident[u]['phone'][:6] + '...')
    keys = {email}
    for a in audit:
        if a['old_value'] and a['old_value'].lower() == email:
            keys.add(a['new_value'].lower())
            u = a['user_id']
            if u in ident:
                keys.add(ident[u]['email'].lower())
                keys.add(ident[u]['email_hash'])
                keys.add(ident[u]['phone'])
                keys.add(ident[u]['name'].lower())
            keys.add(u)
    for a in audit:
        if a['field_name'] == 'email' and a['new_value'] and a['new_value'].lower() == email:
            keys.add(a['old_value'].lower())
    found = []
    for path, text in corpus.items():
        tl = text.lower()
        n = sum(tl.count(k) for k in keys if k)
        if n:
            found.append((path, n))
    found.sort(key=lambda x: -x[1])
    for path, n in found[:8]:
        print(f'   {n:4d}  {path}')
