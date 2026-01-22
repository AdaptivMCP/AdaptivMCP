import json, pathlib
p=pathlib.Path('coverage.json')
print('exists',p.exists(), 'size', p.stat().st_size if p.exists() else None)
data=json.loads(p.read_text())
files=data.get('files',{})
rows=[]
for path,info in files.items():
    if path.startswith('tests/'):
        continue
    summ=info.get('summary',{})
    cov=summ.get('percent_covered', None)
    if cov is None:
        # compute
        covered=summ.get('covered_lines',0)
        num=summ.get('num_statements',0)
        cov=100.0*covered/num if num else 100.0
    rows.append((cov, path, summ.get('num_statements',0), summ.get('covered_lines',0)))
rows.sort()
for cov,path,num,covered in rows[:25]:
    print(f"{cov:6.2f}% {path}  ({covered}/{num})")
print('TOTAL', data.get('totals',{}).get('percent_covered_display'))
