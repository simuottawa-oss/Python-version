# src/part.py
from __future__ import annotations

from collections import Counter
from enum import Enum
from typing import Sequence


class ConstraintType(Enum):
    FIXED_DISTANCE = "fixed_distance"
    COINCIDENT = "coincident"
    PARALLEL = "parallel"
    PERPENDICULAR = "perpendicular"
    VERTICAL = "vertical"
    HORIZONTAL = "horizontal"
    EQUAL = "equal"


class Element:
    """Base class for elements that belong to a Part."""

    def __init__(self) -> None:
        self._id: int | None = None
        self._part: Part | None = None

    @property
    def id(self) -> int:
        if self._id is None:
            raise ValueError("Element has not been added to a Part")
        return self._id

    def _attach(self, part: Part, element_id: int) -> None:
        if self._part is not None and self._part is not part:
            raise ValueError("Element already belongs to another Part")

        self._part = part
        self._id = element_id

    def get_constraint(self, other: Element) -> ConstraintType | None:
        """Return the constraint for this element and another, if any."""
        if self._part is None:
            raise ValueError("Element has not been added to a Part")
        return self._part.get_constraint(self, other)

    def set_constraint(
        self,
        other: Element,
        constraint_type: ConstraintType | None,
    ) -> None:
        """Set or remove the constraint between this element and another."""
        if self._part is None:
            raise ValueError("Element has not been added to a Part")
        self._part.set_constraint(self, other, constraint_type)


class Vertex(Element):
    def __init__(self, x: float, y: float, z: float) -> None:
        super().__init__()
        self._coordinates = (float(x), float(y), float(z))

    def get_coordinates(self) -> tuple[float, float, float]:
        return self._coordinates

    def set_coordinates(self, x: float, y: float, z: float) -> None:
        self._coordinates = (float(x), float(y), float(z))


class Line(Element):
    def __init__(self, first: Vertex, second: Vertex) -> None:
        super().__init__()
        if first is second:
            raise ValueError("A line must have two different vertices")
        self._vertices = (first, second)

    def get_vertices(self) -> tuple[Vertex, Vertex]:
        return self._vertices


class Face(Element):
    def __init__(self, lines: Sequence[Line]) -> None:
        super().__init__()
        if len(lines) != 3:
            raise ValueError("This implementation supports triangular faces")
        self._lines = tuple(lines)

    def get_lines(self) -> tuple[Line, Line, Line]:
        return self._lines  # type: ignore[return-value]


class Part:
    """Own vertices, lines, faces, constraints, and an optional origin."""

    def __init__(self) -> None:
        # IDs are unique across all element types within this Part.
        self._next_id = 0
        self._elements: dict[int, Element] = {}

        # Indexes avoid scanning the element collections.
        self._line_by_vertices: dict[tuple[int, int], Line] = {}
        self._face_by_lines: dict[tuple[int, int, int], Face] = {}
        self._constraints: dict[tuple[int, int], ConstraintType] = {}

        self._origin_id: int | None = None

    def _register(self, element: Element) -> None:
        if element._part is not None:
            if element._part is self:
                return
            raise ValueError("Element already belongs to another Part")

        element._attach(self, self._next_id)
        self._elements[self._next_id] = element
        self._next_id += 1

    def _require_member(self, element: Element) -> None:
        if element._part is not self or self._elements.get(element.id) is not element:
            raise ValueError("Element does not belong to this Part")

    def add_vertex(self, vertex: Vertex | tuple[float, float, float]) -> Vertex:
        """Add a Vertex or create one from an (x, y, z) coordinate tuple."""
        if isinstance(vertex, Vertex):
            if vertex._part is self:
                return vertex
            self._register(vertex)
            return vertex

        if len(vertex) != 3:
            raise ValueError("Vertex coordinates must contain exactly 3 values")

        result = Vertex(*vertex)
        self._register(result)
        return result

    def add_line(
        self,
        line_or_first: Line | Vertex,
        second: Vertex | None = None,
    ) -> Line:
        """Add a Line, or create one from two vertices."""
        if isinstance(line_or_first, Line):
            if second is not None:
                raise ValueError("Do not provide a second vertex when adding a Line")
            line = line_or_first
        else:
            if second is None:
                raise ValueError("Provide both vertices when creating a Line")
            line = Line(line_or_first, second)

        first_vertex, second_vertex = line.get_vertices()
        self._require_member(first_vertex)
        self._require_member(second_vertex)

        key = tuple(sorted((first_vertex.id, second_vertex.id)))
        existing = self._line_by_vertices.get(key)
        if existing is not None:
            return existing

        self._register(line)
        self._line_by_vertices[key] = line
        return line

    def add_face(self, face_or_lines: Face | Sequence[Line]) -> Face:
        """Add a Face, or create a triangular face from three lines."""
        face = (
            face_or_lines
            if isinstance(face_or_lines, Face)
            else Face(face_or_lines)
        )
        lines = face.get_lines()

        if len({line.id for line in lines}) != 3:
            raise ValueError("A face must use three different lines")

        for line in lines:
            self._require_member(line)

        vertices = {
            vertex.id
            for line in lines
            for vertex in line.get_vertices()
        }
        if len(vertices) != 3:
            raise ValueError("The three lines must connect exactly three vertices")

        degree = Counter(
            vertex.id
            for line in lines
            for vertex in line.get_vertices()
        )
        if any(count != 2 for count in degree.values()):
            raise ValueError("The lines must form a closed triangular loop")

        key = tuple(sorted(line.id for line in lines))
        existing = self._face_by_lines.get(key)
        if existing is not None:
            return existing

        self._register(face)
        self._face_by_lines[key] = face
        return face

    def get_constraint(
        self,
        first: Element,
        second: Element,
    ) -> ConstraintType | None:
        """Return None when no constraint has been set for this pair."""
        self._require_member(first)
        self._require_member(second)

        if first is second:
            raise ValueError("A constraint requires two different elements")

        key = tuple(sorted((first.id, second.id)))
        return self._constraints.get(key)

    def set_constraint(
        self,
        first: Element,
        second: Element,
        constraint_type: ConstraintType | None,
    ) -> None:
        """Set, replace, or remove the symmetric constraint for a pair."""
        self._require_member(first)
        self._require_member(second)

        if first is second:
            raise ValueError("A constraint requires two different elements")

        key = tuple(sorted((first.id, second.id)))
        if constraint_type is None:
            self._constraints.pop(key, None)
        elif not isinstance(constraint_type, ConstraintType):
            raise TypeError("constraint_type must be a ConstraintType or None")
        else:
            self._constraints[key] = constraint_type

    def set_origin(self, vertex: Vertex) -> None:
        self._require_member(vertex)
        self._origin_id = vertex.id

    def get_origin(self) -> Vertex | None:
        """Return None when no origin has been set."""
        if self._origin_id is None:
            return None

        origin = self._elements[self._origin_id]
        if not isinstance(origin, Vertex):
            raise RuntimeError("Part origin ID does not refer to a Vertex")
        return origin