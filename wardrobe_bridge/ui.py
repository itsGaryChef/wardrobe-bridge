import json
import pathlib
import bpy
from bpy.props import StringProperty, PointerProperty, CollectionProperty, IntProperty, BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty
from bpy_extras.io_utils import ImportHelper
from . import body_rig, mesh_only
from . import library, workflow
import bpy.utils.previews

_previews = None


def thumbnail_icon(item):
    return _previews[item.asset_id].icon_id if _previews and item.asset_id in _previews else 0


def armature_only(self, obj):
    return obj.type == 'ARMATURE'


class WBPreferences(bpy.types.AddonPreferences):
    bl_idname=__package__
    library_root: StringProperty(name='My master library',subtype='DIR_PATH')
    motion_library_root: StringProperty(name='My pose / animation library',subtype='DIR_PATH')
    def draw(self,context):
        self.layout.prop(self,'library_root')
        self.layout.prop(self,'motion_library_root')
        self.layout.label(text='Personal library shared across projects. Save Preferences to retain it.')


class WBInventoryItem(bpy.types.PropertyGroup):
    asset_id: StringProperty()
    kind: StringProperty()
    category: StringProperty()
    source_avatar: StringProperty()
    preview: StringProperty()


class WBSourceItem(bpy.types.PropertyGroup):
    obj: PointerProperty(type=bpy.types.Object)
    enabled: BoolProperty(name='Fit this item')


class WBMotionItem(bpy.types.PropertyGroup):
    filepath: StringProperty()
    group: StringProperty()
    format: StringProperty()


class WBWorkflow(bpy.types.PropertyGroup):
    library_dir: StringProperty(name='My master library', subtype='DIR_PATH')
    render_dir: StringProperty(name='Keep renders in', subtype='DIR_PATH', default='//work/renders/')
    bridge_dir: StringProperty(name='Agent connection folder', subtype='DIR_PATH', default='//work/wardrobe-agent/')
    inventory: CollectionProperty(type=WBInventoryItem)
    inventory_index: IntProperty(default=0)
    search: StringProperty(name='Search library')
    category_filter: EnumProperty(name='Category', items=[('ALL','All categories','')]+[(value, value.replace('_',' ').title(), '') for value in library.CATEGORIES])
    source_filter: StringProperty(name='Source avatar')
    source_items: CollectionProperty(type=WBSourceItem)
    source_body: PointerProperty(name='Source body reference', type=bpy.types.Object, poll=mesh_only)
    target: PointerProperty(name='Target body', type=bpy.types.Object, poll=mesh_only)
    last_fit: PointerProperty(name='Fit to adjust', type=bpy.types.Object, poll=mesh_only)
    clearance: FloatProperty(name='Clothing clearance', default=.008, min=0, max=.2, subtype='DISTANCE')
    hide_replaced: BoolProperty(name='Hide target items tagged Wearable', default=False)
    asset_name: StringProperty(name='Save as', default='My wearable')
    asset_kind: EnumProperty(name='Type', items=[('WEARABLE','Wearable / outfit','Selected clothing meshes plus their body reference'),('AVATAR','Source avatar','Avatar meshes and rig')])
    asset_category: EnumProperty(name='Category', items=[(value, value.replace('_',' ').title(), '') for value in library.CATEGORIES if value != 'SOURCE_AVATAR'])
    asset_source_avatar: StringProperty(name='Source avatar', description='Avatar this item originally came from', default='Unsorted')
    motion_source: PointerProperty(name='Animation rig', type=bpy.types.Object, poll=armature_only)
    motion_target: PointerProperty(name='Target rig', type=bpy.types.Object, poll=armature_only)
    motion_action: PointerProperty(name='Source action', type=bpy.types.Action)
    motion_name: StringProperty(name='New action name')
    motion_step: IntProperty(name='Bake every', default=1, min=1, max=100)
    motion_root: BoolProperty(name='Retarget root motion', default=True)
    motion_library_dir: StringProperty(name='Pose / animation folder', subtype='DIR_PATH')
    motion_inventory: CollectionProperty(type=WBMotionItem)
    motion_inventory_index: IntProperty(default=0)
    motion_search: StringProperty(name='Search motions')
    region: EnumProperty(name='Region', items=[(r, r.title(), '') for r in workflow.REGIONS])
    side: EnumProperty(name='Side', items=[('BOTH','Both',''),('LEFT','Left',''),('RIGHT','Right','')])
    move: FloatVectorProperty(name='Move XYZ', size=3, subtype='TRANSLATION', min=-.5, max=.5)
    inflate: FloatProperty(name='Expand / contract', default=0, min=-.2, max=.2, subtype='DISTANCE')
    smoothing: FloatProperty(name='Smooth region', default=0, min=0, max=1)
    preview_view: EnumProperty(name='Preview view',items=[(v,v.title(),'') for v in ('FRONT','BACK','LEFT','RIGHT')])
    status: StringProperty(default='Choose a library item or import a source avatar.')


