# Wardrobe Bridge 0.12 — wardrobe, pose, animation, and agent workflow

This version turns the fitting prototype into a reusable Blender workflow: choose a source from your inventory, check the wearable pieces, choose a target body, and press **GO — Fit Outfit**. It includes a local MCP server for agent-driven inspection and revisions.

## Install and try the prepared demo

1. Install `wardrobe_bridge.zip` through Blender's add-on installation from disk, then enable **Wardrobe Bridge**. If an older version is enabled, disable it before replacing it and restart Blender afterward.
2. Open `Wardrobe Library Demo.blend`.
3. In the 3D View, press **N** and open **Wardrobe**.
4. Set **My master library** to this project's `outputs/Avatar Clothing Library` folder and click **Refresh Inventory**. The prepared personal library has 75 entries. Save Blender Preferences to keep your personal library selection across projects.
5. The demo already selects the three 6153 outfit pieces and original 333 as the target. Press **GO — Fit Outfit**. This example exercises exact-fit reuse: the saved pieces were already tailored to the same body and rig.

The add-on has been tested in Blender 5.2. The declared minimum is Blender 4.2, but that version has not been tested in this workspace.

## Build your own master library

Choose any local folder as your personal library. Each user can maintain a separate folder. Wearables are stored as Blender files with their source rig, body reference, materials, and packed image textures. Keep the entire folder together when moving or backing it up.

The inventory is sorted by original source avatar, then into **Source Avatars**, **Outfits**, **Shirts**, **Pants**, **Shoes**, and **Accessories**. Use the category selector and source-avatar search box to narrow the displayed list. New wearable entries store both fields so every user can organize their own growing library.

For a new source avatar:

1. Use **Import Avatar / Wearable** for FBX, GLB, glTF, VRM, or Blender files. Importing a Blender file appends its objects; it does not replace the current project.
2. Select its body meshes and use **Tag Body**. Select the clothing meshes and use **Tag Wearable**. Keep face parts and body details separate from clothing tags.
3. Choose **Source body reference** and use **Use Selected Source Meshes** or check the desired source items in the panel.
4. In **Prepare & Save Library Items**, choose **Source avatar** to save an avatar, or **Wearable / outfit** to save selected clothing. For a wearable, choose its category and enter the avatar it originally came from. Use a descriptive name and click **Save Selected to My Library**.
5. Optionally select representative meshes and use **Use Selected Meshes for Thumbnail**. It renders a permanent PNG and adds a thumbnail to the inventory entry.

If clothes and skin share one mesh, separate the clothing once using Blender's mesh editing tools before saving it. The add-on does not identify clothing from textures or semantically segment a fused avatar.

Unrigged raw assets can also be stored before they are tailored. They load with a **raw placement** warning and must be positioned on a source avatar with a body reference before automatic cross-avatar fitting.

## Fit to another avatar

Select an inventory entry and choose **Use as Source**. Load/import the target, or choose an existing **Target body** from the scene. Check the source items you want and press **GO — Fit Outfit**.

The target body and any meshes on its rig tagged **Body** are used as fitting surfaces. This prevents old clothing from becoming the fitting surface. The optional **Hide target items tagged Wearable** hides those original items only after the new fit succeeds. It does not delete them.

Outputs are separate meshes on the target rig. The operation temporarily uses rig rest positions, then restores their previous state. It does not reshape or mask the target body. If a multi-item fit fails, its newly created meshes are rolled back.

Running **GO** again with the same source wearable and target replaces that wearable's earlier generated fit after the new fit succeeds. Source meshes remain unchanged. Adjustments keep the same visible object and store undo history in mesh data, so revisions do not add duplicate objects to the scene.

When the saved body geometry and rig layout match exactly, geometry and skin weights are reused. For a different body, the add-on creates an anatomical first pass, corrects nearby surface clearance, and assigns target skin weights. This is still a prototype for cross-shape fitting: unusual rigs, rigid armor, thick fur, layered clothes, and very different proportions can require further work.

## Review and adjust

Choose a generated mesh under **Fit to adjust**. **Check Fit** reports weight coverage and a sampled nearest-surface intersection heuristic. It is not a guarantee against intersections in animation.

Use **Render Fit Preview** for front, back, left, and right views at the current animation frame. Every PNG receives a unique filename in **Keep renders in**. The prepared project uses `work/renders`; previews are not deleted when the operation ends.

