"""Bone-guided fitting for weighted garments without a complete source body."""
import numpy as np
from mathutils import Vector, Matrix


def canonical(name):
    spaced = name.lower().strip()
    for side, suffix in [('left', 'l'), ('right', 'r')]:
        for part,key in [('leg','upperleg'),('knee','lowerleg'),('ankle','foot'),('toe','toes'),('arm','upperarm'),('elbow','lowerarm'),('wrist','hand'),('shoulder','shoulder')]:
            if spaced == side+' '+part:return key+suffix
    arp={'root.x':'hips','spine_01.x':'spine','spine_02.x':'chest','spine_03.x':'chest','neck.x':'neck','head.x':'head'}
    for side in ('l','r'):
        for part,key in [('arm_stretch','upperarm'),('arm_twist','upperarm'),('forearm_stretch','lowerarm'),('forearm_twist','lowerarm'),('thigh_stretch','upperleg'),('thigh_twist','upperleg'),('leg_stretch','lowerleg'),('leg_twist','lowerleg'),('toes_01','toes')]:arp[part+'.'+side]=key+side
    if spaced in arp:return arp[spaced]
    n = name.split(':')[-1].lower().replace('_', '').replace('.', '')
    aliases = {'hips': 'hips', 'spine': 'spine', 'spine1': 'chest', 'chest': 'chest', 'neck': 'neck', 'head': 'head'}
    for side, suffix in [('left', 'l'), ('right', 'r')]:
        for mix, vrm, key in [('shoulder','shoulder','shoulder'),('arm','upperarm','upperarm'),('forearm','lowerarm','lowerarm'),('hand','hand','hand'),('upleg','upperleg','upperleg'),('leg','lowerleg','lowerleg'),('foot','foot','foot'),('toebase','toes','toes')]:
            aliases[side+mix] = key+suffix
            aliases[vrm+suffix] = key+suffix
            aliases[side+vrm] = key+suffix
            aliases[suffix+vrm] = key+suffix
            aliases['jbip'+suffix+vrm] = key+suffix
    return aliases.get(n)


def mapped_bones(rig):
    result={};priorities={}
    for bone in rig.data.bones:
        key=canonical(bone.name)
        if not key:continue
        priority=0 if 'twist' in bone.name.lower() else 3 if ('stretch' in bone.name.lower() or bone.name.lower()=='spine_03.x') else 2
        if key not in result or priority>priorities[key]:result[key]=bone;priorities[key]=priority
    return result


def frame(rig, bones, key):
    b = bones[key]
    ends = {'hips':'spine','spine':'chest','chest':'neck','neck':'head'}
    for side in ('l','r'):
        for a,z in [('shoulder','upperarm'),('upperarm','lowerarm'),('lowerarm','hand'),('upperleg','lowerleg'),('lowerleg','foot'),('foot','toes')]: ends[a+side]=z+side
    head = rig.matrix_world @ b.head_local
    end = rig.matrix_world @ bones[ends[key]].head_local if ends.get(key) in bones else rig.matrix_world @ b.tail_local
    axis = (end-head).normalized()
    # Anatomical forward; works with opposing world-space facing directions.
    lateral = (rig.matrix_world @ bones['upperarml'].head_local - rig.matrix_world @ bones['upperarmr'].head_local).normalized()
    front = Vector((0,0,1)).cross(lateral).normalized()
    depth = (front-axis*front.dot(axis)).normalized()
    if depth.length < .1: depth = Vector((0,1,0))
    width = axis.cross(depth).normalized()
    basis = Matrix((width, depth, axis)).transposed()
    return head, basis, max((end-head).length, .01)


