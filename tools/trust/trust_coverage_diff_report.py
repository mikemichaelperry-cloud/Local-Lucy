#!/usr/bin/env python3
import os, re, sys, glob, json

def fail(msg):
    print(f"ERR: {msg}", file=sys.stderr)
    raise SystemExit(1)

def root_from_script():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

def latest(globpat):
    xs=sorted(glob.glob(globpat))
    return xs[-1] if xs else None

def read_domains(path):
    out=set()
    if not path or not os.path.isfile(path):
        return out
    for line in open(path, encoding='utf-8', errors='ignore'):
        s=line.strip().lower()
        if not s or s.startswith('#'): continue
        if s.startswith('- '): s=s[2:].strip()
        s=s.split('#',1)[0].strip().split('/',1)[0].split(':',1)[0].strip()
        if s.startswith('www.'): s=s[4:]
        if re.fullmatch(r'[a-z0-9.-]+', s): out.add(s)
    return out

def read_baseline_tsv(path):
    out={}
    if not path: return out
    for i,line in enumerate(open(path, encoding='utf-8', errors='ignore')):
        if i==0 and line.lower().startswith('domain\t'): continue
        parts=line.rstrip('\n').split('\t')
        if len(parts) < 4: continue
        d,t,cats,req=parts[:4]
        if not re.fullmatch(r'[a-z0-9.-]+', d): continue
        out[d]={'tier':t,'cats':set(x for x in cats.split(',') if x), 'req':req}
    return out

def parse_catalog(path):
    data={}; cur=None
    def ps(s):
        s=s.strip()
        if s.startswith('"') and s.endswith('"'): return s[1:-1]
        if s=='true': return True
        if s=='false': return False
        if s.isdigit(): return int(s)
        if s.startswith('[') and s.endswith(']'):
            inner=s[1:-1].strip(); return [] if not inner else [x.strip().strip('"') for x in inner.split(',') if x.strip()]
        return s
    for line in open(path, encoding='utf-8'):
        t=line.rstrip('\n'); s=t.strip()
        if not s or s.startswith('#'): continue
        ind=len(t)-len(t.lstrip(' '))
        if ind==2 and s.endswith(':'):
            cur=s[:-1].strip(); data[cur]={}; continue
        if ind==4 and ':' in s and cur:
            k,v=s.split(':',1); data[cur][k.strip()]=ps(v)
    return data

def norm_baseline_cats(cats):
    m={
      'news_official':'news_world','news_reporting':'news_world','news_business':'finance','news_israel':'news_israel','news_australia':'news_world',
      'knowledge':'engineering','knowledge_secondary':'engineering','medical_index':'medical','medical':'medical','medical_israel':'medical','medical_australia':'medical',
      'engineering':'engineering','engineering_semiconductor':'electronics','engineering_australia':'engineering','standards':'engineering',
      'ai_labs':'ai','ai_research':'ai','ai_engineering':'ai','economics_data':'finance','economics_israel':'finance','economics_us':'finance','economics_australia':'finance'
    }
    out=set()
    for c in cats:
        out.add(m.get(c,c))
    return out

def read_exceptions(path):
    s=set()
    if not os.path.isfile(path): return s
    for line in open(path, encoding='utf-8', errors='ignore'):
        t=line.strip()
        if not t or t.startswith('#'): continue
        s.add(t)
    return s

def ensure_file(path):
    if not os.path.exists(path):
        open(path,'w',encoding='utf-8',newline='\n').close()

root=root_from_script()
notes=os.path.join(root,'dev_notes','unified_trust_layer_v1')
baseline_domains=latest(os.path.join(notes,'baseline_domains_*_*.txt')) or latest(os.path.join(notes,'baseline_domains_*.txt'))
# prefer exact root-specific names
for candidate in sorted(glob.glob(os.path.join(notes,'baseline_domains_*.txt'))):
    baseline_domains=candidate
baseline_tier=latest(os.path.join(notes,'baseline_tier_map_*.tsv'))
cur_allow=os.path.join(root,'config','trust','generated','allowlist_fetch.txt')
cat_path=os.path.join(root,'config','trust','trust_catalog.yaml')
if not os.path.isfile(cur_allow): fail(f'missing current allowlist: {cur_allow}')
if not os.path.isfile(cat_path): fail(f'missing trust catalog: {cat_path}')
if not baseline_domains or not baseline_tier: fail('missing phase0 baselines in dev_notes/unified_trust_layer_v1')
base_domains=read_domains(baseline_domains)
cur_domains=read_domains(cur_allow)
removed=sorted(base_domains-cur_domains)
added=sorted(cur_domains-base_domains)
base_map=read_baseline_tsv(baseline_tier)
cur_map=parse_catalog(cat_path)
retier=[]; cat_shrink=[]
for d,b in sorted(base_map.items()):
    if d not in cur_map: continue
    ct=str(cur_map[d].get('tier','?'))
    if b['tier'] in {'1','2','3'} and ct in {'1','2','3'} and b['tier'] != ct:
        retier.append((d,b['tier'],ct))
    bc=norm_baseline_cats(b['cats'])
    cc=set(cur_map[d].get('categories',[]) or [])
    if bc and not bc.issubset(cc):
        cat_shrink.append((d, ','.join(sorted(bc)), ','.join(sorted(cc))))
exc_dir=os.path.join(root,'tools','trust')
exc_removed=os.path.join(exc_dir,'migration_exceptions_allow_removed.txt')
exc_retier=os.path.join(exc_dir,'migration_exceptions_allow_retier.txt')
exc_cat=os.path.join(exc_dir,'migration_exceptions_allow_category_change.txt')
for p in (exc_removed,exc_retier,exc_cat): ensure_file(p)
allow_removed=read_exceptions(exc_removed)
allow_retier=read_exceptions(exc_retier)
allow_cat=read_exceptions(exc_cat)
bad_removed=[d for d in removed if d not in allow_removed]
bad_retier=[r for r in retier if f"{r[0]}\t{r[1]}\t{r[2]}" not in allow_retier]
bad_cat=[r for r in cat_shrink if f"{r[0]}\t{r[1]}\t{r[2]}" not in allow_cat]
report={
  'root': root,
  'baseline_domains_file': baseline_domains,
  'baseline_tier_map_file': baseline_tier,
  'current_allowlist': cur_allow,
  'counts': {'baseline_domains': len(base_domains), 'current_domains': len(cur_domains), 'added': len(added), 'removed': len(removed), 'retier': len(retier), 'category_shrink': len(cat_shrink)},
  'added': added,
  'removed': removed,
  'retier': [{'domain':d,'from':a,'to':b} for d,a,b in retier],
  'category_shrink': [{'domain':d,'baseline':a,'current':b} for d,a,b in cat_shrink],
}
print(json.dumps(report, indent=2, sort_keys=True))
if bad_removed or bad_retier or bad_cat:
    msgs=[]
    if bad_removed: msgs.append(f"removed domains without exception: {len(bad_removed)}")
    if bad_retier: msgs.append(f"retier changes without exception: {len(bad_retier)}")
    if bad_cat: msgs.append(f"category shrink without exception: {len(bad_cat)}")
    fail('; '.join(msgs))
