<script lang="ts">
	import { untrack } from 'svelte';
	import type { LibraryStore } from '$lib/library.svelte';

	type Punt = { x: number; y: number };

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
		/** Sinds B12 hoeven de assen geen snelheid × vermogen te zijn. */
		row_axis: 'speed' | 'power' | 'interval';
		column_axis: 'speed' | 'power' | 'interval';
		rows: number | null;
		columns: number | null;
		photo_path: string | null;
		/** De vier hoeken van het bord op de foto; staat in de database (T4). */
		alignment: Punt[] | null;
		cells: Cell[];
		created_at: string;
	};

	const EENHEID = { speed: 'mm/s', power: '%', interval: 'mm' } as const;
	const CEL_SLEUTEL = {
		speed: 'speed_mm_s',
		power: 'power_percent',
		interval: 'interval_mm'
	} as const;

	/** "12 mm/s", "60%" — wat er in dit vakje anders was dan in het buurvakje. */
	function aswaarde(cell: Cell, as: Grid['row_axis']) {
		const waarde = cell[CEL_SLEUTEL[as]];
		if (waarde === null || waarde === undefined) return '';
		return as === 'power' ? `${waarde}%` : `${waarde} ${EENHEID[as]}`;
	}

	/** De twee grootheden die dit vakje onderscheiden, achter elkaar. */
	function celtekst(cell: Cell) {
		if (!grid) return '';
		return `${aswaarde(cell, grid.row_axis)} · ${aswaarde(cell, grid.column_axis)}`;
	}

	let {
		library,
		canEdit = false,
		focusGrid = null
	}: {
		library: LibraryStore;
		canEdit?: boolean;
		/** Net gegenereerd raster: daar wil je meteen naartoe. */
		focusGrid?: number | null;
	} = $props();

	let grids = $state<Grid[]>([]);
	let openId = $state<number | null>(null);
	let picked = $state<string[]>([]);
	let busy = $state(false);
	let error = $state<string | null>(null);
	let photoStamp = $state(0);
	let uitlijnen = $state(false);
	let aangewezen = $state<Cell | null>(null);
	let podium = $state<HTMLElement | null>(null);

	let grid = $derived(grids.find((g) => g.id === openId) ?? null);

	// Kader om alle cellen heen: de maat waarin een cel zijn plek uitdrukt.
	// rows/columns in plaats van speed_steps/power_steps: welke grootheid op
	// welke as staat, ligt sinds B12 niet meer vast.
	let box = $derived.by(() => {
		if (!grid) return null;
		const pitch = grid.cell_mm + grid.gap_mm;
		return {
			width: (grid.columns ?? grid.power_steps) * pitch - grid.gap_mm,
			height: (grid.rows ?? grid.speed_steps) * pitch - grid.gap_mm
		};
	});

	/** "11 aug 21:26" — genoeg om drie proeven van dezelfde week te scheiden. */
	function datum(ruw: string) {
		const d = new Date(ruw.replace(' ', 'T'));
		if (Number.isNaN(d.getTime())) return ruw;
		return d.toLocaleString('nl-NL', {
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

	// Vers gebrand raster: dat is waar je naartoe wilt, niet "kies een raster…".
	$effect(() => {
		if (focusGrid === null) return;
		(async () => {
			await load();
			openId = focusGrid;
		})();
	});

	// ------------------------------------------------------------- uitlijning
	//
	// Een foto van een bord is nooit een strakke uitsnede: je staat er schuin
	// boven, met het bord half in beeld. Zonder correctie ligt de overlay naast
	// de gebrande vakjes en wijs je dus het verkeerde vakje aan — de enige stap
	// die deze app onderscheidt, wordt daarmee waardeloos. Daarom vier
	// sleepbare hoeken en een projectieve afbeelding, precies zoals de
	// perspectiefcorrectie van de camera.

	// De uitlijning hoort bij het bord, niet bij de browser (gat T4): je lijnt
	// uit op de desktop en wijst het beste vakje aan op de tablet naast de
	// machine. Stond dit in localStorage, dan was de tweede helft van die zin
	// een leeg raster over een schuine foto. Nu is het een kolom op test_grid.
	const STANDAARD: Punt[] = [
		{ x: 0.1, y: 0.1 },
		{ x: 0.9, y: 0.1 },
		{ x: 0.9, y: 0.9 },
		{ x: 0.1, y: 0.9 }
	];
	const HOEKNAAM = ['linksboven', 'rechtsboven', 'rechtsonder', 'linksonder'];

	let hoeken = $state<Punt[]>(STANDAARD.map((p) => ({ ...p })));
	let bewaarFout = $state<string | null>(null);

	$effect(() => {
		const id = openId;
		if (id === null) return;
		// Alleen op het wisselen van raster reageren. Zou dit ook op `grids`
		// luisteren, dan sprong de uitlijnstand dicht zodra het bewaren zijn
		// antwoord terugstuurde — middenin het slepen.
		const bewaard = untrack(() => grids.find((g) => g.id === id)?.alignment ?? null);
		hoeken =
			bewaard && bewaard.length === 4
				? bewaard.map((p) => ({ x: p.x, y: p.y }))
				: STANDAARD.map((p) => ({ ...p }));
		// Nog nooit uitgelijnd? Dan is dát de eerste handeling.
		uitlijnen = bewaard === null;
		aangewezen = null;
		bewaarFout = null;
	});

	let bewaartimer: ReturnType<typeof setTimeout> | null = null;

	function bewaarUitlijning() {
		if (openId === null) return;
		// Slepen vuurt bij elke los-gelaten hoek; even wachten scheelt vier
		// schrijfrondes naar de database bij één keer uitlijnen.
		if (bewaartimer) clearTimeout(bewaartimer);
		const id = openId;
		const punten = hoeken.map((p) => ({ x: p.x, y: p.y }));
		bewaartimer = setTimeout(async () => {
			try {
				const response = await fetch(`/api/library/testgrids/${id}/alignment`, {
					method: 'PUT',
					headers: headers(true),
					body: JSON.stringify({ corners: punten })
				});
				if (!response.ok) {
					bewaarFout = 'De uitlijning kon niet bewaard worden.';
					return;
				}
				bewaarFout = null;
				const bijgewerkt: Grid = await response.json();
				grids = grids.map((g) => (g.id === id ? bijgewerkt : g));
			} catch {
				bewaarFout = 'De uitlijning kon niet bewaard worden — geen verbinding.';
			}
		}, 400);
	}

	/**
	 * Projectieve afbeelding van het eenheidsvierkant naar de vier hoeken.
	 *
	 * Een affiene transformatie (schuiven, schalen, scheeftrekken) is niet
	 * genoeg: wie schuin boven het bord staat, fotografeert een trapezium. De
	 * standaardhomografie hieronder vangt dat wél.
	 */
	let afbeelding = $derived.by(() => {
		const [p0, p1, p2, p3] = hoeken;
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

	function naarFoto(u: number, v: number) {
		const m = afbeelding;
		const w = m.g * u + m.h * v + 1 || 1e-9;
		return [(m.a * u + m.b * v + m.c) / w, (m.d * u + m.e * v + m.f) / w];
	}

	/** Een cel als vierhoek in fotocoördinaten (0–1), perspectief en al. */
	function veelhoek(cell: Cell) {
		if (!grid || !box) return '';
		const u0 = (cell.x_mm - grid.origin_x_mm) / box.width;
		const v0 = (cell.y_mm - grid.origin_y_mm) / box.height;
		const u1 = u0 + cell.width_mm / box.width;
		const v1 = v0 + cell.height_mm / box.height;
		return [
			naarFoto(u0, v0),
			naarFoto(u1, v0),
			naarFoto(u1, v1),
			naarFoto(u0, v1)
		]
			.map(([x, y]) => `${x},${y}`)
			.join(' ');
	}

	function sleep(index: number, event: PointerEvent) {
		if (!podium) return;
		const doel = event.currentTarget as HTMLElement;
		doel.setPointerCapture(event.pointerId);
		const rect = podium.getBoundingClientRect();
		const beweeg = (e: PointerEvent) => {
			hoeken[index] = {
				x: Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width)),
				y: Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height))
			};
		};
		const stop = () => {
			doel.removeEventListener('pointermove', beweeg);
			doel.removeEventListener('pointerup', stop);
			bewaarUitlijning();
		};
		doel.addEventListener('pointermove', beweeg);
		doel.addEventListener('pointerup', stop);
	}

	function toets(index: number, event: KeyboardEvent) {
		const stap = event.shiftKey ? 0.02 : 0.004;
		const richting: Record<string, [number, number]> = {
			ArrowLeft: [-stap, 0],
			ArrowRight: [stap, 0],
			ArrowUp: [0, -stap],
			ArrowDown: [0, stap]
		};
		const d = richting[event.key];
		if (!d) return;
		event.preventDefault();
		hoeken[index] = {
			x: Math.min(1, Math.max(0, hoeken[index].x + d[0])),
			y: Math.min(1, Math.max(0, hoeken[index].y + d[1]))
		};
		bewaarUitlijning();
	}

	// ------------------------------------------------------------------ keuze

	function toggle(cell: Cell) {
		if (!canEdit || uitlijnen) return;
		const id = key(cell);
		picked = picked.includes(id) ? picked.filter((p) => p !== id) : [...picked, id];
	}

	let gekozenCellen = $derived(
		grid ? grid.cells.filter((c) => picked.includes(key(c))) : []
	);
	/** De vakjes waar al een preset uit gehaald is — het bewijs onder de kaart. */
	let gebruikteCellen = $derived(
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
				error = 'Foto opslaan mislukte.';
				return;
			}
			await load();
			photoStamp = Date.now();
			// Een verse foto ligt nog niet onder de overlay: dat is de eerste
			// handeling, dus zet hem meteen klaar.
			uitlijnen = true;
		} finally {
			busy = false;
		}
	}

	let gemaakt = $state<number | null>(null);

	async function makePresets() {
		if (!grid || picked.length === 0) return;
		busy = true;
		error = null;
		gemaakt = null;
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
				error = typeof data?.detail === 'string' ? data.detail : 'Preset maken mislukte.';
				return;
			}
			gemaakt = cells.length;
			picked = [];
			await Promise.all([load(), library.load()]);
		} finally {
			busy = false;
		}
	}
