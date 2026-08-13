<script lang="ts">
	import { untrack } from 'svelte';
	import Dialog from './Dialog.svelte';
	import FontPicker from './FontPicker.svelte';
	import GeneratorPreview from './GeneratorPreview.svelte';
	import NumberField from './NumberField.svelte';

	import type { Voorbeeld } from './GeneratorPreview.svelte';

	let {
		open = $bindable(),
		hasSelection = false,
		selectedIds = [],
		busy = false,
		onGenerate
	}: {
		open: boolean;
		hasSelection?: boolean;
		/** Wat er herhaald moet worden. Herhalen en cirkel kunnen zonder deze
		 *  lijst geen echt voorbeeld tonen; dan valt het beeld terug op de
		 *  schets die alleen de velden uitlegt. */
		selectedIds?: string[];
		busy?: boolean;
		onGenerate: (
			what: string,
			body: Record<string, unknown>
		) => Promise<{ error?: string | null; notice?: string | null }>;
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
		lid: true,
		spread: true
	});
	let qr = $state({ text: '', size_mm: '30' });
	let bar = $state({ text: '', kind: 'code128', width_mm: '60', height_mm: '20' });
	let arc = $state({
		text: '',
		cx_mm: '100',
		cy_mm: '100',
		radius_mm: '40',
		font_size_mm: '10',
		inside: false,
		// De API kende `font` al; alleen dit venster vroeg er nooit naar, dus
		// kwam elke boogtekst er in de standaardletter uit. Zelfde kiezer als
		// het tekstvenster — met voorbeeld in de letter zelf.
		font: '',
		fontNaam: ''
	});

	// De typen die python-barcode aankan en die op een laser zinnig zijn.
	const BARCODES = ['code128', 'code39', 'ean13', 'ean8', 'upca', 'itf', 'issn'];

	// "Raster" heette hetzelfde als het testraster, en dat is iets heel anders.
	// Herhalen zegt wat het doet.
	const TABS: { id: Tab; label: string; needsSelection: boolean; icon: string }[] = [
		{
			id: 'grid',
			label: 'Herhalen',
			needsSelection: true,
			icon: 'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z'
		},
		{
			id: 'radial',
			label: 'Cirkel',
			needsSelection: true,
			icon: 'M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16zM12 4v3M20 12h-3M12 20v-3M4 12h3'
		},
		{ id: 'polygon', label: 'Veelhoek', needsSelection: false, icon: 'M12 3l8 6-3 10H7L4 9z' },
		{
			id: 'box',
			label: 'Doos',
			needsSelection: false,
			icon: 'M3 8l9-5 9 5-9 5zM3 8v8l9 5 9-5V8'
		},
		{
			id: 'qrcode',
			label: 'QR-code',
			needsSelection: false,
			icon: 'M3.5 3.5h6v6h-6zM14.5 3.5h6v6h-6zM3.5 14.5h6v6h-6zM14.5 15h2v2h-2zM19 19h1.5v1.5H19'
		},
		{
			id: 'barcode',
			label: 'Streepjescode',
			needsSelection: false,
			icon: 'M4 5v14M7.5 5v14M10 5v14M14 5v14M17 5v14M20 5v14'
		},
		{
			id: 'arctext',
			label: 'Boogtekst',
			needsSelection: false,
			icon: 'M4 16a8 8 0 0 1 16 0M8 12l.8-2.4M12 10.6V8M16 12l-.8-2.4'
		}
	];

	let current = $derived(TABS.find((t) => t.id === tab)!);
	/** De velden van het zichtbare tabblad, voor de schets ernaast. */
	let huidig = $derived(
		(
			{
				grid, radial, polygon, box, qrcode: qr, barcode: bar, arctext: arc
			} as Record<string, Record<string, unknown>>
		)[tab] ?? {}
	);
	let blocked = $derived(current.needsSelection && !hasSelection);

	let notice = $state<string | null>(null);
	/** De lettertypelade van de boogtekst; dicht tot je hem opent. */
	let letterOpen = $state(false);

	async function run(body: Record<string, unknown>) {
		notice = null;
		const outcome = await onGenerate(tab, body);
		error = outcome.error ?? null;
		notice = outcome.notice ?? null;
		// Blijft open als er iets te melden viel — een vel dat er stilzwijgend
		// bijkomt, is precies het soort verrassing dat je niet wilt.
		if (!error && !notice) open = false;
	}

	const n = (value: string) => Number(value);

	/**
	 * Wat er naar de server gaat — één plek, zodat de knop en het voorbeeld
	 * gegarandeerd hetzelfde vragen. Stonden ze los, dan kon het voorbeeld
	 * iets anders laten zien dan de knop maakt, en dat is precies het soort
	 * verschil dat niemand opmerkt tot er hout in de machine ligt.
	 */
	function opdracht(): Record<string, unknown> {
		if (tab === 'grid')
			return {
				columns: n(grid.columns), rows: n(grid.rows),
				gap_x_mm: n(grid.gap_x_mm), gap_y_mm: n(grid.gap_y_mm)
			};
		if (tab === 'radial')
			return {
				repeats: n(radial.repeats), radius_mm: n(radial.radius_mm), rotate: radial.rotate
			};
		if (tab === 'polygon')
			return {
				corners: n(polygon.corners), radius_mm: n(polygon.radius_mm),
				cx_mm: n(polygon.cx_mm), cy_mm: n(polygon.cy_mm),
				inner_radius_mm: polygon.inner.trim() === '' ? null : n(polygon.inner)
			};
		if (tab === 'box')
			return {
				width_mm: n(box.width_mm), depth_mm: n(box.depth_mm), height_mm: n(box.height_mm),
				thickness_mm: n(box.thickness_mm), finger_mm: n(box.finger_mm),
				kerf_mm: n(box.kerf_mm), lid: box.lid, spread: box.spread
			};
		if (tab === 'qrcode') return { text: qr.text.trim(), size_mm: n(qr.size_mm) };
		if (tab === 'barcode')
			return {
				text: bar.text.trim(), kind: bar.kind,
				width_mm: n(bar.width_mm), height_mm: n(bar.height_mm)
			};
		return {
			text: arc.text.trim(), cx_mm: n(arc.cx_mm), cy_mm: n(arc.cy_mm),
			radius_mm: n(arc.radius_mm), font_size_mm: n(arc.font_size_mm),
			inside: arc.inside, font: arc.font || null
		};
	}

	// ---------------------------------------------------------- het voorbeeld

	let voorbeeld = $state<Voorbeeld | null>(null);
	let voorbeeldFout = $state<string | null>(null);
	/**
	 * Valt er iets te tonen?
	 *
	 * Twee redenen van niet. Herhalen en cirkel hebben de gekozen elementen
	 * nodig; die vallen zonder terug op de schets in plaats van op iets
	 * verzonnens. En een QR-code zonder inhoud bestaat niet — daar wachten we
	 * op je eerste letter in plaats van bij elke opening van het venster een
	 * afwijzing op te halen die je zelf al kon zien aankomen.
	 */
	let voorbeeldbaar = $derived(
		(!current.needsSelection || selectedIds.length > 0) &&
			(tab !== 'qrcode' || qr.text.trim() !== '') &&
			(tab !== 'barcode' || bar.text.trim() !== '') &&
			(tab !== 'arctext' || arc.text.trim() !== '')
	);

	/**
	 * Welke velden een getal moeten bevatten voordat er iets te tekenen valt.
	 *
	 * Een veld waar je het getal net uit gewist hebt, is niet fout maar nog
	 * niet af. Stuurden we het toch op, dan leest `Number('')` als nul en komt
	 * er "finger_mm moet groter dan nul zijn" terug — de naam van een
	 * variabele, niet van een veld dat op het scherm "Vinger (mm)" heet. Zelf
	 * zien aankomen is korter dan het antwoord vertalen.
	 *
	 * De binnenstraal van de veelhoek staat er niet bij: leeg betekent daar
	 * "geen ster", en dat is een geldige keuze.
	 */
	const GETALVELDEN: Record<Tab, string[]> = {
		grid: ['columns', 'rows', 'gap_x_mm', 'gap_y_mm'],
		radial: ['repeats', 'radius_mm'],
		polygon: ['corners', 'radius_mm', 'cx_mm', 'cy_mm'],
		box: ['width_mm', 'depth_mm', 'height_mm', 'thickness_mm', 'finger_mm', 'kerf_mm'],
		qrcode: ['size_mm'],
		barcode: ['width_mm', 'height_mm'],
		arctext: ['cx_mm', 'cy_mm', 'radius_mm', 'font_size_mm']
	};
	let onaf = $derived(
		GETALVELDEN[tab].some((veld) => {
			const waarde = huidig[veld];
			return (
				typeof waarde !== 'string' ||
				waarde.trim() === '' ||
				!Number.isFinite(Number(waarde))
			);
		})
	);

	// Antwoorden kunnen elkaar inhalen: je typt door terwijl de vorige ronde
	// nog onderweg is. Alleen de laatste vraag mag het beeld nog zetten.
	let ronde = 0;

	async function haalVoorbeeld(mijn: number, what: string, body: Record<string, unknown>) {
		try {
			const token =
				typeof localStorage === 'undefined' ? '' : (localStorage.getItem('openkerf.token') ?? '');
			const response = await fetch('/api/design/generate/preview', {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					...(token ? { Authorization: `Bearer ${token}` } : {})
				},
				body: JSON.stringify({ ...body, what, ids: selectedIds })
			});
			const data = await response.json().catch(() => null);
			if (mijn !== ronde) return;
			if (!response.ok) {
				voorbeeldFout =
					typeof data?.detail === 'string' ? data.detail : 'Dit kan de engine niet tekenen.';
				return;
			}
			voorbeeldFout = null;
			// Alleen vervangen als er iets geldigs uitkwam; het laatste geldige
			// beeld laten staan is rustiger dan een gat laten vallen, en ook
			// eerlijker: dát is nog steeds wat je zou krijgen als je nu ophield
			// met typen.
			voorbeeld = data;
		} catch (e) {
			if (mijn === ronde) voorbeeldFout = `Netwerkfout: ${e instanceof Error ? e.message : e}`;
		}
	}

	let timer: ReturnType<typeof setTimeout> | null = null;
	// Alleen om te zien óf het tabblad veranderde. Met `untrack` omdat dit
	// geen abonnement mag worden: het staat buiten het effect.
	let vorigTabblad: Tab = untrack(() => tab);
	/**
	 * Meekijken tijdens het typen.
	 *
	 * Een voorbeeld achter een knop is geen voorbeeld: je ziet pas wat je
	 * instelt nadat je besloten hebt dat je het wilt zien. Dus bij elke
	 * wijziging, met 200 ms rust ertussen zodat er niet per aanslag gerekend
	 * wordt. Dit raakt `error` niet aan: dat blok onderaan het formulier hoort
	 * bij een mislukte handeling, niet bij een half getypt getal.
	 */
	$effect(() => {
		const what = tab;
		const body = opdracht();
		// Wat er nog onderweg is, telt niet meer: het hoort bij een vraag die
		// door deze ronde is ingehaald. Zonder dit kan een antwoord op de
		// vórige, nog geldige invoer de melding hieronder weer wegpoetsen.
		if (timer) clearTimeout(timer);
		const mijn = ++ronde;

		// Van tabblad wisselen laat geen vorm van het vorige tabblad achter:
		// dat zou een voorbeeld zijn van iets anders dan het formulier ernaast.
		if (what !== vorigTabblad) {
			vorigTabblad = what;
			voorbeeld = null;
			voorbeeldFout = null;
		}
		if (!open || !voorbeeldbaar) {
			voorbeeld = null;
			voorbeeldFout = null;
			return;
		}
		if (onaf) {
			voorbeeldFout = 'Nog niet compleet: vul de lege velden in.';
			return;
		}
		timer = setTimeout(() => haalVoorbeeld(mijn, what, body), 200);
		return () => {
			if (timer) clearTimeout(timer);
		};
	});

	/** "Panelen maken — 6 stuks, past op dit vel": de knop zegt wát er komt. */
	let knopStaart = $derived.by(() => {
		if (!voorbeeld || voorbeeldFout) return '';
		if (voorbeeld.what === 'box')
			return voorbeeld.sheets > 1
				? ` — ${voorbeeld.parts.length} op dit vel, ${voorbeeld.sheets} vellen`
				: ` — ${voorbeeld.parts.length} stuks, past op dit vel`;
		const b = voorbeeld.bounds;
		const maat = (v: number) => (v >= 100 ? v.toFixed(0) : v.toFixed(1));
		return ` — ${maat(b[2] - b[0])} × ${maat(b[3] - b[1])} mm`;
	});
