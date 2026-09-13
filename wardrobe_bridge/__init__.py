bl_info = {
    'name': 'Wardrobe Bridge', 'author': 'Gary / Codex', 'version': (0, 10, 0),
    'blender': (4, 2, 0), 'location': 'View3D > Sidebar > Wardrobe',
    'description': 'Personal wearable library, automated fit previews, regional revisions, and agent MCP bridge',
    'category': 'Object',
}

import bpy
import bmesh
from bpy.props import PointerProperty, FloatProperty, BoolProperty, EnumProperty
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def mesh_only(self, obj):
    return obj.type == 'MESH'


class WBSettings(bpy.types.PropertyGroup):
    source: PointerProperty(name='Source body', type=bpy.types.Object, poll=mesh_only)
    target: PointerProperty(name='Target body', type=bpy.types.Object, poll=mesh_only)
    garment: PointerProperty(name='Clothing mesh', type=bpy.types.Object, poll=mesh_only)
    offset: FloatProperty(name='Surface clearance', default=0.005, min=0, subtype='DISTANCE')
    strength: FloatProperty(name='Shape adaptation', default=1, min=0, max=1)
    smooth: BoolProperty(name='Smooth transferred weights', default=True)
    template: EnumProperty(name='Template', items=[('SKIRT', 'Skirt', 'Open skirt shell'), ('CUFF', 'Cuff / bracelet', 'Open cylindrical accessory')])


def bounds(obj):
    points = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    lo = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    hi = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    if min(hi - lo) < 1e-6:
        raise ValueError('Body bounds must have nonzero width, depth, and height.')
    return lo, hi


