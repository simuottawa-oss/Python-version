"""Rigid-body integration checks without a display or GPU."""
from dataclasses import replace
import math
import unittest

import numpy as np

from tests import ROOT
from simuo.project.scene import Scene, SceneObject
from simuo.project.transforms import rotation_matrix
from simuo.parts.part_assets import PartAsset
from simuo.parts.sketch_geometry import Sketch, prism_vertices
from simuo.physics.physics_world import PhysicsWorld, contact_reference


class PhysicsTests(unittest.TestCase):
    def part(self, **changes):
        obj = SceneObject(meshPath=ROOT / "Assets/aluminum_cube.simuOPart")
        obj.velocity = [0,0,0]
        for key,value in changes.items():
            setattr(obj,key,value)
        return obj

    def world(self, *objects, **kwargs):
        scene = Scene()
        scene.objects = list(objects)
        world = PhysicsWorld(scene,**kwargs)
        self.addCleanup(world.close)
        return world

    def test_gravity_and_snapshot_isolation(self):
        source = self.part(position=[0,2,0])
        world = self.world(source,floor=False)
        world.step(48)
        self.assertAlmostEqual(world.time,.2)
        self.assertAlmostEqual(world.scene.objects[0].velocity[1],-9.81*.2,places=5)
        self.assertLess(abs(world.scene.objects[0].position[1]-(2-.5*9.81*.2**2)),.005)
        self.assertEqual(source.position,[0,2,0])
        self.assertEqual(source.velocity,[0,0,0])

    def test_rotations_use_editor_convention(self):
        source = self.part(rotation=[20,35,65],angularVelocity=[0,1,0])
        world = self.world(source,gravity=0,floor=False)
        original = rotation_matrix(source.rotation)
        world.sync()
        current = rotation_matrix(world.scene.objects[0].rotation)
        np.testing.assert_allclose(original,current,atol=1e-8)
        world.step(48)
        evolved = rotation_matrix(world.scene.objects[0].rotation)
        self.assertGreater(np.linalg.norm(original-evolved),.1)

    def test_floor_bounce_settling_and_reset(self):
        world = self.world(self.part())
        bounced = False
        for _ in range(2400):
            world.step()
            obj = world.scene.objects[0]
            bounced |= obj.velocity[1] > .3
            self.assertGreater(obj.position[1],.095)
        self.assertTrue(bounced)
        self.assertAlmostEqual(obj.position[1],.1,places=3)
        first = obj.position[:]
        world.reset()
        self.assertEqual(world.time,0)
        self.assertEqual(obj.position,[0,1.1,0])
        world.step(2400)
        np.testing.assert_allclose(obj.position,first,atol=1e-8)

    def test_pair_collision_exchanges_momentum(self):
        a = self.part(position=[-.3,1,0],velocity=[1,0,0])
        b = self.part(position=[.3,1,0],velocity=[-1,0,0])
        a.part = replace(a.part,friction=0,restitution=1)
        b.part = replace(b.part,friction=0,restitution=1)
        world = self.world(a,b,gravity=0,floor=False)
        world.step(120)
        va,vb = [o.velocity[0] for o in world.scene.objects]
        self.assertLess(va,-.8)
        self.assertGreater(vb,.8)
        self.assertAlmostEqual(va+vb,0,places=5)

    def test_friction_reduces_ground_speed(self):
        obj = self.part(position=[0,.1,0],velocity=[1,0,0])
        world = self.world(obj)
        world.step(480)
        self.assertLess(np.linalg.norm(world.scene.objects[0].velocity),.05)

    def test_three_box_stack_remains_supported_and_settles(self):
        objects = [self.part(position=[0, .1 + .2*i, 0]) for i in range(3)]
        for obj in objects:
            obj.part = replace(obj.part, restitution=0)
        world = self.world(*objects)
        world.step(2400)
        for obj, height in zip(world.scene.objects, (.1, .3, .5)):
            np.testing.assert_allclose(obj.position, [0, height, 0], atol=.005)
            self.assertLess(np.linalg.norm(obj.velocity), .01)

    def test_acceleration_is_additional_to_gravity(self):
        world = self.world(self.part(acceleration=[2,9.81,0]),floor=False)
        world.step(48)
        np.testing.assert_allclose(world.scene.objects[0].velocity,[.4,0,0],atol=1e-8)

    def test_kinematic_acceleration_ignores_gravity_and_resets(self):
        source = self.part(position=[1, 2, 3], velocity=[2, 0, 0], acceleration=[4, 0, 0])
        source.body_type = "kinematic"
        world = self.world(source, floor=False)
        obj = world.scene.objects[0]
        world.step(240)

        self.assertEqual(world.masses, [0])
        np.testing.assert_allclose(obj.position, [5, 2, 3])
        np.testing.assert_allclose(obj.velocity, [6, 0, 0])
        mocap = world.model.body_mocapid[world.bodies[0]]
        np.testing.assert_allclose(world.data.mocap_pos[mocap], obj.position)
        self.assertEqual(source.position, [1, 2, 3])
        world.reset()
        self.assertEqual(obj.position, source.position)
        self.assertEqual(obj.velocity, source.velocity)

    def test_kinematic_collider_pushes_dynamic_body_and_uses_bounce(self):
        speeds = []
        for bounce in (0, 1):
            platform = self.part(position=[-2, 0, 0], velocity=[2, 0, 0])
            platform.setPhysicsProperties(bounce, platform.velocity, "kinematic")
            block = self.part(position=[0, 0, 0])
            block.setPhysicsProperties(1, block.velocity, "dynamic")
            world = self.world(platform, block, gravity=0, floor=False)
            world.step(240)
            moving, pushed = world.scene.objects
            np.testing.assert_allclose(moving.position, [0, 0, 0], atol=1e-10)
            self.assertGreater(pushed.position[0], 0.1)
            speeds.append(pushed.velocity[0])
        self.assertGreater(speeds[1], speeds[0] + 0.5)

    def test_static_and_legacy_geometry(self):
        base = SceneObject(meshPath=ROOT / "Assets/cube.simuOPart")
        base.position = [0,.5,0]
        base.scale = [.2,.2,.2]
        box = self.part(position=[0,1.5,0])
        world = self.world(base,box,floor=False)
        world.step(2400)
        self.assertEqual(world.legacy_count,1)
        self.assertEqual(world.scene.objects[0].position,[0,.5,0])
        self.assertAlmostEqual(world.scene.objects[1].position[1],.8,places=2)

    def test_scale_changes_density_mass_and_inertia_but_not_explicit_mass(self):
        density = self.part(scale=[2,1,1])
        explicit = self.part(position=[3,1,0],scale=[2,1,1])
        explicit.part = replace(explicit.part,mass_source="explicit",mass=1)
        world = self.world(density,explicit,gravity=0,floor=False)
        self.assertAlmostEqual(world.masses[0],43.2)
        self.assertEqual(world.masses[1],1)
        inertia = world.model.body_inertia[world.bodies[1]]
        np.testing.assert_allclose(sorted(inertia), sorted([1/150,1/60,1/60]))

    def test_multiple_windows_have_separate_worlds(self):
        a,b = self.world(self.part(),floor=False),self.world(self.part(),floor=False)
        a.step(30)
        self.assertEqual(b.time,0)
        self.assertNotEqual(a.scene.objects[0].position,b.scene.objects[0].position)
        a.close()
        b.step()
        self.assertEqual(b.steps,1)

    def test_invalid_scale_rejected(self):
        with self.assertRaises(ValueError):
            self.world(self.part(scale=[0,1,1]))

    def test_live_gravity_and_floor_reset(self):
        source = self.part(position=[0, 2, 0])
        world = self.world(source, gravity=0, floor=False)
        world.step(48)
        np.testing.assert_allclose(world.scene.objects[0].position, source.position)
        world.set_gravity(-9.81)
        world.step(48)
        self.assertAlmostEqual(world.scene.objects[0].velocity[1], -1.962, places=6)
        world.floor = True
        world.reset()
        world.step(2400)
        self.assertAlmostEqual(world.scene.objects[0].position[1], .1, delta=.005)
        self.assertEqual(source.position, [0, 2, 0])

    def test_close_releases_native_state_and_is_idempotent(self):
        world = self.world(self.part())
        world.close()
        world.close()
        self.assertTrue(world.closed)
        self.assertIsNone(world.model)
        self.assertIsNone(world.data)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            world.step()

    def test_invalid_gravity_and_step_count_do_not_advance(self):
        world = self.world(self.part(), gravity=0)
        for value in (float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                world.set_gravity(value)
        with self.assertRaises(ValueError):
            world.step(-1)
        with self.assertRaises(TypeError):
            world.step(.5)
        self.assertEqual(world.time, 0)
        self.assertEqual(world.gravity, 0)

    def test_empty_and_static_only_worlds_advance_and_reset(self):
        for objects in ([], [self.part(body_type="static")]):
            world = self.world(*objects)
            world.step(24)
            self.assertAlmostEqual(world.time, .1)
            world.reset()
            self.assertEqual(world.time, 0)

    def test_angular_velocity_is_in_world_coordinates(self):
        source = self.part(rotation=[20, 35, 65], angularVelocity=[.3, -.4, .5])
        world = self.world(source, gravity=0, floor=False)
        world.sync()
        np.testing.assert_allclose(world.scene.objects[0].angularVelocity,
                                   source.angularVelocity, atol=1e-10)

    def test_bounce_target_changes_measured_rebound(self):
        rebound = []
        for bounce in (0, .45, .8):
            obj = self.part(position=[0, 1.1, 0])
            obj.restitution = bounce
            world = self.world(obj)
            upward = 0
            for _ in range(240):
                world.step()
                # Soft-contact recovery below the surface is not a rebound.
                if world.scene.objects[0].position[1] > .105:
                    upward = max(upward, world.scene.objects[0].velocity[1])
            rebound.append(upward)
        self.assertLess(rebound[0], .1)
        self.assertGreater(rebound[1], 1)
        self.assertGreater(rebound[2], rebound[1] + .5)

    def test_contact_materials_use_both_surfaces(self):
        a = self.part(position=[-.1, 0, 0])
        b = self.part(position=[.1, 0, 0])
        a.part = replace(a.part, friction=.4)
        b.part = replace(b.part, friction=.5)
        a.restitution, b.restitution = .8, .5
        world = self.world(a, b, gravity=0, floor=False)
        # Inspect the generated MuJoCo contacts, not just the copied scene settings.
        world.step()
        self.assertGreater(world.data.ncon, 0)
        contact = world.data.contact[0]
        np.testing.assert_allclose(contact.friction[:2], [.2, .2])
        np.testing.assert_allclose(contact.solref, contact_reference(.4))

    def test_static_concave_mesh_does_not_fill_open_notch(self):
        # An L-shaped prism has an empty notch inside its overall convex hull.
        sketch = Sketch([[0, 0], [2, 0], [2, .4], [.4, .4], [.4, 2], [0, 2]],
                        True, [None]*6, .2)
        surface = SceneObject()
        surface.asset = PartAsset(prism_vertices(sketch))
        surface.body_type = "static"
        cube = self.part(position=[0, 0, 1], velocity=[0, 0, -1])
        supported = self.part(position=[.7, -.45, 1], velocity=[0, 0, -1])
        world = self.world(surface, cube, supported, gravity=0, floor=False)
        world.step(480)
        np.testing.assert_allclose(world.scene.objects[1].position, [0, 0, -1], atol=.005)
        self.assertGreater(world.scene.objects[2].position[2], .18)

    def test_kinematic_surface_transfers_tangential_velocity(self):
        platform = self.part(position=[0, -.1, 0], scale=[20, 1, 20],
                             velocity=[.5, 0, 0], body_type="kinematic")
        block = self.part(position=[0, .1, 0])
        platform.restitution = block.restitution = 0
        world = self.world(platform, block, floor=False)
        world.step(240)
        self.assertGreater(world.scene.objects[1].velocity[0], .3)
        self.assertGreater(world.scene.objects[1].position[0], .1)
        np.testing.assert_allclose(world.scene.objects[0].position, [.5, -.1, 0], atol=1e-10)

    def test_accelerating_kinematic_platform_supports_dynamic_body(self):
        platform = self.part(position=[0, -.1, 0], scale=[20, 1, 20],
                             acceleration=[0, 1, 0], body_type="kinematic")
        block = self.part(position=[0, .1, 0])
        platform.restitution = block.restitution = 0
        world = self.world(platform, block, floor=False)
        world.step(240)
        moving, supported = world.scene.objects
        np.testing.assert_allclose(moving.position, [0, .4, 0], atol=1e-10)
        np.testing.assert_allclose(supported.position, [0, .6, 0], atol=.005)
        np.testing.assert_allclose(supported.velocity, [0, 1, 0], atol=.01)


if __name__ == "__main__":
    unittest.main()
