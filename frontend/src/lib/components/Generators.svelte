<script lang="ts">
	import Dialog from './Dialog.svelte';

	let {
		open = $bindable(),
		hasSelection = false,
		busy = false,
		onGenerate
	}: {
		open: boolean;
		hasSelection?: boolean;
		busy?: boolean;
		onGenerate: (what: string, body: Record<string, unknown>) => Promise<string | null>;
	} = $props();

	type Tab = 'grid' | 'radial' | 'polygon' | 'box' | 'qrcode' | 'barcode' | 'arctext';
	let tab = $state<Tab>('grid');
	let error = $state<string | null>(null);

	let grid = $state({ columns: '4', rows: '3', gap_x_mm: '5', gap_y_mm: '5' });
	let radial = $state({ repeats: '8', radius_mm: '40', rotate: true });
	let polygon = $state({ corners: '6', radius_mm: '20', inner: '', cx_mm: '50', cy_mm: '50' });
	let box = $state({
		width_mm: '100',
		depth_mm: '80',
		height_mm: '50',
		thickness_mm: '3',
		finger_mm: '10',
		kerf_mm: '0.15',
		lid: true
	});
	let qr = $state({ text: '', size_mm: '30' });
	let bar = $state({ text: '', kind: 'code128', width_mm: '60', height_mm: '20' });
	let arc = $state({
		text: '',
		cx_mm: '100',
		cy_mm: '100',
		radius_mm: '40',
		font_size_mm: '10',
		inside: false
	});

	// De typen die python-barcode aankan en die op een laser zinnig zijn.
	const BARCODES = ['code128', 'code39', 'ean13', 'ean8', 'upca', 'itf', 'issn'];

	const TABS: { id: Tab; label: string; needsSelection: boolean }[] = [
		{ id: 'grid', label: 'Raster', needsSelection: true },
		{ id: 'radial', label: 'Cirkel', needsSelection: true },
		{ id: 'polygon', label: 'Veelhoek', needsSelection: false },
		{ id: 'box', label: 'Doos', needsSelection: false },
		{ id: 'qrcode', label: 'QR-code', needsSelection: false },
		{ id: 'barcode', label: 'Streepjescode', needsSelection: false },
		{ id: 'arctext', label: 'Boogtekst', needsSelection: false }
	];

	let current = $derived(TABS.find((t) => t.id === tab)!);
	let blocked = $derived(current.needsSelection && !hasSelection);

	async function run(body: Record<string, unknown>) {
		error = await onGenerate(tab, body);
		if (!error) open = false;
	}

	const n = (value: string) => Number(value);
</script>

