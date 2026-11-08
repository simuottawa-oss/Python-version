"""Behavior checks: physical values, invalid inputs, simulation and real render output."""
from dataclasses import replace
import json
import math
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from part import load_part, Simulation
from render import Camera, scene, write_svg

SAMPLE = Path(__file__).with_name("aluminum_cube.simuOPart")


class PartTests(unittest.TestCase):
    def setUp(self):
        self.part = load_part(SAMPLE)

    def load_changed(self, mutate):
        data = json.loads(SAMPLE.read_text())
        mutate(data)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.simuOPart"
            path.write_text(json.dumps(data))
            return load_part(path)

    def test_mass_volume_and_inertia(self):
        self.assertAlmostEqual(self.part.volume, 0.008)
        self.assertAlmostEqual(self.part.mass, 21.6)
        for moment in self.part.inertia:
            self.assertAlmostEqual(moment, 0.144)

    def test_size_change_recalculates_mass(self):
        part = self.load_changed(lambda d: d["geometry"].update(size=[0.4,0.2,0.2]))
        self.assertAlmostEqual(part.mass, 43.2)
        self.assertNotEqual(part.inertia[0], part.inertia[1])

    def test_explicit_mass_and_metadata(self):
        part = self.load_changed(lambda d: d["physics"].update(mass_source="explicit", mass=1))
        self.assertEqual(part.mass, 1)
        self.assertAlmostEqual(part.inertia[0], 1/150)
        self.assertEqual(part.properties["demo:temperature_K"], 293.15)

    def test_reject_bad_physics_and_unsupported_semantics(self):
        changes = [lambda d: d.update(version=2),
                   lambda d: d.update(version=True),
                   lambda d: d["geometry"].update(size=[0,1,1]),
                   lambda d: d["geometry"].update(size=[True,1,1]),
                   lambda d: d["material"].update(density=-1),
                   lambda d: d["material"].update(restitution=1.1),
                   lambda d: d["physics"].update(mass=1),
                   lambda d: d["physics"].update(collider="mesh"),
                   lambda d: d["physics"].update(angular_velocity=[1,0,0]),
                   lambda d: d["initial_state"].update(position=[0,0,0]),
                   lambda d: d["initial_state"].update(velocity=[float("inf"),0,0]),
                   lambda d: d.update(properties={"temperature":300}),
                   lambda d: d["units"].update(length="cm")]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.load_changed(change)

    def test_duplicate_json_keys_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "duplicate.simuOPart"
            path.write_text('{"format":".simuOPart","format":"other"}')
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                load_part(path)

    def test_free_fall_matches_analytic_solution(self):
        sim = Simulation(self.part)
        for _ in range(48):
            sim.step()
        self.assertAlmostEqual(sim.time, 0.2)
        expected_y = self.part.position[1] - 0.5*9.81*sim.time**2
        self.assertLess(abs(sim.position[1]-expected_y), 0.005)
        self.assertAlmostEqual(sim.velocity[1], -9.81*sim.time)
        self.assertAlmostEqual(sim.position[0], self.part.velocity[0]*sim.time)

    def test_impact_restitution_and_friction(self):
        sim = Simulation(self.part)
        for _ in range(240):
            previous_vy = sim.velocity[1]
            sim.step()
            if sim.velocity[1] > 0:
                incoming = previous_vy + sim.gravity*sim.dt
                self.assertAlmostEqual(sim.velocity[1], -incoming*self.part.restitution)
                self.assertAlmostEqual(sim.position[1], self.part.size[1]/2)
                self.assertLess(math.hypot(sim.velocity[0],sim.velocity[2]),
                                math.hypot(*self.part.velocity[::2]))
                break
        else:
            self.fail("Expected a bounce within one second")

    def test_settles_above_floor_and_reset_is_repeatable(self):
        sim = Simulation(self.part)
        for _ in range(2400):
            sim.step()
            self.assertGreaterEqual(sim.position[1], self.part.size[1]/2)
        result = (sim.position[:], sim.velocity[:], sim.time)
        self.assertEqual(sim.velocity, [0,0,0])
        sim.reset()
        for _ in range(2400):
            sim.step()
        self.assertEqual((sim.position,sim.velocity,sim.time), result)

    def test_static_part_does_not_move(self):
        part = self.load_changed(lambda d: (d["physics"].update(body_type="static"),
                                            d["initial_state"].update(velocity=[0,0,0])))
        sim = Simulation(part)
        for _ in range(300):
            sim.step()
        self.assertEqual(tuple(sim.position), part.position)

    def test_floor_without_friction_preserves_horizontal_speed(self):
        sim = Simulation(replace(self.part, friction=0))
        for _ in range(1000):
            sim.step()
        self.assertEqual(sim.velocity[0], self.part.velocity[0])
        self.assertEqual(sim.velocity[2], self.part.velocity[2])

    def test_renderer_uses_geometry_color_and_simulation_position(self):
        sim = Simulation(self.part)
        camera = Camera(self.part)
        initial = scene(self.part,sim,camera)
        polygons = [c for c in initial if c[0] == "polygon"]
        self.assertEqual(len(polygons), 6)
        self.assertTrue(all(math.isfinite(x) for c in initial for x in c[1]))
        changed_color = scene(replace(self.part,color="#ff0000"),sim,camera)
        self.assertNotEqual(polygons, [c for c in changed_color if c[0] == "polygon"])
        for _ in range(60):
            sim.step()
        self.assertNotEqual(initial, scene(self.part,sim,camera))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "preview.svg"
            write_svg(path,self.part,sim,camera)
            root = ET.parse(path).getroot()
            self.assertEqual(len(root.findall("{http://www.w3.org/2000/svg}polygon")),6)
            self.assertIn("21.6 kg", path.read_text())


if __name__ == "__main__":
    unittest.main()
