<script lang="ts">
	import { OPERATIONS, type LibraryStore } from '$lib/library.svelte';
	import NumberField from './NumberField.svelte';

	let {
		materialId = null,
		thicknessMm = null,
		library,
		canEdit = false,
		onGenerated
	}: {
		/** Voorgekozen materiaal: van het vel waarop je werkt, of van de kaart
		 *  waar je vandaan komt. */
		materialId?: number | null;
		/** De dikte van dat vel. Een raster gaat over één plaat, en die ligt al
		 *  in de machine — dan is dit getal geen vraag meer. */
		thicknessMm?: number | null;
		library: LibraryStore;
		canEdit?: boolean;
		onGenerated?: (gridId: number) => void;
	} = $props();

	// Kom je vanuit een materiaal, dan staat dat materiaal al ingevuld.
	$effect(() => {
		if (materialId === null) return;
		form.material_id = materialId;
	});
	// En de dikte van het vel erbij: het raster gaat over de plaat die in de
	// machine ligt, dus die twee velden hoeven niet opnieuw ingevuld.
	$effect(() => {
		if (thicknessMm === null) return;
		form.thickness_mm = String(thicknessMm);
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

	let busy = $state(false);
	// Het voorbeeld ververst elke 250 ms; dat mag de hoofdknop niet uitzetten.
	let bezigVoorbeeld = $state(false);
	let error = $state<string | null>(null);
	let gelukt = $state<{ id: number; cellen: number } | null>(null);
	let preview = $state<{ plan: Record<string, number>; cells: Cell[] } | null>(null);

	let form = $state({
		material_id: null as number | null,
		caption: '',
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

	function body(metOpschrift = false) {
		const uit: Record<string, unknown> = {
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
		// De planningsroute kent "caption" niet; alleen het bord krijgt hem mee.
		if (metOpschrift) uit.caption = form.caption.trim();
		return uit;
	}

	async function send(path: string, metOpschrift = false, stil = false) {
		if (stil) bezigVoorbeeld = true;
		else busy = true;
		error = null;
		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			const token =
				typeof localStorage === 'undefined' ? '' : (localStorage.getItem('openkerf.token') ?? '');
			if (token) headers.Authorization = `Bearer ${token}`;
			const response = await fetch(path, {
				method: 'POST',
				headers,
				body: JSON.stringify(body(metOpschrift))
			});
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
			if (stil) bezigVoorbeeld = false;
			else busy = false;
		}
	}

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
	}

	let suggestedFrom = $state<number | null>(null);

	// Live meekijken. Een voorbeeld achter een knop is geen voorbeeld: je ziet
	// pas wat je instelt nadat je besloten hebt dat je het wilt zien.
	let timer: ReturnType<typeof setTimeout> | null = null;
	$effect(() => {
		void [
			form.operation, form.speed_min, form.speed_max, form.power_min,
			form.power_max, form.speed_steps, form.power_steps, form.cell_mm,
			form.gap_mm, form.origin_x_mm, form.origin_y_mm
		];
		if (timer) clearTimeout(timer);
		timer = setTimeout(async () => {
			preview = await send('/api/library/testgrids/preview', false, true);
		}, 250);
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

	/**
	 * Hoe zwaar een vakje verbrandt: veel vermogen en weinig snelheid geven de
	 * diepste snede. Dat is geen natuurkunde maar een leesbaar verloop — het
	 * voorbeeld moet je léren hoe je het bord straks leest, met de zwaarste hoek
	 * rechtsboven.
	 *
	 * Logaritmisch en daarna uitgerekt over het hele bereik: de verhouding
	 * vermogen/snelheid loopt over een raster al snel een factor tien uiteen, en
	 * lineair blijft dan alleen de bovenste rij zichtbaar donker.
	 */
	let brandschaal = $derived.by(() => {
		if (!preview) return { laag: 0, hoog: 1 };
		const scores = preview.cells.map(
			(c) => Math.log(c.power_percent / Math.max(0.001, c.speed_mm_s))
		);
		const laag = Math.min(...scores);
		const hoog = Math.max(...scores);
		return { laag, hoog: hoog > laag ? hoog : laag + 1 };
	});

	function brand(cell: Cell) {
		const score = Math.log(cell.power_percent / Math.max(0.001, cell.speed_mm_s));
		const t = (score - brandschaal.laag) / (brandschaal.hoog - brandschaal.laag);
		// Niet helemaal tot nul: ook het lichtste vakje is een snede in hout.
		return Math.max(0, Math.min(1, 0.12 + 0.88 * t));
	}

	// Het voorbeeld tekenen we in échte pixels in plaats van in millimeters:
	// een SVG met een mm-viewBox maakt van elke 11px-label een reus van 11mm.
	const VOORBEELD_PX = 208;
	let schaal = $derived(preview ? VOORBEELD_PX / Math.max(1, preview.plan.width_mm) : 1);
	let celPx = $derived(preview ? preview.plan.cell_mm * schaal : 0);
	let gatPx = $derived(preview ? preview.plan.gap_mm * schaal : 0);
	// Bij meer dan acht stappen wordt elk label onleesbaar; dan alleen de randen.
	// Een label van elf pixels past niet in een vakje van twintig; dan alleen de
	// twee randwaarden, want die dragen het bereik.
	let toonAlleLabels = $derived(
		snelheden.length <= 8 && vermogens.length <= 8 && celPx >= 30
	);

	function labelbaar(reeks: number[], i: number) {
		return toonAlleLabels || i === 0 || i === reeks.length - 1;
	}

	let geenMateriaal = $derived(form.material_id === null);
	let stap = $derived(gelukt ? 2 : 1);

	async function generate() {
		gelukt = null;
		const grid = await send('/api/library/testgrids', true);
		if (grid) {
			gelukt = { id: grid.id, cellen: grid.cells?.length ?? 0 };
			onGenerated?.(grid.id);
		}
	}
</script>

<div class="wizard">
	<!-- De wizard is de didactische kern van de app: hij vertelt waar je bent en
	     wat er nog komt, ook als stap 3 pas naast de machine gebeurt. -->
	<ol class="stappen" aria-label="Stappen van de testrasterflow">
		<li class:nu={stap === 1}><span class="nr">1</span>Instellen</li>
		<li class:nu={stap === 2}><span class="nr">2</span>Branden</li>
		<li><span class="nr">3</span>Fotograferen</li>
		<li><span class="nr">4</span>Beste vakje → preset</li>
	</ol>

	{#if !canEdit}
		<p class="muted">Een testraster genereren vereist een token.</p>
	{:else}
		<p class="lead">
			Je brandt een bord met vakjes: <strong>vermogen loopt naar rechts op</strong>,
			<strong>snelheid naar beneden</strong>. Straks fotografeer je het bord — met de telefoon
			naast de machine kan ook — en tik je het vakje aan dat het beste uitpakte. Daar maakt
			OpenKerf een preset van.
		</p>

		<div class="werkbank">
			<div class="grid">
				<label class="veld">
					<span class="naam">Materiaal</span>
					<select bind:value={form.material_id}>
						<option value={null}>— geen —</option>
						{#each library.materials as material (material.id)}
							<option value={material.id}>{material.name}</option>
						{/each}
					</select>
				</label>
				<label class="veld">
					<span class="naam">Bewerking</span>
					<select bind:value={form.operation}>
						{#each OPERATIONS as op (op.value)}
							<option value={op.value}>{op.label}</option>
						{/each}
					</select>
				</label>

				{#if geenMateriaal}
					<!-- Vóór het hout eraan gaat, niet erna: zonder materiaal kan er
					     later geen preset uit dit bord komen, en dat is de hele reden
					     dat je het brandt. -->
					<p class="waarschuwing" role="status">
						<strong>Kies een materiaal.</strong> Een preset is een uitspraak over déze laser
						op dít materiaal — zonder materiaal levert het gebrande bord straks niets op.
					</p>
				{/if}

				<NumberField label="Dikte" unit="mm" step={0.5} min={0} bind:value={form.thickness_mm} />
				<NumberField label="Vakje" unit="mm" step={1} min={1} bind:value={form.cell_mm} />

				<NumberField label="Snelheid van" unit="mm/s" step={1} min={0} bind:value={form.speed_min} />
				<NumberField label="tot" unit="mm/s" step={1} min={0} bind:value={form.speed_max} />
				<NumberField label="Vermogen van" unit="%" step={5} min={0} max={100} bind:value={form.power_min} />
				<NumberField label="tot" unit="%" step={5} min={0} max={100} bind:value={form.power_max} />

				<NumberField label="Stappen snelheid" step={1} min={2} bind:value={form.speed_steps} />
				<NumberField label="Stappen vermogen" step={1} min={2} bind:value={form.power_steps} />
				<NumberField label="Tussenruimte" unit="mm" step={1} min={0} bind:value={form.gap_mm} />
				<NumberField label="Start X" unit="mm" step={5} min={0} bind:value={form.origin_x_mm} />
				<NumberField label="Start Y" unit="mm" step={5} min={0} bind:value={form.origin_y_mm} />

				<label class="veld breed">
					<span class="naam">Opschrift op het bord</span>
					<input
						type="text"
						bind:value={form.caption}
						maxlength="48"
						placeholder="bijv. proef achterkant"
					/>
					<span class="hint">
						Wordt mee gegraveerd, met materiaal, dikte en datum erachter. Een bord zonder
						opschrift is over twee weken een raadselachtig stuk hout.
					</span>
				</label>
			</div>

			{#if preview}
				<aside class="preview" aria-label="Voorbeeld van het bord">
					<div class="figures">
						<span class="mono">{preview.cells.length} vakjes</span>
						<span class="mono">{preview.plan.width_mm} × {preview.plan.height_mm} mm</span>
					</div>

					<!-- Het bord zoals het eruitkomt: donkerder = meer verbranding, en
					     de waarden staan erlangs waar ze ook op het hout komen. -->
					<div class="bord" style="--cel: {celPx}px; --gat: {gatPx}px;">
						<div class="hoek"></div>
						<div class="koplabels">
							{#each vermogens as v, i (v)}
								<span class="as mono">{labelbaar(vermogens, i) ? `${v}%` : ''}</span>
							{/each}
						</div>
						<div class="zijlabels">
							{#each snelheden as v, i (v)}
								<span class="as mono">{labelbaar(snelheden, i) ? v : ''}</span>
							{/each}
						</div>
						<div
							class="vakjes"
							style="grid-template-columns: repeat({vermogens.length}, var(--cel));"
						>
							{#each preview.cells as cell (`${cell.row}-${cell.column}`)}
								<span
									class="vakje"
									style="--brand: {brand(cell)}"
									title="{cell.speed_mm_s} mm/s bij {cell.power_percent}%"
								></span>
							{/each}
						</div>
					</div>

					<p class="legenda">
						Rijen: snelheid in mm/s. Kolommen: vermogen. Donkerder is meer verbranding —
						rechtsboven gaat het diepst.
					</p>
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

		{#if error}<p class="error" role="alert">{error}</p>{/if}

		{#if gelukt}
			<p class="gelukt" role="status">
				<strong>Raster #{gelukt.id} staat op het bed</strong> — {gelukt.cellen} vakjes, als
				één groep in je ontwerp. Start de job om het te branden; kom daarna terug voor
				stap 3.
			</p>
		{/if}

		<div class="actions">
			<button class="btn" disabled={busy} onclick={suggest}>Bereik voorstellen</button>
			<button class="btn primary" disabled={busy || !preview} onclick={generate}>
				{#if busy}
					Bezig…
				{:else if preview}
					Raster tekenen — {preview.cells.length} vakjes, {preview.plan.width_mm} × {preview.plan.height_mm} mm
				{:else}
					Raster tekenen
				{/if}
			</button>
		</div>
	{/if}
</div>

<style>
	.wizard { display: grid; gap: var(--space-3); }

	.stappen {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.stappen li {
		display: flex;
		align-items: center;
		gap: var(--space-1h);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.stappen li + li::before {
		content: '';
		width: 12px;
		height: 1px;
		background: var(--line);
		margin-right: var(--space-1h);
	}
	.stappen .nr {
		display: grid;
		place-items: center;
		width: 18px;
		height: 18px;
		border-radius: var(--radius-dot);
		border: 1px solid var(--line);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
	}
	.stappen li.nu { color: var(--text-1); font-weight: 600; }
	.stappen li.nu .nr {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
	}

	.lead { margin: 0; font-size: var(--text-sm); color: var(--text-1); max-width: 62ch; }
	.muted { color: var(--text-2); margin: 0; font-size: var(--text-xs); }

	.grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-2) var(--space-3);
		align-content: start;
	}
	.veld { display: grid; gap: 4px; }
	.veld.breed { grid-column: 1 / -1; }
	.naam { font-size: var(--text-xs); color: var(--text-2); }
	.hint { font-size: var(--text-xs); color: var(--text-2); }
	select, input[type='text'] {
		font: inherit;
		font-size: var(--text-sm);
		width: 100%;
		box-sizing: border-box;
		padding: 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}

	.waarschuwing {
		grid-column: 1 / -1;
		margin: 0;
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-field);
		border-left: 3px solid var(--warn-solid, var(--warn));
		background: color-mix(in srgb, var(--warn-solid, var(--warn)) 12%, transparent);
		font-size: var(--text-xs);
		color: var(--text-1);
	}

	/* Instellen en zien wat je instelt, naast elkaar. Onder 720px stapelt het. */
	.werkbank {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: var(--space-4);
		align-items: start;
	}
	@media (max-width: 720px) {
		.werkbank { grid-template-columns: 1fr; }
		.grid { grid-template-columns: 1fr; }
	}

	.preview {
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		padding: var(--space-3);
		background: var(--surface-1);
		box-shadow: var(--lift-1);
	}
	.figures {
		display: flex;
		justify-content: space-between;
		gap: var(--space-3);
		font-size: var(--text-xs);
		color: var(--text-2);
		margin-bottom: var(--space-2);
	}

	/* Het voorbeeld staat in pixels, niet in millimeters: labels binnen een
	   mm-viewBox worden factor tien te groot. Zie DESIGN-SYSTEM v3. */
	.bord {
		display: grid;
		grid-template-columns: auto auto;
		grid-template-rows: auto auto;
		gap: 4px;
	}
	.koplabels, .zijlabels { display: grid; gap: var(--gat); }
	.koplabels { grid-auto-flow: column; grid-auto-columns: var(--cel); }
	.zijlabels { grid-auto-rows: var(--cel); }
	.as {
		font-size: var(--text-xs);
		color: var(--text-2);
		display: grid;
		place-items: center;
		overflow: hidden;
	}
	.zijlabels .as { justify-items: end; padding-right: 2px; }
	.vakjes { display: grid; gap: var(--gat); }
	/* Het bord is hout en de snede is roet: dezelfde tinten die de
	   materiaalkaart gebruikt, zodat het voorbeeld léést als het bord dat
	   straks op tafel ligt in plaats van als een staafdiagram. */
	.vakje {
		width: var(--cel);
		height: var(--cel);
		background: color-mix(in srgb, var(--void) calc(var(--brand) * 88%), var(--mat-hout));
	}
	.vakjes {
		padding: var(--space-1);
		background: var(--mat-hout);
		border-radius: var(--radius-field);
	}
	.legenda {
		margin: var(--space-2) 0 0;
		max-width: 24ch;
		font-size: var(--text-xs);
		color: var(--text-2);
	}

	/* De knop van stap 1 hoort in beeld te blijven. In een venster van 80vh met
	   twaalf velden erboven verdween hij onder de vouw, en dan lijkt de wizard
	   doodlopend. */
	.actions {
		position: sticky;
		bottom: 0;
		z-index: 1;
		display: flex;
		gap: var(--space-2);
		flex-wrap: wrap;
		margin: 0 calc(-1 * var(--space-4));
		padding: var(--space-3) var(--space-4);
		background: var(--surface-1);
		border-top: 1px solid var(--line);
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
	.btn.primary {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
		flex: 1;
		min-width: 16rem;
	}
	.error, .gelukt {
		margin: 0;
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-field);
		font-size: var(--text-xs);
	}
	.error { background: color-mix(in srgb, var(--danger-solid, var(--danger)) 14%, transparent); }
	.gelukt {
		background: color-mix(in srgb, var(--ok) 14%, transparent);
		border-left: 3px solid var(--ok);
	}
</style>