<Dialog title="Generatoren" bind:open width="560px">
	<div class="tabs">
		{#each TABS as item (item.id)}
			<button class="tab" aria-pressed={tab === item.id} onclick={() => { tab = item.id; error = null; }}>
				{item.label}
			</button>
		{/each}
	</div>

	{#if blocked}
		<p class="hint">Selecteer eerst wat er herhaald moet worden.</p>
	{/if}
	{#if error}
		<p class="error" role="alert">{error}</p>
	{/if}

	{#if tab === 'grid'}
		<p class="lead">
			De selectie in rijen en kolommen herhalen. De afstand is de ruimte <em>tussen</em>
			de vormen, want daar gaat de snede doorheen.
		</p>
		<div class="fields">
			<label><span>Kolommen</span><input class="mono" type="number" min="1" bind:value={grid.columns} /></label>
			<label><span>Rijen</span><input class="mono" type="number" min="1" bind:value={grid.rows} /></label>
			<label><span>Ruimte X (mm)</span><input class="mono" type="number" step="0.5" bind:value={grid.gap_x_mm} /></label>
			<label><span>Ruimte Y (mm)</span><input class="mono" type="number" step="0.5" bind:value={grid.gap_y_mm} /></label>
		</div>
		<button class="go" disabled={blocked || busy} onclick={() => run({
			columns: n(grid.columns), rows: n(grid.rows),
			gap_x_mm: n(grid.gap_x_mm), gap_y_mm: n(grid.gap_y_mm)
		})}>
			{n(grid.columns) * n(grid.rows)} stuks maken
		</button>
	{:else if tab === 'radial'}
		<p class="lead">De selectie rond een middelpunt herhalen.</p>
		<div class="fields">
			<label><span>Aantal</span><input class="mono" type="number" min="2" bind:value={radial.repeats} /></label>
			<label><span>Straal (mm)</span><input class="mono" type="number" step="1" bind:value={radial.radius_mm} /></label>
			<label class="check"><input type="checkbox" bind:checked={radial.rotate} /><span>Meedraaien</span></label>
		</div>
		<button class="go" disabled={blocked || busy} onclick={() => run({
			repeats: n(radial.repeats), radius_mm: n(radial.radius_mm), rotate: radial.rotate
		})}>Rondzetten</button>
	{:else if tab === 'polygon'}
		<p class="lead">
			Een regelmatige veelhoek. Vul een binnenstraal in en het wordt een ster.
		</p>
		<div class="fields">
			<label><span>Hoeken</span><input class="mono" type="number" min="3" bind:value={polygon.corners} /></label>
			<label><span>Straal (mm)</span><input class="mono" type="number" step="1" bind:value={polygon.radius_mm} /></label>
			<label><span>Binnenstraal (mm)</span><input class="mono" type="number" step="1" placeholder="leeg = veelhoek" bind:value={polygon.inner} /></label>
			<label><span>Midden X (mm)</span><input class="mono" type="number" bind:value={polygon.cx_mm} /></label>
			<label><span>Midden Y (mm)</span><input class="mono" type="number" bind:value={polygon.cy_mm} /></label>
		</div>
		<button class="go" disabled={busy} onclick={() => run({
			corners: n(polygon.corners), radius_mm: n(polygon.radius_mm),
			cx_mm: n(polygon.cx_mm), cy_mm: n(polygon.cy_mm),
			inner_radius_mm: polygon.inner.trim() === '' ? null : n(polygon.inner)
		})}>Tekenen</button>
	{:else if tab === 'box'}
		<p class="lead">
			Een doos met vingerlassen, als losse panelen naast elkaar. De maten zijn de
			buitenmaten van de doos; het uitgesneden paneel is aan elke kant één
			materiaaldikte groter, dat zijn de tanden. De snijbreedte (kerf) wordt bij
			de tanden opgeteld, want de laser haalt aan beide kanten van elke snede
			materiaal weg.
		</p>
		<div class="fields">
			<label><span>Breedte (mm)</span><input class="mono" type="number" bind:value={box.width_mm} /></label>
			<label><span>Diepte (mm)</span><input class="mono" type="number" bind:value={box.depth_mm} /></label>
			<label><span>Hoogte (mm)</span><input class="mono" type="number" bind:value={box.height_mm} /></label>
			<label><span>Materiaaldikte (mm)</span><input class="mono" type="number" step="0.1" bind:value={box.thickness_mm} /></label>
			<label><span>Vinger (mm)</span><input class="mono" type="number" step="1" bind:value={box.finger_mm} /></label>
			<label><span>Kerf (mm)</span><input class="mono" type="number" step="0.05" bind:value={box.kerf_mm} /></label>
			<label class="check"><input type="checkbox" bind:checked={box.lid} /><span>Met deksel</span></label>
		</div>
		<button class="go" disabled={busy} onclick={() => run({
			width_mm: n(box.width_mm), depth_mm: n(box.depth_mm), height_mm: n(box.height_mm),
			thickness_mm: n(box.thickness_mm), finger_mm: n(box.finger_mm),
			kerf_mm: n(box.kerf_mm), lid: box.lid
		})}>Panelen maken</button>
	{:else if tab === 'qrcode'}
		<p class="lead">
			Een QR-code als vlakken, niet als plaatje: gegraveerde bitmaps worden op
			hout vaak vaag, gevulde vierkanten niet.
		</p>
		<div class="fields">
			<label class="wide"><span>Inhoud</span><input type="text" placeholder="https://…" bind:value={qr.text} /></label>
			<label><span>Formaat (mm)</span><input class="mono" type="number" step="1" bind:value={qr.size_mm} /></label>
		</div>
		<button class="go" disabled={busy || !qr.text.trim()} onclick={() => run({
			text: qr.text.trim(), size_mm: n(qr.size_mm)
		})}>Plaatsen</button>
	{:else if tab === 'barcode'}
		<p class="lead">
			Een streepjescode als vlakken. EAN en UPC stellen eisen aan lengte en
			controlecijfer; klopt het niet, dan zegt de app dat in plaats van een code
			te maken die niet scant.
		</p>
		<div class="fields">
			<label class="wide"><span>Inhoud</span><input type="text" placeholder="OPENKERF-1" bind:value={bar.text} /></label>
			<label>
				<span>Type</span>
				<select bind:value={bar.kind}>
					{#each BARCODES as item (item)}
						<option value={item}>{item}</option>
					{/each}
				</select>
			</label>
			<label><span>Breedte (mm)</span><input class="mono" type="number" step="1" bind:value={bar.width_mm} /></label>
			<label><span>Hoogte (mm)</span><input class="mono" type="number" step="1" bind:value={bar.height_mm} /></label>
		</div>
		<button class="go" disabled={busy || !bar.text.trim()} onclick={() => run({
			text: bar.text.trim(), kind: bar.kind,
			width_mm: n(bar.width_mm), height_mm: n(bar.height_mm)
		})}>Plaatsen</button>
	{:else}
		<p class="lead">
			Tekst langs een boog, voor een rond bordje of een deksel. Let op: hierna is
			het een pad en geen tekst meer — de engine zou de tekst anders bij de
			eerstvolgende wijziging weer recht renderen en de boog wegpoetsen.
		</p>
		<div class="fields">
			<label class="wide"><span>Tekst</span><input type="text" placeholder="OPENKERF" bind:value={arc.text} /></label>
			<label><span>Midden X (mm)</span><input class="mono" type="number" bind:value={arc.cx_mm} /></label>
			<label><span>Midden Y (mm)</span><input class="mono" type="number" bind:value={arc.cy_mm} /></label>
			<label><span>Straal (mm)</span><input class="mono" type="number" step="1" bind:value={arc.radius_mm} /></label>
			<label><span>Letterhoogte (mm)</span><input class="mono" type="number" step="0.5" bind:value={arc.font_size_mm} /></label>
			<label class="check"><input type="checkbox" bind:checked={arc.inside} /><span>Onderlangs</span></label>
		</div>
		<button class="go" disabled={busy || !arc.text.trim()} onclick={() => run({
			text: arc.text.trim(), cx_mm: n(arc.cx_mm), cy_mm: n(arc.cy_mm),
			radius_mm: n(arc.radius_mm), font_size_mm: n(arc.font_size_mm), inside: arc.inside
		})}>Plaatsen</button>
	{/if}
</Dialog>

<style>
	.tabs { display: flex; gap: 4px; margin-bottom: var(--space-3); flex-wrap: wrap; }
	.tab {
		font-size: var(--text-xs);
		padding: 4px 10px;
		border-radius: 999px;
		border: 1px solid var(--line);
		color: var(--text-2);
		background: var(--surface-1);
	}
	.tab[aria-pressed='true'] {
		border-color: var(--accent);
		color: var(--accent);
		background: color-mix(in srgb, var(--accent) 10%, transparent);
	}
	.lead { margin: 0 0 var(--space-3); font-size: var(--text-xs); color: var(--text-2); line-height: 1.5; }
	.hint { margin: 0 0 var(--space-2); font-size: var(--text-xs); color: var(--warn); }
	.error { margin: 0 0 var(--space-2); font-size: var(--text-xs); color: var(--danger); }
	.fields {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-2) var(--space-3);
		margin-bottom: var(--space-4);
	}
	.fields label { display: grid; gap: 2px; font-size: 10px; color: var(--text-2); }
	.fields .wide { grid-column: 1 / -1; }
	.fields .check { display: flex; align-items: center; gap: 6px; align-self: end; }
	input,
	select {
		font: inherit;
		width: 100%;
		padding: 6px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.check input { width: auto; }
	.go {
		width: 100%;
		padding: 8px 14px;
		border-radius: var(--radius-field);
		border: 1px solid var(--accent);
		background: var(--accent);
		color: var(--accent-ink);
		font-weight: 500;
	}
	.go:disabled { opacity: 0.45; cursor: not-allowed; }
</style>
