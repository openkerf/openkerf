<script lang="ts">
	import { OPERATIONS, type LibraryStore } from '$lib/library.svelte';

	let {
		library,
		canEdit = false,
		onGenerated
	}: { library: LibraryStore; canEdit?: boolean; onGenerated?: () => void } = $props();

	type Cell = {
		row: number;
		column: number;
		speed_mm_s: number;
		power_percent: number;
		x_mm: number;
		y_mm: number;
		width_mm: number;
		height_mm: number;
	};

	let open = $state(false);
	let busy = $state(false);
	let error = $state<string | null>(null);
	let preview = $state<{ plan: Record<string, number>; cells: Cell[] } | null>(null);

	let form = $state({
		material_id: null as number | null,
		thickness_mm: '3',
		operation: 'snijden',
		speed_min: '5',
		speed_max: '25',
		speed_steps: '4',
		power_min: '40',
		power_max: '80',
		power_steps: '4',
		cell_mm: '8',
		gap_mm: '2',
		origin_x_mm: '10',
		origin_y_mm: '10'
	});

	function body() {
		return {
			material_id: form.material_id,
			thickness_mm: form.thickness_mm === '' ? null : Number(form.thickness_mm),
			operation: form.operation,
			speed_min: Number(form.speed_min),
			speed_max: Number(form.speed_max),
			speed_steps: Number(form.speed_steps),
			power_min: Number(form.power_min),
			power_max: Number(form.power_max),
			power_steps: Number(form.power_steps),
			cell_mm: Number(form.cell_mm),
			gap_mm: Number(form.gap_mm),
			origin_x_mm: Number(form.origin_x_mm),
			origin_y_mm: Number(form.origin_y_mm)
		};
	}

	async function send(path: string, method = 'POST') {
		busy = true;
		error = null;
		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			const token =
				typeof localStorage === 'undefined' ? '' : (localStorage.getItem('openkerf.token') ?? '');
			if (token) headers.Authorization = `Bearer ${token}`;
			const response = await fetch(path, { method, headers, body: JSON.stringify(body()) });
			const data = await response.json().catch(() => null);
			if (!response.ok) {
				error =
					typeof data?.detail === 'string'
						? data.detail
						: `De engine weigerde het raster (${response.status}).`;
				return null;
			}
			return data;
		} catch (e) {
			error = `Netwerkfout: ${e instanceof Error ? e.message : e}`;
			return null;
		} finally {
			busy = false;
		}
	}

	// Eerst rekenen, dan pas tekenen: je ziet wat er komt voordat er iets in het
	// ontwerp verschijnt.
	async function showPreview() {
		preview = await send('/api/library/testgrids/preview');
	}

	async function generate() {
		const grid = await send('/api/library/testgrids');
		if (grid) {
			preview = null;
			onGenerated?.();
		}
	}
</script>

<div class="section">
	<div class="section-head">
		<h2 class="section-title">Testraster</h2>
		{#if canEdit}
			<button class="mini" onclick={() => (open = !open)}>{open ? 'Sluiten' : 'Openen'}</button>
		{/if}
	</div>

	{#if !canEdit}
		<p class="muted">Een testraster genereren vereist een token.</p>
	{:else if open}
		<p class="muted">
			Brandt een raster van vakjes: vermogen naar rechts, snelheid naar beneden. Daarna
			fotografeer je het resultaat en wijs je het beste vakje aan — die stap komt nog.
		</p>

		{#if error}<p class="error" role="alert">{error}</p>{/if}

		<div class="grid">
			<label>
				<span>Materiaal</span>
				<select bind:value={form.material_id}>
					<option value={null}>—</option>
					{#each library.materials as material (material.id)}
						<option value={material.id}>{material.name}</option>
					{/each}
				</select>
			</label>
			<label>
				<span>Bewerking</span>
				<select bind:value={form.operation}>
					{#each OPERATIONS as op (op.value)}
						<option value={op.value}>{op.label}</option>
					{/each}
				</select>
			</label>
			<label><span>Dikte (mm)</span><input class="mono" bind:value={form.thickness_mm} /></label>
			<label><span>Vakje (mm)</span><input class="mono" bind:value={form.cell_mm} /></label>

			<label><span>Snelheid van</span><input class="mono" bind:value={form.speed_min} /></label>
			<label><span>tot (mm/s)</span><input class="mono" bind:value={form.speed_max} /></label>
			<label><span>Vermogen van</span><input class="mono" bind:value={form.power_min} /></label>
			<label><span>tot (%)</span><input class="mono" bind:value={form.power_max} /></label>

			<label><span>Stappen snelheid</span><input class="mono" bind:value={form.speed_steps} /></label>
			<label><span>Stappen vermogen</span><input class="mono" bind:value={form.power_steps} /></label>
			<label><span>Start X (mm)</span><input class="mono" bind:value={form.origin_x_mm} /></label>
			<label><span>Start Y (mm)</span><input class="mono" bind:value={form.origin_y_mm} /></label>
		</div>

		{#if preview}
			<div class="preview">
				<div class="figures mono">
					<span>{preview.cells.length} vakjes</span>
					<span>{preview.plan.width_mm} × {preview.plan.height_mm} mm</span>
				</div>
				<svg
					viewBox="0 0 {preview.plan.width_mm} {preview.plan.height_mm}"
					role="img"
					aria-label="Voorbeeld van het raster: {preview.cells.length} vakjes"
				>
					{#each preview.cells as cell (`${cell.row}-${cell.column}`)}
						<rect
							x={cell.x_mm - preview.plan.origin_x_mm}
							y={cell.y_mm - preview.plan.origin_y_mm}
							width={cell.width_mm}
							height={cell.height_mm}
							opacity={0.25 + 0.75 * (cell.power_percent / 100)}
						/>
					{/each}
				</svg>
			</div>
		{/if}

		<div class="actions">
			<button class="btn" disabled={busy} onclick={showPreview}>Voorbeeld</button>
			<button class="btn primary" disabled={busy} onclick={generate}>
				{busy ? 'Bezig…' : 'Genereren'}
			</button>
		</div>
	{/if}
</div>

<style>
	.section { margin-top: var(--space-6); }
	.section-head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
	}
	.section-title {
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-2);
		margin: 0 0 var(--space-2);
	}
	.muted { color: var(--text-2); margin: 0; font-size: var(--text-xs); }
	.mini { font-size: var(--text-xs); color: var(--accent); }
	.grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-2);
		margin: var(--space-3) 0;
	}
	.grid label { display: grid; gap: 2px; font-size: var(--text-xs); color: var(--text-2); }
	input, select {
		font: inherit;
		width: 100%;
		padding: 5px 7px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.preview {
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		padding: var(--space-2);
		margin-bottom: var(--space-2);
	}
	.figures {
		display: flex;
		justify-content: space-between;
		font-size: var(--text-xs);
		color: var(--text-2);
		margin-bottom: var(--space-2);
	}
	.preview svg { width: 100%; height: auto; display: block; }
	.preview rect { fill: var(--accent); }
	.actions { display: flex; gap: var(--space-2); }
	.btn {
		padding: 7px 12px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		font-weight: 500;
	}
	.btn:hover:not(:disabled) { background: var(--surface-2); }
	.btn:disabled { opacity: 0.45; cursor: not-allowed; }
	.btn.primary {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
	}
	.error {
		margin: 0 0 var(--space-2);
		padding: var(--space-2);
		border-radius: var(--radius-field);
		background: color-mix(in srgb, var(--danger) 14%, transparent);
		font-size: var(--text-xs);
	}
</style>
