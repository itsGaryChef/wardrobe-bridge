"""Shared scene operations used by both the Blender UI and MCP tools."""
import json
import math
import pathlib
import uuid
import hashlib
import struct
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree
from . import body_rig, clear_mesh_weights, bounds, activate
from .bone_fit import fit as bone_fit, canonical, mapped_bones


def mesh(name):
    obj = bpy.context.scene.objects.get(name)
    if not obj or obj.type != 'MESH': raise ValueError(f'Mesh not found: {name}')
    return obj


def target_surfaces(target):
    rig = body_rig(target)
    tagged = [o for o in bpy.context.scene.objects if o.type == 'MESH' and body_rig(o) == rig and o.get('wb_role') == 'BODY' and not o.get('wb_fit_id')]
    return list(dict.fromkeys([target] + tagged))


def tree_for(objects):
    points, faces = [], []
    for obj in objects:
        start = len(points)
        points.extend(obj.matrix_world @ v.co for v in obj.data.vertices)
        faces.extend([start+i for i in p.vertices] for p in obj.data.polygons)
    if not faces: raise ValueError('Target surfaces have no polygons.')
    return BVHTree.FromPolygons(points, faces)


def skin_samples(objects, rig):
    points, weights = [], []
    for obj in objects:
        names = {g.index: g.name for g in obj.vertex_groups}
        for v in obj.data.vertices:
            w = {names[g.group]: g.weight for g in v.groups if names[g.group] in rig.data.bones and g.weight > 0}
            total = sum(w.values())
            if not total: continue
            points.append(obj.matrix_world @ v.co); weights.append({n: x/total for n, x in w.items()})
    if not points: raise ValueError('Target needs valid skin weights.')
    tree = KDTree(len(points))
    for i, p in enumerate(points): tree.insert(p, i)
    tree.balance()
    return tree, weights


def near_weights(p, tree, samples):
    result = {}
    for _, i, d in tree.find_n(p, 4):
        for name, weight in samples[i].items(): result[name] = result.get(name, 0) + weight / (d+.001)**2
    result = dict(sorted(result.items(), key=lambda item: -item[1])[:4])
    total = sum(result.values())
    return {n: w/total for n, w in result.items()}


def assign(obj, weights, rig):
    clear_mesh_weights(obj)
    for name in sorted({n for w in weights for n in w}): obj.vertex_groups.new(name=name)
    for i, w in enumerate(weights):
        for name, value in w.items(): obj.vertex_groups[name].add([i], value, 'REPLACE')
    arm = obj.modifiers.new('Wardrobe target skin', 'ARMATURE'); arm.object = rig
    arm.use_deform_preserve_volume = True


def body_signature(obj):
    """Exact rest geometry and rig layout; intentionally not an approximate body classifier."""
    rig=body_rig(obj)
    if not rig: return None
    if any(m.type!='ARMATURE' and (m.show_viewport or m.show_render) for m in obj.modifiers): return None
    if obj.data.shape_keys and any(abs(k.value)>1e-7 for k in obj.data.shape_keys.key_blocks[1:]): return None
    digest=hashlib.sha256()
    for v in obj.data.vertices: digest.update(struct.pack('<3f',*v.co))
    digest.update(str(len(obj.data.polygons)).encode())
    inv=obj.matrix_world.inverted()
    for b in sorted(rig.data.bones,key=lambda b:b.name):
        digest.update(b.name.encode());digest.update((b.parent.name if b.parent else '').encode())
        for p in (inv@rig.matrix_world@b.head_local,inv@rig.matrix_world@b.tail_local):
            digest.update(','.join(f'{c:.5f}' for c in p).encode())
        digest.update(','.join(f'{c:.5f}' for row in (inv@rig.matrix_world@b.matrix_local) for c in row).encode())
    return digest.hexdigest()


def exact_weights(garment,rig):
    result=[]
    for v in garment.data.vertices:
        w={garment.vertex_groups[g.group].name:g.weight for g in v.groups if garment.vertex_groups[g.group].name in rig.data.bones and g.weight>0}
        total=sum(w.values())
        if not total: return None
        result.append({n:x/total for n,x in w.items()})
    return result


def source_key(garment):
    """Stable identity used to replace an earlier fit without touching its source."""
    if garment.get('wb_asset_id'):
        return f"asset:{garment['wb_asset_id']}:{garment.get('wb_asset_object', garment.name)}"
    if not garment.get('wb_source_uid'):
        garment['wb_source_uid'] = uuid.uuid4().hex
    return 'scene:' + garment['wb_source_uid']


