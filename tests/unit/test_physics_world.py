"""Rigid-body integration checks without a display or GPU."""
from dataclasses import replace
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


if __name__ == "__main__":
    unittest.main()
