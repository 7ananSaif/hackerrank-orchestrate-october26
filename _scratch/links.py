import os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EV = os.path.join(ROOT, 'dataset', 'evidence')
targets = ['account_6440', 'account_3136', 'account_5334', 'account_5482',
           'account_5684', 'account_3866', 'analytics_5335', 'analytics_4574',
           'analytics_6077', 'tombstone_8774']
for base, _, files in os.walk(EV):
    for fn in sorted(files):
        if not fn.endswith(('.sql', '.json', '.log', '.txt')):
            continue
        p = os.path.join(base, fn)
        text = open(p, encoding='utf-8', errors='replace').read()
        for t in targets:
            for m in re.finditer(re.escape(t), text):
                s = max(0, m.start() - 150)
                print(f'{fn} [{t}]:', text[s:m.start() + 150].replace('\n', ' '))
                break
