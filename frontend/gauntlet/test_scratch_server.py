import tempfile
import unittest
from pathlib import Path
from scratch_server import bootstrap
from fastapi.testclient import TestClient


class IsolationTest(unittest.TestCase):
    def test_visual_states_never_queue_work_and_execution_is_blocked(self):
        with tempfile.TemporaryDirectory(prefix="openkerf-gauntlet-test-") as folder:
            kernel, server, marker = bootstrap(folder)
            try:
                client = TestClient(server.build_app())
                result = client.post('/api/gauntlet/state', json={'connection': 'disconnected', 'phase': 'paused'})
                self.assertEqual(result.status_code, 200)
                device = client.get('/api/status').json()['devices'][0]
                self.assertEqual(device['connection']['state'], 'disconnected')
                self.assertTrue(device['spooler']['jobs'][0]['paused'])
                self.assertEqual(len(kernel.device.spooler.queue), 0)
                self.assertEqual(client.post('/api/job/start').status_code, 409)
                self.assertEqual(client.post('/api/machine/jog', json={'dx_mm': 1}).status_code, 409)
                self.assertEqual(client.post('/api/gauntlet/state', json={'phase': 'typo'}).status_code, 422)
                self.assertEqual(client.post('/api/gauntlet/state', json={'connection': 'unknown', 'phase': 'idle'}).status_code, 200)
                self.assertEqual(client.get('/api/status').json()['devices'][0]['spooler']['jobs'], [])
                self.assertFalse(client.get('/api/design/capabilities').json()['z_step'])
                self.assertEqual(client.post('/api/gauntlet/state', json={'z_step': True}).status_code, 200)
                self.assertTrue(client.get('/api/design/capabilities').json()['z_step'])
                self.assertEqual(client.post('/api/gauntlet/state', json={'z_step': 'yes'}).status_code, 422)
                events = []
                async def capture(event):
                    events.append(event)
                server.bridge.broadcast = capture
                alarm = client.post('/api/gauntlet/alarm', json={'kind': 'usb_missing'})
                self.assertEqual(alarm.status_code, 200)
                self.assertEqual(events[0]['code'], 'pipe;usb_status')
                self.assertIn('USB connection did not exist', events[0]['args'][0])
                self.assertEqual(client.post('/api/gauntlet/alarm', json={'kind': 'usb_recovered'}).status_code, 200)
                self.assertEqual(client.post('/api/gauntlet/alarm', json={'kind': 'arbitrary signal'}).status_code, 422)
                self.assertEqual(len(kernel.device.spooler.queue), 0)
            finally:
                kernel()

    def test_all_storage_is_temporary_and_only_dummy_driver_is_loaded(self):
        with tempfile.TemporaryDirectory(prefix="openkerf-gauntlet-test-") as folder:
            root = Path(folder).resolve()
            kernel, server, marker = bootstrap(root)
            try:
                for path in marker["paths"].values():
                    self.assertTrue(Path(path).is_relative_to(root), path)
                self.assertTrue(Path(kernel._config_file).is_relative_to(root))
                self.assertTrue(Path(kernel.elements.op_data._config_file).is_relative_to(root))
                self.assertEqual(kernel.device.name, "Dummy Device")
                client = TestClient(server.build_app())
                machines = client.get('/api/machines').json()
                active = next(machine for machine in machines if machine['active'])
                self.assertTrue(active['configured'])
                profile = client.get('/api/library/active-machine')
                self.assertEqual(profile.status_code, 200)
                self.assertEqual(profile.json()['device_path'], active['path'])
                material = client.post('/api/library/materials', json={'name': 'Scratch plywood'})
                self.assertTrue(material.is_success, material.text)
                preset = client.post('/api/library/presets', json={
                    'material_id': material.json()['id'], 'machine_id': profile.json()['id'],
                    'operation': 'snijden', 'thickness_mm': 3, 'speed_mm_s': 20,
                    'power_percent': 40, 'source': 'handmatig',
                })
                self.assertTrue(preset.is_success, preset.text)
                self.assertEqual(len(client.get('/api/library/presets').json()), 1)
                self.assertIsNone(kernel.lookup("provider/device/ruida"))
                self.assertIsNotNone(kernel.lookup("render-op/make_raster"))
                self.assertFalse(marker["hardware"])
                self.assertTrue(any(getattr(route, "path", None) == "/api/gauntlet" for route in server.build_app().routes))
            finally:
                kernel()


if __name__ == "__main__":
    unittest.main()
