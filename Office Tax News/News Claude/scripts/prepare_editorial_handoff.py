"""Turn authored candidate data into a verified future hand-off. No delivery."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone, timedelta
import difflib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
from check_editorial_sources import atomic_json, checkpoint_candidates
from publish_batch import validate_release, prepare_assets

MSK = timezone(timedelta(hours=3))

def commit_handoff(target, release):
    """An atomic, exclusive commit: concurrent writers cannot replace a slot."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.editorial-', suffix='.tmp', dir=target.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        atomic_json(temporary, release)
        os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)

def title_key(text):
    return re.sub(r"[^a-zа-яё0-9]+", " ", text.casefold()).strip()

def check_history(root, items, day):
    db = root / 'state' / 'news_state.sqlite'
    with sqlite3.connect(f'file:{db.as_posix()}?mode=ro', uri=True) as conn:
        rows = conn.execute('select title,act_norm from catalog_entries where catalog_date >= ?',
                            ((datetime.fromisoformat(day)-timedelta(days=30)).date().isoformat(),)).fetchall()
        urls = {row[0] for row in conn.execute('select value from catalog_keys where kind = ?', ('url',))}
    catalog = (root.parent / 'ОПУБЛИКОВАННЫЕ_НОВОСТИ.md').read_text(encoding='utf-8')
    errors = []
    for item in items:
        primary = item['sources'][0]['url']
        if primary in urls or primary in catalog:
            errors.append(f"already published URL: {primary}")
        for old_title, old_act in rows:
            if difflib.SequenceMatcher(None, title_key(item['title']), title_key(old_title)).ratio() >= .9:
                errors.append(f"already published event: {item['title']}")
            if item.get('act') and old_act and title_key(item['act']) == title_key(old_act):
                errors.append(f"already published act: {item['act']}")
    # Reserve a story only once across pending future editorial packages.
    for path in (root / 'pipeline' / 'approved').glob('*_editorial.json'):
        if path.stem <= f'{day}_0000_editorial':
            continue
        existing = json.loads(path.read_text(encoding='utf-8'))
        for old in existing.get('items', []):
            old_urls = {s['url'] for s in old.get('sources', [])[:1]}
            for item in items:
                if item['sources'][0]['url'] in old_urls:
                    errors.append(f"story already reserved in {path.name}")
    if errors:
        raise ValueError('\n'.join(sorted(set(errors))))

def materialize(authored, release_name):
    out=[]
    for raw in authored:
        item=dict(raw)
        for key in ('claim','why_important','source_quote'):
            if not item.get(key):raise ValueError(f'missing authored {key}')
        claim = item['claim']
        publication_claim = item.pop('publication_claim', '')
        primary_quote = item.pop('source_quote')
        item['slug'] = f"{release_name[:16]}-{item['editorial_review']['event_key']}"
        item['caption'] = (item['title']+'\n\n'+(publication_claim+' ' if publication_claim else '')+item.pop('claim')+'\n\nПочему это важно: '+item.pop('why_important')+
                           '\n\n'+'\n'.join('Источник: '+s['url'] for s in item['sources'])+
                           '\n\n#Налоги #АкадемияBEPS #АкадемияБЕПС')
        item['source_verifications'] = [{'url':s['url'],'evidence':[{
            'claim':claim if n == 0 else publication_claim,
            'source_quote':primary_quote if n == 0 else item['publication_date_evidence']['source_quote']}]} for n,s in enumerate(item['sources'])]
        item['channels'] = ['telegram_channel']
        item['image_spec'] = {'badge':'ACADEMY BEPS'}
        out.append(item)
    return out

def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8',errors='backslashreplace')
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('authored_json',type=Path)
    ap.add_argument('--root',type=Path,required=True)
    ap.add_argument('--release',required=True)
    ap.add_argument('--deadline',required=True)
    args=ap.parse_args()
    root=args.root.resolve(); workspace=root.parent
    status_path=workspace/'runtime-logs'/'editorial-preparation-status.json'
    status={'started_at':datetime.now(timezone.utc).isoformat(),'slot':args.release,'verified_materials':0,'delivery_performed':False}
    committed=False
    try:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}_(0900|1300|1700)_editorial',args.release):raise ValueError('invalid release name')
        slot=datetime.strptime(args.release[:15],'%Y-%m-%d_%H%M').replace(tzinfo=MSK)
        if slot <= datetime.now(timezone.utc):raise ValueError('missed-slot backfill is forbidden')
        deadline=datetime.fromisoformat(args.deadline)
        if deadline.tzinfo is None or deadline > slot:raise ValueError('deadline must be aware and precede slot')
        target=root/'pipeline'/'approved'/f'{args.release}.json'
        if target.exists():raise ValueError('existing hand-off must be verified, never overwritten')
        data=json.loads(args.authored_json.read_text(encoding='utf-8-sig'))
        items=materialize(data['candidates'],args.release)
        if len(items)!=10:raise ValueError('exactly ten authored candidates required')
        check_history(root,items,slot.date().isoformat())
        checked=checkpoint_candidates({'candidates':items},workspace/'runtime-logs'/f'{args.release}-source-checks.json',deadline=deadline,timeout=15)
        status['verified_materials']=checked['source_gate_candidate_count']
        if status['verified_materials']!=10:raise ValueError('not all ten sources passed; see source checkpoints')
        for item in items:
            item['primary_source_verified']=True
            item['approval']={'status':'approved','by':'Codex editorial review',
                              'evidence':'Authored factual claim, dated official source, live HTTP 200/exact URL/visible quote, relevance and history review.'}
        release={'date':slot.date().isoformat(),'release':args.release,'items':items}
        validate_release(release,execution=True)
        staged=workspace/'runtime-logs'/f'{args.release}-staged.json'
        atomic_json(staged,release)
        command=[sys.executable,'-X','utf8','-B',str(root/'scripts'/'publish_batch.py'),str(staged),'--root',str(root),'--verify-sources-live']
        subprocess.run(command,check=True,timeout=240)
        assets = prepare_assets(root,release)
        for item in items:
            item.update(image_path=str(assets[item['slug']].resolve()),
                        image_credit='Academy BEPS', image_rights='original artwork')
        if datetime.now(timezone.utc)>=deadline:raise ValueError('deadline elapsed before hand-off commit')
        commit_handoff(target,release)
        committed=True
        command[5]=str(target)
        subprocess.run(command,check=True,timeout=240)
        status.update(result='ready',approved_file=str(target),validation='publish_batch --verify-sources-live passed',handoff_sha256=__import__('hashlib').sha256(target.read_bytes()).hexdigest())
        return_code=0
    except Exception as exc:
        if committed:
            target.replace(workspace/'runtime-logs'/f'{args.release}-failed-final-check.json')
        status.update(result='failed',reason=f'{type(exc).__name__}: {exc}')
        print(status['reason'],file=sys.stderr)
        return_code=1
    status['finished_at']=datetime.now(timezone.utc).isoformat()
    atomic_json(status_path,status)
    atomic_json(workspace/'runtime-logs'/f'{args.release}-preparation-status.json',status)
    print(json.dumps(status,ensure_ascii=False))
    return return_code

if __name__=='__main__':raise SystemExit(main())
