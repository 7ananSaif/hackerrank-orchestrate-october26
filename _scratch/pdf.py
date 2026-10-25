import os, glob, pdfplumber

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in sorted(glob.glob(os.path.join(ROOT, 'dataset', 'evidence', 'documents', '*.pdf'))):
    print('=' * 90)
    print(os.path.basename(p))
    with pdfplumber.open(p) as pdf:
        for i, page in enumerate(pdf.pages):
            t = page.extract_text() or ''
            print(f'--- page {i + 1} ---')
            print(t)
