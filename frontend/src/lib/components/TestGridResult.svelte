<script lang="ts">
	import type { LibraryStore } from '$lib/library.svelte';

	type Cell = {
		row: number;
		column: number;
		speed_mm_s: number;
		power_percent: number;
		x_mm: number;
		y_mm: number;
		width_mm: number;
		height_mm: number;
		preset_id?: number;
	};

	type Grid = {
		id: number;
		material_id: number | null;
		material_name: string | null;
		thickness_mm: number | null;
		operation: string;
		origin_x_mm: number;
		origin_y_mm: number;
		cell_mm: number;
		gap_mm: number;
		speed_steps: number;
		power_steps: number;
		photo_path: string | null;
		cells: Cell[];
		created_at: string;
	};

	let { library, canEdit = false }: { library: LibraryStore; canEdit?: boolean } = $props();

	let grids = $state<Grid[]>([]);
	let openId = $state<number | null>(null);
	let picked = $state<string[]>([]);
	let busy = $state(false);
	let error = $state<string | null>(null);
	let photoStamp = $state(0);

	let grid = $derived(grids.find((g) => g.id === openId) ?? null);

	// Kader om alle cellen heen, zodat de overlay op de foto past.
	let box = $derived.by(() => {
		if (!grid) return null;
		const pitch = grid.cell_mm + grid.gap_mm;
		return {
			width: grid.power_steps * pitch - grid.gap_mm,
			height: grid.speed_steps * pitch - grid.gap_mm
		};
	});

	function key(cell: Cell) {
		return `${cell.row}-${cell.column}`;
	}

	async function load() {
		const response = await fetch('/api/library/testgrids');
		if (response.ok) grids = await response.json();
	}

	load();

	function toggle(cell: Cell) {
		if (!canEdit) return;
		const id = key(cell);
		picked = picked.includes(id) ? picked.filter((p) => p !== id) : [...picked, id];
	}

	function headers(json = false) {
		const out: Record<string, string> = {};
		const token =
			typeof localStorage === 'undefined' ? '' : (localStorage.getItem('openkerf.token') ?? '');
		if (token) out.Authorization = `Bearer ${token}`;
		if (json) out['Content-Type'] = 'application/json';
		return out;
	}

	async function uploadPhoto(event: Event) {
		const input = event.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		input.value = '';
		if (!file || !grid) return;
		busy = true;
		error = null;
		try {
			const form = new FormData();
			form.append('file', file);
			const response = await fetch(`/api/library/testgrids/${grid.id}/photo`, {
				method: 'POST',
				headers: headers(),
				body: form
			});
			if (!response.ok) {
				error = 'Foto opslaan mislukte.';
				return;
			}
			await load();
			photoStamp = Date.now();
		} finally {
			busy = false;
		}
	}

	async function makePresets() {
		if (!grid || picked.length === 0) return;
		busy = true;
		error = null;
		try {
			const cells = picked.map((id) => {
				const [row, column] = id.split('-').map(Number);
				return { row, column };
			});
			const response = await fetch(`/api/library/testgrids/${grid.id}/presets`, {
				method: 'POST',
				headers: headers(true),
				body: JSON.stringify({ cells })
			});
			const data = await response.json().catch(() => null);
			if (!response.ok) {
				error =
					typeof data?.detail === 'string' ? data.detail : 'Preset maken mislukte.';
				return;
			}
			picked = [];
			await Promise.all([load(), library.load()]);
		} finally {
			busy = false;
		}
	}
</script>

