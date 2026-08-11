<script lang="ts">
	/**
	 * De telefoon: monitor en noodrem.
	 *
	 * Geen canvas, geen gereedschappen, geen lagen. Wie hier komt wil weten hoe
	 * het ervoor staat en desnoods ingrijpen — met één duim, terwijl hij naast
	 * de machine staat. Ontwerpen gebeurt op de desktop, en dat zegt dit scherm
	 * ook met zoveel woorden in plaats van een canvas erbij te proppen.
	 */
	import { formatDuration, STATE_LABEL, type Device, type Job, type MachineState } from '$lib/api';
	import type { Controller } from '$lib/control.svelte';
	import type { CameraStore } from '$lib/camera.svelte';

	let {
		device,
		state: machineState,
		job,
		control,
		camera,
		connected,
		position
	}: {
		device: Device | null;
		state: MachineState;
		job: Job | null;
		control: Controller;
		camera: CameraStore;
		connected: boolean;
		position: string;
	} = $props();

	let running = $derived(Boolean(job?.running));
	// Zonder camera en zonder job is er niets om groot in beeld te zetten. Dan
	// krimpt het podium in plaats van 600 pixels grijs te tonen.
	let livebeeld = $derived(
		(camera.state.available && camera.shown && camera.state.running) || running
	);
	let progress = $derived(job?.progress ?? null);
	// Rasters die nog op een foto wachten: dat is de reden dat je met een
	// telefoon naast de machine staat. De bibliotheek houdt ze niet vast, dus
	// halen we ze hier op.
	type Raster = { id: number; material_name: string | null; operation: string; photo_path: string | null };
	let wachtend = $state<Raster[]>([]);
	let bezig = $state<string | null>(null);

	async function haalRasters() {
		const r = await fetch('/api/library/testgrids');
		if (!r.ok) return;
		wachtend = (await r.json()).filter((g: Raster) => !g.photo_path);
	}
	$effect(() => {
		haalRasters();
	});

	async function foto(gridId: number, bestand: File) {
		bezig = 'foto';
		try {
			const form = new FormData();
			form.append('file', bestand);
			const token = localStorage.getItem('openkerf.token') ?? '';
			await fetch(`/api/library/testgrids/${gridId}/photo`, {
				method: 'POST',
				headers: token ? { Authorization: `Bearer ${token}` } : {},
				body: form
			});
			await haalRasters();
		} finally {
			bezig = null;
		}
	}
</script>

