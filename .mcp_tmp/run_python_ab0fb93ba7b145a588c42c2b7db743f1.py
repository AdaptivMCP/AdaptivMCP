import json, pathlib
p=pathlib.Path('coverage.json')
data=json.loads(p.read_text())
files=data.get('files',{})
info=files.get('github_mcp/main_tools/dashboard.py')
s=info['summary']
print('dashboard', s.get('percent_covered'), s.get('covered_lines'), s.get('num_statements'))
rows=[]
for path,info in files.items():
    if path.startswith('tests/'):
        continue
    s=info.get('summary',{})
    cov=s.get('percent_covered')
    if cov is None:
        cov=100.0*s.get('covered_lines',0)/ (s.get('num_statements') or 1)
    rows.append((cov,path,s.get('covered_lines',0),s.get('num_statements',0)))
rows.sort()
print('lowest5')
for cov,path,covered,num in rows[:5]:
    print(cov,path,covered,num)
print('total', data.get('totals',{}).get('percent_covered_display'))
