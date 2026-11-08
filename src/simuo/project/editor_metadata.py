"""Optional panel metadata in the existing version-1 scene format."""

from simuo.project.scene import SceneGroup


def read_object_editor(obj, entry):
    editor = entry.get("editor", {})
    if isinstance(editor, dict):
        obj.editor_visible = editor.get("visible") is not False
        obj.selection_locked = editor.get("selection_locked") is True


def read_groups(data):
    groups = []
    entries = data.get("groups", [])
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        group = SceneGroup(str(entry.get("name", "Group")), identifier=entry.get("id"))
        members = entry.get("objects", [])
        group.members = members if isinstance(members, list) else []
        group.expanded = entry.get("expanded") is not False
        group.editor_visible = entry.get("visible") is not False
        group.selection_locked = entry.get("selection_locked") is True
        groups.append(group)
    roots = data.get("hierarchy_order", [])
    return groups, roots if isinstance(roots, list) else []


def write_group(group):
    return {"id": group.identifier, "name": group.name, "objects": list(group.members),
            "expanded": group.expanded, "visible": group.editor_visible,
            "selection_locked": group.selection_locked}