<div class="telefoon">
	<header>
		<span class="dot {machineState}" aria-hidden="true"></span>
		<span class="staat">{connected ? STATE_LABEL[machineState] : 'Geen verbinding'}</span>
		<span class="machine mono">{device?.label ?? 'geen machine'}</span>
	</header>

	<!-- Groot in beeld: wat er ligt. Camera als die er is, anders de voortgang. -->
	<div class="podium" class:klein={!livebeeld}>
		{#if camera.state.available && camera.shown && camera.state.running}
			<img src={camera.src} alt="Camerabeeld van het bed" />
		{:else}
			<div class="leeg">
				{#if running}
					<span class="groot mono">{Math.round((progress ?? 0) * 100)}%</span>
					<span class="onder">bezig met branden</span>
				{:else}
					<span class="onder">Geen job actief</span>
					{#if camera.state.available}
						<button class="klein" onclick={() => camera.start()}>Camera aanzetten</button>
					{/if}
				{/if}
			</div>
		{/if}
	</div>

	{#if !livebeeld}
		<!-- Er brandt niets: dan is de stand van de machine het nieuws. -->
		<dl class="stand">
			<div><dt>Machine</dt><dd>{device?.label ?? '—'}</dd></div>
			<div><dt>Verbinding</dt><dd>{connected ? 'verbonden' : 'geen'}</dd></div>
			<div><dt>Bed</dt><dd class="mono">{device?.bed.width_mm && device?.bed.height_mm
					? `${Math.round(device.bed.width_mm)} x ${Math.round(device.bed.height_mm)} mm`
					: '—'}</dd></div>
			<div><dt>Positie</dt><dd class="mono">{position}</dd></div>
		</dl>
	{/if}

	{#if job}
		<section class="job">
			<div class="regel">
				<span>{job.label}</span>
				<span class="mono">{formatDuration(job.estimate_seconds)}</span>
			</div>
			<div class="balk" role="progressbar" aria-valuenow={Math.round((progress ?? 0) * 100)}>
				<div class="vol" style="width: {Math.round((progress ?? 0) * 100)}%"></div>
			</div>
			<div class="regel muted mono">
				<span>{Math.round((progress ?? 0) * 100)}%</span>
				<span>{job.steps_done} van {job.steps_total}</span>
			</div>
		</section>
	{/if}

	<!-- De noodrem: vast onderin, binnen duimbereik, ver uit elkaar. -->
	<section class="noodrem">
		<button
			class="rem pauze"
			disabled={!running || control.needsToken}
			onclick={() => control.pause()}
		>Pauze</button>
		<button
			class="rem stop"
			disabled={control.needsToken}
			onclick={() => control.stop()}
		>Stop</button>
	</section>

	{#if wachtend.length}
		<section class="rasters">
			<h2>Testraster fotograferen</h2>
			{#each wachtend as grid (grid.id)}
				<label class="raster">
					<span>{grid.material_name ?? 'raster'} · {grid.operation}</span>
					<span class="knop">{bezig === 'foto' ? 'bezig…' : 'Foto maken'}</span>
					<input
						type="file"
						accept="image/*"
						capture="environment"
						aria-label="Foto van testraster {grid.id}"
						onchange={(e) => {
							const f = e.currentTarget.files?.[0];
							e.currentTarget.value = '';
							if (f) foto(grid.id, f);
						}}
					/>
				</label>
			{/each}
		</section>
	{/if}

	<p class="elders">
		Ontwerpen doe je op de desktop — dit scherm houdt de machine in de gaten.
	</p>
</div>

<style>
	.telefoon {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		height: 100%;
		padding: var(--space-3);
		box-sizing: border-box;
		background: var(--surface-0);
		overflow-y: auto;
	}
	header {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		flex: none;
	}
	.staat { font-weight: 600; font-size: var(--text-md); }
	.machine { margin-left: auto; color: var(--text-2); font-size: var(--text-xs); }
	.dot { width: 10px; height: 10px; border-radius: var(--radius-dot); background: var(--text-2); }
	.dot.ready { background: var(--ok); }
	.dot.running { background: var(--accent); }
	.dot.paused { background: var(--warn-solid); }
	.dot.alarm { background: var(--danger-solid); }

	.podium {
		flex: 1;
		min-height: 180px;
		border-radius: var(--radius-card);
		background: var(--stage);
		box-shadow: var(--lift-1);
		display: grid;
		place-items: center;
		overflow: hidden;
	}
	/* Ingeklapt podium: genoeg om de knop te dragen, niet meer. */
	.podium.klein { flex: none; min-height: 132px; }
	.podium img { width: 100%; height: 100%; object-fit: contain; }
	.leeg { display: grid; gap: var(--space-2); justify-items: center; color: var(--text-2); }
	.groot { font-size: 40px; color: var(--text-1); font-variant-numeric: tabular-nums; }
	.klein {
		font: inherit;
		padding: 10px 16px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
	}

	.stand { flex: none; margin: 0; display: grid; gap: 1px; background: var(--line);
		border: 1px solid var(--line); border-radius: var(--radius-card); overflow: hidden; }
	.stand > div { display: flex; justify-content: space-between; align-items: center;
		min-height: 44px; padding: 0 var(--space-3); background: var(--surface-1); }
	.stand dt { color: var(--text-2); }
	.stand dd { margin: 0; font-weight: 500; }

	.job { flex: none; display: grid; gap: 4px; }
	.regel { display: flex; justify-content: space-between; align-items: baseline; }
	.muted { color: var(--text-2); font-size: var(--text-xs); }
	.balk { height: 8px; border-radius: var(--radius-dot); background: var(--surface-2); overflow: hidden; }
	.vol { height: 100%; background: var(--accent); transition: width var(--transition-panel); }

	/* 24px tussen pauze en stop: tegengestelde gevolgen mogen niet naast
	   elkaar liggen als je met een duim mikt. */
	.noodrem { flex: none; margin-top: auto; display: flex; gap: var(--space-6); }
	.rem {
		flex: 1;
		min-height: 64px;
		font: inherit;
		font-size: var(--text-md);
		font-weight: 600;
		border-radius: var(--radius-card);
		border: 1px solid var(--line);
		background: var(--surface-1);
		color: var(--text-1);
	}
	.rem:disabled { opacity: 0.4; }
	.rem.stop { background: var(--danger-solid); border-color: var(--danger-solid); color: var(--on-color); }

	.rasters { flex: none; display: grid; gap: var(--space-2); }
	.rasters h2 {
		margin: 0;
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-2);
	}
	.raster {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		min-height: 44px;
		padding: 0 var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
	}
	.raster .knop { margin-left: auto; color: var(--accent); font-weight: 500; }
	.raster input { position: absolute; width: 0; height: 0; opacity: 0; }

	.elders {
		flex: none;
		margin: 0;
		font-size: var(--text-xs);
		color: var(--text-2);
		text-align: center;
	}
</style>
