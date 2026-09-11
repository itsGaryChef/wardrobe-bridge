"""Catalog an external FBX/BVH motion folder without copying its binaries."""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

FORMATS = {'.fbx', '.bvh', '.blend'}

def classify(path):
    text = (' '.join(path.parts) + ' ' + path.stem).casefold()
    if 'pose' in text or path.stem.casefold() == 'tpose': return 'pose'
    groups = [
        ('dance', ('dance','samba','breakdance','bboy','moonwalk','shuffle')),
        ('idle', ('idle','breath','standing')),
        ('walk', ('walk','locomotion','strafe','limp')),
        ('run', ('run','jog','sprint')),
        ('jump', ('jump','fall','land')),
        ('combat', ('rifle','gun','pistol','sword','knife','stab','punch','kick','fight','block','grenade','bow','arrow','death','hit')),
        ('gesture', ('wave','salute','thank','talk','greet','point','taunt','dismiss')),
        ('sport', ('baseball','golf','fitness','workout','goalkeeper')),
        ('interaction', ('carry','door','sit','lay','climb','ladder','crawl','kneel','grab','hang')),
    ]
    for category, words in groups:
        if any(word in text for word in words): return category
    return 'other'

def catalog(root):
    clips=[]
    for path in sorted(root.rglob('*')):
        suffix = path.suffix.casefold()
        if not path.is_file() or suffix not in FORMATS or path.name.casefold().endswith('.blend1'): continue
        rel = path.relative_to(root)
        source = rel.parts[0] if len(rel.parts)>1 else 'Unsorted'
        kind = 'pose' if 'poses' in {p.casefold() for p in rel.parts} else ('blend_library' if suffix=='.blend' else 'animation')
        clips.append({'id': re.sub(r'[^a-z0-9]+','-',str(rel.with_suffix('')).casefold()).strip('-'),
                      'name': path.stem, 'source': source, 'kind': kind, 'category': classify(rel),
                      'format': suffix[1:].upper(), 'relative_path': rel.as_posix(), 'bytes': path.stat().st_size,
                      'license_status': 'UNVERIFIED_LOCAL_ONLY', 'fps': None, 'frame_start': None, 'frame_end': None,
                      'loop': None, 'root_motion': None})
    return {'schema':1, 'root':str(root), 'redistributable':False, 'clips':clips}

if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();data=catalog(args.root.resolve());args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(data,indent=2),encoding='utf-8')
    print(json.dumps({'clips':len(data['clips']),'categories':Counter(c['category'] for c in data['clips'])},default=dict))