def activate(context, obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    context.view_layer.objects.active = obj


def body_rig(obj):
    return next((m.object for m in obj.modifiers if m.type == 'ARMATURE' and m.object), None)


def clear_mesh_weights(obj):
    obj.vertex_groups.clear()
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        layer = bm.verts.layers.deform.active
        if layer:
            for vertex in bm.verts:
                vertex[layer].clear()
        bm.to_mesh(obj.data)
    finally:
        bm.free()


def validate(s):
    if not all((s.source, s.target, s.garment)):
        raise ValueError('Choose a source body, target body, and separate clothing mesh.')
    if len({s.source, s.target, s.garment}) != 3:
        raise ValueError('Source, target, and clothing must be three different objects.')
    rig = body_rig(s.target)
    if not rig:
        raise ValueError('Target body needs an Armature modifier with a rig assigned.')
    names = {b.name for b in rig.data.bones if b.use_deform}
    groups = {g.index for g in s.target.vertex_groups if g.name in names}
    if not any(g.group in groups and g.weight > 0 for v in s.target.data.vertices for g in v.groups):
        raise ValueError('Target body has no deform-bone weights to transfer.')
    if not s.source.data.polygons or not s.target.data.polygons:
        raise ValueError('Both bodies need polygon surfaces.')
    if any(body_rig(o) and body_rig(o).data.pose_position != 'REST' for o in (s.source, s.target)):
        raise ValueError('Set both armatures to Rest Position before fitting; match their rest-pose orientation.')
    return rig, names


def transfer(context, garment, target, rig, bone_names, smooth):
    activate(context, garment)
    clear_mesh_weights(garment)
    mod = garment.modifiers.new('Target skin weights', 'DATA_TRANSFER')
    while garment.modifiers.find(mod.name) > 0:
        bpy.ops.object.modifier_move_up(modifier=mod.name)
    mod.object = target
    mod.use_vert_data = True
    mod.data_types_verts = {'VGROUP_WEIGHTS'}
    mod.vert_mapping = 'POLYINTERP_NEAREST'
    mod.layers_vgroup_select_src = 'ALL'
    mod.layers_vgroup_select_dst = 'NAME'
    bpy.ops.object.datalayout_transfer(modifier=mod.name)
    bpy.ops.object.modifier_apply(modifier=mod.name)
    for group in list(garment.vertex_groups):
        if group.name not in bone_names:
            garment.vertex_groups.remove(group)
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        bpy.ops.mesh.select_all(action='SELECT')
        if smooth:
            bpy.ops.object.vertex_group_smooth(group_select_mode='ALL', factor=0.3, repeat=3)
        bpy.ops.object.vertex_group_limit_total(group_select_mode='ALL', limit=4)
        bpy.ops.object.vertex_group_normalize_all(group_select_mode='ALL', lock_active=False)
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')
    arm = garment.modifiers.new('Target rig', 'ARMATURE')
    arm.object = rig
    arm.use_deform_preserve_volume = True
    while garment.modifiers.find(arm.name) > 0:
        bpy.ops.object.modifier_move_up(modifier=arm.name)
    return sum(not any(g.weight > 1e-6 for g in v.groups) for v in garment.data.vertices)


class WB_OT_transfer(bpy.types.Operator):
    bl_idname = 'wardrobe.transfer'
    bl_label = 'Create Fitted Clothing Copy'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        s = context.scene.wardrobe_bridge
        result = None
        old_selected = list(context.selected_objects)
        old_active = context.view_layer.objects.active
        try:
            rig, names = validate(s)
            slo, shi = bounds(s.source)
            tlo, thi = bounds(s.target)
            scale = Vector(tuple((thi[i] - tlo[i]) / (shi[i] - slo[i]) for i in range(3)))
            def align(p):
                return Vector(tuple(tlo[i] + (p[i] - slo[i]) * scale[i] for i in range(3)))
            src_points = [align(s.source.matrix_world @ v.co) for v in s.source.data.vertices]
            target_points = [s.target.matrix_world @ v.co for v in s.target.data.vertices]
            src_tree = BVHTree.FromPolygons(src_points, [list(p.vertices) for p in s.source.data.polygons])
            dst_tree = BVHTree.FromPolygons(target_points, [list(p.vertices) for p in s.target.data.polygons])
            result = bpy.data.objects.new(s.garment.name + '_fitted', s.garment.data.copy())
            context.collection.objects.link(result)
            # Bake only base geometry into world space: no source armature or shape keys.
            if result.data.shape_keys:
                result.shape_key_clear()
            for v, original in zip(result.data.vertices, s.garment.data.vertices):
                p = align(s.garment.matrix_world @ original.co)
                near, normal, index, distance = src_tree.find_nearest(p)
                if near is None:
                    raise ValueError('Could not find a source surface.')
                dest, dn, di, dd = dst_tree.find_nearest(near)
                if dest is None:
                    raise ValueError('Could not find a target surface.')
                # Preserve garment volume/detail relative to its source-body surface.
                p += (dest - near) * s.strength
                hit, n, idx, dist = dst_tree.find_nearest(p)
                signed = (p - hit).dot(n)
                if signed < s.offset:
                    p += n * (s.offset - signed)
                v.co = p
            result.data.update()
            missing = transfer(context, result, s.target, rig, names, s.smooth)
            self.report({'WARNING'} if missing else {'INFO'},
                        f'Created {result.name}. {missing} unweighted vertices. Test poses and inspect fit.')
            return {'FINISHED'}
        except Exception as exc:
            if result:
                mesh = result.data
                bpy.data.objects.remove(result, do_unlink=True)
                if mesh.users == 0:
                    bpy.data.meshes.remove(mesh)
            for obj in old_selected:
                obj.select_set(True)
            context.view_layer.objects.active = old_active
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class WB_OT_bone_fit(bpy.types.Operator):
    bl_idname = 'wardrobe.bone_fit'
    bl_label = 'Create Bone-Guided Fit Preview'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        from .bone_fit import fit
        s = context.scene.wardrobe_bridge
        result = None
        try:
            if not s.garment or not s.target or s.garment == s.target:
                raise ValueError('Choose a weighted garment and a different target body.')
            sr, tr = body_rig(s.garment), body_rig(s.target)
            if not sr or not tr or sr == tr:
                raise ValueError('Garment and target need separate humanoid armatures.')
            if any(r.data.pose_position != 'REST' for r in (sr, tr)):
                raise ValueError('Set both armatures to Rest Position first.')
            targets = [o for o in context.scene.objects if o.type == 'MESH' and body_rig(o) == tr and o.visible_get()]
            points, weights, scales = fit(s.garment, sr, tr, targets, source_body=s.source)
            result = bpy.data.objects.new(s.garment.name + '_bone_fit', s.garment.data.copy())
            context.collection.objects.link(result)
            if result.data.shape_keys:
                result.shape_key_clear()
            clear_mesh_weights(result)
            for v, p in zip(result.data.vertices, points):
                v.co = p
            for name in sorted({name for w in weights for name in w}):
                result.vertex_groups.new(name=name)
            for i, w in enumerate(weights):
                for name, value in w.items():
                    result.vertex_groups[name].add([i], value, 'REPLACE')
            mod = result.modifiers.new('Target rig', 'ARMATURE')
            mod.object = tr
            mod.use_deform_preserve_volume = True
            activate(context, result)
            self.report({'INFO'}, 'Bone-guided preview created. Refine silhouette and coverage before use.')
            return {'FINISHED'}
        except Exception as exc:
            if result:
                mesh = result.data
                bpy.data.objects.remove(result, do_unlink=True)
                if mesh.users == 0:
                    bpy.data.meshes.remove(mesh)
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class WB_OT_template(bpy.types.Operator):
    bl_idname = 'wardrobe.template'
    bl_label = 'Create Editable Template'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        import math
        s = context.scene.wardrobe_bridge
        if not s.target:
            self.report({'ERROR'}, 'Choose a target body first.')
            return {'CANCELLED'}
        try:
            lo, hi = bounds(s.target)
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        size = hi - lo
        center = (hi + lo) / 2
        skirt = s.template == 'SKIRT'
        vertices, faces = [], []
        for row in range(9):
            t = row / 8
            z = lo.z + size.z * (0.40 + 0.18 * t) if skirt else context.scene.cursor.location.z + size.z * 0.035 * t
            rx = size.x * (0.29 - 0.09 * t) if skirt else size.z * 0.035
            ry = size.y * (0.58 - 0.15 * t) if skirt else size.z * 0.035
            cx = center.x if skirt else context.scene.cursor.location.x
            cy = center.y if skirt else context.scene.cursor.location.y
            for col in range(64):
                a = col * 2 * math.pi / 64
                vertices.append((cx + rx * math.cos(a), cy + ry * math.sin(a), z))
                if row < 8:
                    n = (col + 1) % 64
                    faces.append((row * 64 + col, row * 64 + n, (row + 1) * 64 + n, (row + 1) * 64 + col))
        mesh = bpy.data.meshes.new('Wardrobe template')
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        obj = bpy.data.objects.new('Editable skirt' if skirt else 'Editable cuff', mesh)
        context.collection.objects.link(obj)
        activate(context, obj)
        solid = obj.modifiers.new('Fabric thickness', 'SOLIDIFY')
        solid.thickness = size.z * 0.001
        self.report({'INFO'}, 'Template created. Edit its fit before rigging; cuff is placed at the 3D cursor.')
        return {'FINISHED'}


class WB_OT_weights(bpy.types.Operator):
    bl_idname = 'wardrobe.weights'
    bl_label = 'Rig Selected Mesh to Target'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and context.active_object and context.active_object.type == 'MESH'

    def execute(self, context):
        target = context.scene.wardrobe_bridge.target
        original = context.active_object
        rig = body_rig(target) if target else None
        names = {b.name for b in rig.data.bones if b.use_deform} if rig else set()
        if not rig or target == original or not any(g.name in names for g in target.vertex_groups):
            self.report({'ERROR'}, 'Choose a weighted target body and select a different clothing mesh.')
            return {'CANCELLED'}
        copy = original.copy()
        copy.data = original.data.copy()
        copy.name = original.name + '_rigged'
        context.collection.objects.link(copy)
        for m in list(copy.modifiers):
            if m.type == 'ARMATURE':
                copy.modifiers.remove(m)
        try:
            missing = transfer(context, copy, target, rig, names, context.scene.wardrobe_bridge.smooth)
        except Exception as exc:
            mesh = copy.data
            bpy.data.objects.remove(copy, do_unlink=True)
            bpy.data.meshes.remove(mesh)
            activate(context, original)
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'WARNING'} if missing else {'INFO'}, f'Created rigged copy; {missing} unweighted vertices. Inspect in motion.')
        return {'FINISHED'}