def refresh():
    global _previews
    if _previews is not None: bpy.utils.previews.remove(_previews)
    _previews = bpy.utils.previews.new()
    s = bpy.context.scene.wb_workflow; s.inventory.clear()
    rows = sorted(library.index()['assets'], key=lambda row: (row['source_avatar'].casefold(), library.CATEGORY_ORDER[row['category']], row['name'].casefold()))
    for row in rows:
        item = s.inventory.add(); item.name = row['name']; item.asset_id = row['id']; item.kind = row['kind']; item.category = row['category']; item.source_avatar = row['source_avatar']; item.preview = row.get('preview') or ''
        if item.preview:
            path = library.inside(item.preview)
            if path.is_file():
                try: _previews.load(item.asset_id, str(path), 'IMAGE')
                except Exception: pass
    s.inventory_index = min(s.inventory_index, max(0, len(s.inventory)-1))


def populate(objects, source_body=None):
    s = bpy.context.scene.wb_workflow; s.source_items.clear(); s.source_body = source_body
    for obj in objects:
        if obj.type != 'MESH': continue
        item = s.source_items.add(); item.obj = obj
        item.enabled = obj.get('wb_role') == 'WEARABLE' and obj != source_body


def use_loaded(key, destination):
    row, collection, mapping = library.load(key)
    bodies = [mapping[n] for n in row['bodies'] if n in mapping]
    body = mapping.get(row.get('source_body')) or (bodies[0] if bodies else None)
    if destination == 'TARGET':
        if not body:
            bpy.context.scene.wb_workflow.target = None
            return {'collection':collection.name,'objects':[o.name for o in mapping.values()],'body':None,'warning':'Choose the loaded avatar body as Target; this entry has no tagged body.'}
        bpy.context.scene.wb_workflow.target = body
    else: populate(mapping.values(), body)
    warning = 'Loaded raw wearable. Position it on a source avatar and choose that body reference before fitting.' if destination == 'SOURCE' and row.get('readiness') == 'RAW_PLACEMENT' else None
    return {'collection': collection.name, 'objects': [o.name for o in mapping.values()], 'body': body.name if body else None, 'warning': warning}


