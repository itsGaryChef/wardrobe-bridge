import bpy, pathlib, sys, math
from mathutils import Vector
root=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
import wardrobe_bridge as wb
from wardrobe_bridge import retarget
wb.register()

def make_rig(name, names, scale=1.0):
    data=bpy.data.armatures.new(name+'Data');rig=bpy.data.objects.new(name,data);bpy.context.scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active=rig;rig.select_set(True);bpy.ops.object.mode_set(mode='EDIT')
    points={
      'hips':((0,0,1),(0,0,1.2)),'spine':((0,0,1.2),(0,0,1.4)),'chest':((0,0,1.4),(0,0,1.6)),'neck':((0,0,1.6),(0,0,1.72)),'head':((0,0,1.72),(0,0,1.95)),
      'shoulderl':((0,0,1.55),(.18,0,1.55)),'upperarml':((.18,0,1.55),(.48,0,1.55)),'lowerarml':((.48,0,1.55),(.75,0,1.55)),'handl':((.75,0,1.55),(.9,0,1.55)),
      'shoulderr':((0,0,1.55),(-.18,0,1.55)),'upperarmr':((-.18,0,1.55),(-.48,0,1.55)),'lowerarmr':((-.48,0,1.55),(-.75,0,1.55)),'handr':((-.75,0,1.55),(-.9,0,1.55)),
      'upperlegl':((.1,0,1),(.1,0,.58)),'lowerlegl':((.1,0,.58),(.1,0,.15)),'footl':((.1,0,.15),(.1,-.15,.07)),'toesl':((.1,-.15,.07),(.1,-.3,.07)),
      'upperlegr':((-.1,0,1),(-.1,0,.58)),'lowerlegr':((-.1,0,.58),(-.1,0,.15)),'footr':((-.1,0,.15),(-.1,-.15,.07)),'toesr':((-.1,-.15,.07),(-.1,-.3,.07))}
    for key,(head,tail) in points.items():
        b=data.edit_bones.new(names[key]);b.head=Vector(head)*scale;b.tail=Vector(tail)*scale
    bpy.ops.object.mode_set(mode='POSE');bpy.ops.object.mode_set(mode='OBJECT');rig.select_set(False);return rig

keys=['hips','spine','chest','neck','head','shoulderl','upperarml','lowerarml','handl','shoulderr','upperarmr','lowerarmr','handr','upperlegl','lowerlegl','footl','toesl','upperlegr','lowerlegr','footr','toesr']
mix={'hips':'mixamorig:Hips','spine':'mixamorig:Spine','chest':'mixamorig:Spine1','neck':'mixamorig:Neck','head':'mixamorig:Head'}
vrm={k:k for k in ('hips','spine','chest','neck','head')}
for side,word in [('l','Left'),('r','Right')]:
    for key,mixpart,vrmpart in [('shoulder','Shoulder','Shoulder'),('upperarm','Arm','UpperArm'),('lowerarm','ForeArm','LowerArm'),('hand','Hand','Hand'),('upperleg','UpLeg','UpperLeg'),('lowerleg','Leg','LowerLeg'),('foot','Foot','Foot'),('toes','ToeBase','Toes')]:
        mix[key+side]='mixamorig:'+word+mixpart;vrm[key+side]=word.lower()+vrmpart
source=make_rig('Mixamo Source',mix);target=make_rig('VRM Target',vrm,1.25)
source.animation_data_create();action=bpy.data.actions.new('Wave');source.animation_data.action=action
pb=source.pose.bones[mix['upperarml']];pb.rotation_mode='QUATERNION'
for frame,angle in ((1,0),(10,.8)):
    pb.rotation_quaternion=Vector((0,1,0)).rotation_difference(Vector((0,math.cos(angle),math.sin(angle))))
    pb.keyframe_insert('rotation_quaternion',frame=frame)
hips=source.pose.bones[mix['hips']]
for frame,z in ((1,0),(10,.1)):
    hips.location.z=z;hips.keyframe_insert('location',frame=frame)
result=retarget.retarget(source.name,target.name,action.name,'Wave on VRM')
print('RETARGET_RESULT',result,'SOURCE_ACTION',source.animation_data.action)
assert result['status']=='BAKED' and result['mapped_bones']==21 and source.animation_data.action==action
assert target.animation_data.action.name=='Wave on VRM' and target.animation_data.action!=action
assert retarget.mapping(source.name,target.name)['status']=='READY'
bpy.context.scene.frame_set(1);q1=target.pose.bones[vrm['upperarml']].rotation_quaternion.copy()
bpy.context.scene.frame_set(10);q2=target.pose.bones[vrm['upperarml']].rotation_quaternion.copy()
assert q1.rotation_difference(q2).angle>.1
wb.unregister();print('RETARGET_MAPPING_AND_BAKE_PASSED',result['mapped_bones'])