Use the region, side, move, expansion, and smoothing controls to refine a fit. Each change updates the same fit object while retaining its earlier mesh data for **Restore Previous Revision**. Target-body geometry remains untouched. Save selected fitted pieces to the library to reuse the result later.

## Retarget poses and animation

Open **Pose & Animation Retargeting** in the Wardrobe sidebar. Set **My pose / animation library** to a folder containing FBX, BVH, or Blender files and click **Scan Motion Folder**. Choose Animations or Poses, then choose a motion from the second dropdown and click **Load Selected Motion**; its imported armature and action are selected automatically. Then choose the destination armature. **Check Humanoid Mapping** reports whether the recognized VRM/Mixamo-style map is complete enough to bake. **Retarget & Bake Action** creates a new action on the target and leaves the source action unchanged.

The first version maps the standard humanoid torso, head, arms, hands, legs, feet, and toes. It can scale hips translation for root motion and bake every frame or at a chosen interval. Facial animation, finger chains, IK controls, props, spring bones, and arbitrary custom control rigs are not mapped automatically yet.

Version 0.12 includes 45 CC0 Quaternius Universal Animation Library clips from Defold's 3D Animations example. They appear automatically alongside the user's external motion folder; a personal clip with the same name and type takes precedence.

The legacy surface fitting, rigging, skirt, and cuff tools remain under **Advanced / Legacy Tools**. Generating arbitrary new outfits from a text prompt is not included in this release.

## Connect an agent through MCP

The add-on exposes 13 bounded tools, including humanoid mapping inspection and animation retargeting in addition to the wardrobe tools. It does not expose arbitrary Python execution.

1. Keep Blender open and in Object Mode.
2. In **Agent / MCP**, choose a project-specific **Agent connection folder** and click **Enable Agent Connection**. The demo uses `work/wardrobe-agent`.
3. Click **Copy MCP Connection Config** and add the command/arguments to your agent client's MCP configuration. Set `command` to an ordinary Python 3.10+ executable. Do not use `blender.exe` as the server command.
4. For this computer, `Wardrobe MCP Config.json` contains a ready command and paths matching this project. A different computer should use the configuration copied from its own add-on and its own Python path.
5. Restart/reconnect the MCP client as required by that client. The add-on cannot register itself automatically in every agent application.

Example prompts:

- “List my wardrobe inventory. Fit the saved vest and trousers to the target avatar, then show me front and side previews.”
- “Inspect the current fit. Lower the chest area by 1 cm, render it again, and keep the previous revision.”
- “Smooth the knees a little without shrinking the legs. Show me the current animation frame.”
- “Restore the previous revision and save that wearable to my library.”

The agent interprets the prompt and chooses the tool parameters. There is no language model, account, or paid API inside the add-on. Tool coordinates use Blender scene units; “1 cm” is 0.01 units only in a meter-based scene.

The MCP server uses standard stdio transport and a local request folder. Blender executes the requests on its main thread. Loading another project disables the connection; enable it again in the new project. Use separate connection folders for simultaneous Blender sessions. If a request times out after Blender started it, inspect the scene before retrying. A running Blender operation cannot be interrupted safely by the transport.

Protocol references: [MCP stdio transport](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports), [MCP tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools), and [initialization lifecycle](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle).

## Validation and present limits

Tested: registering and unregistering the add-on, old fitting tools, portable library save/load, multi-item Go operation, exact-fit reuse, unchanged original body geometry, normalized skin weights, region revisions and restoration, multi-item failure rollback, path traversal rejection, and invalid tool argument rejection.

A separate Python client completed an MCP stdio handshake and used the live Blender bridge to inspect a scene, inspect a fit, adjust it, receive an actual rendered PNG, and restore the previous revision. Configuration in a specific external agent application's UI has not been performed here.

A separate cross-rig test completed the automatic fitting path and preserved the body and rig state, but its surface heuristic still flagged potential intersections. First-pass cross-shape quality is not solved. The prepared demo deliberately uses previously tailored clothing to test reliable reuse, rather than presenting that tailored result as a new automatic fit.

VRM files currently use Blender's glTF geometry/skin importer. VRM metadata, spring bones, MToon fidelity, and VRM export validation are outside this release.
