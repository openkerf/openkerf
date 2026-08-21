<script lang="ts">
	import { untrack } from 'svelte';
	import { i18n, t } from '$lib/i18n/index.svelte';
	import type { LibraryStore } from '$lib/library.svelte';

	type Point = { x: number; y: number };

	type Cell = {
		row: number;
		column: number;
		speed_mm_s: number;
		power_percent: number;
		interval_mm: number | null;
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
		/** Since B12 the axes need not be speed × power. */
		row_axis: 'speed' | 'power' | 'interval';
		column_axis: 'speed' | 'power' | 'interval';
		rows: number | null;
		columns: number | null;
		photo_path: string | null;
		/** The four corners of the board on the photo; stored in the database (T4). */
		alignment: Point[] | null;
		cells: Cell[];
		created_at: string;
	};

	const EENHEID = { speed: 'mm/s', power: '%', interval: 'mm' } as const;
	const CEL_SLEUTEL = {
		speed: 'speed_mm_s',
		power: 'power_percent',
		interval: 'interval_mm'
	} as const;

	/** "12 mm/s", "60%" — what differed in this square from its neighbour. */
	function axisValue(cell: Cell, as: Grid['row_axis']) {
		const value = cell[CEL_SLEUTEL[as]];
		if (value === null || value === undefined) return '';
		return as === 'power' ? `${value}%` : `${value} ${EENHEID[as]}`;
	}

	/** The two quantities that distinguish this square, one after the other. */
	function cellText(cell: Cell) {
		if (!grid) return '';
		return `${axisValue(cell, grid.row_axis)} · ${axisValue(cell, grid.column_axis)}`;
	}

	let {
		library,
		canEdit = false,
		focusGrid = null
	}: {
		library: LibraryStore;
		canEdit?: boolean;
		/** Net gegenereerd grid: daar wil je meteen naartoe. */
		focusGrid?: number | null;
	} = $props();

	let grids = $state<Grid[]>([]);
	let openId = $state<number | null>(null);
	let picked = $state<string[]>([]);
	let busy = $state(false);
	let error = $state<string | null>(null);
	let photoStamp = $state(0);
	let aligning = $state(false);
	let aangewezen = $state<Cell | null>(null);
	let podium = $state<HTMLElement | null>(null);

	let grid = $derived(grids.find((g) => g.id === openId) ?? null);

	// A frame around all the cells: the measure in which a cell expresses its place.
	// rows/columns instead of speed_steps/power_steps: since B12 which quantity sits
	// on which axis is no longer fixed.
	let box = $derived.by(() => {
		if (!grid) return null;
		const pitch = grid.cell_mm + grid.gap_mm;
		return {
			width: (grid.columns ?? grid.power_steps) * pitch - grid.gap_mm,
			height: (grid.rows ?? grid.speed_steps) * pitch - grid.gap_mm
		};
	});

	/** "11 Aug 21:26" — enough to separate three trials from the same week. */
	function dateOf(ruw: string) {
		const d = new Date(ruw.replace(' ', 'T'));
		if (Number.isNaN(d.getTime())) return ruw;
		return d.toLocaleString(i18n.locale, {
			day: 'numeric',
			month: 'short',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	function key(cell: Cell) {
		return `${cell.row}-${cell.column}`;
	}

	async function load() {
		const response = await fetch('/api/library/testgrids');
		if (response.ok) grids = await response.json();
	}

	load();

	// A freshly burned grid: that is where you want to go, not "choose a grid…".
	$effect(() => {
		if (focusGrid === null) return;
		(async () => {
			await load();
			openId = focusGrid;
		})();
	});

	// ------------------------------------------------------------- uitlijning
	//
	// A photo of a board is never a tidy crop: you state at an angle above it, with
	// the board half in frame. Without correction the overlay lies beside the burned
	// squares and you therefore point at the wrong square — which makes the one step
	// that sets this app apart worthless. Hence four draggable corners and a
	// projective mapping, exactly like the camera's perspective correction.

	// The alignment belongs to the board, not to the browser (gap T4): you align on
	// the desktop and point out the best square on the tablet beside the machine. Kept
	// in localStorage, the second half of that sentence would be an empty grid over a
	// skewed photo. Now it is a column on test_grid.
	const DEFAULT_CORNERS: Point[] = [
		{ x: 0.1, y: 0.1 },
		{ x: 0.9, y: 0.1 },
		{ x: 0.9, y: 0.9 },
		{ x: 0.1, y: 0.9 }
	];
	const HOEKNAAM = [
		t('result.corner.topLeft'),
		t('result.corner.topRight'),
		t('result.corner.bottomRight'),
		t('result.corner.bottomLeft')
	];

	let corners = $state<Point[]>(DEFAULT_CORNERS.map((p) => ({ ...p })));
	let saveError = $state<string | null>(null);

	$effect(() => {
		const id = openId;
		if (id === null) return;
		// React only to switching grids. If this also listened to `grids`, the
		// alignment state would snap shut as soon as saving sent its answer back —
		// in the middle of dragging.
		const saved = untrack(() => grids.find((g) => g.id === id)?.alignment ?? null);
		corners =
			saved && saved.length === 4
				? saved.map((p) => ({ x: p.x, y: p.y }))
				: DEFAULT_CORNERS.map((p) => ({ ...p }));
		// Never aligned before? Then that is the first action.
		aligning = saved === null;
		aangewezen = null;
		saveError = null;
	});

	let bewaartimer: ReturnType<typeof setTimeout> | null = null;

	function saveAlignment() {
		if (openId === null) return;
		// Dragging fires on every released corner; waiting a moment saves four write
		// rounds to the database for one alignment.
		if (bewaartimer) clearTimeout(bewaartimer);
		const id = openId;
		const points = corners.map((p) => ({ x: p.x, y: p.y }));
		bewaartimer = setTimeout(async () => {
			try {
				const response = await fetch(`/api/library/testgrids/${id}/alignment`, {
					method: 'PUT',
					headers: headers(true),
					body: JSON.stringify({ corners: points })
				});
				if (!response.ok) {
					saveError = t('result.align.failed');
					return;
				}
				saveError = null;
				const bijgewerkt: Grid = await response.json();
				grids = grids.map((g) => (g.id === id ? bijgewerkt : g));
			} catch {
				saveError = t('result.align.failedOffline');
			}
		}, 400);
	}

	/**
	 * Projective mapping from the unit square to the four corners.
	 *
	 * An affine transform (translate, scale, shear) is not enough: standing at an
	 * angle above the board you photograph a trapezium. The standard homography
	 * below does catch that.
	 */
	let afbeelding = $derived.by(() => {
		const [p0, p1, p2, p3] = corners;
		const dx1 = p1.x - p2.x;
		const dx2 = p3.x - p2.x;
		const dx3 = p0.x - p1.x + p2.x - p3.x;
		const dy1 = p1.y - p2.y;
		const dy2 = p3.y - p2.y;
		const dy3 = p0.y - p1.y + p2.y - p3.y;
		const noemer = dx1 * dy2 - dy1 * dx2;
		let g = 0;
		let h = 0;
		if (Math.abs(noemer) > 1e-9 && (dx3 !== 0 || dy3 !== 0)) {
			g = (dx3 * dy2 - dy3 * dx2) / noemer;
			h = (dx1 * dy3 - dy1 * dx3) / noemer;
		}
		return {
			a: p1.x - p0.x + g * p1.x,
			b: p3.x - p0.x + h * p3.x,
			c: p0.x,
			d: p1.y - p0.y + g * p1.y,
			e: p3.y - p0.y + h * p3.y,
			f: p0.y,
			g,
			h
		};
	});

	function toPhoto(u: number, v: number) {
		const m = afbeelding;
		const w = m.g * u + m.h * v + 1 || 1e-9;
		return [(m.a * u + m.b * v + m.c) / w, (m.d * u + m.e * v + m.f) / w];
	}

	/** A cell as a quadrilateral in photo coordinates (0–1), perspective and all. */
	function veelhoek(cell: Cell) {
		if (!grid || !box) return '';
		const u0 = (cell.x_mm - grid.origin_x_mm) / box.width;
		const v0 = (cell.y_mm - grid.origin_y_mm) / box.height;
		const u1 = u0 + cell.width_mm / box.width;
		const v1 = v0 + cell.height_mm / box.height;
		return [
			toPhoto(u0, v0),
			toPhoto(u1, v0),
			toPhoto(u1, v1),
			toPhoto(u0, v1)
		]
			.map(([x, y]) => `${x},${y}`)
			.join(' ');
	}

	function sleep(index: number, event: PointerEvent) {
		if (!podium) return;
		const target = event.currentTarget as HTMLElement;
		target.setPointerCapture(event.pointerId);
		const rect = podium.getBoundingClientRect();
		const beweeg = (e: PointerEvent) => {
			corners[index] = {
				x: Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width)),
				y: Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height))
			};
		};
		const stop = () => {
			target.removeEventListener('pointermove', beweeg);
			target.removeEventListener('pointerup', stop);
			saveAlignment();
		};
		target.addEventListener('pointermove', beweeg);
		target.addEventListener('pointerup', stop);
	}

	function onKey(index: number, event: KeyboardEvent) {
		const step = event.shiftKey ? 0.02 : 0.004;
		const richting: Record<string, [number, number]> = {
			ArrowLeft: [-step, 0],
			ArrowRight: [step, 0],
			ArrowUp: [0, -step],
			ArrowDown: [0, step]
		};
		const d = richting[event.key];
		if (!d) return;
		event.preventDefault();
		corners[index] = {
			x: Math.min(1, Math.max(0, corners[index].x + d[0])),
			y: Math.min(1, Math.max(0, corners[index].y + d[1]))
		};
		saveAlignment();
	}

	// ------------------------------------------------------------------ choice

	function toggle(cell: Cell) {
		if (!canEdit || aligning) return;
		const id = key(cell);
		picked = picked.includes(id) ? picked.filter((p) => p !== id) : [...picked, id];
	}

	let pickedCells = $derived(
		grid ? grid.cells.filter((c) => picked.includes(key(c))) : []
	);
	/** The squares a preset has already been taken from — the evidence under the card. */
	let usedCells = $derived(
		grid ? grid.cells.filter((c) => c.preset_id !== undefined && c.preset_id !== null) : []
	);

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
				error = t('error.photoFailed');
				return;
			}
			await load();
			photoStamp = Date.now();
			// A fresh photo is not yet under the overlay: that is the first action, so
			// set it up straight away.
			aligning = true;
		} finally {
			busy = false;
		}
	}

	let made = $state<number | null>(null);

	async function makePresets() {
		if (!grid || picked.length === 0) return;
		busy = true;
		error = null;
		made = null;
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
				error = typeof data?.detail === 'string' ? data.detail : t('error.presetFailed');
				return;
			}
			made = cells.length;
			picked = [];
			await Promise.all([load(), library.load()]);
		} finally {
			busy = false;
		}
	}