def fit(garment, source_rig, target_rig, target_meshes, ease=1.06, source_body=None):
    source, target = mapped_bones(source_rig), mapped_bones(target_rig)
    common = source.keys() & target.keys()
    required = {'hips','spine','chest','upperarml','upperarmr','upperlegl','upperlegr'}
    if not required <= common:
        raise ValueError('Bone-guided fit needs recognized humanoid torso and limb names on both rigs.')
    frames = {k:(frame(source_rig,source,k),frame(target_rig,target,k)) for k in common}
    def samples(meshes, which):
        out={k:[] for k in common}
        for obj in meshes:
            groups={g.index:canonical(g.name) for g in obj.vertex_groups}
            for v in obj.data.vertices:
                weights=[(g.weight,groups.get(g.group)) for g in v.groups if groups.get(g.group) in common]
                if not weights:continue
                w,k=max(weights)
                h,b,l=frames[k][which]
                p=b.transposed() @ (obj.matrix_world @ v.co-h)
                out[k].append((abs(p.x),abs(p.y)))
        return out
    ss,ts=samples([source_body or garment],0),samples(target_meshes,1)
    scales={}
    for k in common:
        length_ratio=frames[k][1][2]/frames[k][0][2]
        if len(ss[k])>12 and len(ts[k])>12:
            a=np.quantile(ss[k],.9,axis=0);b=np.quantile(ts[k],.9,axis=0)
            radial=np.clip(b/np.maximum(a,.008)*ease,.5,5)
        else:radial=np.array([1.5,1.5])
        scales[k]=Vector((float(radial[0]),float(radial[1]),length_ratio))
    groups={g.index:canonical(g.name) for g in garment.vertex_groups}
    result=[]; weights=[]
    # A continuous polyharmonic warp avoids seams where unlike bone lengths meet.
    control_source=[];control_target=[]
    for k in sorted(common):
        if k.startswith(('hand','toes')) or k=='head':continue
        sh,sb,sl=frames[k][0];th,tb,tl=frames[k][1]
        control_source.append(list(sh));control_target.append(list(th))
        if len(ss[k])>12 and len(ts[k])>12:
            a=np.quantile(ss[k],.95,axis=0);b=np.quantile(ts[k],.98,axis=0)*ease
            for axis in (0,1):
                for sign in (-1,1):
                    p=sh+sb.col[2]*(sl*.4)+sb.col[axis]*float(a[axis])*sign
                    q=th+tb.col[2]*(tl*.4)+tb.col[axis]*float(b[axis])*sign
                    control_source.append(list(p));control_target.append(list(q))
    a=np.array(control_source);b=np.array(control_target)
    # Merge coincident anatomical anchors before solving.
    _,indices=np.unique(np.round(a,5),axis=0,return_index=True);a=a[indices];b=b[indices]
    d=np.linalg.norm(a[:,None,:]-a[None,:,:],axis=2)
    p=np.column_stack((np.ones(len(a)),a))
    system=np.block([[d+np.eye(len(a))*.0001,p],[p.T,np.zeros((4,4))]])
    solution=np.linalg.solve(system,np.vstack((b,np.zeros((4,3)))))
    original=np.array([list(garment.matrix_world @ v.co) for v in garment.data.vertices])
    warped=np.linalg.norm(original[:,None,:]-a[None,:,:],axis=2)@solution[:-4]+np.column_stack((np.ones(len(original)),original))@solution[-4:]
    for v in garment.data.vertices:
        p=garment.matrix_world @ v.co
        ww=[(g.weight,groups.get(g.group)) for g in v.groups if groups.get(g.group) in common and g.weight>0]
        total=sum(w for w,k in ww)
        if total<1e-6:raise ValueError(f'Unmapped garment weights at vertex {v.index}')
        q=Vector(); dest_weights={}
        for w,k in ww:
            sh,sb,sl=frames[k][0];th,tb,tl=frames[k][1]
            local=sb.transposed() @ (p-sh)
            local=Vector(tuple(local[i]*scales[k][i] for i in range(3)))
            q+=(th+tb@local)*(w/total)
            name=target[k].name
            dest_weights[name]=dest_weights.get(name,0.0)+w/total
        result.append(Vector(warped[v.index]));weights.append(dest_weights)
    return result, weights, {k:list(v) for k,v in scales.items()}
