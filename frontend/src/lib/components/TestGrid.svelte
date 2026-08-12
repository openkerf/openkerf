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
	// Een vel kan een materiaal-id dragen dat niet meer bestaat, bijvoorbeeld
	// omdat het materiaal uit de bibliotheek verwijderd is. Zonder deze
	// terugval staat er een leeg keuzevak — geen "geen" — en bleef de
	// waarschuwing hieronder weg, want er stond wél iets in het veld. Alleen
	// controleren zodra de lijst binnen is: leeg betekent "nog niet geladen".
	$effect(() => {
		if (form.material_id === null || library.materials.length === 0) return;
		if (!library.materials.some((m) => m.id === form.material_id)) form.material_id = null;
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
		interval_mm: number | null;
		x_mm: number;
		y_mm: number;
		width_mm: number;
		height_mm: number;
	};

	/**
	 * De drie grootheden die je kunt aftasten (besluit B12).
	 *
	 * Twee ervan staan op de assen, de derde blijft vast. Passes staat er
	 * bewust niet bij: dat vermenigvuldigt de brandtijd van het hele bord.
	 */
	type As = 'speed' | 'power' | 'interval';
	const ASSEN: Record<As, { naam: string; eenheid: string; stap: number; max?: number }> = {
		speed: { naam: 'Snelheid', eenheid: 'mm/s', stap: 1 },
		power: { naam: 'Vermogen', eenheid: '%', stap: 5, max: 100 },
		interval: { naam: 'Interval', eenheid: 'mm', stap: 0.01, max: 5 }
	};
	/** Waar de lijnafstand iets betekent; bij snijden legt de kop één lijn. */
	const INTERVAL_BEWERKINGEN = ['graveren-raster'];

	let busy = $state(false);
	// Het voorbeeld ververst elke 250 ms; dat mag de hoofdknop niet uitzetten.
	let bezigVoorbeeld = $state(false);
	let error = $state<string | null>(null);
	let gelukt = $state<{ id: number; cellen: number } | null>(null);
	// De maten in het plan zijn getallen, row_axis/column_axis zijn woorden.
	type Plan = Record<string, number> & {
		row_axis?: As;
		column_axis?: As;
		/** Of de rijlabels links van het raster nog op het bed vallen. */
		label_room?: boolean;
		label_margin_mm?: number;
	};
	let preview = $state<{ plan: Plan; cells: Cell[] } | null>(null);

	let form = $state({
		material_id: null as number | null,
		caption: '',
		thickness_mm: '3',
		operation: 'snijden',
		row_axis: 'speed' as As,
		column_axis: 'power' as As,
		speed_min: '5',
		speed_max: '25',
		speed_steps: '4',
		power_min: '40',
		power_max: '80',
		power_steps: '4',
		interval_min: '0.05',
		interval_max: '0.3',
		interval_steps: '4',
		// De waarden van de grootheid die niet op een as staat.
		speed_mm_s: '15',
		power_percent: '60',
		interval_mm: '0.1',
		cell_mm: '8',
		gap_mm: '2',
		origin_x_mm: '10',
		origin_y_mm: '10'
	});

	/** Onder welke sleutel de vaste waarde van een grootheid naar de API gaat. */
	const VAST_VELD: Record<As, 'speed_mm_s' | 'power_percent' | 'interval_mm'> = {
		speed: 'speed_mm_s',
		power: 'power_percent',
		interval: 'interval_mm'
	};

	let intervalKan = $derived(INTERVAL_BEWERKINGEN.includes(form.operation));
	let assen = $derived([form.row_axis, form.column_axis] as As[]);
	let vasteAs = $derived(
		(['speed', 'power', 'interval'] as As[]).filter(
			(a) => !assen.includes(a) && (a !== 'interval' || intervalKan)
		)
	);

	/**
	 * Twee assen kunnen niet dezelfde grootheid zijn: kies je voor de rijen wat
	 * al in de kolommen staat, dan verhuist die naar de vrijgekomen plek. Dat is
	 * wat een gebruiker bedoelt met "omdraaien", en het scheelt een foutmelding.
	 */
	function kiesAs(welke: 'row_axis' | 'column_axis', nieuw: As) {
		const andere = welke === 'row_axis' ? 'column_axis' : 'row_axis';
		if (form[andere] === nieuw) form[andere] = form[welke];
		form[welke] = nieuw;
	}

	// Springt de bewerking terug naar snijden terwijl interval op een as staat,
	// dan bestaat die as niet meer. Zonder dit blijft het formulier fout.
	$effect(() => {
		if (intervalKan) return;
		if (form.row_axis === 'interval') kiesAs('row_axis', 'speed');
		if (form.column_axis === 'interval') kiesAs('column_axis', 'power');
	});

	function body(metOpschrift = false) {
		const uit: Record<string, unknown> = {
			material_id: form.material_id,
			thickness_mm: form.thickness_mm === '' ? null : Number(form.thickness_mm),
			operation: form.operation,
			row_axis: form.row_axis,
			column_axis: form.column_axis,
			cell_mm: Number(form.cell_mm),
			gap_mm: Number(form.gap_mm),
			origin_x_mm: Number(form.origin_x_mm),
			origin_y_mm: Number(form.origin_y_mm)
		};
		for (const as of ['speed', 'power', 'interval'] as As[]) {
			if (assen.includes(as)) {
				uit[`${as}_min`] = Number(form[`${as}_min`]);
				uit[`${as}_max`] = Number(form[`${as}_max`]);
				uit[`${as}_steps`] = Number(form[`${as}_steps`]);
			} else {
				uit[VAST_VELD[as]] = Number(form[VAST_VELD[as]]);
			}
		}
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
			form.operation, form.row_axis, form.column_axis,
			form.speed_min, form.speed_max, form.speed_steps, form.speed_mm_s,
			form.power_min, form.power_max, form.power_steps, form.power_percent,
			form.interval_min, form.interval_max, form.interval_steps, form.interval_mm,
			form.cell_mm, form.gap_mm, form.origin_x_mm, form.origin_y_mm
		];
		if (timer) clearTimeout(timer);
		timer = setTimeout(async () => {
			preview = await send('/api/library/testgrids/preview', false, true);
		}, 250);
		return () => {
			if (timer) clearTimeout(timer);
		};
	});

	const CEL_SLEUTEL: Record<As, 'speed_mm_s' | 'power_percent' | 'interval_mm'> = {
		speed: 'speed_mm_s',
		power: 'power_percent',
		interval: 'interval_mm'
	};

	/** De waarden waarop echt gebrand wordt — na afronding, in rasterorde. */
	function langsAs(richting: 'row' | 'column'): number[] {
		if (!preview) return [];
		const as: As =
			richting === 'row'
				? (preview.plan.row_axis ?? 'speed')
				: (preview.plan.column_axis ?? 'power');
		const gevonden = new Map<number, number>();
		for (const cell of preview.cells) {
			gevonden.set(cell[richting], cell[CEL_SLEUTEL[as]] as number);
		}
		return [...gevonden.entries()].sort((a, b) => a[0] - b[0]).map(([, v]) => v);
	}
	let rijwaarden = $derived(preview ? langsAs('row') : []);
	let kolomwaarden = $derived(preview ? langsAs('column') : []);

	/**
	 * Hoe zwaar een vakje verbrandt: veel vermogen, weinig snelheid en een klein
	 * interval geven de diepste inbranding. Dat is geen natuurkunde maar een
	 * leesbaar verloop — het voorbeeld moet je léren hoe je het bord straks
	 * leest, met de zwaarste hoek rechtsboven.
	 *
	 * Logaritmisch en daarna uitgerekt over het hele bereik: de verhouding loopt
	 * over een raster al snel een factor tien uiteen, en lineair blijft dan
	 * alleen de bovenste rij zichtbaar donker.
	 */
	function score(cell: Cell) {
		// Een leeg interval telt als 1: dan valt de factor weg in plaats van de
		// hele schaal naar nul te trekken.
		const interval = cell.interval_mm ?? 1;
		return Math.log(
			cell.power_percent / Math.max(0.001, cell.speed_mm_s * Math.max(0.001, interval))
		);
	}

	let brandschaal = $derived.by(() => {
		if (!preview) return { laag: 0, hoog: 1 };
		const scores = preview.cells.map(score);
		const laag = Math.min(...scores);
		const hoog = Math.max(...scores);
		return { laag, hoog: hoog > laag ? hoog : laag + 1 };
	});

	function brand(cell: Cell) {
		const t = (score(cell) - brandschaal.laag) / (brandschaal.hoog - brandschaal.laag);
		// Niet helemaal tot nul: ook het lichtste vakje is een snede in hout.
		return Math.max(0, Math.min(1, 0.12 + 0.88 * t));
	}

	/**
	 * Welke hoek het diepst gaat, uitgerekend in plaats van aangenomen.
	 *
	 * Zolang snelheid omlaag en vermogen naar rechts stonden was dat altijd
	 * rechtsboven. Met vrij te kiezen assen kan het elke hoek zijn — en een
	 * legenda die de verkeerde hoek noemt is erger dan geen legenda.
	 */
	let diepsteHoek = $derived.by(() => {
		if (!preview || preview.cells.length === 0) return null;
		const zwaarste = preview.cells.reduce((a, b) => (score(b) > score(a) ? b : a));
		const onder = zwaarste.row === rijwaarden.length - 1;
		const rechts = zwaarste.column === kolomwaarden.length - 1;
		// Nederlands zegt "rechtsboven", niet "bovenrechts".
		return `${rechts ? 'rechts' : 'links'}${onder ? 'onder' : 'boven'}`;
	});

	/** "0.05 mm", "60%", "12 mm/s" — de aswaarde zoals hij op het hout komt. */
	function toon(as: As, waarde: number | null | undefined) {
		if (waarde === null || waarde === undefined) return '';
		const eenheid = ASSEN[as].eenheid;
		return eenheid === '%' ? `${waarde}%` : `${waarde} ${eenheid}`;
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
		rijwaarden.length <= 8 && kolomwaarden.length <= 8 && celPx >= 30
	);

	function labelbaar(reeks: number[], i: number) {
		return toonAlleLabels || i === 0 || i === reeks.length - 1;
	}

	// "Geen materiaal" is niet hetzelfde als "het veld is leeg": een id dat niet
	// in de bibliotheek staat, levert straks net zo goed geen preset op. De
	// waarschuwing hoort dus ook dán te staan, en niet één frame later.
	let geenMateriaal = $derived(
		form.material_id === null ||
			(library.materials.length > 0 &&
				!library.materials.some((m) => m.id === form.material_id))
	);
	let stap = $derived(gelukt ? 2 : 1);

	async function generate() {
		gelukt = null;
		const grid = await send('/api/library/testgrids', true);
		if (grid) {
			gelukt = { id: grid.id, cellen: grid.cells?.length ?? 0 };
			onGenerated?.(grid.id);
		}
	}

	// ------------------------------------------------- vorige keer (gat T3)
	//
	// Wie wekelijks 3 mm berk test, stelt elke week hetzelfde in. Het vorige
	// raster voor dit materiaal ís die instelling; er is geen aparte
	// voorkeurentabel voor nodig.

	let overgenomen = $state<{ datum: string; raster: number } | null>(null);
	let geladenVoor = $state<number | null | undefined>(undefined);

	const OVER_TE_NEMEN = [
		'operation', 'row_axis', 'column_axis',
		'speed_min', 'speed_max', 'speed_steps',
		'power_min', 'power_max', 'power_steps',
		'interval_min', 'interval_max', 'interval_steps',
		'cell_mm', 'gap_mm', 'origin_x_mm', 'origin_y_mm'
	] as const;

	$effect(() => {
		const id = form.material_id;
		if (id === geladenVoor) return;
		geladenVoor = id;
		overgenomen = null;
		if (id === null) return;
		(async () => {
			const response = await fetch(`/api/library/testgrids/defaults?material_id=${id}`);
			if (!response.ok) return;
			const vorige = await response.json();
			// Alleen overnemen zolang je nog niets gegenereerd hebt: anders
			// overschrijf je het formulier waar je net mee bezig was.
			if (!vorige || gelukt || form.material_id !== id) return;
			for (const sleutel of OVER_TE_NEMEN) {
				const waarde = vorige[sleutel];
				if (waarde === null || waarde === undefined) continue;
				(form as Record<string, unknown>)[sleutel] =
					typeof waarde === 'number' ? String(waarde) : waarde;
			}
			// Een vaste grootheid staat in de vorige rij als min == max.
			for (const as of ['speed', 'power', 'interval'] as As[]) {
				if (vorige[`${as}_steps`] === 1 && vorige[`${as}_min`] != null) {
					form[VAST_VELD[as]] = String(vorige[`${as}_min`]);
				}
			}
			if (vorige.thickness_mm != null) form.thickness_mm = String(vorige.thickness_mm);
			overgenomen = { datum: vorige.from_date, raster: vorige.from_grid };
		})();
	});

	/** "11 aug" — de datum van het raster waar de instelling vandaan komt. */
	function kortedatum(ruw: string) {
		const d = new Date(String(ruw).replace(' ', 'T'));
		if (Number.isNaN(d.getTime())) return ruw;
		return d.toLocaleDateString('nl-NL', { day: 'numeric', month: 'short' });
	}

	// ------------------------------------------------ naar de machine (gat T1)
	//
	// De wizard eindigde op het canvas: het raster stond er, en niets wees je
	// naar Kader tonen of Start job. Die twee staan nu in de succesmelding zelf.
	// Ze roepen dezelfde API's aan als het bedieningspaneel.

	let naarMachine = $state<string | null>(null);
	let machineFout = $state<string | null>(null);

	async function machineActie(pad: string, bezig: string, klaar: string) {
		naarMachine = bezig;
		machineFout = null;
		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			const token =
				typeof localStorage === 'undefined' ? '' : (localStorage.getItem('openkerf.token') ?? '');
			if (token) headers.Authorization = `Bearer ${token}`;
			const response = await fetch(pad, { method: 'POST', headers, body: '{}' });
			if (!response.ok) {
				const data = await response.json().catch(() => null);
				const melding = data?.detail;
				machineFout =
					typeof melding === 'string'
						? melding
						: Array.isArray(melding?.output)
							? melding.output.join(' ')
							: `De machine weigerde dit (${response.status}).`;
				return;
			}
			naarMachine = klaar;
		} catch (e) {
			machineFout = `Netwerkfout: ${e instanceof Error ? e.message : e}`;
		} finally {
			if (naarMachine === bezig) naarMachine = null;
		}
	}

	// ---------------------------------------------------- materiaal erbij (E4)

	let nieuwMateriaal = $state('');
	let materiaalFout = $state<string | null>(null);

	async function maakMateriaal() {
		const naam = nieuwMateriaal.trim();
		if (!naam) return;
		materiaalFout = null;
		const gemaakt = await library.addMaterial(naam);
		if (!gemaakt) {
			materiaalFout = library.error ?? 'Materiaal aanmaken mislukte.';
			return;
		}
		nieuwMateriaal = '';
		form.material_id = gemaakt.id;
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
			Je brandt een bord met vakjes:
			<strong>{ASSEN[form.column_axis].naam.toLowerCase()} loopt naar rechts op</strong>,
			<strong>{ASSEN[form.row_axis].naam.toLowerCase()} naar beneden</strong>. Straks
			fotografeer je het bord — met de telefoon naast de machine kan ook — en tik je het
			vakje aan dat het beste uitpakte. Daar maakt OpenKerf een preset van.
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
					     dat je het brandt. De waarschuwing wijst niet alleen op het
					     gat maar dicht het ook — anders staat er een bezwaar zonder
					     uitweg naast een knop die gewoon doorgaat. -->
					<div class="waarschuwing" role="status">
						<p>
							<strong>Kies een materiaal.</strong> Een preset is een uitspraak over déze laser
							op dít materiaal — zonder materiaal levert het gebrande bord straks niets op.
						</p>
						<div class="erbij">
							<input
								type="text"
								bind:value={nieuwMateriaal}
								maxlength="60"
								placeholder="Nieuw materiaal, bijv. Multiplex berken"
								aria-label="Naam van een nieuw materiaal"
								onkeydown={(e) => {
									if (e.key === 'Enter') {
										e.preventDefault();
										maakMateriaal();
									}
								}}
							/>
							<button
								class="btn"
								disabled={library.busy || nieuwMateriaal.trim() === ''}
								onclick={maakMateriaal}>Aanmaken en kiezen</button
							>
						</div>
						{#if materiaalFout}<p class="fout">{materiaalFout}</p>{/if}
					</div>
				{/if}

				{#if overgenomen}
					<p class="overgenomen" role="status">
						Instellingen overgenomen van je vorige raster voor dit materiaal
						({kortedatum(overgenomen.datum)}, #{overgenomen.raster}). Pas ze gerust aan.
					</p>
				{/if}

				<NumberField label="Dikte" unit="mm" step={0.5} min={0} bind:value={form.thickness_mm} />
				<NumberField label="Vakje" unit="mm" step={1} min={1} bind:value={form.cell_mm} />

				<!-- Besluit B12: je kiest zelf welke twee grootheden je aftast. De
				     derde blijft vast en staat straks op het opschrift van het bord. -->
				<label class="veld">
					<span class="naam">Rijen, naar beneden</span>
					<select
						value={form.row_axis}
						onchange={(e) => kiesAs('row_axis', e.currentTarget.value as As)}
					>
						{#each Object.entries(ASSEN) as [waarde, as] (waarde)}
							{#if waarde !== 'interval' || intervalKan}
								<option value={waarde}>{as.naam}</option>
							{/if}
						{/each}
					</select>
				</label>
				<label class="veld">
					<span class="naam">Kolommen, naar rechts</span>
					<select
						value={form.column_axis}
						onchange={(e) => kiesAs('column_axis', e.currentTarget.value as As)}
					>
						{#each Object.entries(ASSEN) as [waarde, as] (waarde)}
							{#if waarde !== 'interval' || intervalKan}
								<option value={waarde}>{as.naam}</option>
							{/if}
						{/each}
					</select>
				</label>

				<!-- De vaste grootheid staat bij de assen en niet onderaan: hij hoort
				     bij de vraag "wat varieert er", en op een venster van 80vh viel
				     hij anders achter de knoppenbalk. -->
				{#each vasteAs as as (as)}
					<NumberField
						label="{ASSEN[as].naam} (vast, hele bord)"
						unit={ASSEN[as].eenheid}
						step={ASSEN[as].stap}
						min={0}
						max={ASSEN[as].max ?? null}
						bind:value={form[VAST_VELD[as]]}
					/>
				{/each}

				{#each assen as as (as)}
					<NumberField
						label="{ASSEN[as].naam} van"
						unit={ASSEN[as].eenheid}
						step={ASSEN[as].stap}
						min={0}
						max={ASSEN[as].max ?? null}
						bind:value={form[`${as}_min`]}
					/>
					<NumberField
						label="tot"
						unit={ASSEN[as].eenheid}
						step={ASSEN[as].stap}
						min={0}
						max={ASSEN[as].max ?? null}
						bind:value={form[`${as}_max`]}
					/>
				{/each}

				{#each assen as as (as)}
					<NumberField
						label="Stappen {ASSEN[as].naam.toLowerCase()}"
						step={1}
						min={2}
						bind:value={form[`${as}_steps`]}
					/>
				{/each}

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
							{#each kolomwaarden as v, i (i)}
								<span class="as mono"
									>{labelbaar(kolomwaarden, i)
										? form.column_axis === 'power'
											? `${v}%`
											: v
										: ''}</span
								>
							{/each}
						</div>
						<div class="zijlabels">
							{#each rijwaarden as v, i (i)}
								<span class="as mono"
									>{labelbaar(rijwaarden, i)
										? form.row_axis === 'power'
											? `${v}%`
											: v
										: ''}</span
								>
							{/each}
						</div>
						<div
							class="vakjes"
							style="grid-template-columns: repeat({kolomwaarden.length}, var(--cel));"
						>
							{#each preview.cells as cell (`${cell.row}-${cell.column}`)}
								<span
									class="vakje"
									style="--brand: {brand(cell)}"
									title="{toon(form.row_axis, cell[CEL_SLEUTEL[form.row_axis]])} bij {toon(
										form.column_axis,
										cell[CEL_SLEUTEL[form.column_axis]]
									)}"
								></span>
							{/each}
						</div>
					</div>

					{#if preview.plan.label_room === false}
						<!-- De rijlabels worden links van het raster gegraveerd. Bij een
						     kleine Start X vallen ze buiten het bed: dan brandt de
						     machine ze niet en is het bord naderhand onleesbaar. -->
						<p class="krap">
							De rijlabels hebben links van het raster ruwweg
							{Math.ceil(preview.plan.label_margin_mm ?? 0)} mm nodig. Zet
							<strong>Start X</strong> daar
							minstens op, anders vallen ze buiten het bed en blijft het bord onleesbaar.
						</p>
					{/if}

					<p class="legenda">
						Rijen: {ASSEN[form.row_axis].naam.toLowerCase()} in {ASSEN[form.row_axis].eenheid}.
						Kolommen: {ASSEN[form.column_axis].naam.toLowerCase()}.
						{#each vasteAs as as (as)}
							{ASSEN[as].naam} vast op {toon(as, Number(form[VAST_VELD[as]]))}.
						{/each}
						Donkerder is meer verbranding{diepsteHoek ? ` — ${diepsteHoek} gaat het diepst` : ''}.
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
			<!-- Gat T1: hier hield de wizard op en stond je met een getekend raster
			     op het canvas zonder aanwijzing hoe je het brandt. Kader eerst,
			     dan starten — dezelfde volgorde als bij het bedieningspaneel, en
			     dezelfde API's. -->
			<div class="gelukt" role="status">
				<p>
					<strong>Raster #{gelukt.id} staat op het bed</strong> — {gelukt.cellen} vakjes, als
					één groep in je ontwerp. Controleer eerst het kader, brand het daarna, en kom
					dan terug voor stap 3.
				</p>
				<div class="branden">
					<button
						class="btn"
						disabled={naarMachine === 'kader'}
						onclick={() => machineActie('/api/machine/frame', 'kader', 'kader-klaar')}
					>
						{naarMachine === 'kader' ? 'Kader loopt…' : 'Kader tonen'}
					</button>
					<button
						class="btn primary"
						disabled={naarMachine === 'start'}
						onclick={() => machineActie('/api/job/start', 'start', 'start-klaar')}
					>
						{naarMachine === 'start' ? 'Bezig met starten…' : 'Job starten'}
					</button>
				</div>
				{#if naarMachine === 'kader-klaar'}
					<p class="nagekomen">De kop loopt de omtrek van het bed langs. Ligt je plaat goed?</p>
				{:else if naarMachine === 'start-klaar'}
					<p class="nagekomen">
						De job staat in de wachtrij. Blijf erbij tot het bord uit de machine komt.
					</p>
				{/if}
				{#if machineFout}<p class="fout" role="alert">{machineFout}</p>{/if}
			</div>
		{/if}

		<div class="actions">
			<button class="btn" disabled={busy} onclick={suggest}>Bereik voorstellen</button>
			<!-- E4: zonder materiaal blijft dit een gewone knop. Hij werkt — soms
			     wíl je even een bord branden zonder er een preset uit te halen —
			     maar hij belooft niet dat dit de bedoelde weg is. -->
			<!-- Zodra er een raster staat, is starten de volgende stap en niet nóg
			     een raster. Twee even felle knoppen naast elkaar laten je kiezen
			     tussen twee dingen waarvan er maar één aan de orde is. -->
			<button
				class="btn"
				class:primary={!geenMateriaal && !gelukt}
				disabled={busy || !preview}
				onclick={generate}
			>
				{#if busy}
					Bezig…
				{:else if geenMateriaal}
					Toch tekenen zonder materiaal
				{:else if gelukt}
					Nog een raster tekenen
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
		display: grid;
		gap: var(--space-2);
		margin: 0;
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-field);
		border-left: 3px solid var(--warn-solid, var(--warn));
		background: color-mix(in srgb, var(--warn-solid, var(--warn)) 12%, transparent);
		font-size: var(--text-xs);
		color: var(--text-1);
	}
	.waarschuwing p { margin: 0; }
	/* De uitweg staat in de waarschuwing zelf: één regel typen en je bent eruit,
	   zonder de bibliotheek te openen en dit venster kwijt te raken. */
	.erbij { display: flex; gap: var(--space-2); flex-wrap: wrap; }
	.erbij input { flex: 1; min-width: 12rem; }
	.fout { color: var(--danger-solid, var(--danger)); }

	/* Wat de vorige keer werkte, komt terug — maar wel zichtbaar, want anders
	   verandert het formulier onder je handen zonder dat je weet waarom. */
	.overgenomen {
		grid-column: 1 / -1;
		margin: 0;
		padding: var(--space-1h) var(--space-3);
		border-radius: var(--radius-field);
		border-left: 3px solid var(--accent);
		background: color-mix(in srgb, var(--accent) 10%, transparent);
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
	.krap {
		margin: var(--space-2) 0 0;
		padding: var(--space-1h) var(--space-2);
		border-radius: var(--radius-field);
		border-left: 3px solid var(--warn-solid, var(--warn));
		background: color-mix(in srgb, var(--warn-solid, var(--warn)) 12%, transparent);
		max-width: 24ch;
		font-size: var(--text-xs);
		color: var(--text-1);
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
		display: grid;
		gap: var(--space-2);
		background: color-mix(in srgb, var(--ok) 14%, transparent);
		border-left: 3px solid var(--ok);
	}
	.gelukt p { margin: 0; }
	.branden { display: flex; gap: var(--space-2); flex-wrap: wrap; }
	/* De startknop hoort de grootste te zijn in dit blok, maar niet zo groot dat
	   hij de sticky hoofdknop eronder gaat imiteren. */
	.branden .btn { flex: 1; min-width: 10rem; }
	.nagekomen { color: var(--text-2); }
</style>