def remove_object(obj):
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data and not data.users: bpy.data.meshes.remove(data)


def fit_items(names, target_name, source_body_name=None, clearance=.008):
    if bpy.context.mode != 'OBJECT': raise ValueError('Return to Object Mode before fitting.')
    if not 0 <= clearance <= .2 or not math.isfinite(clearance): raise ValueError('Clearance must be between 0 and 0.2 scene units.')
    garments = list(dict.fromkeys(mesh(n) for n in names))
    if any(not g.data.vertices or not g.data.polygons for g in garments): raise ValueError('Wearables need non-empty polygon meshes.')
    target = mesh(target_name); source_body = mesh(source_body_name) if source_body_name else None
    if not garments or target in garments or source_body in garments: raise ValueError('Choose separate wearables and body references.')
    target_rig = body_rig(target)
    if not target_rig: raise ValueError('Target body needs a skin armature.')
    if any(body_rig(g) == target_rig for g in garments): raise ValueError('Source and target must use different rigs. Save/load a source library copy first.')
    if source_body and any(body_rig(g) and body_rig(g) != body_rig(source_body) for g in garments):
        raise ValueError('Source body and wearables must share their source rig.')
    surfaces = target_surfaces(target)
    rigs = {target_rig} | {body_rig(g) for g in garments} | ({body_rig(source_body)} if source_body else set())
    rigs.discard(None); positions = {r: r.data.pose_position for r in rigs}
    old_active = bpy.context.view_layer.objects.active; old_selected = list(bpy.context.selected_objects)
    collection = None; created = []
    keys = {garment: source_key(garment) for garment in garments}
    superseded = [o for o in bpy.context.scene.objects if o.type == 'MESH' and o.get('wb_target') == target.name and o.get('wb_source_key') in set(keys.values())]
    try:
        for r in rigs: r.data.pose_position = 'REST'
        bpy.context.view_layer.update()
        target_tree = tree_for(surfaces); skin, samples = skin_samples(surfaces, target_rig)
        job = uuid.uuid4().hex
        collection = bpy.data.collections.new('Wardrobe fit ' + job[:8]); bpy.context.scene.collection.children.link(collection)
        source_signature=body_signature(source_body) if source_body else None
        exact_match=source_signature is not None and source_signature==body_signature(target)
        reused=[]
        for garment in garments:
            source_rig = body_rig(garment)
            saved_weights=exact_weights(garment,target_rig) if exact_match else None
            if saved_weights:
                transform=target.matrix_world@source_body.matrix_world.inverted()@garment.matrix_world
                coords=[transform@v.co for v in garment.data.vertices];reused.append(garment.name)
            elif source_rig:
                coords, _, _ = bone_fit(garment, source_rig, target_rig, surfaces, source_body=source_body)
            else:
                if not source_body: raise ValueError('Unrigged wearables need a source body reference.')
                lo, hi = bounds(source_body); tlo, thi = bounds(target)
                coords = [Vector(tuple(tlo[j] + ((garment.matrix_world @ v.co)[j]-lo[j]) * (thi[j]-tlo[j])/(hi[j]-lo[j]) for j in range(3))) for v in garment.data.vertices]
            # Smooth the correction field, not the garment topology/details.
            base = [p.copy() for p in coords]; deltas = []
            for p in coords:
                hit, normal, _, distance = target_tree.find_nearest(p)
                signed = (p-hit).dot(normal)
                deltas.append(Vector() if saved_weights else normal * min(max(clearance-signed, 0), .15))
            kd = KDTree(len(base))
            for i, p in enumerate(base): kd.insert(p, i)
            kd.balance()
            for _ in range(3):
                nxt = []
                for i, p in enumerate(base):
                    near = kd.find_n(p, min(10, len(base)))
                    total = sum(1/(d+.01)**2 for _, j, d in near)
                    avg = sum((deltas[j]/(d+.01)**2 for _, j, d in near), Vector())/total
                    nxt.append(deltas[i]*.3 + avg*.7)
                deltas = nxt
            coords = [p+d for p, d in zip(base, deltas)]
            obj = bpy.data.objects.new(garment.name + ' — fit', garment.data.copy()); created.append(obj); collection.objects.link(obj)
            if obj.data.shape_keys: obj.shape_key_clear()
            for v, p in zip(obj.data.vertices, coords): v.co = p
            assign(obj, saved_weights or [near_weights(p, skin, samples) for p in coords], target_rig)
            obj['wb_fit_id'] = job; obj['wb_target'] = target.name; obj['wb_role'] = 'WEARABLE'
            obj['wb_source'] = garment.name; obj['wb_source_key'] = keys[garment]; obj['wb_revision'] = 1
            obj['wb_recipe'] = json.dumps({'source': garment.name, 'source_body': source_body_name, 'target': target.name, 'clearance': clearance, 'adjustments': []})
            obj.data.update()
        # Commit only after every new item succeeded. Re-running GO replaces the
        # earlier generated chain for the same source item and target.
        for old in superseded:
            if old not in created: remove_object(old)
        activate(bpy.context, created[0])
        bpy.context.scene.wb_workflow.last_fit = created[0]
        return {'fit_id': job, 'objects': [o.name for o in created], 'reused_exact_fits': reused, 'status': 'NEEDS_REVIEW', 'message': 'Saved geometry reused for exact body/rig matches; otherwise an automatic first pass. Inspect silhouettes and motion.'}
    except Exception:
        for obj in created:
            data = obj.data; bpy.data.objects.remove(obj, do_unlink=True)
            if not data.users: bpy.data.meshes.remove(data)
        if collection: bpy.data.collections.remove(collection)
        for obj in old_selected: obj.select_set(True)
        bpy.context.view_layer.objects.active = old_active
        raise
    finally:
        for rig, position in positions.items(): rig.data.pose_position = position
        bpy.context.view_layer.update()


