# Controls and editor panels

## Viewport and editing

- `W`, `A`, `S`, and `D` move the camera relative to its viewing direction.
- `Space` moves the camera up. Left/Right turn the camera.
- `C` moves the camera down. Command/Control/Alt shortcuts stop camera movement
  and never start it. Press a movement key again to resume after a shortcut.
- Hold the right mouse button and move the mouse to look around.
- Left-click a mesh in the viewport to select it. A thin blue outline marks the
  selected meshes while preserving their surface shading. Object Hierarchy and
  Properties follow the same selection. Click empty space to clear selection.
- Cmd-click (macOS) or Ctrl-click (Windows/Linux) toggles individual objects in
  the selection, in either the hierarchy or viewport. Shift-click selects a
  visible range in the hierarchy. Shift-click in the viewport toggles a mesh.
- **Edit → Undo / Redo** reverses committed name, transform, visibility, lock,
  import, duplicate, and delete changes. Use Cmd+Z / Shift+Cmd+Z on macOS, or
  Ctrl+Z / Ctrl+Y on Windows. Saving marks a checkpoint: returning to it with
  undo/redo clears the unsaved indicator. Opening or creating a scene starts
  a fresh history. Selection and camera movement do not add history entries.
- **Edit → Duplicate** (Cmd+D / Ctrl+D) copies the selection in place with
  unique names and IDs and selects the copies. **Edit → Delete** (Delete, or
  Backspace on macOS) removes the selection. Both are available in the hierarchy
  context menu and are undone as one action for the entire selection.
- Cmd+A / Ctrl+A selects all matching hierarchy rows, or all visible, unlocked
  viewport objects when the viewport is focused. Text fields keep their normal
  text-editing shortcuts. Duplicate/delete shortcuts are disabled while typing.
- Press `F` with the viewport or hierarchy focused to frame the selected visible
  objects together. Framing keeps the camera's viewing direction and fits them to the
  available viewport size.
- Press `Shift+F` to frame the visible scene, including while no object is selected.
  Hidden objects stay excluded, and isolation is respected.
- During a viewport gesture, `Escape` cancels it. Otherwise, with the viewport focused,
  `Escape` exits isolation first. Outside isolation
  it closes the application. When renaming an object or group, Escape cancels
  the unfinished name change.

## Editor panels

- **View → Object Hierarchy** and **View → Properties** show or hide the two
  panels. Select an object in the viewport or hierarchy to edit its name,
  position, rotation, and scale in Properties. Changes update the viewport
  without a popup dialog.
- Double-click an object's name in the hierarchy to rename it. Importing a model
  leaves the current selection unchanged until you select the new model.
- The hierarchy has a collapsible scene header, compact object rows, and object
  and selection counts. Search filters names without changing the selected
  object. The footer indicates when the selection is filtered out.
- The funnel button beside search filters **Visibility → Visible / Hidden**
  and **Selection Lock → Locked / Unlocked**. The filters combine with each
  other and with the search text. They include inherited group controls and
  temporary isolation, so results match the current viewport state. Active
  filters appear below search. **Clear** resets those filters while keeping
  the search text. Filtering preserves selection and does not edit the scene.
- Click an object's eye button to hide/show it in the viewport. The selection-lock
  button prevents viewport clicks from selecting it. Hidden and locked objects
  remain accessible through the hierarchy and Properties. These editor controls
  are saved with the scene and do not change its physics properties.
- Right-click an object's name for Rename, Frame Selected, visibility, and
  selection-lock actions, plus Duplicate and Delete. Right-clicking a selected
  row preserves the selection so actions apply to all selected objects. `F2`
  also starts renaming the focused object row. Escape cancels an inline rename.
- With multiple objects selected, Properties displays their shared transform
  values and a dash for mixed values. Editing a component assigns that value to
  every selected object, preserving the other components. Reset also applies to
  the entire selection. Rename objects individually.
- Create an organizational group with the hierarchy's **New Group** (folder +) button, **Edit →
  Group Selection** (Cmd+G / Ctrl+G), or the right-click menu. Selected objects
  move into the new group. Without a selection, **New Group** creates an empty group.
  Double-click a group name (or use F2) to rename it. The arrow collapses its
  members, and clicking the name selects the group's objects.
- Drag object names onto the middle of a group row to move them into it. Drag
  near a row's top/bottom edge to reorder, following the blue drop indicator.
  Drag into blank space below the rows to move objects back to the scene root.
  Multi-object drags preserve their displayed order. Group rows can be reordered
  at the root. Clear search and filters before dragging. **Move to Group** in the context
  menu also works while searching. Groups are one level deep and do not change
  object transforms or create transform parenting.
- Group eye/lock controls apply to every member, including objects added later,
  while retaining each object's individual visibility/lock settings. The group
  context menu offers **Remove Group (Keep Objects)**. Creating, renaming,
  removing, moving, and changing group controls support undo/redo. Group names,
  membership, order, controls, and collapse state are saved with the scene. Older scene files still open normally.
- Up/Down and Home/End navigate the displayed hierarchy. Shift extends an object
  range. Right expands a group and enters its members. Left moves to the parent
  group or collapses it. Cmd/Ctrl with navigation keys moves keyboard focus
  without changing the selection. This also works from a row's eye/lock controls.
  Text editors retain their normal arrow-key behavior. Clicking empty hierarchy
  space, including the no-results message, clears selection.
