<script lang="ts">
	import { axisLabel, AXIS_UNIT, type GridAxis } from '$lib/api';
	import { i18n, t } from '$lib/i18n/index.svelte';
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
	/**
	 * Waarom de huidige invoer nog geen bord oplevert.
	 *
	 * Apart van `error`, want dit is geen mislukking maar een tussenstand.
	 * Tijdens het typen van "5" naar "30" is "van" even hoger dan "tot", en dat
	 * duurt precies zolang als het kost om het tweede veld ook aan te passen.
	 * Vóór deze scheiding viel het hele voorbeeldblok dan weg: het formulier
	 * sprong van 506 naar 810 pixels breed en de reden stond onder de vouw.
	 * Nu blijft het laatste geldige beeld staan met deze melding erboven.
	 */
	let voorbeeldFout = $state<string | null>(null);
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
		// Voor het hele bord gelijk. Het geval: een materiaal dat op 5 mm/s
		// bijna doorsnijdt en dat je op 8 mm/s in twee passes wilt proberen.
		passes: '1',
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

	/** Under which key the fixed value of a quantity goes to the API. */
	const VAST_VELD: Record<As, 'speed_mm_s' | 'power_percent' | 'interval_mm'> = {
		speed: 'speed_mm_s',
		power: 'power_percent',
		interval: 'interval_mm'
	};

	let intervalKan = $derived(INTERVAL_BEWERKINGEN.includes(form.operation));
	/** What the label layer is about: caption, border, or both (T10). */
	let labellaagNaam = $derived(
		t(form.text ? 'grid.labelLayer.caption' : 'grid.labelLayer.border')
	);
	/** Raster chosen on an engine that cannot convert it into laser lines. */
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
	 * Two axes cannot be the same quantity: pick for the rows what is already in
	 * the columns and that one moves to the vacated place. That is what a user
	 * means by "swap", and it saves an error message.
	 */
	function kiesAs(welke: 'row_axis' | 'column_axis', nieuw: As) {
		const andere = welke === 'row_axis' ? 'column_axis' : 'row_axis';
		if (form[andere] === nieuw) form[andere] = form[welke];
		form[welke] = nieuw;
	}

	// If the operation jumps back to cutting while interval is on an axis, that axis
	// no longer exists. Without this the form stays invalid.
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
			passes: Number(form.passes),
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
		// Een stille voorbeeldronde raakt `error` niet aan: dat blok staat
		// onderaan het formulier en hoort bij een mislukte handeling, niet bij
		// een half getypt getal.
		if (stil) voorbeeldFout = null;
		else error = null;
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
				const melding =
					typeof data?.detail === 'string'
						? data.detail
						: t('grid.error.refused', { status: response.status });
				if (stil) voorbeeldFout = melding;
				else error = melding;
				return null;
			}
			return data;
		} catch (e) {
			const melding = t('grid.error.network', { message: e instanceof Error ? e.message : e });
			if (stil) voorbeeldFout = melding;
			else error = melding;
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
			form.cell_mm, form.gap_mm, form.passes, form.origin_x_mm, form.origin_y_mm,
			form.anchor, form.text, form.border,
			form.label_speed_mm_s, form.label_power_percent
		];
		if (timer) clearTimeout(timer);
		timer = setTimeout(async () => {
			const verse = await send('/api/library/testgrids/preview', false, true);
			// Alleen vervangen als er een geldig bord uitkwam. Het laatste
			// geldige beeld laten staan is rustiger dan een gat laten vallen —
			// en het is ook eerlijker: dát is nog steeds wat je zou branden als
			// je nu ophield met typen.
			if (verse) preview = verse;
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
		// Word order differs per language: Dutch says "rechtsboven" as one word,
		// English "top right" the other way round — so the catalogue joins them.
		return t('grid.corner', {
			horizontal: t(rechts ? 'grid.corner.right' : 'grid.corner.left'),
			vertical: t(onder ? 'grid.corner.bottom' : 'grid.corner.top')
		});
	});

	/** "3 min 20 s" — a time you can weigh against your coffee. */
	let brandtijd = $derived.by(() => {
		const s = preview?.plan.seconds ?? 0;
		if (!s) return '—';
		if (s < 60) return t('grid.time.seconds', { n: Math.round(s) });
		const minuten = Math.floor(s / 60);
		if (minuten < 60)
			return t('grid.time.minutes', { minutes: minuten, seconds: Math.round(s % 60) });
		return t('grid.time.hours', { hours: Math.floor(minuten / 60), minutes: minuten % 60 });
	});

	/** "0.05 mm", "60%", "12 mm/s" — the axis value as it ends up on the wood. */
	function toon(as: As, waarde: number | null | undefined) {
		if (waarde === null || waarde === undefined) return '';
		const eenheid = AXIS_UNIT[as];
		return eenheid === '%' ? `${waarde}%` : `${waarde} ${eenheid}`;
	}

	// The preview is drawn in real pixels rather than in millimetres: an SVG with a
	// mm viewBox turns every 11px label into a giant of 11mm.
	const VOORBEELD_PX = 208;
	let schaal = $derived(preview ? VOORBEELD_PX / Math.max(1, preview.plan.width_mm) : 1);
	let celPx = $derived(preview ? preview.plan.cell_mm * schaal : 0);
	let gatPx = $derived(preview ? preview.plan.gap_mm * schaal : 0);
	// With more than eight steps every label becomes unreadable; then only the
	// edges. An eleven-pixel label does not fit in a twenty-pixel square; then only
	// the two edge values, because those carry the range.
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

	/**
	 * Waar het vorige bord kwam te liggen.
	 *
	 * Nodig omdat een tweede raster standaard op precies dezelfde plek valt:
	 * Start X en Start Y staan nog op wat ze stonden. Gemeten: twee borden,
	 * allebei op 20, 20 mm, exact over elkaar heen — op het canvas niet te zien
	 * en in de machine een dubbele brand.
	 */
	let vorigBord = $state<{
		id: number;
		x: number;
		y: number;
		breedte: number;
		hoogte: number;
	} | null>(null);

	async function generate() {
		gelukt = null;
		const grid = await send('/api/library/testgrids', true);
		if (grid) {
			gelukt = { id: grid.id, cellen: grid.cells?.length ?? 0 };
			const plan = preview?.plan;
			vorigBord = plan
				? {
						id: grid.id,
						x: plan.outer_x_mm ?? plan.origin_x_mm,
						y: plan.outer_y_mm ?? plan.origin_y_mm,
						breedte: plan.outer_width_mm ?? plan.width_mm,
						hoogte: plan.outer_height_mm ?? plan.height_mm
					}
				: null;
			onGenerated?.(grid.id);
		}
	}

	/**
	 * Terug naar stap 1 voor een volgend bord.
	 *
	 * Dit was één knop met `generate()`: "Nog een raster tekenen" tékende
	 * meteen, zonder je de kans te geven iets te veranderen — en liet daarbij
	 * de melding van het vórige bord staan ("De job staat in de wachtrij"),
	 * onder het nummer van het nieuwe. Nu doet de knop wat hij zegt: hij zet je
	 * terug bij de instellingen, met de plek van het vorige bord in beeld zodat
	 * je het nieuwe ernaast legt in plaats van erop.
	 */
	function opnieuw() {
		gelukt = null;
		naarMachine = null;
		machineFout = null;
		machineLet = null;
		error = null;
	}

	/** Zou het nieuwe bord bovenop het vorige vallen? */
	let botsing = $derived.by(() => {
		if (!vorigBord || gelukt || !preview) return false;
		const plan = preview.plan;
		const x = plan.outer_x_mm ?? plan.origin_x_mm;
		const y = plan.outer_y_mm ?? plan.origin_y_mm;
		const b = plan.outer_width_mm ?? plan.width_mm;
		const h = plan.outer_height_mm ?? plan.height_mm;
		return (
			x < vorigBord.x + vorigBord.breedte &&
			vorigBord.x < x + b &&
			y < vorigBord.y + vorigBord.hoogte &&
			vorigBord.y < y + h
		);
	});

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
		'cell_mm', 'gap_mm', 'passes',
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

	/** "11 Aug" — the date of the grid the setting comes from. */
	function kortedatum(ruw: string) {
		const d = new Date(String(ruw).replace(' ', 'T'));
		if (Number.isNaN(d.getTime())) return ruw;
		return new Intl.DateTimeFormat(i18n.locale, { day: 'numeric', month: 'short' }).format(d);
	}

	// ------------------------------------------------ to the machine (gap T1)
	//
	// The wizard used to end on the canvas: the grid was there, and nothing pointed
	// you at Show frame or Start job. Those two are in the success message itself
	// now. They call the same APIs as the control panel.

	let naarMachine = $state<string | null>(null);
	let machineFout = $state<string | null>(null);
	let machineLet = $state<string | null>(null);

	/**
	 * The hard check the control panel does before starting.
	 *
	 * That panel opens a preflight and only starts after a confirmation; this button
	 * starts directly, and then the most important check must not fall away. Outside
	 * the bed is a block — the head cannot get there, so the machine skips the
	 * movement or runs into its end stop. Outside the sheet is a warning: the head
	 * can get there, there is simply no material. Exactly the distinction
	 * `bounds_report` makes.
	 */
	async function tegenhouder(): Promise<string | null> {
		machineLet = null;
		try {
			const response = await fetch('/api/job/estimate');
			if (!response.ok) return null; // No verdict is not a block.
			const grenzen = (await response.json())?.bounds;
			if (!grenzen) return null;
			if (grenzen.outside_bed > 0) {
				return t('grid.block.outsideBed', { n: grenzen.outside_bed });
			}
			if (grenzen.outside_sheet > 0) {
				machineLet = t('grid.watch.outsideSheet', { n: grenzen.outside_sheet });
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
			materiaalFout = library.error ?? t('error.materialFailed');
			return;
		}
		nieuwMateriaal = '';
		form.material_id = gemaakt.id;
	}
</script>

<div class="wizard">
	<!-- The wizard is the didactic core of the app: it says where you are and what
	     is still to come, even though step 3 only happens beside the machine. -->
	<ol class="stappen" aria-label={t('grid.steps')}>
		<li class:nu={stap === 1}><span class="nr">1</span>{t('grid.step.setUp')}</li>
		<li class:nu={stap === 2}><span class="nr">2</span>{t('grid.step.burn')}</li>
		<li><span class="nr">3</span>{t('grid.step.photograph')}</li>
		<li><span class="nr">4</span>{t('grid.step.bestCell')}</li>
	</ol>

	{#if !canEdit}
		<p class="muted">{t('grid.needsToken')}</p>
	{:else}
		<p class="lead">
			{t('grid.lead', {
				columns: t('grid.lead.right', { axis: axisLabel(form.column_axis).toLowerCase() }),
				rows: t('grid.lead.down', { axis: axisLabel(form.row_axis).toLowerCase() })
			})}
		</p>

		<!-- Gap T7: named settings. Whoever tests 3 mm birch weekly is served by "last
		     time" (T3), but two recipes for the same material — cut beside engrave —
		     cannot sit side by side in that. At the top, as in LightBurn: you pick your
		     recipe before you start tinkering, not after. -->
		<div class="recepten">
			<label class="veld">
				<span class="naam">{t('grid.recipe')}</span>
				<select
					value={gekozenRecept}
					disabled={recepten.length === 0}
					onchange={(e) =>
						kiesRecept(e.currentTarget.value === '' ? null : Number(e.currentTarget.value))}
				>
					<option value={null}
						>{recepten.length === 0 ? t('grid.recipe.none') : t('grid.recipe.pick')}</option
					>
					{#each recepten as recept (recept.id)}
						<option value={recept.id}
							>{recept.name}{recept.material_name
								? ''
								: ` · ${t('grid.recipe.allMaterials')}`}</option
						>
					{/each}
				</select>
			</label>
			<div class="receptknoppen">
				<button class="btn" onclick={() => (bewaren = !bewaren)} aria-expanded={bewaren}>
					{bewaren ? t('grid.recipe.dontSave') : t('grid.recipe.save')}
				</button>
				{#if gekozenRecept !== null}
					<button class="btn stil" disabled={receptBezig} onclick={wisRecept}
						>{t('common.remove')}</button
					>
				{/if}
			</div>
			{#if bewaren}
				<div class="erbij">
					<input
						type="text"
						bind:value={receptNaam}
						maxlength="60"
						placeholder={t('grid.recipe.namePlaceholder')}
						aria-label={t('grid.recipe.nameAria')}
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
						onclick={bewaarRecept}>{t('common.save')}</button
					>
				</div>
				<p class="hint">
					{t('grid.recipe.hint')}
					{form.material_id === null
						? t('grid.recipe.hint.noMaterial')
						: t('grid.recipe.hint.material')}
				</p>
			{/if}
			{#if receptFout}<p class="fout" role="alert">{receptFout}</p>{/if}
		</div>

		<div class="werkbank">
			<div class="grid">
				<div class="paar">
				<label class="veld">
					<span class="naam">{t('library.material')}</span>
					<select bind:value={form.material_id}>
						<option value={null}>{t('grid.none')}</option>
						{#each library.materials as material (material.id)}
							<option value={material.id}>{material.name}</option>
						{/each}
					</select>
				</label>
				<label class="veld">
					<span class="naam">{t('library.operation')}</span>
					<select bind:value={form.operation}>
						{#each OPERATIONS as op (op.value)}
							<option value={op.value}>{op.label}</option>
						{/each}
					</select>
				</label>
				</div>

				{#if geenMateriaal}
					<!-- Before the wood goes, not after: without a material no preset can come
					     out of this board later, and that is the whole reason you burn it. The
					     warning does not only point at the gap but closes it — otherwise there
					     is an objection with no way out beside a button that simply goes
					     ahead. -->
					<div class="waarschuwing" role="status">
						<p>
							<strong>{t('grid.noMaterial.title')}</strong>
							{t('grid.noMaterial.body')}
						</p>
						<div class="erbij">
							<input
								type="text"
								bind:value={nieuwMateriaal}
								maxlength="60"
								placeholder={t('grid.newMaterial.placeholder')}
								aria-label={t('grid.newMaterial.aria')}
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
								onclick={maakMateriaal}>{t('grid.newMaterial.create')}</button
							>
						</div>
						{#if materiaalFout}<p class="fout">{materiaalFout}</p>{/if}
					</div>
				{/if}

				{#if rasterOnmogelijk}
					<!-- The engine turns a raster layer into a bitmap while planning, and that
					     converter lives in the wxPython GUI. When the server runs headless — as
					     here — the layer throws its own shapes away and the board comes out of
					     the machine blank. That is a gap in the engine, not a choice of ours;
					     the least we can do is say it before the wood goes. -->
					<p class="waarschuwing ernstig" role="alert">
						<strong>{t('job.noRaster.title')}</strong>
						{t('grid.noRaster.body')}
					</p>
				{/if}

				{#if overgenomen}
					<p class="overgenomen" role="status">
						{t('grid.carriedOver', {
							date: kortedatum(overgenomen.datum),
							grid: overgenomen.raster
						})}
					</p>
				{/if}

				<div class="paar">
					<NumberField
						label={t('library.thickness')}
						unit="mm"
						step={0.5}
						min={0}
						bind:value={form.thickness_mm}
					/>
					<NumberField label={t('grid.cell')} unit="mm" step={1} min={1} bind:value={form.cell_mm} />
				</div>
				<!-- For the whole board, not per square: passes as an axis would yield a
				     board nobody reads back, and the number goes on the caption so you can
				     still place the board in two weeks.

				     In a `.paar` with one child: that keeps the field the same width as the
				     fields above. Over the full width a number field is 500px for one
				     digit, and then the column no longer lines up. -->
				<div class="paar">
					<NumberField
						label={t('library.passes')}
						unit={t('grid.passes.unit')}
						step={1}
						min={1}
						bind:value={form.passes}
					/>
				</div>

				<!-- Decision B12: you pick which two quantities you sweep. The third stays
				     fixed and ends up on the caption of the board. -->
				<div class="paar">
				<label class="veld">
					<span class="naam">{t('grid.rowsDown')}</span>
					<select
						value={form.row_axis}
						onchange={(e) => kiesAs('row_axis', e.currentTarget.value as As)}
					>
						{#each AS_ORDE as waarde (waarde)}
							{#if waarde !== 'interval' || intervalKan}
								<option value={waarde}>{axisLabel(waarde)}</option>
							{/if}
						{/each}
					</select>
				</label>
				<label class="veld">
					<span class="naam">{t('grid.columnsRight')}</span>
					<select
						value={form.column_axis}
						onchange={(e) => kiesAs('column_axis', e.currentTarget.value as As)}
					>
						{#each AS_ORDE as waarde (waarde)}
							{#if waarde !== 'interval' || intervalKan}
								<option value={waarde}>{axisLabel(waarde)}</option>
							{/if}
						{/each}
					</select>
				</label>
				</div>

				<!-- The fixed quantity sits with the axes and not at the bottom: it belongs
				     to the question "what varies", and on an 80vh window it otherwise fell
				     behind the button bar. -->
				{#each vasteAs as as (as)}
					<NumberField
						label={t('grid.fixedAxis', { axis: axisLabel(as) })}
						unit={AXIS_UNIT[as]}
						step={INVOER[as].stap}
						min={0}
						max={INVOER[as].max ?? null}
						bind:value={form[VAST_VELD[as]]}
					/>
				{/each}

				<!-- From, to and the number of steps are one statement about one axis
				     together. They used to be spread over three places in the grid; now
				     every axis is in a block of its own, with from and to side by side. -->
				{#each assen as as (as)}
					<fieldset class="asblok">
						<!-- The unit once, in the block's heading. It used to be in both field
						     labels ("from (mm/s)", "to (mm/s)") and then you read it twice to
						     understand one range. -->
						<legend class="naam">{t('grid.axisRange', { axis: axisLabel(as), unit: AXIS_UNIT[as] })}</legend>
						<div class="paar">
							<NumberField
								label={t('grid.from')}
								step={INVOER[as].stap}
								min={0}
								max={INVOER[as].max ?? null}
								bind:value={form[`${as}_min`]}
							/>
							<NumberField
								label={t('grid.to')}
								step={INVOER[as].stap}
								min={0}
								max={INVOER[as].max ?? null}
								bind:value={form[`${as}_max`]}
							/>
						</div>
						<div class="paar">
							<NumberField
								label={t('grid.stepsLabel')}
								unit={as === assen[0] ? t('grid.stepsUnit.rows') : t('grid.stepsUnit.columns')}
								step={1}
								min={2}
								bind:value={form[`${as}_steps`]}
							/>
						</div>
					</fieldset>
				{/each}

				<div class="paar">
					<NumberField label={t('grid.gap')} unit="mm" step={1} min={0} bind:value={form.gap_mm} />
				</div>

				<!-- Gap T9: LightBurn asks for X Center/Y Center. On an offcut you know
				     where the middle of your piece of wood is, not where the corner of a
				     grid you have not seen yet should go. The centre applies to the whole
				     board, captions included — otherwise it sits askew the moment the row
				     labels stick out on the left. -->
				<label class="veld">
					<span class="naam">{t('grid.measureFrom')}</span>
					<select bind:value={form.anchor}>
						<option value="corner">{t('grid.anchor.corner')}</option>
						<option value="center">{t('grid.anchor.center')}</option>
					</select>
				</label>
				<div class="paar">
					<NumberField
						label={form.anchor === 'center' ? t('grid.centerX') : t('grid.startX')}
						unit="mm"
						step={5}
						min={0}
						bind:value={form.origin_x_mm}
					/>
					<NumberField
						label={form.anchor === 'center' ? t('grid.centerY') : t('grid.startY')}
						unit="mm"
						step={5}
						min={0}
						bind:value={form.origin_y_mm}
					/>
				</div>

				<!-- Gap T10: LightBurn has Enable Text and Enable Border. For a quick test
				     on an offcut the caption is waste; for a board that goes in the cupboard
				     it is half the evidence. On by default, so whoever does nothing keeps
				     what was there. -->
				<fieldset class="schakelaars">
					<legend class="naam">{t('grid.extras')}</legend>
					<label class="vink">
						<input type="checkbox" bind:checked={form.text} />
						<span>{t('grid.extras.text')}</span>
					</label>
					<label class="vink">
						<input type="checkbox" bind:checked={form.border} />
						<span>{t('grid.extras.border')}</span>
					</label>
					<p class="hint">
						{#if !form.text}
							{t('grid.extras.noText')}
						{:else if form.border}
							{t('grid.extras.bothOn')}
						{:else}
							{t('grid.extras.borderOnly')}
						{/if}
					</p>
				</fieldset>

				{#if form.text || form.border}
					<!-- The label layer was hard-coded at 80 mm/s @30%. That works on birch and
					     not on acrylic, and then the caption burns straight through your
					     board. -->
					<NumberField
						label={t('grid.label.speed', { layer: labellaagNaam })}
						unit="mm/s"
						step={5}
						min={1}
						bind:value={form.label_speed_mm_s}
					/>
					<NumberField
						label={t('grid.label.power', { layer: labellaagNaam })}
						unit="%"
						step={5}
						min={1}
						max={100}
						bind:value={form.label_power_percent}
					/>
				{/if}

				<label class="veld breed">
					<span class="naam">{t('grid.caption')}</span>
					<input
						type="text"
						bind:value={form.caption}
						maxlength="48"
						placeholder={t('grid.caption.placeholder')}
					/>
					<span class="hint">{t('grid.caption.hint')}</span>
				</label>
			</div>

			{#if preview}
				<aside class="preview" aria-label={t('grid.preview')}>
					{#if voorbeeldFout}
						<!-- While typing, an intermediate state is nearly always briefly
						     invalid: you adjust "from" and it is then higher than "to" until you
						     adjust that too. The preview stays, with the reason above it —
						     dropping a hole teaches you nothing and makes half the wizard
						     jump. -->
						<p class="onaf" role="status">
							{voorbeeldFout}<br />
							<span class="stil">{t('grid.preview.lastValid')}</span>
						</p>
					{:else if botsing}
						<!-- The previous board is still there, and Start X/Y is still in the same
						     place. Two boards over each other you do not see on the canvas and do
						     see in the machine. -->
						<p class="onaf" role="status">
							{t('grid.preview.overlap', {
								id: vorigBord?.id,
								anchor: t(form.anchor === 'center' ? 'grid.anchor.centreWord' : 'grid.anchor.startWord')
							})}
						</p>
					{/if}
					<div class="figures">
						<span class="mono">{t('grid.cells', { n: preview.cells.length })}</span>
						<!-- Only when there is more than one: with one pass this is the ordinary
						     course of things and says nothing. -->
						{#if (preview.plan.passes ?? 1) > 1}
							<span class="mono">{t('grid.passesPerCell', { n: preview.plan.passes })}</span>
						{/if}
						<!-- The size of the whole board, not of the squares alone: the caption and
						     the border are burned just as much, and it was precisely those that
						     stuck out on the left and top (T11). LightBurn reports the same as
						     Output Size. -->
						<span class="mono"
							>{preview.plan.outer_width_mm ?? preview.plan.width_mm} × {preview.plan
								.outer_height_mm ?? preview.plan.height_mm} mm</span
						>
					</div>
					{#if (preview.plan.outer_width_mm ?? 0) > preview.plan.width_mm}
						<p class="kosten">
							{t('grid.ofWhich', {
								size: `${preview.plan.width_mm} × ${preview.plan.height_mm} mm`,
								extras:
									form.text && form.border
										? t('grid.extras.both')
										: form.text
											? t('grid.extras.captionOnly')
											: t('grid.extras.borderOnly2')
							})}
						</p>
					{/if}
					<!-- What it is going to cost, before you press generate. With interval as
					     an axis the burn time can quietly go up tenfold: a row at 0.05 mm lays
					     six times as many lines as one at 0.3 mm, and that is in no other
					     number on this form. -->
					<p class="kosten">{t('grid.burnTime', { time: brandtijd })}</p>

					<!-- The board as it comes out: darker = more burning, and the values are
					     alongside where they end up on the wood. -->
					<!-- The switches from T10 have to be visible here and not only in a
					     number: switch the caption off and the axis values disappear from the
					     preview too, because they do not go on the wood. The border is a line
					     around the whole thing, exactly where it burns. -->
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
									title={t('grid.cellTitle', {
										row: toon(form.row_axis, cell[CEL_SLEUTEL[form.row_axis]]),
										column: toon(form.column_axis, cell[CEL_SLEUTEL[form.column_axis]])
									})}
								></span>
							{/each}
						</div>
					</div>

					{#if preview.plan.board_room === false}
						<!-- The board starts outside the bed on the left or the top. That is
						     nearly always down to the row labels: they are engraved left of the
						     grid and are as wide as their longest value. With the centre as the
						     anchor you cannot work that out yourself, so the number is here. -->
						<p class="krap">
							{t('grid.tooFar', {
								position: `${preview.plan.outer_x_mm}, ${preview.plan.outer_y_mm} mm`
							})}
							{#if preview.plan.label_room === false}
								{t('grid.tooFar.labels', { mm: Math.ceil(preview.plan.label_margin_mm ?? 0) })}
							{/if}
							{t('grid.tooFar.move', {
								anchor: t(
									form.anchor === 'center' ? 'grid.anchor.centreWord' : 'grid.anchor.startWord'
								),
								orText: form.text ? t('grid.tooFar.orText') : ''
							})}
						</p>
					{/if}

					<p class="legenda">
						{t('grid.legend.rows', {
							axis: axisLabel(form.row_axis).toLowerCase(),
							unit: AXIS_UNIT[form.row_axis]
						})}
						{t('grid.legend.columns', { axis: axisLabel(form.column_axis).toLowerCase() })}
						{#each vasteAs as as (as)}
							{t('grid.legend.fixed', {
								axis: axisLabel(as),
								value: toon(as, Number(form[VAST_VELD[as]]))
							})}
						{/each}
						{diepsteHoek
							? t('grid.legend.deepest', { corner: diepsteHoek })
							: t('grid.legend.darker')}
					</p>
				</aside>
			{/if}
		</div>

		{#if suggestedFrom !== null}
			<p class="muted">
				{suggestedFrom
					? t('grid.suggested', { n: suggestedFrom })
					: t('grid.suggested.none')}
			</p>
		{/if}

		{#if error}<p class="error" role="alert">{error}</p>{/if}

		{#if gelukt}
			<!-- Gap T1: this is where the wizard used to stop, leaving you with a drawn
			     grid on the canvas and no hint how to burn it. Frame first, then start —
			     the same order as in the control panel, and the same APIs. -->
			<div class="gelukt" role="status">
				<p>
					<strong>{t('grid.done.title', { id: gelukt.id })}</strong>
					{t('grid.done.body', { cells: gelukt.cellen })}
				</p>
				<div class="branden">
					<button
						class="btn"
						disabled={naarMachine === 'kader'}
						onclick={() => machineActie('/api/machine/frame', 'kader', 'kader-klaar')}
					>
						{naarMachine === 'kader' ? t('grid.frameRunning') : t('job.frame')}
					</button>
					<button
						class="btn primary"
						disabled={naarMachine === 'start'}
						onclick={() => machineActie('/api/job/start', 'start', 'start-klaar')}
					>
						{naarMachine === 'start' ? t('grid.starting') : t('job.startJob')}
					</button>
				</div>
				{#if naarMachine === 'kader-klaar'}
					<p class="nagekomen">{t('grid.frameDone')}</p>
				{:else if naarMachine === 'start-klaar'}
					<p class="nagekomen">{t('grid.startDone')}</p>
				{/if}
				{#if machineLet}<p class="nagekomen">{t('grid.watchOut', { what: machineLet })}</p>{/if}
				{#if machineFout}<p class="fout" role="alert">{machineFout}</p>{/if}
			</div>
		{/if}

		<div class="actions">
			<button class="btn" disabled={busy} onclick={suggest}>{t('grid.suggestRange')}</button>
			<!-- Form rule v4: the primary button is on the right, the helper on the left.
			     They used to sit next to each other on the left, and then the button that
			     goes into the wood is as prominent as the one that suggests a number. -->
			<span class="rek"></span>
			<!-- E4: without a material this stays an ordinary button. It works — sometimes
			     you *do* want to burn a board without getting a preset out of it — but it
			     does not promise that this is the intended route. -->
			<!-- Once a grid is there, starting is the next step and not yet another grid.
			     Two equally bright buttons side by side make you choose between two things
			     of which only one is at issue. The button on a burned board does not draw,
			     it puts you back at the settings: a second board would otherwise fall on
			     the first. -->
			{#if gelukt}
				<button class="btn" onclick={opnieuw}>{t('grid.another')}</button>
			{:else}
				<button
					class="btn"
					class:primary={!geenMateriaal}
					disabled={busy || !preview || voorbeeldFout !== null}
					onclick={generate}
				>
					{#if busy}
						{t('common.busy')}
					{:else if voorbeeldFout}
						{t('grid.draw')}
					{:else if geenMateriaal}
						{t('grid.drawAnyway')}
					{:else if preview}
						{t('grid.drawWith', {
							cells: preview.cells.length,
							size: `${preview.plan.outer_width_mm ?? preview.plan.width_mm} × ${
								preview.plan.outer_height_mm ?? preview.plan.height_mm
							} mm`
						})}
					{:else}
						{t('grid.draw')}
					{/if}
				</button>
			{/if}
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

	/* Formulierregel v4: het formulier is een stapel regels, geen doorlopend
	   raster van twee kolommen. In dat raster viel elk veld op de eerstvolgende
	   vrije plek, en dus stond "Snelheid van" naast "Kolommen, naar rechts" met
	   "tot" op de regel eronder — twee velden die één waarde zijn, diagonaal uit
	   elkaar getrokken. Nu bepaalt de opmaak wat bij elkaar hoort: `.paar` zet
	   precies twee velden naast elkaar, al het andere staat op zijn eigen regel.
	   Zie DESIGN-SYSTEM v4, "Formulieren". */
	.grid {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		align-content: start;
	}
	.paar {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-3);
		align-items: end;
	}
	.veld { display: grid; gap: 4px; }
	.naam { font-size: var(--text-xs); color: var(--text-2); }
	/* Een as is één uitspraak: van, tot en het aantal stappen horen in één
	   omlijnd blok, want los in de stroom lazen ze als drie losse getallen. */
	.asblok {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		margin: 0;
		padding: var(--space-2) var(--space-3) var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
	}
	.asblok legend { padding: 0 4px; }
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

	/* Instellen en zien wat je instelt, naast elkaar. Onder 720px stapelt het.
	   De voorbeeldkolom heeft een vaste breedte in plaats van `auto`: met
	   `auto` volgde hij de breedte van het bord, dus veranderde hij mee met de
	   labels ("5" tegenover "12.5 mm/s") en schoof het formulier ernaast heen
	   en weer tijdens het typen. Gemeten: 274 → 304 px bij één cijfer erbij. */
	.werkbank {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 292px;
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
	/* De reden dat het voorbeeld even niet meeloopt. Een rustige melding en
	   geen alarm: dit is een tussenstand tijdens het typen, geen fout. */
	.onaf {
		margin: 0 0 var(--space-2);
		padding: var(--space-1h) var(--space-2);
		border-radius: var(--radius-field);
		border-left: 3px solid var(--warn-solid, var(--warn));
		background: color-mix(in srgb, var(--warn-solid, var(--warn)) 12%, transparent);
		font-size: var(--text-xs);
		color: var(--text-1);
	}
	.onaf .stil { color: var(--text-2); }

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
	.actions .rek { flex: 1; }
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
