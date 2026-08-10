/** Types mirroring the openkerf-api snapshot (api/openkerf_api/status.py). */

export type Position = {
	native: [number, number] | null;
	mm: [number, number] | null;
	state: unknown[] | null;
};

export type Job = {
	label: string;
	type: string;
	status: string | null;
	priority: number | null;
	running: boolean | null;
	steps_done: number | null;
	steps_total: number | null;
	progress: number | null;
	loops_executed: number | null;
	loops: number | null;
	elapsed_seconds: number | null;
	estimate_seconds: number | null;
};

export type Spooler = {
	present: boolean;
	idle: boolean | null;
	queue_length: number;
	jobs: Job[];
};

export type Bed = { width_mm: number | null; height_mm: number | null };

export type Device = {
	label: string | null;
	path: string | null;
	active: boolean;
	laser_status: string | null;
	bed: Bed;
	position: Position;
	spooler: Spooler;
};

export type Capabilities = {
	actions: {
		start: boolean;
		pause: boolean;
		resume: boolean;
		stop: boolean;
		clear_queue: boolean;
		load: boolean;
	};
	auth_required: boolean;
};

export type Snapshot = {
	kernel: { name: string | null; version: string | null };
	devices: Device[];
};

export type SignalEvent = {
	type: 'signal';
	code: string;
	origin: string | null;
	args: unknown[];
	time: number;
};

export type SnapshotEvent = { type: 'snapshot'; data: Snapshot };
export type ApiEvent = SignalEvent | SnapshotEvent;

/** Machine state as the UI shows it — dubbel gecodeerd, nooit alleen kleur. */
export type MachineState = 'offline' | 'ready' | 'busy' | 'paused' | 'alarm';

export function machineState(device: Device | null, connected: boolean): MachineState {
	if (!connected || !device) return 'offline';
	if (device.laser_status === 'active') return 'busy';
	if (device.laser_status === 'pause' || device.laser_status === 'paused') return 'paused';
	return 'ready';
}

export const STATE_LABEL: Record<MachineState, string> = {
	offline: 'Offline',
	ready: 'Gereed',
	busy: 'Bezig',
	paused: 'Pauze',
	alarm: 'Alarm'
};

export function formatMm(value: number | null | undefined): string {
	if (value === null || value === undefined || Number.isNaN(value)) return '—';
	return value.toFixed(1);
}

export function formatDuration(seconds: number | null | undefined): string {
	if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return '—';
	const total = Math.max(0, Math.round(seconds));
	const h = Math.floor(total / 3600);
	const m = Math.floor((total % 3600) / 60);
	const s = total % 60;
	const pad = (n: number) => String(n).padStart(2, '0');
	return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}
