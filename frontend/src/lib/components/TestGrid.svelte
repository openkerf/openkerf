<script lang="ts">
	import { AXIS_LABEL, AXIS_UNIT, type GridAxis } from '$lib/api';
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
	 *
	 * Naam en eenheid komen uit `$lib/api`, want de fotolijst op de telefoon
	 * vat dezelfde rasters samen; twee kopieën van "mm/s" zijn twee kansen om
	 * te gaan afwijken. Wat hier blijft, is invoergedrag van de wizard: de
	 * stapgrootte van de plus-en-min en de bovengrens van het veld.
	 */
	type As = GridAxis;
	const AS_ORDE: As[] = ['speed', 'power', 'interval'];
	const INVOER: Record<As, { stap: number; max?: number }> = {
		speed: { stap: 1 },
		power: { stap: 5, max: 100 },
		interval: { stap: 0.01, max: 5 }
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
		/** Of het hele bord — opschrift en kader erbij — nog op het bed begint. */
		board_room?: boolean;
		anchor?: 'corner' | 'center';
	};
	let preview = $state<{
		plan: Plan;
		cells: Cell[];
		engine?: { raster?: boolean };
	} | null>(null);

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
		// 20 en niet 10: de rijlabels worden links van het raster gegraveerd en
		// zijn bij driecijferige snelheden ruim 17 mm breed. Vanaf 10 begon het
		// bord dus buiten het bed, en dan opent de wizard met een waarschuwing
		// over zijn eigen standaardwaarden.
		origin_x_mm: '20',
		origin_y_mm: '20',
		// Gat T9: vanaf de hoek of vanaf het midden. Een testbord leg je op een
		// reststuk, en dan weet je waar het mídden van dat stuk ligt.
		anchor: 'corner' as 'corner' | 'center',
		// Gat T10: LightBurn heeft Enable Text en Enable Border. Tekst staat aan
		// — het bord is een bewijsstuk — en het kader is er voor wie de foto
		// makkelijker wil uitlijnen.
		text: true,
		border: false,
		label_speed_mm_s: '80',
		label_power_percent: '30'
	});

	/** Onder welke sleutel de vaste waarde van een grootheid naar de API gaat. */
	const VAST_VELD: Record<As, 'speed_mm_s' | 'power_percent' | 'interval_mm'> = {
		speed: 'speed_mm_s',
		power: 'power_percent',
		interval: 'interval_mm'
	};

	let intervalKan = $derived(INTERVAL_BEWERKINGEN.includes(form.operation));
	/** Waar de labellaag over gaat: opschrift, kader, of allebei (T10). */
	let labellaagNaam = $derived(form.text ? 'Opschrift' : 'Kader');
	/** Rasteren gekozen op een engine die het niet kan omzetten naar laserregels. */
	let rasterOnmogelijk = $derived(
		form.operation === 'graveren-raster' && preview?.engine?.raster === false
	);
	let assen = $derived([form.row_axis, form.column_axis] as As[]);
	let vasteAs = $derived(
		AS_ORDE.filter(
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
			origin_y_mm: Number(form.origin_y_mm),
			anchor: form.anchor,
			text: form.text,
			border: form.border,
			label_speed_mm_s: Number(form.label_speed_mm_s),
			label_power_percent: Number(form.label_power_percent)
		};
		for (const as of AS_ORDE) {
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
			form.cell_mm, form.gap_mm, form.origin_x_mm, form.origin_y_mm,
			form.anchor, form.text, form.border,
			form.label_speed_mm_s, form.label_power_percent
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

	/** "3 min 20 s" — een tijd die je tegen je koffie kunt afwegen. */
	let brandtijd = $derived.by(() => {
		const s = preview?.plan.seconds ?? 0;
		if (!s) return '—';
		if (s < 60) return `${Math.round(s)} s`;
		const minuten = Math.floor(s / 60);
		if (minuten < 60) return `${minuten} min ${Math.round(s % 60)} s`;
		return `${Math.floor(minuten / 60)} u ${minuten % 60} min`;
	});

	/** "0.05 mm", "60%", "12 mm/s" — de aswaarde zoals hij op het hout komt. */
	function toon(as: As, waarde: number | null | undefined) {
		if (waarde === null || waarde === undefined) return '';
		const eenheid = AXIS_UNIT[as];
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
		'cell_mm', 'gap_mm',
		'label_speed_mm_s', 'label_power_percent'
	] as const;

	/**
	 * Eén bewaarde instelling in het formulier zetten.
	 *
	 * Werkt voor een vorig raster (T3) en voor een benoemd recept (T7): de
	 * server levert ze in dezelfde vorm, en dat was de reden om T7 óp T3 te
	 * bouwen in plaats van ernaast.
	 */
	function neemOver(vorige: Record<string, unknown>) {
		for (const sleutel of OVER_TE_NEMEN) {
			const waarde = vorige[sleutel];
			if (waarde === null || waarde === undefined) continue;
			(form as Record<string, unknown>)[sleutel] =
				typeof waarde === 'number' ? String(waarde) : waarde;
		}
		// Een vaste grootheid staat in de vorige rij als min == max.
		for (const as of AS_ORDE) {
			if (vorige[`${as}_steps`] === 1 && vorige[`${as}_min`] != null) {
				form[VAST_VELD[as]] = String(vorige[`${as}_min`]);
			}
		}
		// Waar het bord lag en wat er verder op stond (T9, T10). Het punt dat je
		// intikte komt terug, niet de hoek die eruit gerekend is.
		if (vorige.anchor === 'center' || vorige.anchor === 'corner') form.anchor = vorige.anchor;
		if (typeof vorige.text_enabled === 'boolean') form.text = vorige.text_enabled;
		if (typeof vorige.border_enabled === 'boolean') form.border = vorige.border_enabled;
		const x = vorige.anchor_x_mm ?? vorige.origin_x_mm;
		const y = vorige.anchor_y_mm ?? vorige.origin_y_mm;
		if (x != null) form.origin_x_mm = String(x);
		if (y != null) form.origin_y_mm = String(y);
		if (vorige.thickness_mm != null) form.thickness_mm = String(vorige.thickness_mm);
	}

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
			neemOver(vorige);
			overgenomen = { datum: vorige.from_date, raster: vorige.from_grid };
		})();
	});

	// ------------------------------------------ benoemde recepten (gat T7)
	//
	// T3 onthoudt één instelling per materiaal: het vorige raster. Dat dekt de
	// wekelijkse proef, niet twee recepten die je afwisselt — "berk snijden"
	// naast "berk graveren". LightBurn heeft daar een Presets-lijst voor met
	// opslaan en verwijderen; dit is dezelfde lijst, gevuld met dezelfde
	// sleutels als het vorige raster, zodat er één invulroutine is.

	type Recept = {
		id: number;
		name: string;
		material_id: number | null;
		material_name: string | null;
		settings: Record<string, unknown>;
	};

	let recepten = $state<Recept[]>([]);
	let gekozenRecept = $state<number | null>(null);
	let receptNaam = $state('');
	let receptFout = $state<string | null>(null);
	let receptBezig = $state(false);
	/** Het opslaanveld staat dicht tot je het opent: het is niet de hoofdweg. */
	let bewaren = $state(false);

	async function haalRecepten() {
		const vraag =
			form.material_id === null
				? '/api/library/testgrids/recipes'
				: `/api/library/testgrids/recipes?material_id=${form.material_id}`;
		const response = await fetch(vraag);
		if (!response.ok) return;
		recepten = await response.json();
		if (gekozenRecept !== null && !recepten.some((r) => r.id === gekozenRecept)) {
			gekozenRecept = null;
		}
	}

	$effect(() => {
		void form.material_id;
		haalRecepten();
	});

	function kiesRecept(id: number | null) {
		gekozenRecept = id;
		const recept = recepten.find((r) => r.id === id);
		if (!recept) return;
		// Een recept overschrijft het formulier; dat is waarvoor je hem koos.
		// De herkomstregel van T3 klopt daarna niet meer, dus die gaat weg.
		overgenomen = null;
		neemOver(recept.settings);
		receptNaam = recept.name;
	}

	async function bewaarRecept() {
		const naam = receptNaam.trim();
		if (!naam) return;
		receptBezig = true;
		receptFout = null;
		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			const token =
				typeof localStorage === 'undefined' ? '' : (localStorage.getItem('openkerf.token') ?? '');
			if (token) headers.Authorization = `Bearer ${token}`;
			// Precies wat er straks gebrand wordt, min het opschrift: dat hoort
			// bij één bord en niet bij het recept.
			const instellingen = { ...body(false) };
			delete (instellingen as Record<string, unknown>).material_id;
			const response = await fetch('/api/library/testgrids/recipes', {
				method: 'POST',
				headers,
				body: JSON.stringify({
					name: naam,
					material_id: form.material_id,
					settings: instellingen
				})
			});
			const data = await response.json().catch(() => null);
			if (!response.ok) {
				receptFout =
					typeof data?.detail === 'string'
						? data.detail
						: `Opslaan mislukte (${response.status}).`;
				return;
			}
			await haalRecepten();
			gekozenRecept = data?.id ?? null;
			bewaren = false;
		} finally {
			receptBezig = false;
		}
	}

	async function wisRecept() {
		if (gekozenRecept === null) return;
		receptBezig = true;
		receptFout = null;
		try {
			const headers: Record<string, string> = {};
			const token =
				typeof localStorage === 'undefined' ? '' : (localStorage.getItem('openkerf.token') ?? '');
			if (token) headers.Authorization = `Bearer ${token}`;
			const response = await fetch(`/api/library/testgrids/recipes/${gekozenRecept}`, {
				method: 'DELETE',
				headers
			});
			if (!response.ok) {
				receptFout = `Verwijderen mislukte (${response.status}).`;
				return;
			}
			gekozenRecept = null;
			receptNaam = '';
			await haalRecepten();
		} finally {
			receptBezig = false;
		}
	}

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
	let machineLet = $state<string | null>(null);

	/**
	 * De harde controle die het bedieningspaneel vóór het starten doet.
	 *
	 * Dat paneel opent een pre-flight en start pas na bevestiging; deze knop
	 * start rechtstreeks, en dan mag de belangrijkste controle niet wegvallen.
	 * Buiten het bed is een blokkade — daar kán de kop niet komen, dus de
	 * machine slaat de beweging over of loopt tegen zijn eindaanslag. Buiten het
	 * vel is een waarschuwing: de kop kan er wel komen, er ligt alleen geen
	 * materiaal. Precies het onderscheid dat `bounds_report` maakt.
	 */
	async function tegenhouder(): Promise<string | null> {
		machineLet = null;
		try {
			const response = await fetch('/api/job/estimate');
			if (!response.ok) return null; // Geen oordeel is geen blokkade.
			const grenzen = (await response.json())?.bounds;
			if (!grenzen) return null;
			if (grenzen.outside_bed > 0) {
				return `${grenzen.outside_bed} ${
					grenzen.outside_bed === 1 ? 'vorm ligt' : 'vormen liggen'
				} buiten het bed — daar komt de kop niet. Zet Start X of Start Y hoger en teken het raster opnieuw.`;
			}
			if (grenzen.outside_sheet > 0) {
				machineLet = `${grenzen.outside_sheet} ${
					grenzen.outside_sheet === 1 ? 'vorm valt' : 'vormen vallen'
				} buiten het vel: daar ligt geen materiaal.`;
			}
			return null;
		} catch {
			return null;
		}
	}

	async function machineActie(pad: string, bezig: string, klaar: string) {
		naarMachine = bezig;
		machineFout = null;
		try {
			// Alleen vóór het branden. Een kader laten lopen is juist de manier om
			// te zien dat iets buiten het bed valt; dat tegenhouden zou de
			// controle blokkeren die je wilde doen.
			if (pad.includes('/job/start')) {
				const bezwaar = await tegenhouder();
				if (bezwaar) {
					machineFout = bezwaar;
					return;
				}
			}
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
			<strong>{AXIS_LABEL[form.column_axis].toLowerCase()} loopt naar rechts op</strong>,
			<strong>{AXIS_LABEL[form.row_axis].toLowerCase()} naar beneden</strong>. Straks
			fotografeer je het bord — met de telefoon naast de machine kan ook — en tik je het
			vakje aan dat het beste uitpakte. Daar maakt OpenKerf een preset van.
		</p>

		<!-- Gat T7: benoemde instellingen. Wie wekelijks 3 mm berk test heeft
		     genoeg aan "vorige keer" (T3), maar twee recepten voor hetzelfde
		     materiaal — snijden naast graveren — kunnen daar niet naast elkaar
		     staan. Bovenaan, zoals in LightBurn: je kiest je recept vóór je
		     gaat sleutelen, niet erna. -->
		<div class="recepten">
			<label class="veld">
				<span class="naam">Recept</span>
				<select
					value={gekozenRecept}
					disabled={recepten.length === 0}
					onchange={(e) =>
						kiesRecept(e.currentTarget.value === '' ? null : Number(e.currentTarget.value))}
				>
					<option value={null}
						>{recepten.length === 0
							? '— nog geen bewaarde instellingen —'
							: '— kies een bewaarde instelling —'}</option
					>
					{#each recepten as recept (recept.id)}
						<option value={recept.id}
							>{recept.name}{recept.material_name ? '' : ' · alle materialen'}</option
						>
					{/each}
				</select>
			</label>
			<div class="receptknoppen">
				<button class="btn" onclick={() => (bewaren = !bewaren)} aria-expanded={bewaren}>
					{bewaren ? 'Niet opslaan' : 'Dit opslaan…'}
				</button>
				{#if gekozenRecept !== null}
					<button class="btn stil" disabled={receptBezig} onclick={wisRecept}>Verwijderen</button>
				{/if}
			</div>
			{#if bewaren}
				<div class="erbij">
					<input
						type="text"
						bind:value={receptNaam}
						maxlength="60"
						placeholder="Naam, bijv. Berk 3 mm snijden"
						aria-label="Naam van dit recept"
						onkeydown={(e) => {
							if (e.key === 'Enter') {
								e.preventDefault();
								bewaarRecept();
							}
						}}
					/>
					<button
						class="btn"
						disabled={receptBezig || receptNaam.trim() === ''}
						onclick={bewaarRecept}>Opslaan</button
					>
				</div>
				<p class="hint">
					Bewaart alles op dit formulier behalve het opschrift.
					{form.material_id === null
						? 'Zonder materiaal gekozen wordt dit een recept voor alle materialen.'
						: 'Hoort bij het gekozen materiaal; een gelijknamig recept wordt bijgewerkt.'}
				</p>
			{/if}
			{#if receptFout}<p class="fout" role="alert">{receptFout}</p>{/if}
		</div>

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

				{#if rasterOnmogelijk}
					<!-- De engine zet een rasterlaag tijdens het plannen om in een
					     bitmap, en die omzetter zit in de wxPython-GUI. Draait de
					     server headless — zoals hier — dan gooit de laag zijn eigen
					     vormen weg en komt het bord blanco uit de machine. Dat is
					     een gat in de engine, geen keuze van ons; het minste wat we
					     kunnen doen is het zeggen vóór het hout eraan gaat. -->
					<p class="waarschuwing ernstig" role="alert">
						<strong>Deze server kan rasterlagen niet branden.</strong> De omzetter die
						een rastervlak naar laserregels rekent, zit in de wxPython-versie van de
						engine en ontbreekt hier. Een raster­bord komt blanco uit de machine.
						Kies <strong>Graveren · vector</strong> of <strong>Snijden</strong>, of brand
						dit raster vanuit de wxPython-UI.
					</p>
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
						{#each AS_ORDE as waarde (waarde)}
							{#if waarde !== 'interval' || intervalKan}
								<option value={waarde}>{AXIS_LABEL[waarde]}</option>
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
						{#each AS_ORDE as waarde (waarde)}
							{#if waarde !== 'interval' || intervalKan}
								<option value={waarde}>{AXIS_LABEL[waarde]}</option>
							{/if}
						{/each}
					</select>
				</label>

				<!-- De vaste grootheid staat bij de assen en niet onderaan: hij hoort
				     bij de vraag "wat varieert er", en op een venster van 80vh viel
				     hij anders achter de knoppenbalk. -->
				{#each vasteAs as as (as)}
					<NumberField
						label="{AXIS_LABEL[as]} (vast, hele bord)"
						unit={AXIS_UNIT[as]}
						step={INVOER[as].stap}
						min={0}
						max={INVOER[as].max ?? null}
						bind:value={form[VAST_VELD[as]]}
					/>
				{/each}

				{#each assen as as (as)}
					<NumberField
						label="{AXIS_LABEL[as]} van"
						unit={AXIS_UNIT[as]}
						step={INVOER[as].stap}
						min={0}
						max={INVOER[as].max ?? null}
						bind:value={form[`${as}_min`]}
					/>
					<NumberField
						label="tot"
						unit={AXIS_UNIT[as]}
						step={INVOER[as].stap}
						min={0}
						max={INVOER[as].max ?? null}
						bind:value={form[`${as}_max`]}
					/>
				{/each}

				{#each assen as as (as)}
					<NumberField
						label="Stappen {AXIS_LABEL[as].toLowerCase()}"
						step={1}
						min={2}
						bind:value={form[`${as}_steps`]}
					/>
				{/each}

				<NumberField label="Tussenruimte" unit="mm" step={1} min={0} bind:value={form.gap_mm} />

				<!-- Gat T9: LightBurn vraagt X Center/Y Center. Op een restplank weet
				     je waar het midden van je stuk hout ligt, niet waar de hoek van
				     een raster moet komen dat je nog niet gezien hebt. Het midden
				     slaat op het hele bord, opschriften inbegrepen — anders ligt het
				     scheef zodra de rijlabels links uitsteken. -->
				<label class="veld breed">
					<span class="naam">Positie meten vanaf</span>
					<select bind:value={form.anchor}>
						<option value="corner">De linkerbovenhoek van het bord</option>
						<option value="center">Het midden van het bord</option>
					</select>
				</label>
				<NumberField
					label={form.anchor === 'center' ? 'Midden X' : 'Start X'}
					unit="mm"
					step={5}
					min={0}
					bind:value={form.origin_x_mm}
				/>
				<NumberField
					label={form.anchor === 'center' ? 'Midden Y' : 'Start Y'}
					unit="mm"
					step={5}
					min={0}
					bind:value={form.origin_y_mm}
				/>

				<!-- Gat T10: LightBurn heeft Enable Text en Enable Border. Voor een
				     proefje op een restje is het opschrift verspilling; voor een bord
				     dat de kast in gaat is het het halve bewijsstuk. Standaard aan,
				     dus wie niets doet houdt wat er stond. -->
				<fieldset class="schakelaars">
					<legend class="naam">Wat er verder op het bord komt</legend>
					<label class="vink">
						<input type="checkbox" bind:checked={form.text} />
						<span>Opschrift en aslabels graveren</span>
					</label>
					<label class="vink">
						<input type="checkbox" bind:checked={form.border} />
						<span>Randkader om het bord</span>
					</label>
					<p class="hint">
						{#if !form.text}
							Zonder opschrift is het bord over twee weken een raadselachtig stuk hout —
							en de aswaarden staan er dan ook niet bij.
						{:else if form.border}
							Het kader loopt om alles heen, opschrift inbegrepen. Handig om de foto
							straks op uit te lijnen.
						{:else}
							Het kader is een lijn om het hele bord; hij maakt het uitlijnen van de
							foto makkelijker.
						{/if}
					</p>
				</fieldset>

				{#if form.text || form.border}
					<!-- De labellaag stond hard op 80 mm/s @30%. Dat werkt op berken en
					     niet op acryl, en dan brandt het opschrift dwars door je bord. -->
					<NumberField
						label="{labellaagNaam}: snelheid"
						unit="mm/s"
						step={5}
						min={1}
						bind:value={form.label_speed_mm_s}
					/>
					<NumberField
						label="{labellaagNaam}: vermogen"
						unit="%"
						step={5}
						min={1}
						max={100}
						bind:value={form.label_power_percent}
					/>
				{/if}

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
						<!-- De maat van het hele bord, niet van de vakjes alleen: het
						     opschrift en het kader worden net zo goed gebrand, en juist
						     die staken links en boven uit (T11). LightBurn meldt
						     hetzelfde als Output Size. -->
						<span class="mono"
							>{preview.plan.outer_width_mm ?? preview.plan.width_mm} × {preview.plan
								.outer_height_mm ?? preview.plan.height_mm} mm</span
						>
					</div>
					{#if (preview.plan.outer_width_mm ?? 0) > preview.plan.width_mm}
						<p class="kosten">
							Waarvan <span class="mono"
								>{preview.plan.width_mm} × {preview.plan.height_mm} mm</span
							> vakjes; de rest is {form.text && form.border
								? 'opschrift en kader'
								: form.text
									? 'opschrift'
									: 'kader'}.
						</p>
					{/if}
					<!-- Wat het gaat kosten, vóór je op genereren drukt. Met interval
					     als as kan de brandtijd stil vertienvoudigen: een rij op
					     0,05 mm legt zes keer zoveel regels als een op 0,3 mm, en dat
					     staat in geen enkel ander getal in dit formulier. -->
					<p class="kosten">
						Brandtijd ongeveer <strong class="mono">{brandtijd}</strong>, zonder de
						opschriften.
					</p>

					<!-- Het bord zoals het eruitkomt: donkerder = meer verbranding, en
					     de waarden staan erlangs waar ze ook op het hout komen. -->
					<!-- De schakelaars van T10 horen hier te zien te zijn en niet alleen
					     in een getal: zet je het opschrift uit, dan verdwijnen de
					     aswaarden ook uit het voorbeeld, want ze komen niet op het hout.
					     Het kader is een lijn om het geheel, precies waar hij brandt. -->
					<div
						class="bord"
						class:kaal={!form.text}
						class:kader={form.border}
						style="--cel: {celPx}px; --gat: {gatPx}px;"
					>
						{#if form.text}
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
						{/if}
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

					{#if preview.plan.board_room === false}
						<!-- Het bord begint links of boven buiten het bed. Dat komt bijna
						     altijd door de rijlabels: die worden links van het raster
						     gegraveerd en zijn zo breed als hun langste waarde. Bij het
						     midden als ankerpunt kun je dat niet zelf uitrekenen, dus
						     staat het getal erbij. -->
						<p class="krap">
							Het bord begint op <strong class="mono"
								>{preview.plan.outer_x_mm}, {preview.plan.outer_y_mm} mm</strong
							>, en dat ligt buiten het bed.
							{#if preview.plan.label_room === false}
								De rijlabels hebben links ruwweg {Math.ceil(preview.plan.label_margin_mm ?? 0)} mm
								nodig.
							{/if}
							Schuif het {form.anchor === 'center' ? 'midden' : 'startpunt'} naar rechts of
							naar beneden{form.text ? ', of zet het opschrift uit' : ''}.
						</p>
					{/if}

					<p class="legenda">
						Rijen: {AXIS_LABEL[form.row_axis].toLowerCase()} in {AXIS_UNIT[form.row_axis]}.
						Kolommen: {AXIS_LABEL[form.column_axis].toLowerCase()}.
						{#each vasteAs as as (as)}
							{AXIS_LABEL[as]} vast op {toon(as, Number(form[VAST_VELD[as]]))}.
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
				{#if machineLet}<p class="nagekomen">Let op: {machineLet}</p>{/if}
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
					Raster tekenen — {preview.cells.length} vakjes, {preview.plan.outer_width_mm ??
						preview.plan.width_mm} × {preview.plan.outer_height_mm ??
						preview.plan.height_mm} mm
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
	/* Een bord dat blanco uit de machine komt is geen aandachtspunt maar een
	   verspilde plaat: die melding krijgt de gevaarkleur. */
	.waarschuwing.ernstig {
		/* Terug naar één tekstblok: het gedeelde kader is een grid, en dan wordt
		   elk woord tussen twee <strong>'s een eigen rij. */
		display: block;
		border-left-color: var(--danger-solid, var(--danger));
		background: color-mix(in srgb, var(--danger-solid, var(--danger)) 12%, transparent);
	}
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

	/* De receptenbalk: één regel bovenaan, zoals in LightBurn. Kiezen is de
	   hoofdactie, opslaan staat ernaast en klapt pas open als je het vraagt —
	   anders is het eerste wat je ziet een leeg naamveld. */
	.recepten {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: var(--space-2) var(--space-3);
		align-items: end;
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-2);
	}
	.recepten .erbij,
	.recepten .hint,
	.recepten .fout { grid-column: 1 / -1; }
	.receptknoppen { display: flex; gap: var(--space-2); }
	.receptknoppen .btn { min-height: 38px; padding: var(--space-1h) var(--space-3); }
	/* Verwijderen is stil: het staat er voor als je het nodig hebt, niet als
	   suggestie naast de knop die je wél moet gebruiken. */
	.btn.stil { border-color: transparent; background: transparent; color: var(--text-2); }
	.btn.stil:hover:not(:disabled) { background: var(--surface-1); color: var(--text-1); }

	/* Twee schakelaars die bij elkaar horen: een fieldset, want ze delen één
	   vraag ("wat komt er verder op het bord"). */
	.schakelaars {
		grid-column: 1 / -1;
		display: grid;
		gap: var(--space-1h);
		margin: 0;
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
	}
	.schakelaars legend { padding: 0 var(--space-1); }
	.vink {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-sm);
		color: var(--text-1);
	}
	.schakelaars .hint { margin: 0; max-width: 52ch; }

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
		.preview { position: static; }
	}

	.preview {
		/* Meekijken terwijl je sleutelt. Het formulier is met de positiekeuze en
		   de schakelaars langer geworden dan het venster: wie onderin "vanaf het
		   midden" koos, zag het voorbeeld niet meer waarin dat verschil zichtbaar
		   is. Boven 720px, want daaronder staat het voorbeeld ónder het formulier
		   en zou plakken betekenen dat het de velden afdekt. */
		position: sticky;
		top: 0;
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
	/* Zonder opschrift is er ook geen labelkolom: dan is het bord precies de
	   vakjes, en dat hoort het voorbeeld te laten zien. */
	.bord.kaal { grid-template-columns: auto; grid-template-rows: auto; }
	/* Het randkader zoals het brandt: om alles heen, met de tussenruimte ertussen
	   die de generator ook aanhoudt. */
	.bord.kader {
		padding: var(--space-2);
		border: 1px solid var(--text-2);
		border-radius: var(--radius-sharp);
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
	.kosten {
		margin: 0 0 var(--space-2);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.kosten strong { color: var(--text-1); }
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