REGIONS = ('ALL', 'TORSO', 'SHOULDERS', 'ARMS', 'ELBOWS', 'HIPS', 'LEGS', 'KNEES', 'FEET')


def region_weight(obj, vertex, region, side):
    names = {g.index: canonical(g.name) for g in obj.vertex_groups}
    keys = {'TORSO': ('spine', 'chest', 'neck'), 'SHOULDERS': ('shoulder', 'upperarm'), 'ARMS': ('upperarm','lowerarm','hand'),
            'ELBOWS': ('upperarm','lowerarm'), 'HIPS': ('hips','upperleg'), 'LEGS': ('upperleg','lowerleg'),
            'KNEES': ('upperleg','lowerleg'), 'FEET': ('foot','toes')}
    value = 0
    for g in vertex.groups:
        key = names.get(g.group)
        if not key: continue
        if side != 'BOTH' and not key.endswith('l' if side == 'LEFT' else 'r'): continue
        if region == 'ALL' or key.startswith(keys[region]): value += g.weight
    if region == 'ALL' and side == 'BOTH': value = 1
    if region in {'ELBOWS', 'KNEES'}:
        rig = body_rig(obj); bones = mapped_bones(rig)
        prefix = 'lowerarm' if region == 'ELBOWS' else 'lowerleg'
        p = obj.matrix_world @ vertex.co
        centers = [rig.matrix_world @ bones[prefix+s].head_local for s in ('l','r') if prefix+s in bones and (side == 'BOTH' or s == ('l' if side == 'LEFT' else 'r'))]
        if not centers: return 0
        height = max((rig.matrix_world@b.head_local).z for b in rig.data.bones) - min((rig.matrix_world@b.head_local).z for b in rig.data.bones)
        radius = max(height*.14, .01)
        t = max(0, 1-min((p-c).length for c in centers)/radius)
        value *= t*t*(3-2*t)
    return min(1, value)


