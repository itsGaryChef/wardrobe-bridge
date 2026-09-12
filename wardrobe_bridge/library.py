"""Portable, per-user wearable library. Blender IDs are stored with their dependencies."""
import json
import pathlib
import uuid
import bpy

CATEGORIES = ('SOURCE_AVATAR', 'OUTFIT', 'SHIRT', 'PANTS', 'SHOES', 'ACCESSORY')
CATEGORY_ORDER = {name: index for index, name in enumerate(CATEGORIES)}


def infer_category(row):
    if row.get('kind') == 'AVATAR': return 'SOURCE_AVATAR'
    name = row.get('name', '').casefold()
    if any(word in name for word in ('trouser', 'pants', 'shorts')): return 'PANTS'
    if any(word in name for word in ('boot', 'shoe', 'sneaker')): return 'SHOES'
    if any(word in name for word in ('shirt', 'tee', 'jacket', 'coat')) and 'outfit' not in name: return 'SHIRT'
    if any(word in name for word in ('outfit', 'suit', 'armor', 'armour', 'vest')): return 'OUTFIT'
    return 'ACCESSORY'


def normalize(row):
    row = dict(row)
    category = row.get('category') or infer_category(row)
    row['category'] = category if category in CATEGORIES else infer_category(row)
    row['source_avatar'] = (row.get('source_avatar') or ('Unsorted' if row.get('kind') != 'AVATAR' else row.get('name')) or 'Unsorted').strip()
    return row


def preferences():
    addon=bpy.context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def folder():
    prefs=preferences()
    value = prefs.library_root if prefs and prefs.library_root else bpy.context.scene.wb_workflow.library_dir
    if not value:
        raise ValueError('Choose your master library folder first.')
    return pathlib.Path(bpy.path.abspath(value)).resolve()


def index():
    path = folder() / 'wardrobe-library.json'
    if not path.exists():
        return {'schema': 1, 'assets': []}
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema') != 1 or not isinstance(data.get('assets'), list):
        raise ValueError('Unsupported wardrobe library format.')
    data['assets'] = [normalize(row) for row in data['assets']]
    return data


def inside(relative):
    root = folder()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Library entry points outside its library.')
    return path


def capture(objects, name, kind='WEARABLE', source_body=None, category=None, source_avatar=None):
    from . import body_rig
    objects = list(dict.fromkeys(objects))
    if not name.strip() or kind not in {'AVATAR', 'WEARABLE'}:
        raise ValueError('Choose a name and asset type.')
    category = 'SOURCE_AVATAR' if kind == 'AVATAR' else (category or 'OUTFIT')
    if category not in CATEGORIES or (kind == 'AVATAR' and category != 'SOURCE_AVATAR'):
        raise ValueError('Choose a valid inventory category.')
    source_avatar = (source_avatar or (name if kind == 'AVATAR' else 'Unsorted')).strip()
    meshes = [o for o in objects if o.type == 'MESH']
    if kind == 'AVATAR':
        selected_rigs = {o for o in objects if o.type == 'ARMATURE'}
        meshes = list(dict.fromkeys(meshes + [o for o in bpy.context.scene.objects if o.type == 'MESH' and body_rig(o) in selected_rigs]))
        objects = list(dict.fromkeys(objects+meshes))
    if not meshes:
        raise ValueError('Select at least one mesh to save.')
    rigs = {body_rig(o) for o in meshes} - {None}
    if len(rigs) > 1:
        raise ValueError('Save one avatar/rig at a time.')
    if kind == 'WEARABLE' and source_body in meshes:
        raise ValueError('Select the wearables only; the source body is included separately.')
    if source_body and rigs and body_rig(source_body) not in rigs:
        raise ValueError('The source body must use the wearable rig.')
    raw_placement = kind == 'WEARABLE' and not rigs and not source_body
    included = set(objects) | rigs
    if source_body:
        included.add(source_body)
        if body_rig(source_body): included.add(body_rig(source_body))
    if kind == 'AVATAR' and rigs:
        included.update(o for o in bpy.context.scene.objects if o.type == 'MESH' and body_rig(o) in rigs and not o.get('wb_fit_id'))
    for obj in list(included):
        parent = obj.parent
        while parent:
            included.add(parent); parent = parent.parent
    data = index()
    root = folder(); root.mkdir(parents=True, exist_ok=True)
    key = uuid.uuid4().hex
    relative = f'assets/{key}.blend'
    path = inside(relative); path.parent.mkdir(exist_ok=True)
    # Pack textures referenced by these meshes so each saved asset is portable.
    for obj in included:
        if obj.type != 'MESH': continue
        for mat in obj.data.materials:
            if mat and mat.use_nodes:
                for node in mat.node_tree.nodes:
                    if node.type == 'TEX_IMAGE' and node.image and node.image.source == 'FILE' and node.image.size[0]:
                        node.image.pack()
    bpy.data.libraries.write(str(path), included, path_remap='RELATIVE_ALL', fake_user=True, compress=True)
    row = {'id': key, 'name': name.strip(), 'kind': kind, 'blend': relative,
           'objects': [o.name for o in included],
           'wearables': [o.name for o in meshes] if kind == 'WEARABLE' else [o.name for o in included if o.type == 'MESH' and o.get('wb_role') == 'WEARABLE'],
           'bodies': [o.name for o in included if o.type == 'MESH' and (o == source_body or o.get('wb_role') == 'BODY')],
           'source_body': source_body.name if source_body else None, 'preview': None,
           'category': category, 'source_avatar': source_avatar,
           'readiness': 'RAW_PLACEMENT' if raw_placement else 'READY',
           'hidden': [o.name for o in included if o.hide_render] if kind == 'AVATAR' else []}
    data['assets'].append(row)
    temp = root / ('index-' + key + '.tmp')
    temp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temp.replace(root / 'wardrobe-library.json')
    return row


def load(key):
    row = next((r for r in index()['assets'] if r['id'] == key), None)
    if not row: raise ValueError('Library item not found. Refresh the inventory.')
    path = inside(row['blend'])
    if not path.is_file(): raise ValueError('The saved asset file is missing.')
    with bpy.data.libraries.load(str(path), link=False) as (src, dst):
        if not set(row['objects']) <= set(src.objects): raise ValueError('Library object references are incomplete.')
        dst.objects = list(row['objects'])
    mapping = dict(zip(row['objects'], dst.objects))
    collection = bpy.data.collections.new(row['name'])
    bpy.context.scene.collection.children.link(collection)
    for original, obj in mapping.items():
        collection.objects.link(obj)
        obj.hide_render = original in row.get('hidden',[]); obj.hide_set(obj.hide_render)
        obj['wb_asset_id'] = key
        obj['wb_asset_object'] = original
        # Imported saved fits become source assets; stale scene references must not follow them.
        for prop in ('wb_fit_id','wb_target','wb_previous','wb_revision'):
            if prop in obj: del obj[prop]
        if original in row['wearables']: obj['wb_role'] = 'WEARABLE'
        elif original in row['bodies']: obj['wb_role'] = 'BODY'
    return row, collection, mapping


def set_preview(key, png_path):
    import shutil
    data = index(); row = next(r for r in data['assets'] if r['id'] == key)
    relative = f'previews/{key}.png'; destination = inside(relative); destination.parent.mkdir(exist_ok=True)
    shutil.copy2(png_path, destination)
    row['preview'] = relative
    temp = folder() / ('preview-' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(data, indent=2), encoding='utf-8'); temp.replace(folder() / 'wardrobe-library.json')