class WB_PT_panel(bpy.types.Panel):
    bl_label = 'Manual Fitting Tools'
    bl_idname = 'WB_PT_panel'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Wardrobe'
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 90

    def draw(self, context):
        layout = self.layout
        s = context.scene.wardrobe_bridge
        layout.label(text='Match rest poses; Z up, same facing.', icon='INFO')
        for prop in ('source', 'target', 'garment', 'strength', 'offset', 'smooth'):
            layout.prop(s, prop)
        layout.operator('wardrobe.transfer', icon='MOD_CLOTH')
        layout.operator('wardrobe.bone_fit', icon='ARMATURE_DATA')
        layout.separator()
        layout.label(text='Outfits and accessories')
        layout.prop(s, 'template')
        layout.operator('wardrobe.template', icon='MESH_CYLINDER')
        layout.operator('wardrobe.weights', icon='ARMATURE_DATA')
        layout.label(text='Always inspect shoulders, hips, and poses.')


classes = (WBSettings, WB_OT_transfer, WB_OT_bone_fit, WB_OT_template, WB_OT_weights, WB_PT_panel)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.wardrobe_bridge = PointerProperty(type=WBSettings)
    from . import ui
    ui.register()


def unregister():
    from . import ui
    ui.unregister()
    del bpy.types.Scene.wardrobe_bridge
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == '__main__':
    register()