def adjust(name, region='ALL', side='BOTH', move=(0,0,0), inflate=0, smoothing=0):
    obj = mesh(name)
    if not obj.get('wb_fit_id'): raise ValueError('Adjust a generated fit; original avatars are protected.')
    if region not in REGIONS or side not in {'BOTH','LEFT','RIGHT'}: raise ValueError('Unknown region or side.')
    if len(move) != 3 or any(not math.isfinite(x) or abs(x) > .5 for x in move) or not math.isfinite(inflate) or abs(inflate) > .2 or not math.isfinite(smoothing) or not 0 <= smoothing <= 1:
        raise ValueError('Adjustment is out of range.')
    rig = body_rig(obj); previous_position = rig.data.pose_position
    rig.data.pose_position = 'REST'
    try:
        previous_data = obj.data.copy(); previous_data.name = obj.data.name + ' — revision backup'
        previous_data.use_fake_user = True
        previous_data['wb_revision'] = int(obj.get('wb_revision', 1))
        previous_data['wb_recipe'] = obj.get('wb_recipe', '{}')
        previous_data['wb_previous_mesh'] = obj.get('wb_previous_mesh', '')
        revised_data = obj.data.copy(); obj.data = revised_data
        obj['wb_previous_mesh'] = previous_data.name
        obj['wb_revision'] = int(obj.get('wb_revision', 1))+1
        points = [v.co.copy() for v in obj.data.vertices]
        # Geometric neighbors also cross UV seams in imported meshes.
        tree = KDTree(len(points))
        for i, p in enumerate(points): tree.insert(p, i)
        tree.balance()
        inv = obj.matrix_world.to_3x3().inverted(); translation = inv @ Vector(move)
        for v in obj.data.vertices:
            w = region_weight(obj, obj.data.vertices[v.index], region, side)
            neighbors = tree.find_n(v.co, min(8, len(points)))
            avg = sum((points[i] for _, i, d in neighbors), Vector())/len(neighbors)
            v.co += (translation + inv @ (obj.matrix_world.to_3x3() @ obj.data.vertices[v.index].normal).normalized()*inflate + (avg-points[v.index])*smoothing)*w
        recipe = json.loads(obj.get('wb_recipe', '{}')); recipe.setdefault('adjustments', []).append({'region': region, 'side': side, 'move': list(move), 'inflate': inflate, 'smoothing': smoothing})
        obj['wb_recipe'] = json.dumps(recipe)
        obj.hide_render = False; obj.hide_set(False); obj.data.update()
        bpy.context.scene.wb_workflow.last_fit = obj; activate(bpy.context, obj)
        return {'object': obj.name, 'previous': obj.name, 'previous_mesh': previous_data.name, 'revision': obj['wb_revision']}
    finally:
        rig.data.pose_position = previous_position


def undo(name):
    obj = mesh(name)
    previous_data = bpy.data.meshes.get(obj.get('wb_previous_mesh', ''))
    if previous_data:
        current = obj.data; obj.data = previous_data; previous_data.use_fake_user = False
        obj['wb_revision'] = int(previous_data.get('wb_revision', 1))
        obj['wb_recipe'] = previous_data.get('wb_recipe', '{}')
        older = previous_data.get('wb_previous_mesh', '')
        if older: obj['wb_previous_mesh'] = older
        elif 'wb_previous_mesh' in obj: del obj['wb_previous_mesh']
        if not current.users: bpy.data.meshes.remove(current)
        bpy.context.scene.wb_workflow.last_fit = obj; activate(bpy.context, obj)
        return {'object': obj.name, 'revision': obj['wb_revision']}
    # Compatibility with revisions created by Wardrobe Bridge 0.5 and older.
    previous = bpy.context.scene.objects.get(obj.get('wb_previous', ''))
    if not previous: raise ValueError('This fit has no earlier adjustment revision.')
    obj.hide_render = True; obj.hide_set(True); previous.hide_render = False; previous.hide_set(False)
    bpy.context.scene.wb_workflow.last_fit = previous; activate(bpy.context, previous)
    return {'object': previous.name, 'revision': previous.get('wb_revision', 1)}


