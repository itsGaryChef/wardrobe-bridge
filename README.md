# Wardrobe Bridge

Wardrobe Bridge is a Blender add-on for moving clothing between humanoid avatars, transferring skin weights, maintaining a personal wearable library, refining generated fits, and retargeting humanoid animation. It is designed around VRM and Mixamo-style rigs while preserving the source avatar and target body.

The repository contains the add-on itself. Personal avatars, clothing, renders, fitted examples, and each user's inventory are deliberately stored outside the repository.

## Current features

- Import FBX, GLB, glTF, VRM geometry, and Blender files.
- Save source avatars and separate wearables into a portable personal library.
- Sort inventory by source avatar and by Outfits, Shirts, Pants, Shoes, or Accessories.
- Fit multiple wearable meshes to a different humanoid body and transfer normalized weights.
- Reuse previously tailored geometry when the saved source body and target match exactly.
- Refine torso, shoulder, limb, elbow, knee, hip, and foot regions with reversible revisions.
- Retarget and bake actions between recognized VRM and Mixamo-style humanoid rigs.
- Connect a local MCP client for bounded inspection, fitting, revision, preview, library, and retargeting operations.
- Save every generated preview as a uniquely named PNG in the configured render directory.

Cross-shape fitting and animation retargeting require visual review. Facial source meshes, facial animation, finger chains, IK control rigs, props, VRM spring bones, and arbitrary custom controls are outside the automatic retargeter's current scope.

## Install

1. Download a release ZIP or build one with `python scripts/package_addon.py`.
2. In Blender, open **Edit → Preferences → Add-ons**.
3. Choose **Install from Disk**, select `wardrobe_bridge.zip`, and enable **Wardrobe Bridge**.
4. Restart Blender after replacing an older version.
5. In the 3D View, press **N** and open the **Wardrobe** tab.

Blender 5.2 is the tested version. The manifest declares Blender 4.2 as the minimum.

## Create a personal wardrobe library

Choose a folder under **Wardrobe → My master library**. This folder should live outside the installed add-on so upgrades cannot overwrite it.

1. Import an avatar or wearable.
2. Select body meshes and click **Tag Body**.
3. Select separate clothing meshes and click **Tag Wearable**.
4. Set **Source body reference**.
5. Under **Prepare & Save Library Items**, choose Source Avatar or Wearable.
6. For a wearable, select its category and enter the avatar it originally came from.
7. Click **Save Selected to My Library**.

The library stores `.blend` assets, packed image textures, previews, and `wardrobe-library.json`. Back up the entire chosen folder. Clothing fused into a body mesh must be separated once before it can become an independent wearable.

Unrigged items may be saved as raw-placement assets. They can be browsed and loaded immediately, but must be positioned on a source avatar and given a body reference before automatic cross-avatar fitting.

## Fit clothing

1. Select a library item and click **Use as Source**, or import a source avatar.
2. Choose its body reference and enable the wearable pieces to transfer.
3. Load or import the destination avatar and choose its target body.
4. Press **GO — Fit Outfit**.
5. Inspect the result in several poses and use **Review & Refine** where necessary.

The source remains unchanged. Running GO again for the same source wearable and target replaces the previous generated fit after the new operation succeeds. Revisions keep one visible fit object and store undo history in mesh data.

## Retarget an animation

1. Open **Pose & Animation Retargeting**.
2. Set **My pose / animation library** to a folder containing FBX, BVH, or Blender motion files.
3. Click **Scan Motion Folder**, choose Animations or Poses, and select a motion from the second dropdown.
4. Click **Load Selected Motion**. The imported source rig and action are selected automatically.
5. Choose the destination armature.
6. Click **Check Humanoid Mapping**.
7. Choose the bake interval and whether to preserve scaled hips/root translation.
8. Click **Retarget & Bake Action**.

The add-on creates a new target action and preserves the source action. The mapping recognizes common VRM, VRoid, Mixamo, and Auto-Rig Pro humanoid names. Inspect feet, hips, shoulders, and hand orientation after baking.

Loading an inventory asset switches the active 3D View to Material Preview so packed textures and material colors are visible. The loader reports empty material slots or unavailable texture images when it finds them.

## Bundled animation library

Redistributable animation clips will live under `wardrobe_bridge/motions/`. The manifest is intentionally empty until properly licensed FBX files are supplied and converted. Do not commit an animation unless its license permits redistribution in this add-on.

Source FBX files should be organized by category before processing:

```text
incoming-motion/
  idle/
  walk/
  run/
  jump/
  dance/
  gesture/
  combat/
  emote/
```

Each release clip should record its title, category, FPS, frame range, loop behavior, root-motion behavior, source, author, license, and attribution requirements in the bundled manifest.

To catalog a local collection without copying its files into Git:

```powershell
python scripts/catalog_motion_folder.py "D:\Photos\3D Files\Avatars\Animation Library" "work\animation-library-catalog.json"
```

Catalog entries remain marked `UNVERIFIED_LOCAL_ONLY` until their redistribution terms are documented.

## MCP connection

Enable **Agent Connection** in Blender and copy the generated MCP configuration. The server uses standard input/output and a local bridge directory. Its Python process does not execute arbitrary Python supplied by an MCP client.

The tool set can inspect the scene and library, load and tag items, fit clothes, inspect and revise fits, change the preview frame, render persistent previews, save library assets, inspect/MCP inspect humanoid mappings, and bake retargeted actions.

## Development

Run the syntax and synthetic retarget checks from the repository root:

```powershell
python scripts/check.py
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --python tests/test_retarget.py
```

Build the installable ZIP:

```powershell
python scripts/package_addon.py
```

Generated archives are written to `dist/` and are ignored by Git.

## Content and licensing

No license has been assigned to this repository yet. That means the code and assets remain fully copyrighted by their respective owners until a license is selected. Third-party animations must include compatible redistribution terms and attribution before they are added to a release.
