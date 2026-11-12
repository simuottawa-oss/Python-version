"""Rigid-body integration checks without a display or GPU."""
from dataclasses import replace
import copy
import math
import unittest

import numpy as np

from tests import ROOT
from simuo.project.scene import Scene, SceneObject
from simuo.physics.physics_world import PhysicsWorld, quaternion


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
        original = np.asarray(world.bullet.getMatrixFromQuaternion(quaternion(source.rotation)))
        world.sync()
        current = np.asarray(world.bullet.getMatrixFromQuaternion(quaternion(world.scene.objects[0].rotation)))
        np.testing.assert_allclose(original,current,atol=1e-8)
        world.step(48)
        evolved = np.asarray(world.bullet.getMatrixFromQuaternion(quaternion(world.scene.objects[0].rotation)))
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
        bullet_position, _ = world.bullet.getBasePositionAndOrientation(world.bodies[0], physicsClientId=world.client)
        np.testing.assert_allclose(bullet_position, obj.position)
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
        info = world.bullet.getDynamicsInfo(world.bodies[1],-1,physicsClientId=world.client)
        np.testing.assert_allclose(info[2],[1/150,1/60,1/60])

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

    def motion(self, world):
        return [[*o.position, *o.rotation, *o.velocity, *o.angularVelocity]
                for o in world.scene.objects]

    def test_step_back_restores_collision_state_and_resumes(self):
        world = self.world(self.part(position=[0, .11, 0], velocity=[1, -2, 0],
                                     angularVelocity=[0, 1, 0]))
        self.assertFalse(world.can_step_back)
        self.assertFalse(world.step_back())
        world.step(130)
        previous = self.motion(world)
        world.step()
        future = self.motion(world)
        self.assertTrue(world.step_back())
        self.assertEqual(world.steps, 130)
        self.assertAlmostEqual(world.time, 130 * world.dt)
        np.testing.assert_allclose(self.motion(world), previous, atol=1e-8)
        world.step()
        np.testing.assert_allclose(self.motion(world), future, atol=1e-8)

    def test_rewind_kinematic_and_dynamic_motion_to_initial_state(self):
        platform = self.part(position=[-1, 0, 0], velocity=[2, 0, 0],
                             acceleration=[1, 0, 0], body_type="kinematic")
        source_state = copy.deepcopy(platform.__dict__)
        world = self.world(platform, self.part(position=[0, 0, 0]), gravity=0, floor=False)
        world.history_interval = 3
        world.history_limit = 2
        initial = self.motion(world)
        world.step(17)
        expected = self.motion(world)
        world.step()
        self.assertLessEqual(len(world._history), 3)
        world.step_back()
        np.testing.assert_allclose(self.motion(world), expected, atol=1e-8)
        while world.can_step_back:
            world.step_back()
        self.assertEqual(world.steps, 0)
        np.testing.assert_allclose(self.motion(world), initial, atol=1e-8)
        self.assertEqual(platform.position, source_state["position"])
        self.assertEqual(platform.velocity, source_state["velocity"])

    def test_settings_reset_history_and_release_saved_states(self):
        world = self.world(self.part(), floor=False)
        world.step(80)
        world.set_gravity(0)
        self.assertFalse(world.can_step_back)
        self.assertEqual(len(world._history), 1)
        motion = self.motion(world)
        world.step()
        world.step_back()
        self.assertEqual(world.steps, 80)
        np.testing.assert_allclose(self.motion(world), motion, atol=1e-8)
        world.reset()
        self.assertEqual(world.steps, 0)
        self.assertFalse(world.can_step_back)
        self.assertEqual(list(world._history), [0])
        world.close()
        self.assertEqual(world._history, {})


if __name__ == "__main__":
    unittest.main()