- The compact **Show Selected** button beside the scene name (also in View) clears search and filters and expands groups
  containing selected objects. The adjacent **Isolate Selected** icon temporarily
  hides everything else. It highlights blue while active, with an **Isolated view**
  indicator in the footer. Click it again or use the checked View menu item to
  restore the view. Hover the header icons to see their action names.
  Escape also exits isolation from the hierarchy or viewport. Isolation respects
  individual/group visibility, does not change the saved
  scene or undo history, and is cleared on opening/creating a scene.
- Properties has collapsible **Transform** and **Mesh** sections, color-coded
  X/Y/Z fields, and a source-asset label with the full mesh path in its tooltip.
  Use **Reset** for the whole transform, or the reset button beside a vector for
  just position, rotation, or scale. Scale resets to one. Position and rotation
  reset to zero.
- Use Enter or leave a numeric field to apply typed values. Up/Down steps the
  focused field. Scrolling over an unfocused numeric field does not edit it.
  Rotation values are in degrees.
- Drag a panel's title bar to move it. Drop it on a highlighted docking area to
  snap it to the left, right, top, or bottom of the viewport, or beside another
  panel. Drop onto another panel to group them in tabs.
- Drag the divider between panels or the viewport to resize them. Panels can
  also float as separate windows. Drag them back into the editor to dock again.
- The default layout stacks Object Hierarchy above Properties on the right.
  **View → Reset Layout** reopens both panels in this arrangement.
- The editor remembers the window geometry and panel layout on normal exit.
  These preferences are local to the application and are not part of scene files.
- Modified scenes prompt to save before closing, opening another project, or
  creating a new one. Canceling a save keeps the current scene open.

## Viewport tools

- The compact toolbar inside the viewport offers **Select**, **Move**,
  **Rotate**, and **Scale**. The active tool stays highlighted. Use the bottom
  chevron to show labels. `T` or **View → Viewport Tools** hides/shows the rail.
- **Select:** click objects normally, or drag a rectangle (box selection). A plain box replaces
  selection, Shift adds, and Cmd/Ctrl toggles. By default only visible mesh surfaces
  count. Enable **Select through** (X-Ray) in the options row to select through other objects.
- **Move:** drag a colored axis arrow, a small plane tile, or the center circle for
  movement in the screen plane. An axis facing the camera has a small colored
  depth handle. Drag vertically to move along it.
- **Rotate:** drag a colored ring around its axis. **Scale:** drag an axis square
  for local-axis scaling, or the center square for uniform scaling. Scaling
  multiplies existing scales and preserves mirrored objects. It stops before zero.
- **Scene axes** (World) keeps the handles aligned to fixed scene directions.
  **Object axes** (Local) follows the last selected editable object's rotation.
  Scale always uses object axes.
- **Selection center** (Median) rotates/scales around the average position of the
  selected objects. **Last selected** (Active) instead uses the last selected
  editable object's position. These refer to object origins, rather than mesh bounds.
- Hover over a tool or option to read its explanation. The center selector appears
  for Rotate and Scale. The axes selector appears for Move and Rotate, since Scale
  always follows object axes. Options wrap onto another row in a narrow viewport.
- Snapping uses relative increments: **1 unit** for moving, **15°** for rotating,
  and **0.1** for scaling. Hold **Shift** during a transform for finer adjustment.
- Multi-object transforms preserve offsets when moving and use the chosen pivot
  when rotating/scaling. Hidden or selection-locked objects are excluded.
- Properties follows live previews. Release to commit one undo step for the whole
  drag. **Escape** or **right-click** cancels. Changing tool/selection, losing focus,
  or resizing also cancels an unfinished transform. Tool options and selection do
  not create scene edits. Cmd/Ctrl-click still toggles objects in every tool.
- **View → Frame Selected** (`F`) and **Frame Scene** (`Shift+F`) remain available.
  Camera controls are unchanged and pause during selection/transform drags.

Use **Edit → Physics Properties** to edit bounce, body type, and starting velocity. **Render** opens the physics playback window for the current scene.

## Import and save

Use **Import File** to add a `.simuOPart` or OBJ mesh. An OBJ import can create
a separate temporary part while keeping the source file intact. Temporary
imports appear in **Temporary parts**. When saving the scene, choose a
permanent destination for each one. Canceling a destination dialog cancels the
scene save. Keep the resulting part files with the scene when moving it.

## Physics playback

Use **Edit → Physics Properties** to set the body's static/dynamic mode,
bounce, and initial velocity for the scene instance. Choose **Render** to run
a separate simulation of the scene. Reopen playback after changing scene
properties to use the new values.

Playback provides **Pause/Play** (`P`), **Step** (1/240 s), **Reset** (`R`),
**Frame scene** (`F`), gravity, and an optional floor. Bullet uses the
instance's transform and motion along with the part's mass and material.
Legacy OBJ parts default to static. A dynamic legacy mesh uses a convex hull
for collision and a default mass of 1 kg. See [file formats](file-formats.md)
for what the scene stores.
