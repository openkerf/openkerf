"""Snapshot shape and defensiveness of the read-only status layer."""

from openkerf_api.status import StatusReader


def test_snapshot_has_kernel_and_devices(kernel):
    snap = StatusReader(kernel).snapshot()

    assert snap["kernel"]["name"] == "MeerK40t"
    assert isinstance(snap["devices"], list)
    assert snap["devices"], "bootstrap starts a dummy device"


def test_device_snapshot_shape(kernel):
    device = next(iter(kernel.services("device")))
    snap = StatusReader(kernel).device_snapshot(device, getattr(kernel.device, "path", None))

    assert set(snap) == {"label", "path", "active", "laser_status", "position", "spooler"}
    assert snap["active"] is True
    assert set(snap["position"]) == {"native", "mm", "state"}
    assert snap["spooler"]["present"] is True
    assert snap["spooler"]["queue_length"] == 0
    assert snap["spooler"]["jobs"] == []


def test_position_is_reported_in_native_units_and_mm(kernel):
    device = next(iter(kernel.services("device")))
    position = StatusReader(kernel).position(device)

    assert position["native"] is not None
    assert len(position["native"]) == 2
    assert position["mm"] is not None
    assert all(isinstance(v, float) for v in position["mm"])


def test_snapshot_is_json_serialisable(kernel):
    import json

    json.dumps(StatusReader(kernel).snapshot(), default=str)


def test_reader_survives_a_broken_device(kernel):
    class Broken:
        path = "broken"
        label = "Broken"

        @property
        def driver(self):
            raise RuntimeError("device fell over")

        @property
        def spooler(self):
            raise RuntimeError("device fell over")

    # A device that raises on every access must degrade, not take the API down.
    snap = StatusReader(kernel).device_snapshot(Broken())
    assert snap["label"] == "Broken"
    assert snap["position"]["native"] is None
    assert snap["spooler"]["present"] is False


def test_progress_fraction():
    assert StatusReader._progress(5, 10) == 0.5
    assert StatusReader._progress(0, 0) is None
    assert StatusReader._progress(None, 10) is None
    assert StatusReader._progress(20, 10) == 1.0