<div class="section">
	<h2 class="section-title">Rasterresultaten</h2>

	{#if grids.length === 0}
		<p class="muted">Nog geen testrasters gegenereerd.</p>
	{:else}
		<select class="picker" bind:value={openId}>
			<option value={null}>Kies een raster…</option>
			{#each grids as g (g.id)}
				<option value={g.id}>
					#{g.id} · {g.material_name ?? 'geen materiaal'} · {g.operation}
				</option>
			{/each}
		</select>
	{/if}

	{#if error}<p class="error" role="alert">{error}</p>{/if}

	{#if grid && box}
		<div class="stage">
			{#if grid.photo_path}
				<img src="/api/library/testgrids/{grid.id}/photo?v={photoStamp}" alt="Foto van het gebrande raster" />
			{:else}
				<div class="nophoto">
					<p>Nog geen foto. Maak er een van het gebrande raster.</p>
				</div>
			{/if}

			<!-- Overlay: elk vakje ligt op zijn eigen plek in het raster, dus een
			     tik vertaalt terug naar de snelheid en het vermogen van die cel. -->
			<svg
				viewBox="0 0 {box.width} {box.height}"
				preserveAspectRatio="none"
				aria-label="Raster-overlay: kies het beste vakje"
			>
				{#each grid.cells as cell (key(cell))}
					<g
						class="cell"
						class:picked={picked.includes(key(cell))}
						class:used={cell.preset_id !== undefined}
					>
						<rect
							role="button"
							tabindex="0"
							aria-label="{cell.speed_mm_s} mm/s bij {cell.power_percent} procent"
							aria-pressed={picked.includes(key(cell))}
							x={cell.x_mm - grid.origin_x_mm}
							y={cell.y_mm - grid.origin_y_mm}
							width={cell.width_mm}
							height={cell.height_mm}
							onclick={() => toggle(cell)}
							onkeydown={(e) => {
								if (e.key === 'Enter' || e.key === ' ') {
									e.preventDefault();
									toggle(cell);
								}
							}}
						/>
					</g>
				{/each}
			</svg>
		</div>

		<p class="hint mono">
			{#if picked.length}
				{picked.length} vakje{picked.length === 1 ? '' : 's'} gekozen
			{:else}
				Tik het vakje aan dat het beste resultaat gaf
			{/if}
		</p>

		{#if canEdit}
			<div class="actions">
				<label class="btn file">
					Foto toevoegen
					<input type="file" accept="image/*" capture="environment" onchange={uploadPhoto} />
				</label>
				<button
					class="btn primary"
					disabled={busy || picked.length === 0}
					onclick={makePresets}
				>
					{busy ? 'Bezig…' : 'Preset maken'}
				</button>
			</div>
			{#if grid.material_id === null}
				<p class="hint">
					Dit raster hoort bij geen materiaal, dus er kan nog geen preset uit. Koppel er een
					materiaal aan bij het genereren.
				</p>
			{/if}
		{/if}
	{/if}
</div>

<style>
	.section { margin-top: var(--space-6); }
	.section-title {
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-2);
		margin: 0 0 var(--space-2);
	}
	.muted { color: var(--text-2); margin: 0; font-size: var(--text-xs); }
	.picker {
		font: inherit;
		width: 100%;
		padding: 6px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.stage {
		position: relative;
		margin-top: var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		overflow: hidden;
	}
	.stage img { display: block; width: 100%; height: auto; }
	.nophoto {
		display: grid;
		place-items: center;
		aspect-ratio: 4 / 3;
		background: var(--surface-2);
		color: var(--text-2);
		font-size: var(--text-xs);
		text-align: center;
		padding: var(--space-4);
	}
	.stage svg {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
	}
	.cell rect {
		fill: transparent;
		stroke: color-mix(in srgb, var(--accent) 55%, transparent);
		stroke-width: 1;
		vector-effect: non-scaling-stroke;
		cursor: pointer;
	}
	.cell.used rect {
		stroke: var(--ok);
		stroke-dasharray: 3 2;
	}
	.cell.picked rect {
		fill: color-mix(in srgb, var(--accent) 25%, transparent);
		stroke: var(--accent);
		stroke-width: 2;
	}
	.hint {
		margin: var(--space-2) 0 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.actions { display: flex; gap: var(--space-2); margin-top: var(--space-2); }
	.btn {
		padding: 7px 12px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		font-weight: 500;
		font-size: var(--text-sm);
	}
	.btn:hover:not(:disabled) { background: var(--surface-2); }
	.btn:disabled { opacity: 0.45; cursor: not-allowed; }
	.btn.primary {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
	}
	.btn.file { cursor: pointer; }
	.btn.file input { display: none; }
	.error {
		margin: var(--space-2) 0 0;
		padding: var(--space-2);
		border-radius: var(--radius-field);
		background: color-mix(in srgb, var(--danger) 14%, transparent);
		font-size: var(--text-xs);
	}
</style>