def inspect(name):
    obj = mesh(name); target = mesh(obj.get('wb_target', '')); rig = body_rig(obj)
    position = rig.data.pose_position
    try:
        rig.data.pose_position = 'REST'; bpy.context.view_layer.update(); tree = tree_for(target_surfaces(target))
        samples = list(obj.data.vertices)[::max(1, len(obj.data.vertices)//1500)]
        close_inside = 0
        for v in samples:
            p = obj.matrix_world@v.co; hit, n, _, d = tree.find_nearest(p)
            if d < .05 and (p-hit).dot(n) < -.002: close_inside += 1
        return {'object': name, 'revision': obj.get('wb_revision'), 'vertices': len(obj.data.vertices),
                'unweighted': sum(not any(g.weight > 0 for g in v.groups) for v in obj.data.vertices),
                'max_weight_sum_error': max((abs(sum(g.weight for g in v.groups)-1) for v in obj.data.vertices), default=0),
                'sampled_vertices': len(samples), 'possible_surface_penetrations': close_inside,
                'status': 'NEEDS_REVIEW', 'note': 'Rest-pose nearest-surface heuristic; not a collision guarantee. Render and inspect posed joints.',
                'recipe': json.loads(obj.get('wb_recipe', '{}'))}
    finally:
        rig.data.pose_position = position; bpy.context.view_layer.update()


def preview(names, label='preview', view='FRONT'):
    if view not in {'FRONT','BACK','LEFT','RIGHT'}: raise ValueError('Unknown preview view.')
    objects = [mesh(n) for n in names]
    for obj in list(objects):
        if obj.get('wb_target'):
            target = mesh(obj['wb_target']); rig = body_rig(target)
            objects.extend(o for o in bpy.context.scene.objects if o.type == 'MESH' and body_rig(o) == rig and not o.hide_render and not o.hide_get())
    objects = list(dict.fromkeys(objects))
    value = bpy.context.scene.wb_workflow.render_dir
    if not value: raise ValueError('Choose a persistent render folder first.')
    root = pathlib.Path(bpy.path.abspath(value)).resolve(); root.mkdir(parents=True, exist_ok=True)
    label = ''.join(c if c.isalnum() or c in '_-' else '_' for c in label)[:60] or 'preview'
    path = root / f'{label}_{uuid.uuid4().hex[:12]}.png'
    original_scene = bpy.context.scene
    scene = bpy.data.scenes.new('Wardrobe preview'); linked = set(objects)
    linked.update(body_rig(o) for o in objects if body_rig(o))
    for o in list(linked):
        parent = o.parent
        while parent: linked.add(parent); parent = parent.parent
    hidden = {o: o.hide_render for o in linked}; created = []
    world = bpy.data.worlds.new('Wardrobe studio'); scene.world = world; world.use_nodes = True
    try:
        for o in linked: scene.collection.objects.link(o); o.hide_render = False
        scene.frame_set(original_scene.frame_current)
        deps = bpy.context.evaluated_depsgraph_get()
        points = [o.evaluated_get(deps).matrix_world@Vector(p) for o in objects for p in o.evaluated_get(deps).bound_box]
        lo = Vector(tuple(min(p[i] for p in points) for i in range(3))); hi = Vector(tuple(max(p[i] for p in points) for i in range(3))); center = (hi+lo)/2
        size = max(hi-lo); size = max(size, .1)
        data = bpy.data.cameras.new('Wardrobe camera'); cam = bpy.data.objects.new('Wardrobe camera', data); created.append(cam); scene.collection.objects.link(cam); scene.camera = cam
        rig = next((body_rig(o) for o in objects if body_rig(o)), None); front = Vector((0,-1,0))
        if rig:
            bones = mapped_bones(rig)
            if 'upperarml' in bones and 'upperarmr' in bones: front = (rig.matrix_world@bones['upperarml'].head_local - rig.matrix_world@bones['upperarmr'].head_local).normalized().cross(Vector((0,0,1)))
            if 'footr' in bones and 'toesr' in bones:
                forward=rig.matrix_world@bones['toesr'].head_local-rig.matrix_world@bones['footr'].head_local;forward.z=0
                if forward.length>.001:front=forward.normalized()
        if view=='BACK':front=-front
        elif view=='LEFT':front=Vector((-front.y,front.x,0))
        elif view=='RIGHT':front=Vector((front.y,-front.x,0))
        cam.location = center + front*size*3 + Vector((size*.45,0,size*.3)); cam.rotation_euler = (center-cam.location).to_track_quat('-Z','Y').to_euler(); data.type = 'ORTHO'; data.ortho_scale = size*1.3
        for delta, power in [(front*size*2+Vector((size,0,size*2)), 850), (-front*size+Vector((-size,0,size)), 650)]:
            data = bpy.data.lights.new('Wardrobe softbox','AREA'); data.energy = power; data.size = size*2
            light = bpy.data.objects.new('Wardrobe softbox',data); created.append(light); scene.collection.objects.link(light); light.location = center+delta; light.rotation_euler = (center-light.location).to_track_quat('-Z','Y').to_euler()
        world.node_tree.nodes['Background'].inputs[0].default_value = (.10,.12,.16,1); world.node_tree.nodes['Background'].inputs[1].default_value = .5
        scene.render.engine = 'BLENDER_EEVEE'; scene.render.resolution_x = 900; scene.render.resolution_y = 900; scene.render.resolution_percentage = 100; scene.render.image_settings.file_format = 'PNG'; scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True, scene=scene.name)
        return {'path': str(path), 'frame': original_scene.frame_current, 'view':view}
    finally:
        for o, state in hidden.items(): o.hide_render = state
        bpy.data.scenes.remove(scene)
        for o in created:
            data = o.data; bpy.data.objects.remove(o, do_unlink=True)
            if isinstance(data, bpy.types.Camera): bpy.data.cameras.remove(data)
            else: bpy.data.lights.remove(data)
        bpy.data.worlds.remove(world)
