import csv, os, collections, json, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, 'dataset')


def load(name):
    with open(os.path.join(D, name), encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


sa = load('system_activity.csv')
print('DETAILS SAMPLE PER EVENT_TYPE')
by_type = collections.defaultdict(list)
for r in sa:
    by_type[r['event_type']].append(r)
for t, rows in sorted(by_type.items()):
    print(f'--- {t}  n={len(rows)}')
    for r in rows[:3]:
        print('   ', json.dumps(r, ensure_ascii=False))

print()
print('rows with user_id in details:', sum(1 for r in sa if re.search(r'user_\d+', r['details'])))
for r in sa:
    if re.search(r'user_\d+', r['details']):
        print('USERID_ROW', json.dumps(r, ensure_ascii=False))
        break

print()
print('LINK_RESOURCE_IDENTITY rows:')
for r in sa:
    if r['event_type'] == 'LINK_RESOURCE_IDENTITY':
        print('  ', json.dumps(r, ensure_ascii=False))

print()
print('CLASSIFY_REQUEST rows:')
for r in sa:
    if r['event_type'] == 'CLASSIFY_REQUEST':
        print('  ', json.dumps(r, ensure_ascii=False))

print()
print('RESTORE_BACKUP / CHECK_RESTORE_ACCESS / CHECK_DATA_FLOW / DISABLE_DATA_FLOW / BLOCK_RESTORE rows:')
for r in sa:
    if r['event_type'] in ('RESTORE_BACKUP', 'CHECK_DATA_FLOW', 'DISABLE_DATA_FLOW', 'BLOCK_RESTORE'):
        print('  ', json.dumps(r, ensure_ascii=False))