</script>

<div class="resultaat">
	<div class="head">
		<h2 class="title">{t('result.title')}</h2>
		{#if grids.length}
			<select class="picker" bind:value={openId} aria-label={t('result.pickGrid')}>
				<option value={null}>{t('result.pickGrid.option')}</option>
				{#each grids as g (g.id)}
					<!-- The date with it: whoever has done three tests on the same material
					     otherwise sees three identical lines. -->
					<option value={g.id}>
						{dateOf(g.created_at)} · {g.material_name ?? t('result.noMaterial')} · {g.operation}
						{g.photo_path ? t('result.withPhoto') : t('result.waitingPhoto')}
					</option>
				{/each}
			</select>
		{/if}
	</div>

	{#if grids.length === 0}
		<p class="muted">{t('result.noGrids')}</p>
	{/if}

	{#if error}<p class="notice failure" role="alert">{error}</p>{/if}
	{#if made}
		<p class="notice good" role="status">
			{t('result.saved', {
				n: made,
				material: grid?.material_name ?? t('result.thisMaterial')
			})}
		</p>
	{/if}

	{#if grid && box}
		{#if !grid.photo_path}
			<!-- No photo: then no grid of empty squares over nothing. Say what has to
			     happen and how you do it with a phone. -->
			<div class="geenfoto">
				<p class="why">
					<strong>{t('result.burnFirst')}</strong>
					{t('result.burnFirst.how')}
				</p>
				{#if canEdit}
					<label class="btn primary big file">
						{t('library.addPhoto')}
						<input type="file" accept="image/*" capture="environment" onchange={uploadPhoto} />
					</label>
				{/if}
				<p class="muted">{t('result.orPhone')}</p>
			</div>
		{:else}
			<div class="podium" bind:this={podium}>
				<img
					src="/api/library/testgrids/{grid.id}/photo?v={photoStamp}"
					alt={t('result.photoAlt')}
				/>

				<svg viewBox="0 0 1 1" preserveAspectRatio="none" class:aligning>
					{#each grid.cells as cell (key(cell))}
						<g
							class="cell"
							class:picked={picked.includes(key(cell))}
							class:used={cell.preset_id !== undefined && cell.preset_id !== null}
							class:aangewezen={aangewezen !== null &&
								aangewezen.row === cell.row &&
								aangewezen.column === cell.column}
						>
							<polygon
								role="button"
								tabindex={aligning ? -1 : 0}
								aria-label="Row {cell.row + 1}, column {cell.column + 1} — {cellText(cell)}"
								aria-pressed={picked.includes(key(cell))}
								points={veelhoek(cell)}
								onclick={() => toggle(cell)}
								onpointerenter={() => (aangewezen = cell)}
								onfocus={() => (aangewezen = cell)}
								onkeydown={(e) => {
									if (e.key === 'Enter' || e.key === ' ') {
										e.preventDefault();
										toggle(cell);
									}
								}}
							/>
						</g>
					{/each}
					{#if aligning}
						<polygon
							class="frame"
							points={corners.map((p) => `${p.x},${p.y}`).join(' ')}
						/>
					{/if}
				</svg>

				{#if aligning}
					{#each corners as point, i (i)}
						<button
							class="corner"
							style="left: {point.x * 100}%; top: {point.y * 100}%"
							aria-label={t('result.corner.drag', { corner: HOEKNAAM[i] })}
							onpointerdown={(e) => sleep(i, e)}
							onkeydown={(e) => onKey(i, e)}
						><span></span></button>
					{/each}
				{/if}

				<!-- Which setting is under your finger? Without this you point at a square
				     without knowing what you are choosing. -->
				<div class="aflezing mono" aria-live="polite">
					{#if aligning}
						{t('result.dragCorners')}
					{:else if aangewezen}
						{t('result.rowColumn', {
							row: aangewezen.row + 1,
							column: aangewezen.column + 1,
							values: cellText(aangewezen)
						})}
					{:else}
						{t('result.tapBest')}
					{/if}
				</div>
			</div>

			<div class="onderbalk">
				<button
					class="btn"
					aria-pressed={aligning}
					onclick={() => {
						aligning = !aligning;
						if (!aligning) saveAlignment();
					}}
				>{aligning ? t('result.alignDone') : t('result.align')}</button>

				{#if canEdit}
					<label class="btn file">
						{t('result.otherPhoto')}
						<input type="file" accept="image/*" capture="environment" onchange={uploadPhoto} />
					</label>
				{/if}

				<div class="choice">
					{#if pickedCells.length}
						{#each pickedCells as cell (key(cell))}
							<button
								class="chip mono"
								onclick={() => toggle(cell)}
								aria-label={t('result.undoChoice', {
									row: cell.row + 1,
									column: cell.column + 1,
									values: cellText(cell)
								})}
							>{t('result.chip', {
									row: cell.row + 1,
									column: cell.column + 1,
									values: cellText(cell)
								})} ×</button>
						{/each}
					{:else}
						<span class="muted">{t('result.noneChosen')}</span>
					{/if}
				</div>

				{#if canEdit}
					<button
						class="btn primary"
						disabled={busy || picked.length === 0 || grid.material_id === null}
						onclick={makePresets}
					>
						{#if busy}
							{t('common.busy')}
						{:else if picked.length}
							{t('result.makePresets', { n: picked.length })}
						{:else}
							{t('result.makePreset')}
						{/if}
					</button>
				{/if}
			</div>

			{#if saveError}<p class="notice failure" role="alert">{saveError}</p>{/if}

			{#if usedCells.length}
				<!-- Gap M4: the provenance said "row 2, column 3" and nothing was marked on
				     the photo. Now that the alignment is saved, the same overlay can point
				     at the square — here by highlighting it, and in the library because the
				     photo with ?cell= gets the outline drawn in. -->
				<div class="herkomst">
					<span class="muted">{t('result.becamePreset')}</span>
					{#each usedCells as cell (key(cell))}
						<button
							class="chip bewijs mono"
							onpointerenter={() => (aangewezen = cell)}
							onpointerleave={() => (aangewezen = null)}
							onfocus={() => (aangewezen = cell)}
							onblur={() => (aangewezen = null)}
							onclick={() => (aangewezen = cell)}
						>{t('result.chip', {
								row: cell.row + 1,
								column: cell.column + 1,
								values: cellText(cell)
							})}</button>
					{/each}
					<span class="muted">{t('result.pointHighlights')}</span>
				</div>
			{/if}

			{#if grid.material_id === null}
				<p class="notice waarschuwing">{t('result.gridNoMaterial')}</p>
			{/if}
		{/if}
	{/if}
</div>

<style>
	.resultaat {
		display: grid;
		gap: var(--space-3);
		margin-top: var(--space-6);
		padding-top: var(--space-4);
		border-top: 1px solid var(--line);
	}
	.head { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; }
	.title {
		margin: 0;
		font-size: var(--text-sm);
		font-weight: 600;
		letter-spacing: -0.01em;
		color: var(--text-1);
	}
	.muted { color: var(--text-2); margin: 0; font-size: var(--text-xs); }
	.picker {
		font: inherit;
		font-size: var(--text-sm);
		flex: 1;
		min-width: 16rem;
		padding: 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}

	.geenfoto {
		display: grid;
		justify-items: center;
		gap: var(--space-3);
		padding: var(--space-6) var(--space-4);
		text-align: center;
		border: 1px dashed var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-2);
	}
	.why { margin: 0; max-width: 44ch; font-size: var(--text-sm); color: var(--text-1); }

	.podium {
		position: relative;
		/* Shrink to the photo: otherwise the corners lie partly in the grey
		   letterbox naast het beeld. */
		width: fit-content;
		margin-inline: auto;
		/* Dragging must not select text: that turns half the dialog blue. */
		user-select: none;
		-webkit-user-select: none;
		border-radius: var(--radius-card);
		overflow: hidden;
		background: var(--surface-2);
		box-shadow: var(--lift-1);
		/* The action bar has to stay on screen: a photo that fills the whole dialog
		   pushes "Make preset" below the fold, and then the flow ends nowhere. */
		max-height: 46vh;
		display: grid;
		place-items: center;
	}
	.podium img { display: block; max-width: 100%; max-height: 46vh; }
	.podium svg { position: absolute; inset: 0; width: 100%; height: 100%; }
	.podium svg.aligning { pointer-events: none; }

	/* This SVG measures in units from 0 to 1 and is stretched to hundreds of pixels.
	   Every edge therefore gets non-scaling-stroke, and there is no text, radius or
	   shadow in it. See DESIGN-SYSTEM, "SVG that measures in millimetres
	   meet". */
	.cell polygon {
		fill: transparent;
		stroke: color-mix(in srgb, var(--accent) 60%, transparent);
		stroke-width: 1;
		vector-effect: non-scaling-stroke;
		cursor: pointer;
		outline: none;
	}
	.cell polygon:focus-visible {
		stroke: var(--accent);
		stroke-width: 3;
		stroke-dasharray: 4 3;
	}
	.cell.used polygon {
		stroke: var(--ok);
		stroke-dasharray: 3 2;
		fill: color-mix(in srgb, var(--ok) 14%, transparent);
	}
	/* Pointing at the provenance line lights up the square on the photo: that is the
	   whole promise of "row 2, column 3" — that you find it again. */
	.cell.aangewezen polygon {
		stroke: var(--ok);
		stroke-width: 4;
		stroke-dasharray: none;
		fill: color-mix(in srgb, var(--ok) 30%, transparent);
	}
	.cell.picked polygon {
		fill: color-mix(in srgb, var(--accent) 26%, transparent);
		stroke: var(--accent);
		stroke-width: 3;
	}
	.frame {
		fill: none;
		stroke: var(--accent);
		stroke-width: 2;
		stroke-dasharray: 6 4;
		vector-effect: non-scaling-stroke;
	}

	/* A 44px touch target with a small dot in it: your finger has to reach it, your
	   eye has to see where the corner exactly lies. */
	.corner {
		position: absolute;
		width: var(--grip);
		height: var(--grip);
		margin: calc(var(--grip) / -2) 0 0 calc(var(--grip) / -2);
		border-radius: var(--radius-dot);
		background: color-mix(in srgb, var(--accent) 22%, transparent);
		border: 1px solid var(--accent);
		display: grid;
		place-items: center;
		cursor: grab;
		touch-action: none;
	}
	.corner span {
		width: 8px;
		height: 8px;
		border-radius: var(--radius-dot);
		background: var(--accent);
	}
	.corner:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

	.aflezing {
		position: absolute;
		left: var(--space-2);
		bottom: var(--space-2);
		padding: 4px var(--space-3);
		border-radius: var(--radius-dot);
		font-size: var(--text-xs);
		background: color-mix(in srgb, var(--surface-1) 88%, transparent);
		border: 1px solid var(--line);
		color: var(--text-1);
		backdrop-filter: blur(6px);
		pointer-events: none;
	}

	.onderbalk {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		flex-wrap: wrap;
	}
	.choice { display: flex; gap: var(--space-1); flex-wrap: wrap; flex: 1; min-width: 8rem; }
	.herkomst {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		flex-wrap: wrap;
		font-size: var(--text-xs);
	}
	.chip.bewijs {
		border-color: var(--ok);
		background: color-mix(in srgb, var(--ok) 12%, transparent);
	}

	.chip {
		font: inherit;
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		padding: 4px var(--space-2);
		border-radius: var(--radius-dot);
		border: 1px solid var(--accent);
		background: color-mix(in srgb, var(--accent) 12%, transparent);
		color: var(--text-1);
	}

	.btn {
		min-height: 40px;
		padding: var(--space-2) var(--space-4);
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		font: inherit;
		font-size: var(--text-sm);
		font-weight: 500;
		color: var(--text-1);
	}
	.btn:hover:not(:disabled) { background: var(--surface-2); }
	/* Without this rule the general hover beats .primary: on hover the button went
	   light grey with white text. Same specificity, later in the stylesheet — a
	   classic. */
	.btn.primary:hover:not(:disabled) {
		background: color-mix(in srgb, var(--accent) 88%, var(--text-1));
	}
	/* A disabled primary button must not look like a button that works: 45% accent
	   still reads as "click me" in the dark theme. */
	.btn.primary:disabled {
		background: var(--surface-2);
		border-color: var(--line);
		color: var(--text-2);
		opacity: 1;
	}
	.btn:disabled { opacity: 0.45; cursor: not-allowed; }
	.btn[aria-pressed='true'] {
		background: color-mix(in srgb, var(--accent) 14%, transparent);
		border-color: var(--accent);
		color: var(--accent);
	}
	.btn.primary {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
	}
	.btn.big { min-height: 48px; padding: 12px 20px; font-size: var(--text-md); }
	.btn.file { cursor: pointer; display: inline-grid; place-items: center; }
	.btn.file input { position: absolute; width: 0; height: 0; opacity: 0; }

	.notice {
		margin: 0;
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-field);
		font-size: var(--text-xs);
	}
	.notice.failure { background: color-mix(in srgb, var(--danger-solid) 14%, transparent); }
	.notice.good {
		background: color-mix(in srgb, var(--ok) 14%, transparent);
		border-left: 3px solid var(--ok);
	}
	.notice.waarschuwing {
		background: color-mix(in srgb, var(--warn-solid) 12%, transparent);
		border-left: 3px solid var(--warn-solid);
	}

	@media (max-width: 720px) {
		.onderbalk .btn { flex: 1; }
	}
</style>
