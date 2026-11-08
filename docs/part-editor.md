# Part Editor

Open **New Part** or **Open Part…** from the startup menu, or use
**File → New Part** from the scene editor. Try the
[feature demo](../Assets/feature_demo.simuOPart) for a model with an editable
history.

## Sketch and extrude

1. Select the **Front**, **Right**, or **Top** plane, or a flat face of an
   existing solid. Choose **New Sketch**.
2. Draw lines, three-point arcs, or circles. For an arc, click its start, a
   point on the curve, and its end. Esc cancels a pending arc.
3. Select an edge and use **Add dimension…** to set line length or arc radius
   in millimetres. Use **Constraints** to make straight lines horizontal,
   vertical, or equal. Ctrl-click selects multiple lines for **Make equal**.
4. Close the outline and choose **Finish Sketch → Extrude**. Set the distance
   and choose direction or symmetry. You can also extrude a flat face directly.
5. Select a sketch in the feature tree to revisit it. Deleting a sketch or
   extrusion can also remove features that depend on its faces. The editor
   prompts before removing dependents.

The **Constraints** list shows dimensions and relations. Delete an entry to
remove the constraint while keeping the geometry in place. Undo restores it.
Press `F` to frame the current sketch or model, or `F1` for editor help.

## Save and export

Use **File → Save SimuO Part** to keep editable sketches, supports, constraints,
extrusions, and part properties. You can save unfinished sketches as drafts.
Import a saved solid into a scene using **Import File**.

Use **File → Export → OBJ… / STL…** after extruding a solid. The exports contain
local mesh coordinates in metres. STL readers may require you to choose metres
on import. Use the `.simuOPart` file to preserve editable geometry and physics
properties. See [file formats](file-formats.md) for the supported versions.