class WB_UL_inventory(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        value=thumbnail_icon(item)
        row = layout.row(align=True)
        if value: row.label(text=item.name, icon_value=value)
        else: row.label(text=item.name, icon='ARMATURE_DATA' if item.kind == 'AVATAR' else 'MOD_CLOTH')
        row.label(text=item.category.replace('_',' ').title())
    def filter_items(self, context, data, propname):
        s = context.scene.wb_workflow; search = s.search.casefold(); source = s.source_filter.casefold()
        flags=[]
        for item in getattr(data, propname):
            text = f'{item.name} {item.source_avatar} {item.category}'.casefold()
            visible = search in text and source in item.source_avatar.casefold() and (s.category_filter == 'ALL' or item.category == s.category_filter)
            flags.append(self.bitflag_filter_item if visible else 0)
        return flags, []


class WB_UL_motion_inventory(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row=layout.row(align=True);row.label(text=item.name,icon='POSE_HLT' if item.group.casefold().startswith('pose') else 'ACTION')
        row.label(text=item.group)
    def filter_items(self, context, data, propname):
        search=context.scene.wb_workflow.motion_search.casefold()
        flags=[self.bitflag_filter_item if search in f'{item.name} {item.group} {item.format}'.casefold() else 0 for item in getattr(data,propname)]
        return flags,[]


def refresh_motions(settings):
    prefs=library.preferences();value=prefs.motion_library_root if prefs and prefs.motion_library_root else settings.motion_library_dir
    root=pathlib.Path(bpy.path.abspath(value)).resolve()
    if not root.is_dir(): raise ValueError('Choose an existing pose / animation folder.')
    settings.motion_inventory.clear()
    for path in sorted((p for p in root.rglob('*') if p.is_file() and p.suffix.casefold() in {'.fbx','.bvh','.blend'}),key=lambda p:str(p).casefold()):
        item=settings.motion_inventory.add();item.name=path.stem;item.filepath=str(path);item.format=path.suffix[1:].upper()
        relative=path.relative_to(root);item.group=relative.parts[0] if len(relative.parts)>1 else item.format
    settings.motion_inventory_index=min(settings.motion_inventory_index,max(0,len(settings.motion_inventory)-1))
    return len(settings.motion_inventory)


def load_motion_file(settings, filepath):
    path=pathlib.Path(filepath)
    if not path.is_file(): raise ValueError('The selected motion file is missing.')
    before_objects=set(bpy.data.objects);before_actions=set(bpy.data.actions)
    suffix=path.suffix.casefold()
    if suffix=='.fbx': bpy.ops.import_scene.fbx(filepath=str(path),use_anim=True)
    elif suffix=='.bvh': bpy.ops.import_anim.bvh(filepath=str(path),update_scene_fps=True)
    elif suffix=='.blend':
        with bpy.data.libraries.load(str(path),link=False) as (src,dst): dst.actions=src.actions;dst.objects=list(src.objects)
        for obj in dst.objects:
            if obj: bpy.context.scene.collection.objects.link(obj)
    else: raise ValueError('Choose an FBX, BVH, or Blender motion file.')
    imported_objects=set(bpy.data.objects)-before_objects;armatures=[obj for obj in imported_objects if obj.type=='ARMATURE']
    actions=list(set(bpy.data.actions)-before_actions)
    if not actions: actions=[obj.animation_data.action for obj in armatures if obj.animation_data and obj.animation_data.action]
    actions=[action for action in actions if action]
    if not armatures or not actions: raise ValueError('No animated armature and action were found in this file.')
    source=max(armatures,key=lambda obj:len(obj.data.bones));action=max(actions,key=lambda value:value.frame_range[1]-value.frame_range[0])
    settings.motion_source=source;settings.motion_action=action
    bpy.context.scene.frame_start=int(action.frame_range[0]);bpy.context.scene.frame_end=int(action.frame_range[1]);bpy.context.scene.frame_set(int(action.frame_range[0]))
    return source,action


class WB_OT_motion_refresh(bpy.types.Operator):
    bl_idname='wardrobe.motion_refresh';bl_label='Scan Motion Folder'
    def execute(self,context):
        try:
            count=refresh_motions(context.scene.wb_workflow);context.scene.wb_workflow.status=f'Found {count} pose / animation files.';return {'FINISHED'}
        except Exception as exc:self.report({'ERROR'},str(exc));return {'CANCELLED'}


class WB_OT_motion_load(bpy.types.Operator):
    bl_idname='wardrobe.motion_load';bl_label='Load Selected Motion';bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        try:
            s=context.scene.wb_workflow
            if not s.motion_inventory: raise ValueError('Scan the motion folder and choose an item first.')
            item=s.motion_inventory[min(s.motion_inventory_index,len(s.motion_inventory)-1)]
            source,action=load_motion_file(s,item.filepath);s.status=f'Loaded {item.name}: {source.name} / {action.name}';return {'FINISHED'}
        except Exception as exc:self.report({'ERROR'},str(exc));return {'CANCELLED'}


class WB_OT_refresh(bpy.types.Operator):
    bl_idname = 'wardrobe.library_refresh'; bl_label = 'Refresh Inventory'
    def execute(self, context):
        try: refresh(); return {'FINISHED'}
        except Exception as exc: self.report({'ERROR'}, str(exc)); return {'CANCELLED'}


class WB_OT_load(bpy.types.Operator):
    bl_idname = 'wardrobe.library_load'; bl_label = 'Load Library Item'; bl_options = {'REGISTER','UNDO'}
    destination: EnumProperty(items=[('SOURCE','Source',''),('TARGET','Target','')])
    def execute(self, context):
        try:
            s = context.scene.wb_workflow
            if not s.inventory: raise ValueError('Choose a library item first.')
            result = use_loaded(s.inventory[s.inventory_index].asset_id, self.destination)
            s.status = result.get('warning') or ('Loaded ' + result['collection']); return {'FINISHED'}
        except Exception as exc: self.report({'ERROR'}, str(exc)); return {'CANCELLED'}


class WB_OT_source_selection(bpy.types.Operator):
    bl_idname = 'wardrobe.source_selection'; bl_label = 'Use Selected Source Meshes'
    def execute(self, context):
        source_body = context.scene.wb_workflow.source_body
        populate(context.selected_objects, source_body)
        for item in context.scene.wb_workflow.source_items: item.enabled = item.obj != source_body
        return {'FINISHED'}


class WB_OT_tag(bpy.types.Operator):
    bl_idname = 'wardrobe.tag'; bl_label = 'Tag Selected Meshes'; bl_options = {'REGISTER','UNDO'}
    role: EnumProperty(items=[('BODY','Body',''),('WEARABLE','Wearable','')])
    def execute(self, context):
        for obj in context.selected_objects:
            if obj.type == 'MESH': obj['wb_role'] = self.role
        for item in context.scene.wb_workflow.source_items:
            if item.obj: item.enabled = item.obj.get('wb_role') == 'WEARABLE' and item.obj != context.scene.wb_workflow.source_body
        return {'FINISHED'}


class WB_OT_import(bpy.types.Operator, ImportHelper):
    bl_idname = 'wardrobe.import_avatar'; bl_label = 'Import Avatar / Wearable'; bl_options = {'REGISTER','UNDO'}
    filter_glob: StringProperty(default='*.fbx;*.glb;*.gltf;*.vrm;*.blend', options={'HIDDEN'})
    destination: EnumProperty(name='Use as', items=[('SOURCE','Source',''),('TARGET','Target','')])
    def execute(self, context):
        before = set(bpy.data.objects)
        try:
            suffix = pathlib.Path(self.filepath).suffix.lower()
            if suffix == '.fbx': bpy.ops.import_scene.fbx(filepath=self.filepath)
            elif suffix in {'.glb','.gltf','.vrm'}: bpy.ops.import_scene.gltf(filepath=self.filepath)
            elif suffix == '.blend':
                with bpy.data.libraries.load(self.filepath, link=False) as (src, dst): dst.objects = src.objects
                for obj in dst.objects:
                    if obj: context.scene.collection.objects.link(obj)
            else: raise ValueError('Choose FBX, GLB, glTF, VRM, or Blender format.')
            imported = set(bpy.data.objects)-before; meshes = [o for o in imported if o.type == 'MESH']
            bodies = [o for o in meshes if o.get('wb_role') == 'BODY' or o.name.casefold() in {'body','fullbody','basebody'}]
            body = bodies[0] if len(bodies) == 1 else None
            if body: body['wb_role'] = 'BODY'
            if self.destination == 'SOURCE': populate(meshes, body)
            elif body: context.scene.wb_workflow.target = body
            context.scene.wb_workflow.status = 'Imported. Choose the body reference and check clothing pieces to fit.'
            if suffix == '.vrm': self.report({'INFO'}, 'VRM geometry and skin imported; VRM metadata/export is not handled by this importer.')
            return {'FINISHED'}
        except Exception as exc:
            for obj in set(bpy.data.objects)-before: bpy.data.objects.remove(obj, do_unlink=True)
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}


class WB_OT_save_asset(bpy.types.Operator):
    bl_idname = 'wardrobe.library_save'; bl_label = 'Save Selected to My Library'
    def execute(self, context):
        try:
            s = context.scene.wb_workflow; selected = list(context.selected_objects)
            reference = s.source_body
            fitted = [o for o in selected if o.get('wb_target')]
            if fitted: reference = context.scene.objects.get(fitted[0]['wb_target'])
            row = library.capture(selected, s.asset_name, s.asset_kind, reference, s.asset_category, s.asset_source_avatar)
            refresh(); s.status = 'Saved ' + row['name']; return {'FINISHED'}
        except Exception as exc: self.report({'ERROR'}, str(exc)); return {'CANCELLED'}


class WB_OT_go(bpy.types.Operator):
    bl_idname = 'wardrobe.go'; bl_label = 'GO — Fit Outfit'; bl_options = {'REGISTER','UNDO'}
    def execute(self, context):
        s = context.scene.wb_workflow
        try:
            if not s.target: raise ValueError('Choose a target body.')
            names = [item.obj.name for item in s.source_items if item.enabled and item.obj]
            result = workflow.fit_items(names, s.target.name, s.source_body.name if s.source_body else None, s.clearance)
            if s.hide_replaced:
                for obj in context.scene.objects:
                    if obj.type == 'MESH' and body_rig(obj) == body_rig(s.target) and obj.get('wb_role') == 'WEARABLE' and not obj.get('wb_fit_id'):
                        obj.hide_render = True; obj.hide_set(True)
            s.status = f"Created {len(result['objects'])} fitted items. Review fit and pose."; return {'FINISHED'}
        except Exception as exc: s.status = str(exc); self.report({'ERROR'}, str(exc)); return {'CANCELLED'}


class WB_OT_adjust(bpy.types.Operator):
    bl_idname = 'wardrobe.adjust'; bl_label = 'Create Adjusted Revision'; bl_options = {'REGISTER','UNDO'}
    def execute(self, context):
        try:
            s = context.scene.wb_workflow
            if not s.last_fit: raise ValueError('Choose a generated fit.')
            workflow.adjust(s.last_fit.name, s.region, s.side, s.move, s.inflate, s.smoothing)
            s.status = 'Adjustment saved as a new revision.'; return {'FINISHED'}
        except Exception as exc: self.report({'ERROR'}, str(exc)); return {'CANCELLED'}


class WB_OT_undo_fit(bpy.types.Operator):
    bl_idname = 'wardrobe.undo_adjustment'; bl_label = 'Restore Previous Revision'; bl_options = {'REGISTER','UNDO'}
    def execute(self, context):
        try: workflow.undo(context.scene.wb_workflow.last_fit.name); return {'FINISHED'}
        except Exception as exc: self.report({'ERROR'}, str(exc)); return {'CANCELLED'}


class WB_OT_check(bpy.types.Operator):
    bl_idname = 'wardrobe.inspect_fit'; bl_label = 'Check Fit'
    def execute(self, context):
        try:
            s = context.scene.wb_workflow; result = workflow.inspect(s.last_fit.name)
            s.status = f"{result['unweighted']} unweighted; {result['possible_surface_penetrations']} possible sampled intersections. Visual review needed."
            self.report({'INFO'}, s.status); return {'FINISHED'}
        except Exception as exc: self.report({'ERROR'}, str(exc)); return {'CANCELLED'}


class WB_OT_preview(bpy.types.Operator):
    bl_idname = 'wardrobe.preview'; bl_label = 'Render Fit Preview'
    def execute(self, context):
        try:
            s = context.scene.wb_workflow
            if not s.last_fit: raise ValueError('Choose a generated fit.')
            result = workflow.preview([s.last_fit.name], 'wardrobe-fit',s.preview_view); s.status = 'Saved ' + pathlib.Path(result['path']).name; return {'FINISHED'}
        except Exception as exc: self.report({'ERROR'}, str(exc)); return {'CANCELLED'}


class WB_OT_thumbnail(bpy.types.Operator):
    bl_idname = 'wardrobe.library_thumbnail'; bl_label = 'Use Selected Meshes for Thumbnail'
    def execute(self, context):
        try:
            s = context.scene.wb_workflow; item = s.inventory[s.inventory_index]
            result = workflow.preview([o.name for o in context.selected_objects if o.type == 'MESH'], 'library-thumbnail')
            library.set_preview(item.asset_id, result['path']); refresh(); return {'FINISHED'}
        except Exception as exc: self.report({'ERROR'}, str(exc)); return {'CANCELLED'}


class WB_OT_bridge(bpy.types.Operator):
    bl_idname = 'wardrobe.agent_bridge'; bl_label = 'Toggle Agent Connection'
    def execute(self, context):
        from . import bridge
        try:
            if bridge.running(): bridge.stop(); context.scene.wb_workflow.status = 'Agent disconnected.'
            else: bridge.start(); context.scene.wb_workflow.status = 'Agent bridge enabled for this Blender session.'
            return {'FINISHED'}
        except Exception as exc: self.report({'ERROR'}, str(exc)); return {'CANCELLED'}


class WB_OT_mapping(bpy.types.Operator):
    bl_idname='wardrobe.retarget_mapping'; bl_label='Check Humanoid Mapping'
    def execute(self,context):
        from . import retarget
        try:
            s=context.scene.wb_workflow
            if not s.motion_source or not s.motion_target: raise ValueError('Choose source and target armatures.')
            result=retarget.mapping(s.motion_source.name,s.motion_target.name)
            s.status=f"{result['status']}: {len(result['mapped'])} mapped bones; {len(result['source_only'])} source-only."
            self.report({'INFO'} if result['status']=='READY' else {'WARNING'},s.status);return {'FINISHED'}
        except Exception as exc:self.report({'ERROR'},str(exc));return {'CANCELLED'}


class WB_OT_retarget(bpy.types.Operator):
    bl_idname='wardrobe.retarget_action'; bl_label='Retarget & Bake Action'; bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        from . import retarget
        try:
            s=context.scene.wb_workflow
            if not s.motion_source or not s.motion_target or not s.motion_action: raise ValueError('Choose both armatures and a source action.')
            result=retarget.retarget(s.motion_source.name,s.motion_target.name,s.motion_action.name,s.motion_name,step=s.motion_step,root_motion=s.motion_root)
            s.status=f"Baked {result['action']} with {result['mapped_bones']} mapped bones."
            return {'FINISHED'}
        except Exception as exc:self.report({'ERROR'},str(exc));return {'CANCELLED'}


def agent_config(settings):
    path=str(pathlib.Path(bpy.path.abspath(settings.bridge_dir)).resolve())
    server=str(pathlib.Path(__file__).with_name('mcp_server.py'))
    return {'mcpServers':{'wardrobe':{'command':'python','args':[server,'--bridge-dir',path]}}}


class WB_OT_agent_config(bpy.types.Operator):
    bl_idname='wardrobe.copy_agent_config';bl_label='Copy MCP Connection Config'
    def execute(self,context):
        s=context.scene.wb_workflow
        context.window_manager.clipboard=json.dumps(agent_config(s),indent=2)
        self.report({'INFO'},'Config copied. Set command to your Python 3.10+ executable in your MCP client.');return {'FINISHED'}


class WB_PT_workflow(bpy.types.Panel):
    bl_label = 'Wardrobe — My Library'; bl_idname = 'WB_PT_workflow'; bl_space_type = 'VIEW_3D'; bl_region_type = 'UI'; bl_category = 'Wardrobe'
    def draw(self, context):
        layout = self.layout; s = context.scene.wb_workflow
        prefs=library.preferences()
        if prefs: layout.prop(prefs,'library_root')
        else: layout.prop(s,'library_dir')
        layout.operator('wardrobe.library_refresh', icon='FILE_REFRESH'); layout.prop(s, 'search')
        row=layout.row(align=True); row.prop(s,'category_filter'); row.prop(s,'source_filter')
        layout.template_list('WB_UL_inventory','',s,'inventory',s,'inventory_index', rows=4)
        if s.inventory:
            value=thumbnail_icon(s.inventory[min(s.inventory_index,len(s.inventory)-1)])
            if value: layout.template_icon(icon_value=value,scale=6)
        row = layout.row(); row.operator('wardrobe.library_load', text='Use as Source').destination='SOURCE'; row.operator('wardrobe.library_load', text='Use as Target').destination='TARGET'
        layout.operator('wardrobe.import_avatar', icon='IMPORT')
        box = layout.box(); box.label(text='1. Source wearables'); box.prop(s,'source_body'); box.operator('wardrobe.source_selection')
        for item in s.source_items:
            if item.obj:
                row = box.row(); row.prop(item, 'enabled', text=item.obj.name)
        box = layout.box(); box.label(text='2. Target avatar'); box.prop(s,'target'); box.prop(s,'clearance'); box.prop(s,'hide_replaced')
        row=box.row(); row.scale_y=1.5; row.operator('wardrobe.go', icon='PLAY')
        layout.label(text=s.status[:100], icon='INFO')


class WB_PT_save(bpy.types.Panel):
    bl_label='Prepare & Save Library Items'; bl_idname='WB_PT_save'; bl_space_type='VIEW_3D'; bl_region_type='UI'; bl_category='Wardrobe'; bl_options={'DEFAULT_CLOSED'}
    def draw(self, context):
        layout=self.layout; s=context.scene.wb_workflow
        row=layout.row(); row.operator('wardrobe.tag',text='Tag Body').role='BODY'; row.operator('wardrobe.tag',text='Tag Wearable').role='WEARABLE'
        layout.prop(s,'asset_kind'); layout.prop(s,'asset_name')
        if s.asset_kind == 'WEARABLE': layout.prop(s,'asset_category'); layout.prop(s,'asset_source_avatar')
        layout.operator('wardrobe.library_save'); layout.operator('wardrobe.library_thumbnail')
        layout.label(text='Fused clothing needs separation once.')


class WB_PT_refine(bpy.types.Panel):
    bl_label='Review & Refine'; bl_idname='WB_PT_refine'; bl_space_type='VIEW_3D'; bl_region_type='UI'; bl_category='Wardrobe'
    def draw(self, context):
        layout=self.layout; s=context.scene.wb_workflow
        layout.prop(s,'last_fit'); layout.operator('wardrobe.inspect_fit'); layout.prop(s,'render_dir'); layout.prop(s,'preview_view'); layout.operator('wardrobe.preview')
        for name in ('region','side','move','inflate','smoothing'): layout.prop(s,name)
        layout.operator('wardrobe.adjust'); layout.operator('wardrobe.undo_adjustment')


class WB_PT_agent(bpy.types.Panel):
    bl_label='Agent / MCP'; bl_idname='WB_PT_agent'; bl_space_type='VIEW_3D'; bl_region_type='UI'; bl_category='Wardrobe'; bl_options={'DEFAULT_CLOSED'}
    def draw(self, context):
        from . import bridge
        layout=self.layout; s=context.scene.wb_workflow
        layout.prop(s,'bridge_dir'); layout.operator('wardrobe.agent_bridge',text='Disconnect Agent' if bridge.running() else 'Enable Agent Connection')
        layout.operator('wardrobe.copy_agent_config')
        layout.label(text='Connect the bundled stdio MCP server.')
        layout.label(text='Prompt your agent to inspect or refine a fit.')


class WB_PT_motion(bpy.types.Panel):
    bl_label='Pose & Animation Retargeting'; bl_idname='WB_PT_motion'; bl_space_type='VIEW_3D'; bl_region_type='UI'; bl_category='Wardrobe'
    def draw(self,context):
        layout=self.layout;s=context.scene.wb_workflow
        box=layout.box();box.label(text='Motion Library')
        prefs=library.preferences();box.prop(prefs,'motion_library_root') if prefs else box.prop(s,'motion_library_dir')
        row=box.row(align=True);row.operator('wardrobe.motion_refresh',icon='FILE_REFRESH');row.prop(s,'motion_search',text='')
        box.template_list('WB_UL_motion_inventory','',s,'motion_inventory',s,'motion_inventory_index',rows=5)
        box.operator('wardrobe.motion_load',icon='IMPORT')
        box.label(text='Loading selects its imported rig and action automatically.')
        layout.prop(s,'motion_source');layout.prop(s,'motion_target');layout.prop(s,'motion_action')
        layout.prop(s,'motion_name');row=layout.row(align=True);row.prop(s,'motion_step');row.prop(s,'motion_root')
        layout.operator('wardrobe.retarget_mapping',icon='BONE_DATA');layout.operator('wardrobe.retarget_action',icon='ACTION')
        layout.label(text='Creates a new target action; source animation is preserved.')


classes=(WBPreferences,WBInventoryItem,WBSourceItem,WBMotionItem,WBWorkflow,WB_UL_inventory,WB_UL_motion_inventory,WB_OT_refresh,WB_OT_motion_refresh,WB_OT_motion_load,WB_OT_load,WB_OT_source_selection,WB_OT_tag,WB_OT_import,WB_OT_save_asset,WB_OT_go,WB_OT_adjust,WB_OT_undo_fit,WB_OT_check,WB_OT_preview,WB_OT_thumbnail,WB_OT_bridge,WB_OT_agent_config,WB_OT_mapping,WB_OT_retarget,WB_PT_workflow,WB_PT_save,WB_PT_refine,WB_PT_motion,WB_PT_agent)


def register():
    for cls in classes: bpy.utils.register_class(cls)
    bpy.types.Scene.wb_workflow=PointerProperty(type=WBWorkflow)
    from .bridge import before_load
    bpy.app.handlers.load_pre.append(before_load)


def unregister():
    global _previews
    from . import bridge
    bridge.stop()
    if bridge.before_load in bpy.app.handlers.load_pre: bpy.app.handlers.load_pre.remove(bridge.before_load)
    if _previews is not None: bpy.utils.previews.remove(_previews); _previews=None
    if hasattr(bpy.types.Scene,'wb_workflow'): del bpy.types.Scene.wb_workflow
    for cls in reversed(classes): bpy.utils.unregister_class(cls)
