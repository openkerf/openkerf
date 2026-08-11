<script lang="ts">
	import { OPERATIONS, type LibraryStore } from '$lib/library.svelte';
	import NumberField from './NumberField.svelte';

	let {
		materialId = null,
		library,
		canEdit = false,
		onGenerated
	}: {
		/** Voorgekozen materiaal, als je hier vanuit de bibliotheek komt. */
		materialId?: number | null;
		library: LibraryStore;
		canEdit?: boolean;
		onGenerated?: () => void;
	} = $props();

	// Kom je vanuit een materiaal, dan staat dat materiaal al ingevuld en gaat
	// het formulier meteen open — anders begin je met kiezen wat je net koos.
	$effect(() => {
		if (materialId === null) return;
		form.material_id = materialId;
		open = true;
	});

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
	/**
	 * Bereik voorstellen rond wat de bibliotheek al weet.
	 *
	 * ARCHITECTUUR.md: de app stelt het bereik voor rond het verwachte
	 * werkpunt. Zonder presets komt er een breed maar redelijk startpunt.
	 */
	async function suggest() {
		const thickness = form.thickness_mm === '' ? null : Number(form.thickness_mm);
		const range = await library.suggest(form.material_id, form.operation, thickness);
		if (!range) return;
		form = {
			...form,
			speed_min: String(range.speed_min),
			speed_max: String(range.speed_max),
			power_min: String(range.power_min),
			power_max: String(range.power_max)
		};
		suggestedFrom = range.based_on;
		preview = null;
	}

	let suggestedFrom = $state<number | null>(null);

	async function showPreview() {
		preview = await send('/api/library/testgrids/preview');
	}

	// Live meekijken. Een voorbeeld achter een knop is geen voorbeeld: je ziet
	// pas wat je instelt nadat je besloten hebt dat je het wilt zien.
	let timer: ReturnType<typeof setTimeout> | null = null;
	$effect(() => {
		// Aanraken zodat de effect-tracker weet waar hij op moet letten.
		void [
			form.operation, form.speed_min, form.speed_max, form.power_min,
			form.power_max, form.speed_steps, form.power_steps, form.cell_mm,
			form.gap_mm, form.origin_x_mm, form.origin_y_mm
		];
		if (!open) return;
		if (timer) clearTimeout(timer);
		timer = setTimeout(showPreview, 250);
		return () => {
			if (timer) clearTimeout(timer);
		};
	});

	/** De waarden waarop echt gebrand wordt — na afronding. */
	let snelheden = $derived(
		preview ? [...new Set(preview.cells.map((c) => c.speed_mm_s))].sort((a, b) => a - b) : []
	);
	let vermogens = $derived(
		preview ? [...new Set(preview.cells.map((c) => c.power_percent))].sort((a, b) => a - b) : []
	);

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

		<div class="werkbank">
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
			<NumberField label="Dikte" unit="mm" step={0.5} min={0} bind:value={form.thickness_mm} />
			<NumberField label="Vakje" unit="mm" step={1} min={1} bind:value={form.cell_mm} />

			<NumberField label="Snelheid van" unit="mm/s" step={1} min={0} bind:value={form.speed_min} />
			<NumberField label="tot" unit="mm/s" step={1} min={0} bind:value={form.speed_max} />
			<NumberField label="Vermogen van" unit="%" step={5} min={0} max={100} bind:value={form.power_min} />
			<NumberField label="tot" unit="%" step={5} min={0} max={100} bind:value={form.power_max} />

			<NumberField label="Stappen snelheid" step={1} min={2} bind:value={form.speed_steps} />
			<NumberField label="Stappen vermogen" step={1} min={2} bind:value={form.power_steps} />
			<NumberField label="Start X" unit="mm" step={5} min={0} bind:value={form.origin_x_mm} />
			<NumberField label="Start Y" unit="mm" step={5} min={0} bind:value={form.origin_y_mm} />
		</div>

		{#if preview}
			<aside class="preview">
				<div class="figures mono">
					<span>{preview.cells.length} vakjes</span>
					<span>{preview.plan.width_mm} × {preview.plan.height_mm} mm</span>
				</div>
				<!-- De waarden waarop je écht snijdt. Ze worden afgerond op nette
				     stappen, en dat hoor je te zien vóór het hout eraan gaat. -->
				<div class="reeks">
					<span class="wat">rijen, mm/s</span>
					{#each snelheden as v (v)}<span class="waarde mono">{v}</span>{/each}
				</div>
				<div class="reeks">
					<span class="wat">kolommen, %</span>
					{#each vermogens as v (v)}<span class="waarde mono">{v}</span>{/each}
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
			</aside>
		{/if}
		</div>

		{#if suggestedFrom !== null}
			<p class="muted">
				{suggestedFrom
					? `Bereik voorgesteld op basis van ${suggestedFrom} bestaande preset${suggestedFrom === 1 ? '' : 's'}.`
					: 'Nog geen presets voor deze combinatie; dit is een breed startpunt.'}
			</p>
		{/if}

		<div class="actions">
			<button class="btn" disabled={busy} onclick={suggest}>Bereik voorstellen</button>
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
	select {
		font: inherit;
		width: 100%;
		padding: 4px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.reeks {
		display: flex;
		align-items: baseline;
		flex-wrap: wrap;
		gap: 4px;
		margin-top: var(--space-2);
	}
	.reeks .wat { font-size: var(--text-xs); color: var(--text-2); min-width: 7em; }
	.waarde {
		font-size: var(--text-xs);
		padding: 1px var(--space-2);
		border-radius: var(--radius-dot);
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
	/* Het hele bord in één blik. Een SVG met viewBox rekt zich anders op tot de
	   volle breedte en duwt de knoppen uit beeld. */
	.preview svg { height: 190px; width: 100%; display: block; }
	/* Instellen en zien wat je instelt, naast elkaar. Onder 720px stapelt het;
	   dan is er geen ruimte voor twee kolommen. */
	.werkbank { display: grid; grid-template-columns: 1fr 260px; gap: var(--space-4); align-items: start; }
	@media (max-width: 720px) { .werkbank { grid-template-columns: 1fr; } }
	.preview rect { fill: var(--accent); }
	.actions { display: flex; gap: var(--space-2); }
	.btn {
		padding: 8px 12px;
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
