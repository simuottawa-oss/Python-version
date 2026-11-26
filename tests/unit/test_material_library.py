"""JSON catalog authority, personal-library persistence and snapshot validation."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from simuo.materials import (MaterialDefinition, MaterialRecord, MaterialCatalog,
                            PRESETS, BUNDLED_MATERIALS, load_material, save_material)


class MaterialLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.catalog = MaterialCatalog(self.root/'library')
        self.record = MaterialRecord(MaterialDefinition('Measured alloy', 123e9, .29, 4200.,
            yield_strength=300123456.789, ultimate_tensile_strength=450987654.321),
            source_url='https://example.org/properties', strength_notes='Measured specimen')

    def test_presets_keep_existing_order_strengths_and_references(self):
        self.assertEqual([p.preset_id for p in PRESETS], ['steel-a36','stainless-304','aluminum-6061-t6',
            'titanium-ti6al4v','copper-c110','abs','polycarbonate'])
        self.assertEqual(PRESETS[0].yield_strength, 36*6894757.293168)
        self.assertEqual(PRESETS[0].ultimate_tensile_strength, 58*6894757.293168)
        self.assertEqual(PRESETS[2].yield_strength, 240e6)
        self.assertEqual(PRESETS[2].ultimate_tensile_strength, 260e6)
        for record in BUNDLED_MATERIALS:
            self.assertTrue(record.source_url)
        self.assertTrue(BUNDLED_MATERIALS[0].strength_notes)

    def test_json_library_restart_and_conflicting_import(self):
        path = self.root/'alloy.json'
        save_material(path, self.record)
        self.assertEqual(load_material(path), self.record)
        saved = self.catalog.import_file(path)
        self.assertTrue(saved.material.preset_id.startswith('user:'))
        self.assertEqual(self.catalog.import_file(path), saved)
        restarted = MaterialCatalog(self.catalog.directory)
        self.assertEqual(restarted.get(saved.material.preset_id), saved)
        changed = replace(saved, material=replace(saved.material, density=9999.))
        save_material(path, changed)
        second = restarted.import_file(path)
        self.assertNotEqual(second.material.preset_id, saved.material.preset_id)
        self.assertEqual(restarted.get(saved.material.preset_id), saved)
        self.assertEqual(second.material.name, 'Measured alloy (2)')

    def test_explicit_replacement_preserves_id_and_existing_snapshots(self):
        first = self.catalog.save(self.record)
        copy = self.catalog.save(self.record)
        self.assertNotEqual(first.material.preset_id, copy.material.preset_id)
        changed = replace(first, material=replace(first.material, yield_strength=310e6))
        replacement = self.catalog.save(changed, replace_id=first.material.preset_id)
        self.assertEqual(replacement.material.preset_id, first.material.preset_id)
        self.assertEqual(first.material.yield_strength, self.record.material.yield_strength)
        with self.assertRaises(ValueError):
            self.catalog.save(self.record, replace_id='steel-a36')

    def test_partial_material_and_invalid_or_corrupt_files(self):
        path = self.root/'density.json'
        save_material(path, MaterialDefinition('Density only', density=800.))
        self.assertEqual(load_material(path).material.density, 800.)
        with self.assertRaisesRegex(ValueError, 'at least one'):
            save_material(path, MaterialDefinition('Empty'))
        self.assertEqual(load_material(path).material.density, 800.)
        original = self.record.to_dict()
        for update in ({'version': True}, {'version': 99}, {'format': 'other'},
                       {'material': None}, {'material': {'name':'Bad','density':-1}},
                       {'material': {'name':'Bad','yield_strength':300.,'ultimate_tensile_strength':200.}},
                       {'material': {'name':'Bad','yield_strength':float('nan')}}):
            path.write_text(json.dumps({**original, **update}))
            with self.subTest(update=update), self.assertRaises(ValueError):
                load_material(path)
        self.catalog.directory.mkdir()
        (self.catalog.directory/'corrupt.json').write_text('{bad')
        saved = self.catalog.save(self.record)
        self.assertEqual(self.catalog.get(saved.material.preset_id), saved)
        self.assertEqual(len(self.catalog.errors), 1)

    def test_failed_atomic_write_keeps_previous_file(self):
        path = self.root/'material.json'
        save_material(path, self.record)
        before = path.read_bytes()
        with patch('simuo.project.temporary_parts.os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                save_material(path, replace(self.record, material=replace(self.record.material, density=999.)))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.root.glob('.material.json.*')), [])

    def test_bundled_json_is_found_in_a_packaged_resource_directory(self):
        import shutil
        import sys
        from simuo.materials import _load_bundled
        from simuo.resources.paths import resource_path
        source = resource_path('Assets', 'materials')
        shutil.copytree(source, self.root/'bundle'/'Assets'/'materials')
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, '_MEIPASS', str(self.root/'bundle'), create=True):
            self.assertEqual(_load_bundled(), BUNDLED_MATERIALS)
