"""Opt-in local queue. Blender work runs only on its main thread via a timer."""
import json
import os
import pathlib
import time
import uuid
import bpy
from .protocol import validate_call

_root=None
_session=None

@bpy.app.handlers.persistent
def before_load(_):
    stop()

def running():return _root is not None

def atomic(path,data):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data),encoding='utf-8');temp.replace(path)

def start():
    global _root,_session
    value=bpy.context.scene.wb_workflow.bridge_dir
    if not value:raise ValueError('Choose an agent connection folder.')
    root=pathlib.Path(bpy.path.abspath(value)).resolve();root.mkdir(parents=True,exist_ok=True)
    status=root/'session.json'
    if status.exists():
        prior=json.loads(status.read_text(encoding='utf-8'))
        if prior.get('active') and time.time()-prior.get('heartbeat',0)<300:raise ValueError('Another Blender session is using this agent folder. Choose a different folder.')
    _root=root;_session=uuid.uuid4().hex
    atomic(status,{'session':_session,'pid':os.getpid(),'active':True,'heartbeat':time.time()})
    if not bpy.app.timers.is_registered(pump):bpy.app.timers.register(pump,first_interval=.2)

def stop():
    global _root,_session
    if bpy.app.timers.is_registered(pump):bpy.app.timers.unregister(pump)
    if _root:
        atomic(_root/'session.json',{'session':_session,'active':False,'heartbeat':time.time()})
    _root=None;_session=None

def dispatch(name,args):
    from . import body_rig,library,workflow,ui,retarget
    validate_call(name,args)
    if bpy.context.mode!='OBJECT' and name not in {'wardrobe_scene','wardrobe_library'}:raise ValueError('Return Blender to Object Mode before agent operations.')
    if name=='wardrobe_scene':
        return {'frame':bpy.context.scene.frame_current,'objects':[{'name':o.name,'type':o.type,'role':o.get('wb_role'),'rig':body_rig(o).name if o.type=='MESH' and body_rig(o) else None,'fit_id':o.get('wb_fit_id'),'revision':o.get('wb_revision'),'hidden':o.hide_render} for o in bpy.context.scene.objects if o.type in {'MESH','ARMATURE'}]}
    if name=='wardrobe_library':return library.index()
    if name=='wardrobe_load':return ui.use_loaded(args['asset_id'],args['destination'])
    if name=='wardrobe_tag':
        objects=[workflow.mesh(n) for n in args['objects']]
        for obj in objects:obj['wb_role']=args['role']
        return {'tagged':[o.name for o in objects],'role':args['role']}
    if name=='wardrobe_fit':return workflow.fit_items(args['objects'],args['target'],args.get('source_body'),args.get('clearance',.008))
    if name=='wardrobe_inspect':return workflow.inspect(args['object'])
    if name=='wardrobe_adjust':return workflow.adjust(args['object'],args.get('region','ALL'),args.get('side','BOTH'),args.get('move',(0,0,0)),args.get('inflate',0),args.get('smoothing',0))
    if name=='wardrobe_undo':return workflow.undo(args['object'])
    if name=='wardrobe_frame':bpy.context.scene.frame_set(args['frame']);return {'frame':args['frame']}
    if name=='wardrobe_preview':return workflow.preview(args['objects'],args.get('label','agent-preview'),args.get('view','FRONT'))
    if name=='wardrobe_retarget_map':return retarget.mapping(args['source'],args['target'])
    if name=='wardrobe_retarget':return retarget.retarget(args['source'],args['target'],args['action'],args.get('output_name',''),args.get('frame_start'),args.get('frame_end'),args.get('step',1),args.get('root_motion',True))
    if name=='wardrobe_save_asset':
        result=library.capture([workflow.mesh(n) for n in args['objects']],args['name'],args.get('kind','WEARABLE'),workflow.mesh(args['source_body']) if args.get('source_body') else None,args.get('category'),args.get('source_avatar'))
        ui.refresh();return result
    raise ValueError('Unsupported tool.')

def pump():
    if not _root:return None
    atomic(_root/'session.json',{'session':_session,'pid':os.getpid(),'active':True,'heartbeat':time.time()})
    for path in sorted(_root.glob('request-*.json'))[:1]:
        # IDs are chosen by the transport, not arbitrary filesystem paths.
        key=path.stem.removeprefix('request-')
        if len(key)!=32 or any(c not in '0123456789abcdef' for c in key):continue
        response=_root/f'response-{key}.json'
        try:
            if path.stat().st_size>1000000:raise ValueError('Request too large.')
            request=json.loads(path.read_text(encoding='utf-8'))
            if request.get('session')!=_session:raise ValueError('Expired Blender session; reconnect.')
            if request.get('deadline',0)<time.time():raise ValueError('Expired request; not executed.')
            if (_root/f'cancel-{key}.json').exists():raise ValueError('Cancelled before execution.')
            bpy.context.scene.wb_workflow.status='Agent: '+str(request.get('tool',''))
            result=dispatch(request['tool'],request.get('arguments',{}))
            atomic(response,{'ok':True,'result':result})
            bpy.context.scene.wb_workflow.status='Agent completed: '+request['tool']
        except Exception as exc:atomic(response,{'ok':False,'error':str(exc)})
        finally:path.unlink(missing_ok=True)
    return .2
