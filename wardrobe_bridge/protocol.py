"""Dependency-free tool schemas and strict argument validation shared by both ends."""
import math

NAME={'type':'string','minLength':1,'maxLength':256}
NAMES={'type':'array','items':NAME,'minItems':1,'maxItems':128}

def tool(name, description, properties=None, required=(), read_only=False):
    return {'name':name,'description':description,'inputSchema':{'type':'object','properties':properties or {},'required':list(required),'additionalProperties':False},
            'annotations':{'readOnlyHint':read_only,'destructiveHint':False,'openWorldHint':False}}

TOOLS=[
    tool('wardrobe_scene','List scene meshes, rigs, body/wearable tags and generated fit revisions.',read_only=True),
    tool('wardrobe_library','List the user-selected master library.',read_only=True),
    tool('wardrobe_load','Append a library avatar or wearable as a source or target.',{'asset_id':NAME,'destination':{'type':'string','enum':['SOURCE','TARGET']}},('asset_id','destination')),
    tool('wardrobe_tag','Tag existing meshes as body references or wearables for library preparation.',{'objects':NAMES,'role':{'type':'string','enum':['BODY','WEARABLE']}},('objects','role')),
    tool('wardrobe_fit','Create fitted copies on an unchanged target. This is a first pass requiring visual review.',{'objects':NAMES,'target':NAME,'source_body':NAME,'clearance':{'type':'number','minimum':0,'maximum':.2}},('objects','target')),
    tool('wardrobe_inspect','Check a generated fit: normalized weights, rest-pose intersection samples, recipe and revision. Not an animation guarantee.',{'object':NAME},('object',),True),
    tool('wardrobe_adjust','Create a reversible revision. Move is world XYZ in scene units. Positive inflate expands. Regions use skin weights; elbows/knees also use joint distance.',{'object':NAME,'region':{'type':'string','enum':['ALL','TORSO','SHOULDERS','ARMS','ELBOWS','HIPS','LEGS','KNEES','FEET']},'side':{'type':'string','enum':['BOTH','LEFT','RIGHT']},'move':{'type':'array','items':{'type':'number','minimum':-.5,'maximum':.5},'minItems':3,'maxItems':3},'inflate':{'type':'number','minimum':-.2,'maximum':.2},'smoothing':{'type':'number','minimum':0,'maximum':1}},('object',)),
    tool('wardrobe_undo','Restore the previous generated-fit revision.',{'object':NAME},('object',)),
    tool('wardrobe_frame','Select a frame of existing animation for visual pose review. Does not create or change keyframes.',{'frame':{'type':'integer','minimum':0,'maximum':100000}},('frame',)),
    tool('wardrobe_preview','Render supplied meshes and their target avatar at the current frame. Return an image and a unique permanent PNG in the configured render folder.',{'objects':NAMES,'label':NAME,'view':{'type':'string','enum':['FRONT','BACK','LEFT','RIGHT']}},('objects',)),
    tool('wardrobe_retarget_map','Inspect the humanoid bone mapping between VRM, Mixamo, and other recognized rigs.',{'source':NAME,'target':NAME},('source','target'),True),
    tool('wardrobe_retarget','Bake a source action onto a target humanoid rig as a new action while preserving the source.',{'source':NAME,'target':NAME,'action':NAME,'output_name':NAME,'frame_start':{'type':'integer','minimum':-100000,'maximum':100000},'frame_end':{'type':'integer','minimum':-100000,'maximum':100000},'step':{'type':'integer','minimum':1,'maximum':100},'root_motion':{'type':'boolean'}},('source','target','action')),
    tool('wardrobe_save_asset','Save selected meshes, rig, source avatar, and wardrobe category as a reusable personal library asset.',{'objects':NAMES,'name':NAME,'kind':{'type':'string','enum':['AVATAR','WEARABLE']},'source_body':NAME,'category':{'type':'string','enum':['SOURCE_AVATAR','OUTFIT','SHIRT','PANTS','SHOES','ACCESSORY']},'source_avatar':NAME},('objects','name')),
]

def validate_value(value,schema):
    typ=schema['type']
    if typ=='string':
        if not isinstance(value,str) or not schema.get('minLength',0)<=len(value)<=schema.get('maxLength',10000):raise ValueError('Invalid string argument.')
    elif typ in {'number','integer'}:
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError('Expected a finite number.')
        if typ=='integer' and not isinstance(value,int):raise ValueError('Expected an integer.')
        if value<schema.get('minimum',-math.inf) or value>schema.get('maximum',math.inf):raise ValueError('Number outside allowed range.')
    elif typ=='array':
        if not isinstance(value,list) or not schema.get('minItems',0)<=len(value)<=schema.get('maxItems',10000):raise ValueError('Invalid array argument.')
        for item in value:validate_value(item,schema['items'])
    elif typ=='boolean':
        if not isinstance(value,bool):raise ValueError('Expected a boolean.')
    if 'enum' in schema and value not in schema['enum']:raise ValueError('Unknown enum value.')

def validate_call(name,args):
    entry=next((t for t in TOOLS if t['name']==name),None)
    if not entry:raise ValueError('Unknown wardrobe tool.')
    schema=entry['inputSchema']
    if not isinstance(args,dict) or set(args)-set(schema['properties']) or not set(schema['required'])<=set(args):raise ValueError('Missing or unexpected tool arguments.')
    for key,value in args.items():validate_value(value,schema['properties'][key])
    return args
