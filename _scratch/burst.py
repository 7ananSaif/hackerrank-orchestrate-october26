import csv, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, 'dataset')


def load(n):
    with open(os.path.join(D, n), encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


acts = load('system_activity.csv')
ids = {'account_001', 'account_002', 'account_003', 'account_004', 'account_005',
       'account_006', 'account_007', 'account_008', 'search_001', 'support_001',
       'export_001', 'analytics_901'}
for r in acts:
    if r['resource_id'] in ids:
        print(r['activity_id'], r['event_time'], r['event_type'], r['source_system'],
              '->', r['target_system'], r['resource_id'], r['reported_result'])

print()
print('=== bursts for sample cases 01-11 (deletion_worker rows in window) ===')
reqs = load('sample_deletion_requests.csv')
for req in reqs[:11]:
    lo, hi = req['requested_at'], req['audit_at']
    print('---', req['case_id'], req['email'], lo, hi)
    for r in acts:
        if lo <= r['event_time'] <= hi and r['source_system'] == 'deletion_worker':
            print('   ', r['activity_id'], r['event_time'], r['event_type'],
                  r['target_system'], r['resource_id'], r['reported_result'])