</script>

<Dialog title="Generatoren" bind:open width="800px">
	<div class="tabs">
		{#each TABS as item (item.id)}
			<button class="tab" aria-pressed={tab === item.id} onclick={() => { tab = item.id; error = null; }}>
				<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
					<path d={item.icon} />
				</svg>
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
	{#if notice}
		<p class="notice">{notice}</p>
	{/if}

	<div class="werkbank">
	<div class="formulier">
	{#if tab === 'grid'}
		<p class="lead">
			De selectie in rijen en kolommen herhalen. De afstand is de ruimte <em>tussen</em>
			de vormen, want daar gaat de snede doorheen.
		</p>
		<div class="fields">
			<NumberField label="Kolommen" step={1} min={1} bind:value={grid.columns} />
			<NumberField label="Rijen" step={1} min={1} bind:value={grid.rows} />
			<NumberField label="Ruimte X" unit="mm" step={0.5} bind:value={grid.gap_x_mm} />
			<NumberField label="Ruimte Y" unit="mm" step={0.5} bind:value={grid.gap_y_mm} />
		</div>
		<button class="go" disabled={blocked || busy} onclick={() => run(opdracht())}>
			{n(grid.columns) * n(grid.rows)} stuks maken{knopStaart}
		</button>
	{:else if tab === 'radial'}
		<p class="lead">De selectie rond een middelpunt herhalen.</p>
		<div class="fields">
			<NumberField label="Aantal" step={1} min={2} bind:value={radial.repeats} />
			<NumberField label="Straal" unit="mm" step={1} bind:value={radial.radius_mm} />
			<label class="check"><input type="checkbox" bind:checked={radial.rotate} /><span>Meedraaien</span></label>
		</div>
		<button class="go" disabled={blocked || busy} onclick={() => run(opdracht())}
			>Rondzetten{knopStaart}</button
		>
	{:else if tab === 'polygon'}
		<p class="lead">
			Een regelmatige veelhoek. Vul een binnenstraal in en het wordt een ster.
		</p>
		<div class="fields">
			<NumberField label="Hoeken" step={1} min={3} bind:value={polygon.corners} />
			<NumberField label="Straal" unit="mm" step={1} bind:value={polygon.radius_mm} />
			<NumberField label="Binnenstraal" unit="mm" step={1} bind:value={polygon.inner} />
			<NumberField label="Midden X" unit="mm" step={1} bind:value={polygon.cx_mm} />
			<NumberField label="Midden Y" unit="mm" step={1} bind:value={polygon.cy_mm} />
		</div>
		<button class="go" disabled={busy} onclick={() => run(opdracht())}
			>Tekenen{knopStaart}</button
		>
	{:else if tab === 'box'}
		<p class="lead">
			Losse panelen met vingerlassen. De maten zijn buitenmaten; de kerf wordt
			bij de tanden opgeteld omdat de laser aan beide kanten materiaal
			wegneemt. Past het niet op één vel, dan gaat de rest naar een volgend vel.
		</p>
		<div class="fields">
			<NumberField label="Breedte" unit="mm" step={1} bind:value={box.width_mm} />
			<NumberField label="Diepte" unit="mm" step={1} bind:value={box.depth_mm} />
			<NumberField label="Hoogte" unit="mm" step={1} bind:value={box.height_mm} />
			<NumberField label="Materiaaldikte" unit="mm" step={0.1} bind:value={box.thickness_mm} />
			<NumberField label="Vinger" unit="mm" step={1} bind:value={box.finger_mm} />
			<NumberField label="Kerf" unit="mm" step={0.05} bind:value={box.kerf_mm} />
			<label class="check"><input type="checkbox" bind:checked={box.lid} /><span>Met deksel</span></label>
			<label class="check">
				<input type="checkbox" bind:checked={box.spread} />
				<span>Verdelen over vellen als het niet past</span>
			</label>
		</div>
		<button class="go" disabled={busy} onclick={() => run(opdracht())}
			>Panelen maken{knopStaart}</button
		>
	{:else if tab === 'qrcode'}
		<p class="lead">
			Een QR-code als vlakken, niet als plaatje: gegraveerde bitmaps worden op
			hout vaak vaag, gevulde vierkanten niet.
		</p>
		<div class="fields">
			<label class="wide"><span>Inhoud</span><input type="text" placeholder="https://…" bind:value={qr.text} /></label>
			<NumberField label="Formaat" unit="mm" step={1} bind:value={qr.size_mm} />
		</div>
		<button class="go" disabled={busy || !qr.text.trim()} onclick={() => run(opdracht())}
			>Plaatsen{knopStaart}</button
		>
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
			<NumberField label="Breedte" unit="mm" step={1} bind:value={bar.width_mm} />
			<NumberField label="Hoogte" unit="mm" step={1} bind:value={bar.height_mm} />
		</div>
		<button class="go" disabled={busy || !bar.text.trim()} onclick={() => run(opdracht())}
			>Plaatsen{knopStaart}</button
		>
	{:else}
		<p class="lead">
			Tekst langs een boog, voor een rond bordje of een deksel. Let op: hierna is
			het een pad en geen tekst meer — de engine zou de tekst anders bij de
			eerstvolgende wijziging weer recht renderen en de boog wegpoetsen.
		</p>
		<div class="fields">
			<label class="wide"><span>Tekst</span><input type="text" placeholder="OPENKERF" bind:value={arc.text} /></label>
			<NumberField label="Midden X" unit="mm" step={1} bind:value={arc.cx_mm} />
			<NumberField label="Midden Y" unit="mm" step={1} bind:value={arc.cy_mm} />
			<NumberField label="Straal" unit="mm" step={1} bind:value={arc.radius_mm} />
			<NumberField label="Letterhoogte" unit="mm" step={0.5} bind:value={arc.font_size_mm} />
			<label class="check"><input type="checkbox" bind:checked={arc.inside} /><span>Onderlangs</span></label>
		</div>
		<!-- Ingeklapt tot je hem opent: de lijst is 200 lettertypen lang en duwde
		     de knop "Plaatsen" uit beeld (gemeten: van 725 naar 865 px). De
		     regel zegt wél welke letter er nu gekozen is, want anders is een
		     dichte lade hetzelfde als geen keuze. -->
		<div class="letterkeuze">
			<button class="letterregel" aria-expanded={letterOpen} onclick={() => (letterOpen = !letterOpen)}>
				<span>Lettertype</span>
				<strong>{arc.font ? arc.fontNaam || arc.font : 'Standaard'}</strong>
				<span class="pijl" aria-hidden="true">{letterOpen ? '▴' : '▾'}</span>
			</button>
			{#if letterOpen}
				<FontPicker bind:font={arc.font} bind:fontName={arc.fontNaam} sample={arc.text} />
			{/if}
		</div>
		<button class="go" disabled={busy || !arc.text.trim()} onclick={() => run(opdracht())}
			>Plaatsen{knopStaart}</button
		>
	{/if}
	</div>

	<!-- De vorm naast het formulier dat hem maakt. -->
	<GeneratorPreview soort={tab} waarden={huidig} {voorbeeld} fout={voorbeeldFout}>
		{#if current.needsSelection}
			Schets, niet op schaal
		{:else if !voorbeeldbaar}
			Typ iets, dan staat het hier
		{:else}
			Even rekenen…
		{/if}
	</GeneratorPreview>
	</div>
</Dialog>

<style>
	/* Instellen links, zien wat je instelt rechts. Onder 720px stapelt het. */
	.werkbank { display: grid; grid-template-columns: 1fr 210px; gap: var(--space-4); align-items: start; }
	.formulier { min-width: 0; }
	@media (max-width: 720px) { .werkbank { grid-template-columns: 1fr; } }

	.tabs {
		display: flex;
		gap: 2px;
		margin-bottom: var(--space-3);
		flex-wrap: wrap;
		border-bottom: 1px solid var(--line);
	}
	/* Tabbladen, geen pillen: dit is navigatie tussen formulieren. Met een
	   icoon erboven herken je de doos zonder te lezen. */
	.tab {
		display: grid;
		justify-items: center;
		gap: 2px;
		font-size: var(--text-xs);
		padding: var(--space-2) var(--space-3) var(--space-2);
		border: 0;
		border-bottom: 2px solid transparent;
		border-radius: 0;
		color: var(--text-2);
		background: none;
	}
	.tab:hover { color: var(--text-1); }
	.tab[aria-pressed='true'] {
		border-bottom-color: var(--accent);
		color: var(--accent);
		font-weight: 500;
	}
	.lead { margin: 0 0 var(--space-3); font-size: var(--text-xs); color: var(--text-2); line-height: 1.5; }
	.hint { margin: 0 0 var(--space-2); font-size: var(--text-xs); color: var(--warn); }
	.error { margin: 0 0 var(--space-2); font-size: var(--text-xs); color: var(--danger); }
	.notice { margin: 0 0 var(--space-2); font-size: var(--text-xs); color: var(--accent); }
	.fields {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-2) var(--space-3);
		margin-bottom: var(--space-4);
	}
	.fields label { display: grid; gap: 2px; font-size: var(--text-xs); color: var(--text-2); }
	.fields .wide { grid-column: 1 / -1; }
	.fields .check { display: flex; align-items: center; gap: 6px; align-self: end; }
	.letterkeuze { margin-bottom: var(--space-4); }
	.letterregel {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		width: 100%;
		min-height: 40px;
		padding: 8px var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-2);
		font-size: var(--text-xs);
		text-align: left;
	}
	.letterregel strong { flex: 1; color: var(--text-1); font-weight: 500; }
	.letterregel .pijl { color: var(--text-2); }
	.letterregel:hover { border-color: var(--accent); }
	input,
	select {
		font: inherit;
		width: 100%;
		padding: 8px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.check input { width: auto; }
	.go {
		width: 100%;
		padding: 8px 16px;
		border-radius: var(--radius-field);
		border: 1px solid var(--accent);
		background: var(--accent);
		color: var(--accent-ink);
		font-weight: 500;
	}
	.go:disabled { opacity: 0.45; cursor: not-allowed; }
</style>
