"""Humanoid pose/action retargeting for VRM, Mixamo, and common rig names."""
import bpy
from mathutils import Matrix, Vector
from .bone_fit import mapped_bones


def armature(name):
    obj = bpy.context.scene.objects.get(name)
    if not obj or obj.type != 'ARMATURE': raise ValueError(f'Armature not found: {name}')
    return obj


def mapping(source_name, target_name):
    source, target = armature(source_name), armature(target_name)
    if source == target: raise ValueError('Choose different source and target armatures.')
    sm, tm = mapped_bones(source), mapped_bones(target)
    common = sorted(sm.keys() & tm.keys())
    pairs = [{'human_bone': key, 'source': sm[key].name, 'target': tm[key].name} for key in common]
    return {'source': source.name, 'target': target.name, 'mapped': pairs,
            'source_only': sorted(sm.keys()-tm.keys()), 'target_only': sorted(tm.keys()-sm.keys()),
            'status': 'READY' if {'hips','spine','head'} <= set(common) and len(common) >= 10 else 'PARTIAL'}


def rig_height(rig):
    points = [rig.matrix_world @ point for b in rig.data.bones for point in (b.head_local, b.tail_local)]
    return max(p.z for p in points)-min(p.z for p in points) if points else 1.0


def retarget(source_name, target_name, action_name, output_name='', frame_start=None, frame_end=None, step=1, root_motion=True):
    source, target = armature(source_name), armature(target_name)
    report = mapping(source_name, target_name)
    if report['status'] == 'PARTIAL':
        raise ValueError(f"Incomplete humanoid map ({len(report['mapped'])} bones). Need hips, spine, head, and at least 10 recognized bones.")
    action = bpy.data.actions.get(action_name)
    if not action: raise ValueError(f'Action not found: {action_name}')
    if not 1 <= step <= 100: raise ValueError('Frame step must be between 1 and 100.')
    first = int(action.frame_range[0] if frame_start is None else frame_start)
    last = int(action.frame_range[1] if frame_end is None else frame_end)
    if first > last or last-first > 100000: raise ValueError('Choose a valid animation frame range.')
    sm, tm = mapped_bones(source), mapped_bones(target); common = sorted(sm.keys() & tm.keys())
    old_frame = bpy.context.scene.frame_current
    source.animation_data_create(); target.animation_data_create()
    old_source_action = source.animation_data.action; old_target_action = target.animation_data.action
    output = bpy.data.actions.new(output_name.strip() or f'{action.name} — {target.name}')
    output['wb_retarget_source_action'] = action.name; output['wb_retarget_source_rig'] = source.name
    output['wb_retarget_target_rig'] = target.name
    source_scale = max(rig_height(source), 1e-6); scale = rig_height(target)/source_scale
    source.animation_data.action = action; target.animation_data.action = output
    try:
        frames = list(range(first, last+1, step))
        if frames[-1] != last: frames.append(last)
        for frame in frames:
            bpy.context.scene.frame_set(frame); bpy.context.view_layer.update()
            for pb in target.pose.bones:
                pb.location = Vector(); pb.rotation_mode = 'QUATERNION'; pb.rotation_quaternion.identity(); pb.scale = (1,1,1)
            bpy.context.view_layer.update()
            for key in common:
                spb = source.pose.bones[sm[key].name]; tpb = target.pose.bones[tm[key].name]
                source_rest = source.matrix_world @ sm[key].matrix_local
                source_pose = source.matrix_world @ spb.matrix
                target_rest = target.matrix_world @ tm[key].matrix_local
                delta = source_pose.to_quaternion() @ source_rest.to_quaternion().inverted()
                location = target_rest.translation.copy()
                if key == 'hips' and root_motion:
                    location += (source_pose.translation-source_rest.translation)*scale
                desired = Matrix.LocRotScale(location, delta @ target_rest.to_quaternion(), Vector((1,1,1)))
                tpb.matrix = target.matrix_world.inverted() @ desired
                tpb.rotation_mode = 'QUATERNION'
                tpb.keyframe_insert('rotation_quaternion', frame=frame, group=tpb.name)
                if key == 'hips': tpb.keyframe_insert('location', frame=frame, group=tpb.name)
            bpy.context.view_layer.update()
        output['wb_retarget_mapped_bones'] = len(common)
        return {'action': output.name, 'frames': [first,last], 'step': step, 'mapped_bones': len(common),
                'root_motion': root_motion, 'status': 'BAKED', 'mapping': report}
    except Exception:
        target.animation_data.action = old_target_action
        bpy.data.actions.remove(output)
        raise
    finally:
        source.animation_data.action = old_source_action
        bpy.context.scene.frame_set(old_frame)