</script>

<div class="resultaat">
	<div class="kop">
		<h2 class="titel">Stap 3 en 4 — foto en preset</h2>
		{#if grids.length}
			<select class="picker" bind:value={openId} aria-label="Kies een testraster">
				<option value={null}>Kies een raster…</option>
				{#each grids as g (g.id)}
					<!-- Datum erbij: wie drie proeven op hetzelfde materiaal heeft
					     gedaan, ziet anders drie identieke regels. -->
					<option value={g.id}>
						{datum(g.created_at)} · {g.material_name ?? 'geen materiaal'} · {g.operation}
						{g.photo_path ? '· met foto' : '· wacht op foto'}
					</option>
				{/each}
			</select>
		{/if}
	</div>

	{#if grids.length === 0}
		<p class="muted">
			Nog geen testrasters. Zodra je er hierboven een tekent en brandt, kun je hem hier
			fotograferen en het beste vakje aanwijzen.
		</p>
	{/if}

	{#if error}<p class="melding fout" role="alert">{error}</p>{/if}
	{#if gemaakt}
		<p class="melding goed" role="status">
			{gemaakt} preset{gemaakt === 1 ? '' : 's'} opgeslagen bij
			{grid?.material_name ?? 'dit materiaal'}. Je vindt ze in de materiaalbibliotheek.
		</p>
	{/if}

	{#if grid && box}
		{#if !grid.photo_path}
			<!-- Geen foto: dan geen raster van lege vakjes over het niets. Zeg wat
			     er moet gebeuren en hoe je het met de telefoon doet. -->
			<div class="geenfoto">
				<p class="waarom">
					<strong>Brand dit raster en fotografeer het bord.</strong>
					Recht van boven, het hele bord in beeld — de hoeken lijn je hierna zelf uit.
				</p>
				{#if canEdit}
					<label class="btn primary groot file">
						Foto toevoegen
						<input type="file" accept="image/*" capture="environment" onchange={uploadPhoto} />
					</label>
				{/if}
				<p class="muted">
					Of pak je telefoon: open OpenKerf daarop en dit raster staat onder
					“Testraster fotograferen”.
				</p>
			</div>
		{:else}
			<div class="podium" bind:this={podium}>
				<img
					src="/api/library/testgrids/{grid.id}/photo?v={photoStamp}"
					alt="Foto van het gebrande raster"
				/>

				<svg viewBox="0 0 1 1" preserveAspectRatio="none" class:uitlijnen>
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
								tabindex={uitlijnen ? -1 : 0}
								aria-label="Rij {cell.row + 1}, kolom {cell.column + 1} — {celtekst(cell)}"
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
					{#if uitlijnen}
						<polygon
							class="kader"
							points={hoeken.map((p) => `${p.x},${p.y}`).join(' ')}
						/>
					{/if}
				</svg>

				{#if uitlijnen}
					{#each hoeken as punt, i (i)}
						<button
							class="hoek"
							style="left: {punt.x * 100}%; top: {punt.y * 100}%"
							aria-label="Hoek {HOEKNAAM[i]} verslepen"
							onpointerdown={(e) => sleep(i, e)}
							onkeydown={(e) => toets(i, e)}
						><span></span></button>
					{/each}
				{/if}

				<!-- Welke instelling ligt er onder je vinger? Zonder dit wijs je een
				     vakje aan zonder te weten wat je kiest. -->
				<div class="aflezing mono" aria-live="polite">
					{#if uitlijnen}
						Sleep de vier hoeken naar de hoeken van het gebrande raster
					{:else if aangewezen}
						rij {aangewezen.row + 1}, kolom {aangewezen.column + 1} · {celtekst(aangewezen)}
					{:else}
						Tik het vakje aan dat het beste uitpakte
					{/if}
				</div>
			</div>

			<div class="onderbalk">
				<button
					class="btn"
					aria-pressed={uitlijnen}
					onclick={() => {
						uitlijnen = !uitlijnen;
						if (!uitlijnen) bewaarUitlijning();
					}}
				>{uitlijnen ? 'Uitlijnen klaar' : 'Overlay uitlijnen'}</button>

				{#if canEdit}
					<label class="btn file">
						Andere foto
						<input type="file" accept="image/*" capture="environment" onchange={uploadPhoto} />
					</label>
				{/if}

				<div class="keuze">
					{#if gekozenCellen.length}
						{#each gekozenCellen as cell (key(cell))}
							<button
								class="chip mono"
								onclick={() => toggle(cell)}
								aria-label="Rij {cell.row + 1}, kolom {cell.column + 1}, {celtekst(cell)}: keuze ongedaan maken"
							>rij {cell.row + 1}, kol {cell.column + 1} · {celtekst(cell)} ×</button>
						{/each}
					{:else}
						<span class="muted">Nog geen vakje gekozen</span>
					{/if}
				</div>

				{#if canEdit}
					<button
						class="btn primary"
						disabled={busy || picked.length === 0 || grid.material_id === null}
						onclick={makePresets}
					>
						{#if busy}
							Bezig…
						{:else if picked.length}
							Preset maken van {picked.length} vakje{picked.length === 1 ? '' : 's'}
						{:else}
							Preset maken
						{/if}
					</button>
				{/if}
			</div>

			{#if bewaarFout}<p class="melding fout" role="alert">{bewaarFout}</p>{/if}

			{#if gebruikteCellen.length}
				<!-- Gat M4: de herkomst zei "rij 2, kolom 3" en op de foto was niets
				     gemarkeerd. Nu de uitlijning bewaard is, kan dezelfde overlay
				     het vakje aanwijzen — hier door het op te lichten, en in de
				     bibliotheek doordat de foto met ?cell= de rand meegebrand
				     krijgt. -->
				<div class="herkomst">
					<span class="muted">Werd een preset:</span>
					{#each gebruikteCellen as cell (key(cell))}
						<button
							class="chip bewijs mono"
							onpointerenter={() => (aangewezen = cell)}
							onpointerleave={() => (aangewezen = null)}
							onfocus={() => (aangewezen = cell)}
							onblur={() => (aangewezen = null)}
							onclick={() => (aangewezen = cell)}
						>rij {cell.row + 1}, kol {cell.column + 1} · {celtekst(cell)}</button>
					{/each}
					<span class="muted">— aanwijzen licht het vakje op de foto op.</span>
				</div>
			{/if}

			{#if grid.material_id === null}
				<p class="melding waarschuwing">
					Dit raster hoort bij geen materiaal, dus er kan geen preset uit. Koppel een
					materiaal bij het genereren van het volgende raster.
				</p>
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
	.kop { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; }
	.titel {
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
	.waarom { margin: 0; max-width: 44ch; font-size: var(--text-sm); color: var(--text-1); }

	.podium {
		position: relative;
		/* Krimpen tot de foto: anders liggen de hoeken deels in de grijze
		   letterbox naast het beeld. */
		width: fit-content;
		margin-inline: auto;
		/* Slepen mag geen tekst selecteren: dat kleurt het halve venster blauw. */
		user-select: none;
		-webkit-user-select: none;
		border-radius: var(--radius-card);
		overflow: hidden;
		background: var(--surface-2);
		box-shadow: var(--lift-1);
		/* De actiebalk moet in beeld blijven: een foto die het hele venster vult
		   duwt "Preset maken" onder de vouw, en dan eindigt de flow nergens. */
		max-height: 46vh;
		display: grid;
		place-items: center;
	}
	.podium img { display: block; max-width: 100%; max-height: 46vh; }
	.podium svg { position: absolute; inset: 0; width: 100%; height: 100%; }
	.podium svg.uitlijnen { pointer-events: none; }

	/* Deze SVG meet in eenheden van 0 tot 1 en wordt naar honderden pixels
	   uitgerekt. Elke rand krijgt daarom non-scaling-stroke, en er staat geen
	   tekst, straal of schaduw in. Zie DESIGN-SYSTEM, "SVG die in millimeters
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
	/* Aanwijzen in de herkomstregel licht het vakje op de foto op: dat is de
	   hele belofte van "rij 2, kolom 3" — dat je hem terugvindt. */
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
	.kader {
		fill: none;
		stroke: var(--accent);
		stroke-width: 2;
		stroke-dasharray: 6 4;
		vector-effect: non-scaling-stroke;
	}

	/* 44px raakdoel met een kleine punt erin: je vinger moet erbij kunnen, je
	   oog moet zien waar de hoek precies ligt. */
	.hoek {
		position: absolute;
		width: var(--greep);
		height: var(--greep);
		margin: calc(var(--greep) / -2) 0 0 calc(var(--greep) / -2);
		border-radius: var(--radius-dot);
		background: color-mix(in srgb, var(--accent) 22%, transparent);
		border: 1px solid var(--accent);
		display: grid;
		place-items: center;
		cursor: grab;
		touch-action: none;
	}
	.hoek span {
		width: 8px;
		height: 8px;
		border-radius: var(--radius-dot);
		background: var(--accent);
	}
	.hoek:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

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
	.keuze { display: flex; gap: var(--space-1); flex-wrap: wrap; flex: 1; min-width: 8rem; }
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
	/* Zonder deze regel wint de algemene hover van .primary: de knop werd bij
	   aanwijzen lichtgrijs met witte tekst. Zelfde specificiteit, later in de
	   stylesheet — een klassieke. */
	.btn.primary:hover:not(:disabled) {
		background: color-mix(in srgb, var(--accent) 88%, var(--text-1));
	}
	/* Een uitgeschakelde primaire knop mag er niet uitzien als een knop die het
	   doet: 45% accent leest in het donkere thema nog steeds als "klik mij". */
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
	.btn.groot { min-height: 48px; padding: 12px 20px; font-size: var(--text-md); }
	.btn.file { cursor: pointer; display: inline-grid; place-items: center; }
	.btn.file input { position: absolute; width: 0; height: 0; opacity: 0; }

	.melding {
		margin: 0;
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-field);
		font-size: var(--text-xs);
	}
	.melding.fout { background: color-mix(in srgb, var(--danger-solid) 14%, transparent); }
	.melding.goed {
		background: color-mix(in srgb, var(--ok) 14%, transparent);
		border-left: 3px solid var(--ok);
	}
	.melding.waarschuwing {
		background: color-mix(in srgb, var(--warn-solid) 12%, transparent);
		border-left: 3px solid var(--warn-solid);
	}

	@media (max-width: 720px) {
		.onderbalk .btn { flex: 1; }
	}
</style>
