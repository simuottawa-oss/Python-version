import unittest

from src.part_class import ConstraintType, Element, Face, Line, Part, Vertex


class ElementTests(unittest.TestCase):
    def test_unregistered_element_has_no_id(self):
        element = Element()

        with self.assertRaises(ValueError):
            _ = element.id

    def test_unregistered_element_cannot_access_constraints(self):
        first = Vertex(0, 0, 0)
        second = Vertex(1, 0, 0)

        with self.assertRaises(ValueError):
            first.get_constraint(second)
        with self.assertRaises(ValueError):
            first.set_constraint(second, ConstraintType.COINCIDENT)

    def test_vertex_converts_and_updates_coordinates(self):
        vertex = Vertex(1, 2, 3)
        self.assertEqual(vertex.get_coordinates(), (1.0, 2.0, 3.0))

        vertex.set_coordinates(4, 5, 6)
        self.assertEqual(vertex.get_coordinates(), (4.0, 5.0, 6.0))

    def test_line_exposes_its_vertices(self):
        first = Vertex(0, 0, 0)
        second = Vertex(1, 0, 0)

        line = Line(first, second)

        self.assertEqual(line.get_vertices(), (first, second))

    def test_line_rejects_the_same_vertex_twice(self):
        vertex = Vertex(0, 0, 0)

        with self.assertRaises(ValueError):
            Line(vertex, vertex)

    def test_face_exposes_its_three_lines(self):
        first = Vertex(0, 0, 0)
        second = Vertex(1, 0, 0)
        third = Vertex(0, 1, 0)
        lines = (
            Line(first, second),
            Line(second, third),
            Line(third, first),
        )

        face = Face(lines)

        self.assertEqual(face.get_lines(), lines)

    def test_face_rejects_a_non_triangular_number_of_lines(self):
        with self.assertRaises(ValueError):
            Face([])

        with self.assertRaises(ValueError):
            Face([Line(Vertex(0, 0, 0), Vertex(1, 0, 0))] * 4)


class PartTests(unittest.TestCase):
    def make_triangle(self, part):
        first = part.add_vertex((0, 0, 0))
        second = part.add_vertex((1, 0, 0))
        third = part.add_vertex((0, 1, 0))
        first_line = part.add_line(first, second)
        second_line = part.add_line(second, third)
        third_line = part.add_line(third, first)
        return (first, second, third), (first_line, second_line, third_line)

    def test_add_vertex_from_coordinates_assigns_id_and_float_coordinates(self):
        part = Part()

        vertex = part.add_vertex((1, 2, 3))

        self.assertEqual(vertex.id, 0)
        self.assertEqual(vertex.get_coordinates(), (1.0, 2.0, 3.0))

    def test_add_existing_vertex_returns_the_same_vertex(self):
        part = Part()
        vertex = Vertex(1, 2, 3)

        added = part.add_vertex(vertex)

        self.assertIs(added, vertex)
        self.assertIs(part.add_vertex(vertex), vertex)

    def test_vertex_ids_are_unique_across_element_types(self):
        part = Part()
        vertices, lines = self.make_triangle(part)

        face = part.add_face(lines)

        self.assertEqual(
            [element.id for element in (*vertices, *lines, face)],
            list(range(7)),
        )

    def test_add_vertex_rejects_coordinates_with_wrong_length(self):
        part = Part()

        for coordinates in ((0, 1), (0, 1, 2, 3)):
            with self.subTest(coordinates=coordinates):
                with self.assertRaises(ValueError):
                    part.add_vertex(coordinates)

    def test_vertex_cannot_belong_to_two_parts(self):
        first_part = Part()
        second_part = Part()
        vertex = first_part.add_vertex((0, 0, 0))

        with self.assertRaises(ValueError):
            second_part.add_vertex(vertex)

    def test_add_line_from_two_vertices(self):
        part = Part()
        first = part.add_vertex((0, 0, 0))
        second = part.add_vertex((1, 0, 0))

        line = part.add_line(first, second)

        self.assertEqual(line.get_vertices(), (first, second))
        self.assertEqual(line.id, 2)

    def test_add_line_accepts_a_line_object(self):
        part = Part()
        first = part.add_vertex((0, 0, 0))
        second = part.add_vertex((1, 0, 0))
        line = Line(first, second)

        self.assertIs(part.add_line(line), line)

    def test_duplicate_line_is_reused_independent_of_vertex_order(self):
        part = Part()
        first = part.add_vertex((0, 0, 0))
        second = part.add_vertex((1, 0, 0))

        line = part.add_line(first, second)

        self.assertIs(part.add_line(second, first), line)
        self.assertIs(part.add_line(Line(first, second)), line)

    def test_add_line_requires_both_vertices(self):
        part = Part()
        vertex = part.add_vertex((0, 0, 0))

        with self.assertRaises(ValueError):
            part.add_line(vertex)

    def test_add_line_rejects_a_second_vertex_with_a_line_object(self):
        part = Part()
        first = part.add_vertex((0, 0, 0))
        second = part.add_vertex((1, 0, 0))
        line = Line(first, second)

        with self.assertRaises(ValueError):
            part.add_line(line, second)

    def test_add_line_rejects_vertices_from_another_part(self):
        part = Part()
        other_part = Part()
        first = part.add_vertex((0, 0, 0))
        foreign_vertex = other_part.add_vertex((1, 0, 0))

        with self.assertRaises(ValueError):
            part.add_line(first, foreign_vertex)

    def test_add_face_from_three_lines(self):
        part = Part()
        _, lines = self.make_triangle(part)

        face = part.add_face(lines)

        self.assertEqual(face.get_lines(), lines)
        self.assertEqual(face.id, 6)

    def test_add_face_accepts_a_face_object(self):
        part = Part()
        _, lines = self.make_triangle(part)
        face = Face(lines)

        self.assertIs(part.add_face(face), face)

    def test_duplicate_face_is_reused_independent_of_line_order(self):
        part = Part()
        _, lines = self.make_triangle(part)

        face = part.add_face(lines)

        self.assertIs(part.add_face(tuple(reversed(lines))), face)
        self.assertIs(part.add_face(Face(lines)), face)

    def test_add_face_rejects_repeated_lines(self):
        part = Part()
        first = part.add_vertex((0, 0, 0))
        second = part.add_vertex((1, 0, 0))
        line = part.add_line(first, second)

        with self.assertRaises(ValueError):
            part.add_face((line, line, line))

    def test_add_face_rejects_lines_from_another_part(self):
        part = Part()
        other_part = Part()
        _, foreign_lines = self.make_triangle(other_part)

        with self.assertRaises(ValueError):
            part.add_face(foreign_lines)

    def test_add_face_rejects_lines_that_do_not_connect_three_vertices(self):
        part = Part()
        first = part.add_vertex((0, 0, 0))
        second = part.add_vertex((1, 0, 0))
        third = part.add_vertex((2, 0, 0))
        fourth = part.add_vertex((3, 0, 0))
        lines = (
            part.add_line(first, second),
            part.add_line(second, third),
            part.add_line(third, fourth),
        )

        with self.assertRaises(ValueError):
            part.add_face(lines)

    def test_origin_is_none_until_set(self):
        part = Part()

        self.assertIsNone(part.get_origin())

    def test_origin_can_be_set_and_changed(self):
        part = Part()
        first = part.add_vertex((0, 0, 0))
        second = part.add_vertex((1, 0, 0))

        part.set_origin(first)
        self.assertIs(part.get_origin(), first)

        part.set_origin(second)
        self.assertIs(part.get_origin(), second)

    def test_origin_must_be_a_vertex_in_the_part(self):
        part = Part()
        other_part = Part()
        foreign_vertex = other_part.add_vertex((0, 0, 0))

        with self.assertRaises(ValueError):
            part.set_origin(foreign_vertex)

    def test_constraint_is_none_until_set(self):
        part = Part()
        first = part.add_vertex((0, 0, 0))
        second = part.add_vertex((1, 0, 0))

        self.assertIsNone(part.get_constraint(first, second))

    def test_constraint_is_symmetric_and_can_be_replaced(self):
        part = Part()
        first = part.add_vertex((0, 0, 0))
        second = part.add_vertex((1, 0, 0))

        first.set_constraint(second, ConstraintType.COINCIDENT)
        self.assertEqual(second.get_constraint(first), ConstraintType.COINCIDENT)

        part.set_constraint(second, first, ConstraintType.PARALLEL)
        self.assertEqual(first.get_constraint(second), ConstraintType.PARALLEL)

    def test_constraint_can_be_removed(self):
        part = Part()
        first = part.add_vertex((0, 0, 0))
        second = part.add_vertex((1, 0, 0))
        part.set_constraint(first, second, ConstraintType.FIXED_DISTANCE)

        part.set_constraint(first, second, None)

        self.assertIsNone(part.get_constraint(first, second))

    def test_constraint_rejects_a_non_constraint_type(self):
        part = Part()
        first = part.add_vertex((0, 0, 0))
        second = part.add_vertex((1, 0, 0))

        with self.assertRaises(TypeError):
            part.set_constraint(first, second, "coincident")

    def test_constraint_cannot_be_set_between_an_element_and_itself(self):
        part = Part()
        vertex = part.add_vertex((0, 0, 0))

        with self.assertRaises(ValueError):
            part.get_constraint(vertex, vertex)

        with self.assertRaises(ValueError):
            part.set_constraint(vertex, vertex, ConstraintType.COINCIDENT)

    def test_constraint_requires_both_elements_to_belong_to_the_part(self):
        part = Part()
        other_part = Part()
        vertex = part.add_vertex((0, 0, 0))
        foreign_vertex = other_part.add_vertex((1, 0, 0))

        with self.assertRaises(ValueError):
            part.get_constraint(vertex, foreign_vertex)

        with self.assertRaises(ValueError):
            part.set_constraint(vertex, foreign_vertex, ConstraintType.COINCIDENT)


if __name__ == "__main__":
    unittest.main()
