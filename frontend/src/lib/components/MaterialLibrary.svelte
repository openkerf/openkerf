<script lang="ts">
	import { tick, untrack } from 'svelte';
	import NumberField from './NumberField.svelte';
	import Menu from './Menu.svelte';
	import type { Menu as MenuList } from '$lib/actions';
	import {
		OPERATION_LAYER,
		OPERATIONS,
		SOURCE_LABEL,
		operationName,
		toen,
		type ImportPreview,
		type ImportResult,
		type PresetConflict,
		type LibraryStore,
		type Preset
	} from '$lib/library.svelte';
	import type { DesignOperation } from '$lib/design.svelte';

	let {
		library,
		operations,
		canEdit = false,
		sheetMaterialId = null,
		sheetMaterialName = null,
		onApplied,
		onMakeGrid,
		token = ''
	}: {
		library: LibraryStore;
		operations: DesignOperation[];
		canEdit?: boolean;
		/** Het materiaal van het vel waarop je werkt (besluit B1). De bibliotheek
		 *  opent daarop gefilterd: je zoekt instellingen voor wat er ín de
		 *  machine ligt, niet voor alles wat je ooit gebrand hebt. */
		sheetMaterialId?: number | null;
		sheetMaterialName?: string | null;
		onApplied?: () => void;
		/** Opent het testrastervenster voor dit materiaal. */
		onMakeGrid?: (materialId: number | null) => void;
		token?: string;
	} = $props();

	// Het venster wordt bij elke opening opnieuw opgebouwd, dus dit is ook echt
	// de stand waarin je hem elke keer aantreft. Bewust alleen de beginwaarde:
	// wisselt het vel terwijl dit openstaat, dan hoort het filter niet onder je
	// handen vandaan te schuiven — vandaar untrack.
	let materialId = $state<number | null>(untrack(() => sheetMaterialId));
	let zoek = $state('');
	let adding = $state(false);
	let newMaterial = $state('');
	let draft = $state({
		material_id: null as number | null,
		operation: 'snijden',
		thickness_mm: '3',
		speed_mm_s: '',
		power_percent: ''
	});
	let targetOperation = $state<string>('');
	let editing = $state<number | null>(null);
	let herkomst = $state<number | null>(null);
	let weghalen = $state<number | null>(null);
	let addingMachine = $state(false);
	let shareError = $state<string | null>(null);
	let machineDraft = $state({ name: '', power_watt: '', lens_mm: '' });

	/**
	 * Het menu op een instelling.
	 *
	 * Herkomst, bewerken, delen en verwijderen stonden als vier knoppen op elke
	 * regel. Ze horen bij één instelling en zijn geen van de vier de handeling
	 * die je hier komt doen, dus staan ze achter één ⋯ — en achter de
	 * rechterklik, net als overal elders in de app.
	 */
	let rijMenu = $state<{ lijst: MenuList; x: number; y: number } | null>(null);

	function presetMenu(preset: Preset): MenuList {
		return [
			{
				items: [
					{
						id: 'toepassen',
						label: chosenOperation ? `Toepassen op laag ${laagNummer}` : 'Toepassen',
						off: chosenOperation ? undefined : 'Maak eerst een laag aan in de tab Lagen',
						run: () => apply(preset)
					}
				]
			},
			{
				items: [
					{
						id: 'herkomst',
						label: 'Herkomst en bewijs',
						on: herkomst === preset.id,
						explain: 'Waar deze waarden vandaan komen',
						run: () => {
							editing = null;
							herkomst = herkomst === preset.id ? null : preset.id;
						}
					},
					{
						id: 'bewerken',
						label: 'Waarden bijstellen',
						on: editing === preset.id,
						off: canEdit ? undefined : 'Vereist een token',
						run: () => {
							herkomst = null;
							editing = editing === preset.id ? null : preset.id;
						}
					},
					{
						id: 'raster',
						label: `Testraster maken voor ${preset.material_name}`,
						off: canEdit ? undefined : 'Vereist een token',
						run: () => onMakeGrid?.(preset.material_id)
					},
					{
						id: 'delen',
						label: 'Delen met Presetariat',
						off: canEdit ? undefined : 'Vereist een token',
						run: () => share(preset)
					}
				]
			},
			{
				items: [
					{
						id: 'weg',
						label: 'Instelling verwijderen',
						off: canEdit ? undefined : 'Vereist een token',
						danger: true,
						run: () => (weghalen = preset.id)
					}
				]
			}
		];
	}

	function opendMenu(event: MouseEvent, preset: Preset) {
		event.preventDefault();
		const doel = event.currentTarget as HTMLElement | null;
		const doos = doel?.getBoundingClientRect();
		rijMenu = {
			lijst: presetMenu(preset),
			// Een klik op de ⋯-knop hangt het menu onder die knop; een rechterklik
			// op de regel hangt het bij de cursor.
			x: event.type === 'contextmenu' || !doos ? event.clientX : doos.left - 180,
			y: event.type === 'contextmenu' || !doos ? event.clientY : doos.bottom + 4
		};
	}

	let chosenOperation = $derived(
		operations.find((o) => o.id === targetOperation) ?? operations[0] ?? null
	);
	let laagNummer = $derived(
		chosenOperation ? operations.findIndex((o) => o.id === chosenOperation.id) + 1 : 0
	);
	$effect(() => {
		const gekozen = chosenOperation;
		if (gekozen && targetOperation !== gekozen.id) targetOperation = gekozen.id;
	});

	const operationLabel = operationName;

	/** Zoeken over alles wat op de kaart staat: naam, dikte, bewerking, notitie. */
	function raakt(preset: Preset, term: string) {
		if (!term) return true;
		const hooiberg = [
			preset.material_name,
			preset.thickness_mm !== null ? `${preset.thickness_mm} mm` : '',
			operationLabel(preset.operation),
			preset.operation,
			preset.note,
			preset.machine_name ?? '',
			SOURCE_LABEL[preset.source].text
		]
			.join(' ')
			.toLowerCase();
		return term
			.toLowerCase()
			.split(/\s+/)
			.filter(Boolean)
			.every((woord) => hooiberg.includes(woord));
	}

	/**
	 * Alle instellingen die aan het zoekwoord en het machinefilter voldoen —
	 * bewust **niet** aan het gekozen materiaal.
	 *
	 * Het materiaal is sinds v4 de lijst links, en die lijst moet alle materialen
	 * blijven tonen: filterde hij zichzelf, dan bleef er na één klik één regel
	 * over en was er geen weg meer naar het volgende materiaal. Het inperken op
	 * materiaal gebeurt in `zichtbarePresets`, aan de rechterkant.
	 */
	let zichtbaar = $derived(library.presetsFor(null).filter((p) => raakt(p, zoek.trim())));

	function gebruikt(preset: Preset) {
		return preset.last_used_at ? Date.parse(`${preset.last_used_at.replace(' ', 'T')}Z`) : 0;
	}

	/**
	 * Wat je gisteren gebruikte, staat vandaag bovenaan.
	 *
	 * Alfabetisch sorteren is eerlijk en onbruikbaar: wie elke dag hetzelfde
	 * multiplex snijdt, scrollde langs acryl, karton en leer om er te komen.
	 */
	let recent = $derived(
		zichtbaar
			.filter((p) => p.last_used_at)
			.sort((a, b) => gebruikt(b) - gebruikt(a))
			.slice(0, 3)
	);

	/** Op welke dikte er gefilterd wordt binnen het gekozen materiaal. */
	let dikte = $state<number | null>(null);
	// Van materiaal wisselen zet het diktefilter terug: een dikte die dit
	// materiaal niet heeft, geeft een leeg paneel zonder dat je ziet waarom.
	$effect(() => {
		void materialId;
		untrack(() => (dikte = null));
	});

	/** De diktes die dit materiaal werkelijk heeft, dun naar dik. */
	let diktes = $derived.by(() => {
		const groep = groepen.find((g) => g.materialId === materialId);
		const waarden = new Set<number | null>();
		for (const preset of groep?.presets ?? []) waarden.add(preset.thickness_mm);
		return [...waarden].sort((a, b) => (a ?? -1) - (b ?? -1));
	});

	/**
	 * Wat er rechts staat, op leesvolgorde: dun naar dik, en binnen een dikte de
	 * gemeten instellingen eerst. Een gemeten waarde is meer waard dan een
	 * geschatte, dus die hoort bovenaan te staan en niet op alfabet.
	 */
	const BRON_ORDE: Record<string, number> = { testraster: 0, presetariat: 1, geextrapoleerd: 2, handmatig: 3 };
	let zichtbarePresets = $derived.by(() => {
		const groep = groepen.find((g) => g.materialId === materialId);
		const lijst = (groep?.presets ?? []).filter((p) => dikte === null || p.thickness_mm === dikte);
		return [...lijst].sort(
			(a, b) =>
				(a.thickness_mm ?? -1) - (b.thickness_mm ?? -1) ||
				(BRON_ORDE[a.source] ?? 9) - (BRON_ORDE[b.source] ?? 9) ||
				a.operation.localeCompare(b.operation, 'nl')
		);
	});

	type Groep = { naam: string; materialId: number; presets: Preset[]; laatst: number };
	let groepen = $derived.by<Groep[]>(() => {
		const kaart = new Map<number, Groep>();
		for (const preset of zichtbaar) {
			let groep = kaart.get(preset.material_id);
			if (!groep) {
				groep = {
					naam: preset.material_name,
					materialId: preset.material_id,
					presets: [],
					laatst: 0
				};
				kaart.set(preset.material_id, groep);
			}
			groep.presets.push(preset);
			groep.laatst = Math.max(groep.laatst, gebruikt(preset));
		}
		// Materialen zonder presets horen er ook bij: zonder die groep is er
		// geen plek waar "testraster maken" logisch staat.
		for (const materiaal of library.materials) {
			if (kaart.has(materiaal.id)) continue;
			if (zoek.trim() && !materiaal.name.toLowerCase().includes(zoek.trim().toLowerCase()))
				continue;
			kaart.set(materiaal.id, {
				naam: materiaal.name,
				materialId: materiaal.id,
				presets: [],
				laatst: 0
			});
		}
		return [...kaart.values()].sort(
			(a, b) => b.laatst - a.laatst || a.naam.localeCompare(b.naam, 'nl')
		);
	});

	async function createMaterial() {
		if (!newMaterial.trim()) return;
		const created = await library.addMaterial(newMaterial.trim());
		if (created) {
			materialId = created.id;
			newMaterial = '';
			adding = false;
		}
	}

	async function createPreset() {
		const doel = draft.material_id ?? materialId;
		if (doel === null) return;
		const created = await library.addPreset({
			material_id: doel,
			operation: draft.operation,
			thickness_mm: draft.thickness_mm === '' ? null : Number(draft.thickness_mm),
			speed_mm_s: Number(draft.speed_mm_s),
			power_percent: Number(draft.power_percent)
		});
		if (created) draft = { ...draft, speed_mm_s: '', power_percent: '' };
	}

	/**
	 * Een eigen preset aandragen bij de gedeelde catalogus.
	 *
	 * De API maakt er een catalogusregel van en levert een voorgevuld voorstel
	 * op GitHub; wij openen dat, zodat de gebruiker zelf ziet wat hij deelt.
	 */
	async function share(preset: Preset) {
		shareError = null;
		const response = await fetch(`/api/presetariat/contribution/${preset.id}`);
		if (!response.ok) {
			shareError = (await response.json().catch(() => null))?.detail ?? 'Delen lukte niet.';
			return;
		}
		const shared = await response.json();
		window.open(shared.issue_url, '_blank', 'noopener');
	}

	async function saveEdit(preset: Preset, fields: Record<string, unknown>) {
		await library.updatePreset(preset.id, fields);
	}

	async function createMachine() {
		if (!machineDraft.name.trim()) return;
		const created = await library.addMachineProfile({
			name: machineDraft.name.trim(),
			power_watt: machineDraft.power_watt === '' ? null : Number(machineDraft.power_watt),
			lens_mm: machineDraft.lens_mm === '' ? null : Number(machineDraft.lens_mm)
		});
		if (created) {
			machineDraft = { name: '', power_watt: '', lens_mm: '' };
			addingMachine = false;
		}
	}

	async function apply(preset: Preset) {
		const target = chosenOperation;
		if (!target) return;
		if (await library.applyTo(preset.id, target.id)) onApplied?.();
	}

	/**
	 * Welke textuur bij een materiaal hoort.
	 *
	 * Op naam raden is grof, maar het alternatief is een veld dat niemand
	 * invult. Onbekend materiaal krijgt een neutrale strook — dat is eerlijker
	 * dan hout suggereren.
	 */
	function textuur(naam: string | null): string {
		const n = (naam ?? '').toLowerCase();
		if (/multiplex|plywood|hout|wood|mdf|berk|populier|eiken/.test(n)) return 'hout';
		if (/acryl|acrylic|plexi|pmma/.test(n)) return 'acryl';
		if (/leer|leather/.test(n)) return 'leer';
		if (/karton|papier|paper|card/.test(n)) return 'karton';
		if (
			/staal|metaal|alu|steel|metal|messing|rvs|inox|chroom|koper|brass|copper|titaan/.test(n)
		)
			return 'metaal';
		return 'onbekend';
	}

	let bezigFoto = $state<number | null>(null);

	async function fotoBij(gridId: number, bestand: File) {
		bezigFoto = gridId;
		try {
			const form = new FormData();
			form.append('file', bestand);
			const response = await fetch(`/api/library/testgrids/${gridId}/photo`, {
				method: 'POST',
				headers: token ? { Authorization: `Bearer ${token}` } : {},
				body: form
			});
			if (response.ok) await library.load();
		} finally {
			bezigFoto = null;
		}
	}

	// ------------------------------------------------ uitwisselen (besluit B7)

	type Voorstel = ImportPreview['samenvoegen']['materials']['similar'][number];

	let voorbeeld = $state<ImportPreview | null>(null);
	let bestandsnaam = $state('');
	let modus = $state<'samenvoegen' | 'vervangen'>('samenvoegen');
	let botsWint = $state<'eigen' | 'bestand'>('eigen');
	/** Welk materiaal uit het bestand op welk eigen materiaal gelegd wordt. */
	let koppel = $state<Record<string, number>>({});
	let wisZeker = $state(false);
	let klaar = $state<ImportResult | null>(null);
	/**
	 * Elk voorstel dat we ooit toonden, ook nadat het aangevinkt is.
	 *
	 * Zodra je koppelt, telt het materiaal als bekend en verdwijnt het uit de
	 * voorstellen van de server — en daarmee zou het vinkje verdwijnen dat je
	 * net zette. Dan is de keuze niet meer terug te draaien zonder afbreken.
	 */
	let gezien = $state<Record<string, Voorstel>>({});
	let voorstellen = $derived.by(() => {
		const lijst = [...(voorbeeld?.samenvoegen.materials.similar ?? [])];
		for (const naam of Object.keys(koppel)) {
			if (gezien[naam] && !lijst.some((p) => p.name === naam)) lijst.push(gezien[naam]);
		}
		return lijst.sort((a, b) => a.name.localeCompare(b.name, 'nl'));
	});

	/** Kwam er iets binnen dat het huidige filter niet laat zien? */
	let verborgen = $state(false);
	let wisselEl = $state<HTMLElement | null>(null);
	let klaarEl = $state<HTMLElement | null>(null);

	/**
	 * Het venster is de scrollbak, en je drukte op een knop onderaan.
	 *
	 * Zonder dit verschijnt het voorbeeld met zijn kop en zijn tellingen bóven
	 * beeld: je landt midden in een beslissing en moet eerst omhoog om te zien
	 * waar hij over gaat.
	 */
	async function naarBoven(welke: 'voorbeeld' | 'klaar') {
		await tick();
		(welke === 'klaar' ? klaarEl : wisselEl)?.scrollIntoView({ block: 'start' });
	}

	async function kiesBestand(bestand: File) {
		klaar = null;
		modus = 'samenvoegen';
		botsWint = 'eigen';
		koppel = {};
		gezien = {};
		wisZeker = false;
		bestandsnaam = bestand.name;
		voorbeeld = await library.uploadBundle(bestand);
		if (voorbeeld) naarBoven('voorbeeld');
	}

	/**
	 * Twee namen voor dezelfde plank aan elkaar knopen.
	 *
	 * Het voorbeeld wordt daarna opnieuw opgehaald: het aantal nieuwe materialen
	 * verandert erdoor, en een telling die niet meebeweegt met je keuze is een
	 * telling die je niet kunt vertrouwen.
	 */
	async function koppelen(paar: Voorstel, on: boolean) {
		// Onthouden vóór het herrekenen: daarna kent de server dit materiaal en
		// draagt hij het voorstel niet meer aan.
		gezien = { ...gezien, [paar.name]: paar };
		koppel = on
			? { ...koppel, [paar.name]: paar.material_id }
			: Object.fromEntries(Object.entries(koppel).filter(([k]) => k !== paar.name));
		if (voorbeeld) {
			const opnieuw = await library.previewBundle(voorbeeld.bundle, koppel);
			if (opnieuw) voorbeeld = opnieuw;
		}
	}

	async function importeren() {
		if (!voorbeeld) return;
		const zichtbaarVoor = library.presets.length;
		const uitkomst = await library.importBundle(voorbeeld.bundle, modus, koppel, botsWint);
		if (uitkomst) {
			// "4 instellingen erbij" terwijl het scherm niet verandert, is geen
			// geruststelling maar een raadsel: ze horen dan bij een andere machine
			// en vallen buiten het filter. Gemeten in plaats van geraden.
			verborgen =
				uitkomst.presets.added > 0 &&
				library.presets.length - zichtbaarVoor < uitkomst.presets.added;
			klaar = uitkomst;
			voorbeeld = null;
			naarBoven('klaar');
		}
	}

	/**
	 * Draagt de kant uit het bestand het betere bewijs?
	 *
	 * "Mijn waarden houden" is de veilige regel, maar niet als jouw waarde
	 * uitgerekend is en die uit het bestand op een raster gebrand. Dan wint de
	 * regel het van de meting, en dat hoort iemand te zien vóór hij kiest.
	 */
	function sterkerBewijs(botsing: PresetConflict) {
		return botsing.theirs.source === 'testraster' && botsing.mine.source !== 'testraster';
	}

	/** "3 instellingen" — en "1 instelling", want dat leest een mens ook. */
	function tel(aantal: number, enkel: string, meer: string) {
		return `${aantal} ${aantal === 1 ? enkel : meer}`;
	}

	/** Wat er aan een machineprofiel hangt; alleen wat er werkelijk is. */
	function bewijs(machine: { presets: number; test_grids: number }) {
		const delen = [];
		if (machine.presets) delen.push(tel(machine.presets, 'instelling', 'instellingen'));
		if (machine.test_grids) delen.push(tel(machine.test_grids, 'raster', 'rasters'));
		return delen.join(' · ');
	}

	/**
	 * De rasterfoto, met het gekozen vakje omcirkeld als we weten welk vakje het was.
	 *
	 * De server tekent de markering in het beeld (`?cell=<rij>-<kolom>`), dus een
	 * gewone `<img>` volstaat en er is hier geen overlay-wiskunde nodig. Zonder
	 * bekend vakje vragen we de foto onbewerkt op — dat is de veilige val-terug.
	 */
	function fotoUrl(preset: Preset) {
		const basis = `/api/library/testgrids/${preset.grid_id}/photo`;
		return preset.grid_cell
			? `${basis}?cell=${preset.grid_cell.row}-${preset.grid_cell.column}`
			: basis;
	}

	/** Past deze preset bij het laagtype waar hij op gezet wordt? */
	function pastBij(preset: Preset, laag: DesignOperation | null) {
		if (!laag) return true;
		const toegestaan = OPERATION_LAYER[preset.operation];
		return !toegestaan || toegestaan.includes(laag.type);
	}
</script>

{#snippet bronIcoon(soort: string)}
	<svg
		class="ico"
		width="13"
		height="13"
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2.2"
		stroke-linecap="round"
		stroke-linejoin="round"
		aria-hidden="true"
	>
		{#if soort === 'check'}
			<circle cx="12" cy="12" r="9" stroke-width="1.9" />
			<path d="M8 12.4l2.6 2.6L16 9.6" />
		{:else if soort === 'alert'}
			<path d="M12 4.5L21 19.5H3z" stroke-width="1.9" stroke-linejoin="round" />
			<path d="M12 10v4" />
			<path d="M12 17h.01" />
		{:else if soort === 'down'}
			<path d="M12 4v11" />
			<path d="M7.5 10.5L12 15l4.5-4.5" />
			<path d="M5 19h14" />
		{:else}
			<path d="M4 20l4-1 10-10-3-3L5 16z" stroke-width="1.9" />
			<path d="M15 6l3 3" />
		{/if}
	</svg>
{/snippet}

{#snippet kaart(preset: Preset, toonMateriaal: boolean)}
	{@const bron = SOURCE_LABEL[preset.source]}
	{@const past = !canEdit || pastBij(preset, chosenOperation)}
	{@const uit = herkomst === preset.id || editing === preset.id}
	<article
		class="preset {bron.tone}"
		class:open={uit}
		role="presentation"
		oncontextmenu={(e) => canEdit && opendMenu(e, preset)}
	>
		<!--
			Eén regel per instelling in plaats van een kaart van 200 px hoog.

			Wat de taak vraagt is vergelijken: welke dikte, welke bewerking, hoe
			hard, en is het gemeten of gegokt. Dat zijn vier dingen en die passen
			op één regel. In de oude kaart stonden dezelfde vier dingen verspreid
			over vier blokken met een tussenkop per waarde, plus een volle alinea
			uitleg en vijf knoppen — samen 200 px, dus twee instellingen per
			schermvulling. Gemeten in de oude opzet: dertien instellingen was
			2 600 px scrollen. Wat er verder over een instelling te weten valt,
			staat er nog steeds, maar pas als je erom vraagt.
		-->
		<div class="rij">
			<div class="wat">
				<span class="maat mono">
					{#if preset.thickness_mm !== null}{preset.thickness_mm} mm{:else}—{/if}
				</span>
				<span class="bewerking">
					{#if toonMateriaal}<span class="mat">{preset.material_name}</span> · {/if}
					{operationLabel(preset.operation)}
				</span>
				{#if !past}
						<!-- De bewerking van deze instelling past niet bij de laag waar hij
						     op gezet zou worden. Dat is een eigenschap van deze regel, dus
						     staat het bij de bewerking — niet als kleur op de knop. Met tien
						     van de dertien regels oranje leest het scherm als tien fouten in
						     plaats van als één mismatch die je zelf koos. -->
						<span
							class="mismatch"
							title="Dit zijn waarden voor {operationLabel(
								preset.operation
							).toLowerCase()}; laag {laagNummer} is een {chosenOperation?.label.toLowerCase()}-laag"
						>
							<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M12 8v5" /><path d="M12 17h.01" /><path d="M10.3 3.9 2.4 18a1.8 1.8 0 0 0 1.6 2.7h16a1.8 1.8 0 0 0 1.6-2.7L13.7 3.9a1.8 1.8 0 0 0-3.4 0Z" /></svg>
						ander soort
					</span>
				{/if}
			</div>

			<div class="waarden mono">
				<span title="Snelheid">{preset.speed_mm_s}<small>mm/s</small></span>
				<span title="Vermogen">{preset.power_percent}<small>%</small></span>
				{#if preset.passes > 1}<span title="Passes">{preset.passes}<small>×</small></span>{/if}
				{#if preset.interval_mm && preset.operation === 'graveren-raster'}
					<span title="Lijnafstand">{preset.interval_mm}<small>mm</small></span>
				{/if}
			</div>

			<!-- De bron als één merk, met de volle uitleg in de tooltip en in de
			     herkomst. De alinea die dit op elke kaart uitschreef was op één
			     kaart nuttig en op dertien ruis. -->
			<span class="badge {bron.tone}" title="{bron.means}{bron.advice ? ' ' + bron.advice : ''}">
				{@render bronIcoon(bron.icon)}
				{bron.text}
			</span>

			{#if preset.grid_photo}
				<button
					class="bewijs"
					aria-label="Foto van het testraster"
					onclick={() => (herkomst = herkomst === preset.id ? null : preset.id)}
					title={preset.grid_cell
						? `Het testraster, met vakje rij ${preset.grid_cell.row + 1}, kolom ${preset.grid_cell.column + 1} omcirkeld`
						: 'Foto van het testraster waar deze instelling uit komt'}
				>
					<img src={fotoUrl(preset)} alt="" />
				</button>
			{:else}
				<span class="geenfoto" aria-hidden="true"></span>
			{/if}

			{#if canEdit}
				<!-- Eén knop die de taak afmaakt, en de rest achter een menu. Er
				     stonden vier knoppen op elke regel — toepassen, herkomst,
				     bewerken, verwijderen — en dan is de knop die je 95 % van de tijd
				     wil, één van de vier. -->
				<button
					class="doe"
					disabled={library.busy || !chosenOperation}
					title={chosenOperation
						? past
							? `Zet snelheid en vermogen op laag ${laagNummer}`
							: `Let op: dit zijn waarden voor ${operationLabel(preset.operation).toLowerCase()}, en laag ${laagNummer} is daar niet voor bedoeld`
						: 'Maak eerst een laag aan in de tab Lagen'}
					onclick={() => apply(preset)}
				>
					Toepassen
				</button>
				<button
					class="meer"
					aria-label="Meer voor deze instelling"
					aria-haspopup="menu"
					title="Meer — of rechterklik op de regel"
					onclick={(e) => opendMenu(e, preset)}
				>
					<svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="12" cy="5" r="1.7" /><circle cx="12" cy="12" r="1.7" /><circle cx="12" cy="19" r="1.7" /></svg>
				</button>
			{/if}
		</div>

		{#if weghalen === preset.id}
			<!-- Bevestigen onder de regel die het raakt, niet in een venster: het
			     is één instelling en de vraag hoort naast wat er weggaat. -->
			<div class="zekerweg" role="alert">
				<span>
					{#if preset.thickness_mm !== null}{preset.thickness_mm} mm {/if}{operationLabel(
						preset.operation
					).toLowerCase()} van {preset.material_name} weggooien?
					{#if preset.source === 'testraster'}Deze is gemeten op een testraster.{/if}
				</span>
				<button class="mini" onclick={() => (weghalen = null)}>Bewaren</button>
				<button class="mini gevaar" onclick={() => library.removePreset(preset.id)}>
					Weggooien
				</button>
			</div>
		{/if}

		{#if herkomst === preset.id}
			<!-- De community-herkomst is een eersteklas element, geen verborgen
			     database: wie, welke machine, welk vakje, welke foto. -->
			<div class="herkomst">
				<dl>
					<dt>Bron</dt>
					<dd>{bron.text} — {bron.means.toLowerCase()}</dd>
					<dt>Machine</dt>
					<dd>{preset.machine_name ?? 'Onbekend — profiel niet gekoppeld'}</dd>
					{#if preset.grid_id}
						<dt>Testraster</dt>
						<dd>
							<!-- Staat de foto ernaast, dan noemt het bijschrift het vakje al;
							     twee regels verder hetzelfde herhalen is ruis. -->
							#{preset.grid_id}{preset.grid_date ? ` · gebrand ${toen(preset.grid_date)}` : ''}{preset.grid_cell &&
							!preset.grid_photo
								? ` · vakje rij ${preset.grid_cell.row + 1}, kolom ${preset.grid_cell.column + 1}`
								: ''}
						</dd>
					{/if}
					{#if preset.note}
						<dt>Notitie</dt>
						<dd>{preset.note}</dd>
					{/if}
					<dt>Luchtassist</dt>
					<dd>{preset.air_assist ? 'aan' : 'uit'}</dd>
					{#if preset.last_used_at}
						<dt>Laatst gebruikt</dt>
						<dd>{toen(preset.last_used_at)}</dd>
					{/if}
				</dl>
				<div class="bewijsvak">
					{#if preset.grid_photo}
						<img
							src={fotoUrl(preset)}
							alt={preset.grid_cell
								? `Foto van testraster ${preset.grid_id}, met vakje rij ${preset.grid_cell.row + 1}, kolom ${preset.grid_cell.column + 1} omcirkeld`
								: `Foto van testraster ${preset.grid_id}`}
						/>
						<p class="onder">
							{#if preset.grid_cell}
								<!-- De markering volgt de uitlijning van het raster; is die niet
								     gezet, dan valt de server terug op het hele beeld en klopt
								     de omtrek bij benadering. Daarom benoemt het bijschrift het
								     vakje, in plaats van te beweren dat de cirkel exact zit. -->
								De omtrek wijst vakje rij {preset.grid_cell.row + 1}, kolom
								{preset.grid_cell.column + 1} aan — daar komen deze waarden uit.
								{#if preset.grid_aligned === false}
									<span class="benadering">
										De uitlijning van deze foto is niet gezet, dus de omtrek is bij
										benadering — lijn het raster uit voor een exacte markering.
									</span>
								{/if}
							{:else}
								Het gebrande raster waar deze waarden uit komen.
							{/if}
						</p>
					{:else if preset.grid_id}
						<p class="onder">
							Van dit raster is nog geen foto. Zonder foto is er niets om de keuze aan
							af te lezen.
						</p>
						{#if canEdit}
							<label class="mini file">
								{bezigFoto === preset.grid_id ? 'bezig…' : 'Foto toevoegen'}
								<input
									type="file"
									accept="image/*"
									capture="environment"
									onchange={(e) => {
										const f = e.currentTarget.files?.[0];
										e.currentTarget.value = '';
										if (f && preset.grid_id) fotoBij(preset.grid_id, f);
									}}
								/>
							</label>
						{/if}
					{:else}
						<!-- Twee verschillende gevallen, en ze mogen niet dezelfde zin
						     krijgen. Zegt de bron "gemeten" maar hangt er geen raster aan,
						     dan is dát het bericht — niet "niet gemeten", want dat spreekt
						     de badge op dezelfde regel tegen. -->
						<p class="onder">
							{#if preset.source === 'testraster'}
								Deze instelling zegt dat hij gemeten is, maar er hangt geen
								testraster aan — bijvoorbeeld omdat hij uit een import komt. Het
								bewijs is er dus niet meer bij.
							{:else}
								Geen testraster: deze waarden zijn niet gemeten maar ingevoerd.
							{/if}
						</p>
						{#if canEdit}
							<button class="mini" onclick={() => onMakeGrid?.(preset.material_id)}>
								Testraster maken
							</button>
						{/if}
					{/if}
					{#if canEdit}
						<button class="mini" onclick={() => share(preset)}>Delen met Presetariat</button>
					{/if}
				</div>
			</div>
		{/if}

		{#if canEdit && editing === preset.id}
			<!-- Materiaal, bewerking en bron liggen vast: dat is de identiteit
			     van een preset, geen instelling. -->
			<div class="edit">
				<NumberField
					label="Snelheid"
					unit="mm/s"
					step={1}
					min={0.1}
					value={String(preset.speed_mm_s)}
					onchange={(v) => saveEdit(preset, { speed_mm_s: Number(v) })}
				/>
				<NumberField
					label="Vermogen"
					unit="%"
					step={1}
					min={1}
					max={100}
					value={String(preset.power_percent)}
					onchange={(v) => saveEdit(preset, { power_percent: Number(v) })}
				/>
				{#if preset.operation === 'graveren-raster'}
					<NumberField
						label="Lijnafstand"
						unit="mm"
						step={0.01}
						min={0.01}
						value={String(preset.interval_mm ?? '')}
						onchange={(v) => saveEdit(preset, { interval_mm: Number(v) })}
					/>
				{/if}
				<NumberField
					label="Passes"
					step={1}
					min={1}
					value={String(preset.passes)}
					onchange={(v) => saveEdit(preset, { passes: Number(v) })}
				/>
				<NumberField
					label="Dikte"
					unit="mm"
					step={0.5}
					min={0}
					value={String(preset.thickness_mm ?? '')}
					onchange={(v) => saveEdit(preset, { thickness_mm: Number(v) })}
				/>
				<label class="wide"
					><span>Notitie</span>
					<input
						type="text"
						value={preset.note}
						placeholder="bijv. schone onderkant, geen schroeirand"
						onchange={(e) => saveEdit(preset, { note: e.currentTarget.value })}
					/>
				</label>
				<label class="wide"
					><span>Machineprofiel</span>
					<select
						value={preset.machine_name ?? ''}
						onchange={(e) => {
							const found = library.machines.find((m) => m.name === e.currentTarget.value);
							saveEdit(preset, { machine_id: found?.id ?? null });
						}}
					>
						<option value="">—</option>
						{#each library.machines as machine (machine.id)}
							<option value={machine.name}>{machine.name}</option>
						{/each}
					</select>
				</label>
			</div>
		{/if}
	</article>
{/snippet}

{#if voorbeeld}
	<!-- Het importvoorbeeld neemt het hele venster over. Dit is het moment
	     waarop de beslissing valt; ernaast blijven bladeren door de bibliotheek
	     die je op het punt staat te overschrijven, helpt niemand. -->
	{@const s = voorbeeld.samenvoegen}
	<section class="wissel" bind:this={wisselEl}>
		<header class="wisselkop">
			<h2>Dit gaat er gebeuren</h2>
			<p class="bron">
				<span class="mono">{bestandsnaam}</span>
				{#if voorbeeld.exported_at}
					<span class="scheiding">·</span> geëxporteerd {toen(voorbeeld.exported_at)}
				{/if}
			</p>
			<ul class="inhoud">
				<li>{tel(voorbeeld.bevat.materials, 'materiaal', 'materialen')}</li>
				<li>{tel(voorbeeld.bevat.presets, 'instelling', 'instellingen')}</li>
				<li>{tel(voorbeeld.bevat.machines, 'machineprofiel', 'machineprofielen')}</li>
				<li>{tel(voorbeeld.bevat.test_grids, 'testraster', 'testrasters')}</li>
				<li class:mist={voorbeeld.bevat.photos === 0}>
					{tel(voorbeeld.bevat.photos, 'foto', "foto's")}
				</li>
			</ul>
			<!-- Waar het naast komt te liggen. Zonder dit zijn "6 instellingen"
			     zes losse getallen; ernaast is het een verhouding. -->
			<p class="nu">
				Je bibliotheek nu: {tel(voorbeeld.huidig.materials, 'materiaal', 'materialen')} ·
				{tel(voorbeeld.huidig.presets, 'instelling', 'instellingen')} ·
				{tel(voorbeeld.huidig.test_grids, 'testraster', 'testrasters')}
			</p>
		</header>

		<!-- De twee keuzes staan naast elkaar en dragen allebei hun gevolg, zodat
		     "vervangen" niet per ongeluk gekozen wordt omdat het korter klinkt. -->
		<div class="keuzes">
			<label class="keuze" class:aan={modus === 'samenvoegen'}>
				<input type="radio" name="importmodus" value="samenvoegen" bind:group={modus} />
				<span class="titelklein">Samenvoegen</span>
				<span class="uitleg">Wat je hebt blijft staan; wat er nog niet is komt erbij.</span>
			</label>
			<label class="keuze gevaar" class:aan={modus === 'vervangen'}>
				<input type="radio" name="importmodus" value="vervangen" bind:group={modus} />
				<span class="titelklein">Vervangen</span>
				<span class="uitleg">Je huidige bibliotheek gaat weg en wordt dit bestand.</span>
			</label>
		</div>

		{#if modus === 'samenvoegen'}
			<ul class="gevolg">
				{#if s.materials.new.length}
					<li class="erbij">
						<strong>{tel(s.materials.new.length, 'nieuw materiaal', 'nieuwe materialen')}</strong>
						<span class="fijn">{s.materials.new.join(', ')}</span>
					</li>
				{/if}
				{#if s.materials.existing.length}
					<li class="zelfde">
						{tel(s.materials.existing.length, 'materiaal', 'materialen')} herkend als wat je al hebt
					</li>
				{/if}
				{#if s.presets.new}
					<li class="erbij">
						<strong>{tel(s.presets.new, 'instelling', 'instellingen')} erbij</strong>
					</li>
				{/if}
				{#if s.presets.identical}
					<li class="zelfde">
						{tel(s.presets.identical, 'instelling is', 'instellingen zijn')} identiek — die blijven
						zoals ze zijn
					</li>
				{/if}
				{#if s.test_grids.new}
					<li class="erbij">
						<strong>{tel(s.test_grids.new, 'testraster', 'testrasters')} erbij</strong>
						<span class="fijn">met de foto's die erbij horen</span>
					</li>
				{/if}
				{#if s.machines.new.length}
					<li class="erbij">
						<strong
							>{tel(s.machines.new.length, 'machineprofiel', 'machineprofielen')} erbij</strong
						>
						<span class="fijn">{s.machines.new.join(', ')}</span>
					</li>
				{/if}
				{#if !s.materials.new.length && !s.presets.new && !s.test_grids.new && !s.presets.conflicts.length}
					<li class="zelfde">
						Er komt niets bij: dit bestand staat al helemaal in je bibliotheek.
					</li>
				{/if}
			</ul>

			{#if voorstellen.length}
				<!-- De valkuil uit M5: "Berkentriplex" en "Multiplex berken" zijn één
				     plank. Zelf samenvoegen zou een gok zijn met andermans getallen op
				     jouw materiaal; aanwijzen mag de gebruiker wel. -->
				<div class="blok">
					<h3>Zelfde plank, andere naam?</h3>
					<p class="fijn">
						Deze materialen uit het bestand lijken op iets wat je al hebt. Samenvoegen
						zet hun instellingen bij het materiaal dat je al kent; laat je het staan,
						dan komen er twee.
					</p>
					{#each voorstellen as paar (paar.name)}
						<label class="samenvoeg">
							<input
								type="checkbox"
								checked={koppel[paar.name] === paar.material_id}
								onchange={(e) => koppelen(paar, e.currentTarget.checked)}
							/>
							<span>
								<strong>{paar.name}</strong> samenvoegen met <strong>{paar.match}</strong>
								<span class="fijn">— {paar.why}</span>
							</span>
						</label>
					{/each}
				</div>
			{/if}

			{#if s.presets.conflicts.length}
				<div class="blok bots">
					<h3>{tel(s.presets.conflicts.length, 'instelling botst', 'instellingen botsen')}</h3>
					<p class="fijn">
						Dezelfde plank, dezelfde snede, andere getallen. Kies wie wint — je eigen
						waarden zijn op jouw machine gemeten.
					</p>
					<div class="wint">
						<label class="bereik">
							<input type="radio" name="botsing" value="eigen" bind:group={botsWint} />
							<span>Mijn waarden houden</span>
						</label>
						<label class="bereik">
							<input type="radio" name="botsing" value="bestand" bind:group={botsWint} />
							<span>Die uit het bestand overnemen</span>
						</label>
					</div>
					<ul class="botsingen">
						{#each s.presets.conflicts as botsing (`${botsing.material}-${botsing.operation}-${botsing.thickness_mm}`)}
							<li>
								<span class="wat">
									{botsing.material}{botsing.thickness_mm !== null
										? `, ${botsing.thickness_mm} mm`
										: ''} · {operationLabel(botsing.operation)}
								</span>
								<span class="paar">
									<span class="kant" class:wint={botsWint === 'eigen'}>
										<span class="k">Van mij</span>
										<span class="mono"
											>{botsing.mine.speed_mm_s} mm/s · {botsing.mine.power_percent}%</span
										>
									</span>
									<span class="pijl" aria-hidden="true">→</span>
									<span class="kant" class:wint={botsWint === 'bestand'}>
										<span class="k">Uit het bestand</span>
										<span class="mono"
											>{botsing.theirs.speed_mm_s} mm/s · {botsing.theirs.power_percent}%</span
										>
									</span>
								</span>
								{#if sterkerBewijs(botsing)}
									<span class="beter">
										Die uit het bestand is op een testraster gebrand; die van jou is
										{SOURCE_LABEL[botsing.mine.source as Preset['source']]?.text.toLowerCase() ??
											botsing.mine.source}.
									</span>
								{/if}
							</li>
						{/each}
					</ul>
				</div>
			{/if}
		{:else}
			<div class="blok wis">
				<h3>Dit wist wat je nu hebt</h3>
				<p>
					{tel(voorbeeld.vervangen.removes.materials, 'materiaal', 'materialen')},
					{tel(voorbeeld.vervangen.removes.presets, 'instelling', 'instellingen')} en
					{tel(voorbeeld.vervangen.removes.test_grids, 'testraster', 'testrasters')} verdwijnen,
					met de foto's die erbij horen. Dat is niet terug te draaien.
				</p>
				<!-- Het advies moet hier op te volgen zijn. Anders staat er "maak
				     eerst een back-up" op een scherm dat je moet verlaten om er een
				     te maken, en dan doet niemand het. -->
				<p class="fijn">
					Wil je hem nog kunnen terughalen?
					<button class="mini" onclick={() => library.exportBundle()}>
						Exporteer hem eerst
					</button>
				</p>
				<label class="samenvoeg">
					<input type="checkbox" bind:checked={wisZeker} />
					<span>Ja, wis mijn bibliotheek en zet dit bestand ervoor in de plaats.</span>
				</label>
			</div>
		{/if}

		{#if library.error}
			<p class="error" role="alert">{library.error}</p>
		{/if}

		<div class="acties">
			<button
				class="btn primary"
				class:danger={modus === 'vervangen'}
				disabled={library.busy || (modus === 'vervangen' && !wisZeker)}
				onclick={importeren}
			>
				{modus === 'vervangen' ? 'Wissen en importeren' : 'Samenvoegen'}
			</button>
			<button class="btn" onclick={() => (voorbeeld = null)}>Annuleren</button>
		</div>
	</section>
{:else}

{#if klaar}
	<!-- Wat er daadwerkelijk gebeurd is, in dezelfde woorden als het voorbeeld. -->
	<div class="klaar" role="status" bind:this={klaarEl}>
		<strong>
			{klaar.mode === 'vervangen' ? 'Bibliotheek vervangen' : 'Bibliotheek samengevoegd'}
		</strong>
		<span>
			{tel(klaar.presets.added, 'instelling', 'instellingen')} erbij{klaar.presets.updated
				? `, ${tel(klaar.presets.updated, 'bijgewerkt', 'bijgewerkt')}`
				: ''}{klaar.presets.skipped
				? `, ${klaar.presets.skipped} ongewijzigd gelaten`
				: ''} · {tel(klaar.test_grids, 'testraster', 'testrasters')}.
		</span>
		{#if verborgen && library.activeMachine}
			<span class="fijn">
				Een deel hoort bij een andere machine; zet “Alleen {library.activeMachine.name}” uit om
				het te zien.
			</span>
		{/if}
		<button class="mini" onclick={() => (klaar = null)}>Sluiten</button>
	</div>
{/if}

<!-- Filters over een lege verzameling zijn meubilair: drie bedieningen die
     niets te bedienen hebben, boven een venster dat zegt dat er niets is. Bij
     een lege bibliotheek verdwijnen ze en houdt de uitnodiging het woord. -->
{#if library.materials.length > 0}
<div class="kopblok">
	<div class="balk">
	<input
		class="zoek"
		type="search"
		bind:value={zoek}
		placeholder="Zoek materiaal, dikte of bewerking"
		aria-label="Zoeken in de bibliotheek"
	/>
	<!-- Hier stond een keuzelijst "Alle materialen". Die deed precies hetzelfde
	     als de lijst links, en twee bedieningen voor één keuze levert vooral de
	     vraag op welke van de twee de echte is. De lijst won: die toont ook hoe
	     véél instellingen een materiaal heeft, en welk materiaal op het vel ligt. -->
	{#if canEdit}
		<button class="btn" onclick={() => (adding = !adding)}>
			{adding ? 'Annuleren' : 'Nieuw materiaal'}
		</button>
	{/if}
</div>

<div class="context">
	<!-- De twee inperkingen horen bij elkaar: samen zeggen ze "dit is wat er bij
	     deze laser en dit vel hoort". Los van elkaar aan de twee uiteinden van
	     de balk leest het als twee losse instellingen. -->
	<div class="filters">
	{#if sheetMaterialId !== null && sheetMaterialName}
		<!-- Dezelfde schakelaar als "alleen deze machine", want het is dezelfde
		     soort inperking: een preset geldt voor één laser op één materiaal.
		     Uitzetten toont de rest — dit filter is een startpunt, geen muur. -->
		<label class="bereik">
			<input
				type="checkbox"
				checked={materialId === sheetMaterialId}
				onchange={(e) => (materialId = e.currentTarget.checked ? sheetMaterialId : null)}
			/>
			<span>Alleen {sheetMaterialName} <span class="waarom">— van dit vel</span></span>
		</label>
	{/if}
	{#if library.activeMachine}
		<!-- Een preset geldt voor één laser op één materiaal. Standaard zie je
		     die van de machine die nu aanstaat; de rest is één vinkje weg. -->
		<label class="bereik">
			<input
				type="checkbox"
				checked={library.onlyThisMachine}
				onchange={() => library.toggleScope()}
			/>
			<span>Alleen {library.activeMachine.name}</span>
		</label>
	{/if}
	</div>
	<!-- Het doel stond er alleen bij twee of meer lagen. Maar "Toepassen" moet
	     altijd zeggen wáárop, ook als er één laag is: anders is de knop een
	     belofte zonder adres, en dan is de waarschuwing dat de bewerking niet
	     past ook niet te plaatsen. -->
	{#if operations.length}
		<label class="doel">
			<span>Toepassen op</span>
			{#if operations.length > 1}
				<select bind:value={targetOperation}>
					{#each operations as op, index (op.id)}
						<option value={op.id}>Laag {index + 1} · {op.label}</option>
					{/each}
				</select>
			{:else}
				<strong>Laag 1 · {operations[0].label}</strong>
			{/if}
		</label>
	{/if}
	</div>
</div>
{/if}

<!-- Alleen zinnig als er iets toe te passen valt. Bij een lege bibliotheek stond
     deze uitleg over lagen bóven de mededeling dat er nog geen materialen zijn:
     twee keer "je hebt niets", in de verkeerde volgorde, en het antwoord op een
     vraag die je nog niet gesteld had. -->
{#if canEdit && operations.length === 0 && library.materials.length > 0}
	<!-- Eén keer zeggen waarom "Toepassen" niet kan, niet op elke kaart opnieuw. -->
	<p class="melding">
		Er is nog geen laag om een instelling op te zetten. Maak er een aan in de tab
		Lagen; daarna zet één tik de snelheid en het vermogen erop.
	</p>
{/if}

{#if shareError}
	<p class="error" role="alert">{shareError}</p>
{/if}
{#if library.error}
	<p class="error" role="alert">{library.error}</p>
{/if}

{#if adding}
	<div class="row">
		<input type="text" bind:value={newMaterial} placeholder="bijv. Multiplex berken" />
		<button class="btn primary" disabled={library.busy || !newMaterial.trim()} onclick={createMaterial}>
			Opslaan
		</button>
	</div>
{/if}

{#if library.materials.length === 0}
	<!-- Een lege bibliotheek was één grijze alinea onderaan een venster vol
	     filters die niets te filteren hadden. Dit is het eerste wat een nieuwe
	     gebruiker hier ziet, dus krijgt het de vorm van een uitnodiging: wat dit
	     is, waarom het de moeite waard is, en de twee wegen naar binnen. -->
	<div class="onthaal">
		<h2>Nog geen materialen</h2>
		<p>
			Hier leg je vast wat op jóuw laser werkt: per materiaal en dikte een
			snelheid en een vermogen, met de foto van het testraster waar ze uit
			komen. De volgende keer 3 mm berk is daarmee één tik werk in plaats van
			opnieuw uitzoeken.
		</p>
		<div class="wegen">
			{#if canEdit}
				<button class="btn primary" onclick={() => (adding = true)}>
					Eerste materiaal toevoegen
				</button>
			{/if}
			<p class="fijn">
				Of haal er een op uit het Presetariat — dat is de gedeelde catalogus van
				andere lasers.
			</p>
		</div>
	</div>
{:else if groepen.length === 0}
	<!-- Niets gevonden is geen doodlopende weg zolang je de zoekopdracht kunt
	     weggooien zonder het veld te zoeken. -->
	<div class="onthaal smal">
		<h2>Niets gevonden voor “{zoek}”</h2>
		<p>
			De bibliotheek bevat {library.materials.length}
			{library.materials.length === 1 ? 'materiaal' : 'materialen'}. Zoek op de
			materiaalnaam zelf — “berk” vindt meer dan “berken 3mm snijden”.
		</p>
		<button class="btn" onclick={() => (zoek = '')}>Zoekopdracht wissen</button>
	</div>
{:else}
	<!--
		Twee panelen in plaats van één lange kolom.

		De taak is "vind de instelling voor wat er in de machine ligt". Dat is
		eerst een materiaal kiezen en dan één regel aanwijzen. In de oude opzet
		stonden álle materialen onder elkaar met álle instellingen uitgeklapt, dus
		was stap één scrollen en stap twee opnieuw scrollen. Nu staat links wát je
		hebt en rechts wát erbij hoort — de vorm die LightBurn en xTool er beide
		voor gebruiken, en de vorm die past bij de vraag.
	-->
	<div class="tweeluik">
		<nav class="materialen" aria-label="Materialen">
			<ul>
				<!-- Onlangs gebruikt is de eerste regel en geen aparte sectie met
				     dubbele kaarten: het is een kéuze in dezelfde lijst. -->
				{#if recent.length}
					<li>
						<button
							class="matrij"
							class:aan={materialId === null && !zoek.trim()}
							onclick={() => {
								materialId = null;
								zoek = '';
							}}
						>
							<span class="matnaam">Onlangs gebruikt</span>
							<span class="mataantal mono">{recent.length}</span>
						</button>
					</li>
				{/if}
				{#each groepen as groep (groep.materialId)}
					<li>
						<button
							class="matrij"
							class:aan={materialId === groep.materialId}
							onclick={() => (materialId = groep.materialId)}
							oncontextmenu={(e) => {
								e.preventDefault();
								rijMenu = {
									x: e.clientX,
									y: e.clientY,
									lijst: [
										{
											items: [
												{
													id: 'alleen',
													label: 'Alleen dit materiaal tonen',
													on: materialId === groep.materialId,
													run: () => (materialId = groep.materialId)
												},
												{
													id: 'grid',
													label: 'Testraster maken',
													off: canEdit ? undefined : 'Vereist een token',
													run: () => onMakeGrid?.(groep.materialId)
												}
											]
										}
									]
								};
							}}
						>
							<span class="matnaam">{groep.naam}</span>
							{#if groep.materialId === sheetMaterialId}
								<!-- Wát er in de machine ligt is de reden dat je hier bent; dat
								     hoort in de lijst te staan en niet alleen in een filtervinkje. -->
								<span class="ligt" title="Het materiaal van dit vel">op het vel</span>
							{/if}
							<span class="mataantal mono">{groep.presets.length}</span>
						</button>
					</li>
				{/each}
			</ul>
		</nav>

		<div class="instellingen">
			{#if materialId === null}
				{#if recent.length}
					<h2 class="kop">Onlangs gebruikt</h2>
					{#each recent as preset (preset.id)}
						{@render kaart(preset, true)}
					{/each}
					<p class="fijn">
						Kies links een materiaal voor alles wat daarbij hoort.
					</p>
				{:else}
					{#each groepen as groep (groep.materialId)}
						{#each groep.presets as preset (preset.id)}
							{@render kaart(preset, true)}
						{/each}
					{/each}
				{/if}
			{:else}
				{@const groep = groepen.find((g) => g.materialId === materialId)}
				{#if groep}
					<div class="materiaalkop">
						<h2 class="kop">{groep.naam}</h2>
						{#if canEdit}
							<button class="mini" onclick={() => onMakeGrid?.(groep.materialId)}>
								Testraster maken
							</button>
						{/if}
					</div>

					{#if diktes.length > 1}
						<!-- Dikte is de tweede vraag die iedereen stelt en de eerste die je
						     kunt afvinken. Als filter en niet als kop, want je wil de
						     buurdikte er soms bij zien staan. -->
						<div class="diktes" role="group" aria-label="Dikte">
							<button class="chip" class:aan={dikte === null} onclick={() => (dikte = null)}>
								Alle diktes
							</button>
							{#each diktes as d (d)}
								<button class="chip" class:aan={dikte === d} onclick={() => (dikte = d)}>
									{d === null ? 'geen dikte' : `${d} mm`}
								</button>
							{/each}
						</div>
					{/if}

					{#if zichtbarePresets.length === 0}
						<p class="leeg">
							{#if groep.presets.length === 0}
								Nog geen instellingen voor {groep.naam}. Een testraster brandt een reeks
								vakjes op dit materiaal; van het beste vakje maak je een instelling die
								hier komt te staan.
							{:else}
								Geen instelling voor {dikte} mm. Kies een andere dikte, of brand er een
								testraster voor.
							{/if}
						</p>
						{#if canEdit}
							<button class="btn primary" onclick={() => onMakeGrid?.(groep.materialId)}>
								Testraster maken
							</button>
						{/if}
					{:else}
						{#each zichtbarePresets as preset (preset.id)}
							{@render kaart(preset, false)}
						{/each}
					{/if}
				{/if}
			{/if}
		</div>
	</div>
{/if}

{#if canEdit && library.materials.length}
	<details class="vouw">
		<summary>Instelling met de hand toevoegen</summary>
		<div class="grid">
			<label class="wide">
				<span>Materiaal</span>
				<select bind:value={draft.material_id}>
					<option value={null}>{materialId === null ? 'Kies een materiaal' : 'Gefilterde materiaal'}</option>
					{#each library.materials as material (material.id)}
						<option value={material.id}>{material.name}</option>
					{/each}
				</select>
			</label>
			<label>
				<span>Bewerking</span>
				<select bind:value={draft.operation}>
					{#each OPERATIONS as op (op.value)}
						<option value={op.value}>{op.label}</option>
					{/each}
				</select>
			</label>
			<NumberField label="Dikte" unit="mm" step={0.5} min={0} bind:value={draft.thickness_mm} />
			<NumberField label="Snelheid" unit="mm/s" step={1} min={0.1} bind:value={draft.speed_mm_s} />
			<NumberField label="Vermogen" unit="%" step={1} min={1} max={100} bind:value={draft.power_percent} />
		</div>
		<p class="fijn">
			Met de hand ingevoerd betekent: niet gemeten. Deze instelling krijgt daarom de
			badge “Handmatig”.
		</p>
		<button
			class="btn"
			disabled={library.busy ||
				!draft.speed_mm_s ||
				!draft.power_percent ||
				(draft.material_id ?? materialId) === null}
			onclick={createPreset}
		>
			Opslaan
		</button>
	</details>

	<details class="vouw">
		<summary>Machineprofielen ({library.machines.length})</summary>
		<p class="fijn">
			Een instelling is pas herbruikbaar als je weet op welke machine hij gemaakt is —
			daarom staat het profiel los van de instelling.
		</p>
		{#if library.machines.length}
			<ul class="profiles">
				{#each library.machines as machine (machine.id)}
					{@const leeg = machine.presets + machine.test_grids === 0}
					{@const actief = machine.id === library.activeMachine?.id}
					<li class:verweesd={machine.orphaned}>
						<span>{machine.name}</span>
						<span class="mono">{machine.power_watt ? `${machine.power_watt} W` : ''}</span>
						{#if machine.orphaned}
							<!-- Er hoort geen ingestelde machine meer bij dit profiel. -->
							<span
								class="merk"
								title="Er is geen ingestelde machine (meer) die bij dit profiel hoort"
							>
								geen machine
							</span>
						{/if}
						{#if !leeg}
							<!-- Wát eraan hangt, want dat bepaalt of hij weg kan: een profiel
							     met instellingen of rasters is bewijs, een profiel zonder is
							     rommel. Alleen noemen wat er is — "0 instellingen" naast een
							     profiel dat wél een testraster draagt, is een halve waarheid. -->
							<span class="fijn">{bewijs(machine)}</span>
						{:else if canEdit && !actief}
							<button
								class="mini"
								disabled={library.busy}
								onclick={() => library.removeMachineProfile(machine.id)}>Opruimen</button
							>
						{/if}
					</li>
				{/each}
			</ul>
		{/if}
		{#if addingMachine}
			<div class="grid">
				<label class="wide"
					><span>Naam</span><input bind:value={machineDraft.name} placeholder="bijv. 5030 CO2" /></label
				>
				<NumberField label="Vermogen" unit="W" step={5} min={0} bind:value={machineDraft.power_watt} />
				<NumberField label="Lens" unit="mm" step={0.5} min={0} bind:value={machineDraft.lens_mm} />
			</div>
			<button class="btn" disabled={library.busy || !machineDraft.name.trim()} onclick={createMachine}>
				Opslaan
			</button>
		{:else}
			<button class="mini" onclick={() => (addingMachine = true)}>Profiel toevoegen</button>
		{/if}
	</details>
{/if}

<!-- Besluit B7. Buiten het blok hierboven, want importeren in een lege
     bibliotheek is juist de gewone reden om hier te zijn: nieuwe computer. -->
<section class="uitwissel">
	<h3>Bibliotheek uitwisselen</h3>
	<p class="fijn">
		Eén bestand met je materialen, instellingen, machineprofielen en de foto's van je
		testrasters — voor een back-up of een andere computer.
	</p>
	<div class="uitknoppen">
		<button
			class="btn"
			disabled={library.busy || library.materials.length === 0}
			title={library.materials.length === 0 ? 'Er is nog niets om te exporteren' : undefined}
			onclick={() => library.exportBundle()}
		>
			Bibliotheek exporteren
		</button>
		{#if canEdit}
			<label class="btn file">
				Bibliotheek importeren…
				<input
					type="file"
					accept=".openkerf-lib,application/zip"
					onchange={(e) => {
						const f = e.currentTarget.files?.[0];
						e.currentTarget.value = '';
						if (f) kiesBestand(f);
					}}
				/>
			</label>
		{/if}
	</div>
</section>
{/if}

{#if rijMenu}
	<Menu menu={rijMenu.lijst} x={rijMenu.x} y={rijMenu.y} onClose={() => (rijMenu = null)} />
{/if}

<style>
	/* Zoeken moet bereikbaar blijven als je door twintig materialen scrollt;
	   het venster zelf is de scrollbak, dus dit plakt aan zijn bovenkant. */
	.kopblok {
		position: sticky;
		top: calc(-1 * var(--space-4));
		z-index: 2;
		margin: calc(-1 * var(--space-4)) calc(-1 * var(--space-4)) 0;
		padding: var(--space-4) var(--space-4) 0;
		background: var(--surface-1);
	}
	.balk {
		display: flex;
		gap: var(--space-2);
		align-items: center;
	}
	.zoek { flex: 1; min-width: 0; }
	.context {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin-top: var(--space-2);
		padding-bottom: var(--space-2);
		border-bottom: 1px solid var(--line);
	}
	.doel {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.filters {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-2) var(--space-4);
	}
	.bereik {
		display: flex;
		align-items: center;
		gap: var(--space-1h);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	/* Waaróm dit filter aanstaat, in de schakelaar zelf: anders lijkt het een
	   voorkeur die iemand ooit heeft aangezet. */
	.waarom { color: var(--text-2); }
	.kop {
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-2);
		margin: var(--space-4) 0 var(--space-2);
	}
	.leeg { color: var(--text-2); margin: 0 0 var(--space-2); }
	/* Een lege staat mag ruimte innemen: hij is hier het scherm, niet een
	   voetnoot eronder. */
	.onthaal {
		padding: var(--space-6) 0 var(--space-4);
		max-width: 46ch;
	}
	.onthaal.smal { padding: var(--space-5) 0; }
	.onthaal h2 {
		font-size: var(--text-md);
		font-weight: 600;
		margin: 0 0 var(--space-2);
		color: var(--text-1);
	}
	.onthaal p { margin: 0 0 var(--space-3); color: var(--text-2); }
	.wegen { display: grid; justify-items: start; gap: var(--space-3); }
	.wegen .fijn { margin: 0; max-width: 42ch; }
	.fijn { color: var(--text-2); font-size: var(--text-xs); margin: 0 0 var(--space-2); }
	.mini {
		font-size: var(--text-xs);
		color: var(--accent);
		padding: 4px var(--space-1h);
		border-radius: var(--radius-field);
	}
	.mini:hover { background: var(--surface-2); }
	.mini.stil { color: var(--text-2); }
	.mini.gevaar { color: var(--danger); font-weight: 600; }
	.row { display: flex; gap: var(--space-2); margin: var(--space-2) 0; }
	.row input { flex: 1; min-width: 0; }
	input,
	select {
		font: inherit;
		padding: 8px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.btn {
		padding: 8px 12px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		font-weight: 500;
		white-space: nowrap;
	}
	.btn:hover:not(:disabled) { background: var(--surface-2); }
	.btn:disabled { opacity: 0.45; cursor: not-allowed; }
	.btn.primary {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
	}

	/* Materiaal als beeld — maar één keer per materiaal. Tien keer dezelfde
	   houtstrook onder elkaar is behang; één band boven de groep is identiteit. */
	/* Nerf: twee lagen strepen onder een lichte hoek, met een warme ondergrond. */
	/* Acryl: glad, met één schuine glans. */
	/* Leer: onregelmatige korrel uit gestapelde radiale vlekken. */
	/* Karton: golfprofiel, van opzij gezien. */
	/* Metaal: geborsteld, met een lopende glans. */

	/* ── Het tweeluik ────────────────────────────────────────────────────────
	   Links wat je hebt, rechts wat erbij hoort. De linkerkolom is vast: hij
	   moet niet meebewegen zodra je een materiaal met een lange naam aanwijst,
	   want dan schuift de lijst onder je cursor vandaan. */
	.tweeluik {
		display: grid;
		grid-template-columns: 232px minmax(0, 1fr);
		gap: var(--space-4);
		align-items: start;
	}
	.materialen ul {
		margin: 0;
		padding: 0;
		list-style: none;
		display: flex;
		flex-direction: column;
		gap: 1px;
	}
	.matrij {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		width: 100%;
		padding: 7px var(--space-2);
		border: none;
		border-radius: var(--radius-field);
		background: none;
		color: var(--text-1);
		text-align: left;
		font: inherit;
		font-size: var(--text-sm);
	}
	.matrij:hover { background: var(--surface-2); }
	.matrij.aan {
		background: color-mix(in srgb, var(--accent) 12%, transparent);
		color: var(--accent);
		font-weight: 500;
	}
	.matnaam { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.mataantal { flex: none; font-size: var(--text-xs); color: var(--text-2); }
	.matrij.aan .mataantal { color: inherit; }
	/* Wat er in de machine ligt: één woord, niet een tweede kleur. */
	.ligt {
		flex: none;
		font-size: 10px;
		letter-spacing: 0.03em;
		padding: 1px 5px;
		border-radius: var(--radius-dot);
		border: 1px solid color-mix(in srgb, var(--accent) 40%, var(--line));
		color: var(--accent);
		white-space: nowrap;
	}
	.materiaalkop {
		display: flex;
		align-items: baseline;
		gap: var(--space-3);
		margin-bottom: var(--space-2);
	}
	.materiaalkop .kop { margin: 0; }
	.diktes {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1h);
		margin-bottom: var(--space-3);
	}
	.chip {
		padding: 3px 10px;
		border: 1px solid var(--line);
		border-radius: 999px;
		background: var(--surface-1);
		color: var(--text-2);
		font: inherit;
		font-size: var(--text-xs);
	}
	.chip:hover { background: var(--surface-2); color: var(--text-1); }
	.chip.aan {
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 12%, transparent);
		color: var(--accent);
		font-weight: 500;
	}

	/* ── Eén instelling = één regel ──────────────────────────────────────── */
	.preset {
		position: relative;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		margin-top: 4px;
		padding: 0 var(--space-2) 0 calc(var(--space-2) + 4px);
	}
	.preset:first-of-type { margin-top: 0; }
	/* De bron zit ook in de rand: bij het scrollen zie je aan de linkerkant
	   welke instellingen gemeten zijn en welke gegokt. */
	.preset::before {
		content: '';
		position: absolute;
		left: 0;
		top: -1px;
		bottom: -1px;
		width: 4px;
		border-radius: var(--radius-field) 0 0 var(--radius-field);
		background: var(--line);
	}
	.preset.ok::before { background: var(--ok); }
	.preset.warn::before { background: var(--warn-solid); }
	.preset.open {
		border-color: color-mix(in srgb, var(--accent) 45%, var(--line));
		box-shadow: var(--lift-1);
	}

	.rij {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		min-height: 40px;
	}
	.wat { flex: 1; min-width: 0; display: flex; align-items: baseline; gap: var(--space-2); }
	/* De dikte in een eigen kolom van vaste breedte: dat is waar het oog langs
	   loopt als je "3 mm" zoekt, en dan moeten de getallen onder elkaar staan. */
	.maat {
		flex: none;
		width: 4.4em;
		font-weight: 600;
		font-size: var(--text-sm);
	}
	.bewerking {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: var(--text-sm);
	}
	.bewerking .mat { font-weight: 500; }
	.waarden {
		flex: none;
		display: flex;
		gap: var(--space-3);
		font-size: var(--text-sm);
		font-variant-numeric: tabular-nums;
	}
	.waarden span { min-width: 4.2em; text-align: right; }
	.waarden small { color: var(--text-2); margin-left: 1px; }

	.badge {
		flex: none;
		display: inline-flex;
		align-items: center;
		gap: 3px;
		width: 7.6em;
		font-size: var(--text-xs);
		font-weight: 600;
		padding: 1px 6px;
		border-radius: var(--radius-dot);
		border: 1px solid var(--line);
		background: var(--surface-2);
		color: var(--text-2);
		white-space: nowrap;
	}
	.badge.ok {
		background: color-mix(in srgb, var(--ok) 14%, transparent);
		border-color: color-mix(in srgb, var(--ok) 40%, transparent);
		color: var(--ok);
	}
	.badge.warn {
		background: color-mix(in srgb, var(--warn) 16%, transparent);
		border-color: color-mix(in srgb, var(--warn) 45%, transparent);
		color: var(--warn);
	}
	.ico { flex: none; }

	.bewijs,
	.geenfoto {
		flex: none;
		width: 28px;
		height: 28px;
		padding: 0;
		border-radius: var(--radius-field);
		overflow: hidden;
	}
	.bewijs {
		border: 1px solid var(--line);
		background: var(--surface-2);
	}
	.bewijs img { width: 100%; height: 100%; object-fit: cover; display: block; }

	.doe {
		flex: none;
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 5px 12px;
		border: 1px solid var(--accent);
		border-radius: var(--radius-field);
		background: var(--accent);
		color: var(--accent-ink);
		font: inherit;
		font-size: var(--text-xs);
		font-weight: 500;
	}
	.doe:disabled { opacity: 0.4; cursor: not-allowed; }
	/* Een instelling voor een ander soort bewerking mag je toepassen, maar niet
	   zonder dat je het weet. Eén teken bij de bewerking, met de hele uitleg in
	   de tooltip. */
	.mismatch {
		display: inline-flex;
		align-items: center;
		gap: 2px;
		margin-left: 4px;
		font-size: 10px;
		font-weight: 600;
		letter-spacing: 0.02em;
		color: var(--warn);
		white-space: nowrap;
	}
	.meer {
		flex: none;
		display: grid;
		place-items: center;
		width: 26px;
		height: 26px;
		border: none;
		border-radius: var(--radius-field);
		background: none;
		color: var(--text-2);
	}
	.meer:hover { background: var(--surface-2); color: var(--text-1); }

	.zekerweg {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		flex-wrap: wrap;
		padding: var(--space-2) 0 var(--space-2);
		border-top: 1px solid var(--line);
		font-size: var(--text-xs);
	}
	.zekerweg span { flex: 1; min-width: 12em; }

	.rek { flex: 1; min-width: var(--space-6); }
	.zeker { font-size: var(--text-xs); color: var(--text-2); }

	.herkomst {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: var(--space-3);
		margin-top: var(--space-2);
		padding-top: var(--space-2);
		border-top: 1px dashed var(--line);
	}
	.herkomst dl {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 2px var(--space-2);
		margin: 0;
		font-size: var(--text-xs);
	}
	.herkomst dt { color: var(--text-2); }
	.herkomst dd { margin: 0; }
	/* Zonder opgeslagen uitlijning valt de server terug op het hele beeld; bij een
	   schuine foto met veel rand ligt de omtrek dan een halve cel mis. Dat zeggen
	   is beter dan een markering die exact lijkt en het niet is. */
	.benadering { display: block; margin-top: 2px; color: var(--warn); }
	.bewijsvak {
		display: grid;
		justify-items: start;
		gap: 4px;
		max-width: 180px;
	}
	.bewijsvak img {
		width: 100%;
		max-width: 160px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
	}
	.bewijsvak .onder { margin: 0; font-size: var(--text-xs); color: var(--text-2); }
	.file { position: relative; overflow: hidden; }
	.file input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }

	.edit {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-2);
		margin-top: var(--space-2);
		padding-top: var(--space-2);
		border-top: 1px dashed var(--line);
	}
	.edit label { display: grid; gap: 4px; font-size: var(--text-xs); color: var(--text-2); }
	.edit label.wide { grid-column: 1 / -1; }
	.edit input,
	.edit select { width: 100%; }

	.vouw {
		margin-top: var(--space-4);
		padding-top: var(--space-3);
		border-top: 1px solid var(--line);
	}
	.vouw summary {
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-2);
		cursor: pointer;
		margin-bottom: var(--space-2);
	}
	.profiles { list-style: none; margin: var(--space-2) 0; padding: 0; }
	.profiles li {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: 8px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		margin-bottom: 4px;
		font-size: var(--text-xs);
	}
	/* De naam duwt de rest naar rechts; zo staan het vermogen en het merkje
	   op één lijn, ook als het ene profiel wel een merkje heeft en het andere niet. */
	.profiles li > span:first-child { flex: 1; min-width: 0; }
	/* Verweesd is geen fout maar wel iets om te weten: gedempt, niet rood. */
	.profiles li.verweesd { border-style: dashed; }
	.profiles li.verweesd > span:first-child { color: var(--text-2); }
	.profiles .merk {
		flex: none;
		padding: 2px 8px;
		border-radius: var(--radius-pill, 999px);
		background: var(--surface-2);
		color: var(--text-2);
		white-space: nowrap;
	}
	.grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-2);
		margin-bottom: var(--space-2);
	}
	.grid label { display: grid; gap: 4px; font-size: var(--text-xs); color: var(--text-2); }
	.grid label.wide { grid-column: 1 / -1; }
	.grid input,
	.grid select { width: 100%; }
	.hint {
		font-weight: 400;
		text-transform: none;
		letter-spacing: 0;
	}
	.melding {
		margin: var(--space-2) 0 0;
		padding: var(--space-2);
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-2);
		color: var(--text-2);
		font-size: var(--text-xs);
	}
	.error {
		margin: var(--space-2) 0;
		padding: var(--space-2);
		border-radius: var(--radius-field);
		background: color-mix(in srgb, var(--danger) 14%, transparent);
		font-size: var(--text-xs);
	}

	/* ------------------------------------------- uitwisselen (besluit B7) */

	.uitwissel {
		margin-top: var(--space-4);
		padding-top: var(--space-3);
		border-top: 1px solid var(--line);
	}
	.uitwissel h3 {
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-2);
		margin: 0 0 var(--space-2);
	}
	.uitwissel .fijn { max-width: 52ch; }
	.uitknoppen { display: flex; gap: var(--space-2); flex-wrap: wrap; }

	/* Het voorbeeld is een eigen scherm, geen strook onder de lijst: hier valt
	   de beslissing, dus krijgt het de ruimte en de leesbreedte ervoor. */
	.wisselkop { margin-bottom: var(--space-4); }
	.wisselkop h2 {
		font-size: var(--text-lg);
		font-weight: 600;
		letter-spacing: -0.01em;
		margin: 0;
		color: var(--text-1);
	}
	.bron { margin: 4px 0 var(--space-3); font-size: var(--text-xs); color: var(--text-2); }
	.scheiding { opacity: 0.5; }
	.inhoud {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1h);
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.inhoud li {
		font-size: var(--text-xs);
		padding: var(--space-1) var(--space-3);
		border-radius: var(--radius-dot);
		border: 1px solid var(--line);
		background: var(--surface-2);
		color: var(--text-2);
	}
	/* Nul foto's is geen detail: dan komt het bewijs niet mee. */
	.inhoud li.mist { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 45%, transparent); }
	.nu { margin: var(--space-2) 0 0; font-size: var(--text-xs); color: var(--text-2); }

	.keuzes {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-2);
	}
	.keuze {
		display: grid;
		grid-template-columns: auto 1fr;
		grid-template-areas: 'radio titel' '. uitleg';
		gap: 2px var(--space-2);
		align-items: start;
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-1);
		cursor: pointer;
	}
	.keuze input { grid-area: radio; margin: 2px 0 0; }
	.keuze .titelklein { grid-area: titel; font-weight: 600; }
	.keuze .uitleg { grid-area: uitleg; font-size: var(--text-xs); color: var(--text-2); }
	.keuze.aan { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }
	.keuze.gevaar.aan {
		border-color: var(--danger);
		box-shadow: inset 0 0 0 1px var(--danger);
		background: color-mix(in srgb, var(--danger) 8%, transparent);
	}

	.gevolg {
		list-style: none;
		margin: var(--space-3) 0 0;
		padding: 0;
		display: grid;
		gap: var(--space-1h);
	}
	.gevolg li {
		display: flex;
		align-items: baseline;
		flex-wrap: wrap;
		gap: var(--space-2);
		padding-left: var(--space-4);
		position: relative;
		font-size: var(--text-sm);
	}
	/* Erbij of ongewijzigd, in vorm en niet alleen in kleur. */
	.gevolg li::before {
		position: absolute;
		left: 0;
		top: 0;
		font-weight: 700;
	}
	.gevolg li.erbij::before { content: '+'; color: var(--ok); }
	.gevolg li.zelfde::before { content: '='; color: var(--text-2); }
	.gevolg li.zelfde { color: var(--text-2); }
	.gevolg .fijn { margin: 0; }

	.blok {
		margin-top: var(--space-3);
		padding: var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-2);
	}
	.blok h3 {
		margin: 0 0 4px;
		font-size: var(--text-sm);
		font-weight: 600;
	}
	.blok.bots { border-color: color-mix(in srgb, var(--warn) 45%, transparent); }
	.blok.wis {
		border-color: color-mix(in srgb, var(--danger) 50%, transparent);
		background: color-mix(in srgb, var(--danger) 9%, transparent);
	}
	.blok.wis p { margin: 0 0 var(--space-2); }
	/* Op aanraakbreedtes is een selectievakje 44px hoog (design system), dus
	   uitlijnen op de bovenkant zet het glyphje een regel onder zijn eigen
	   label. Centreren houdt het naast de tekst op elk apparaat. */
	.samenvoeg {
		display: grid;
		grid-template-columns: auto 1fr;
		align-items: center;
		gap: var(--space-2);
		margin-top: var(--space-2);
		font-size: var(--text-xs);
		cursor: pointer;
	}
	.wint { display: flex; gap: var(--space-4); margin: var(--space-2) 0; }
	.botsingen { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }
	/* Twee waarden vergelijken kan alleen als ze in een kolom staan. Elke regel
	   deelt daarom hetzelfde grid: wat, van mij, van het bestand. */
	.botsingen li {
		display: grid;
		grid-template-columns: 1fr auto auto;
		align-items: start;
		gap: 4px var(--space-3);
		padding: var(--space-2);
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		font-size: var(--text-xs);
	}
	.botsingen .wat { font-weight: 500; }
	.beter { grid-column: 1 / -1; color: var(--warn); }
	.paar { display: contents; }
	.kant {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: 2px;
		color: var(--text-2);
	}
	/* Wie wint is af te lezen zonder de keuze erboven terug te lezen: de
	   winnende kant staat vet en gemarkeerd, de andere blijft leesbaar — het
	   zijn allebei getallen die je wilt kunnen zien. */
	.kant.wint { color: var(--text-1); font-weight: 600; }
	.kant.wint .k::after {
		content: ' ✓';
		color: var(--ok);
	}
	.kant .k {
		font-size: var(--text-xs);
		color: var(--text-2);
		font-weight: 400;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.pijl { display: none; }

	.acties {
		display: flex;
		gap: var(--space-2);
		margin-top: var(--space-4);
		padding-top: var(--space-3);
		border-top: 1px solid var(--line);
	}
	.btn.danger {
		background: var(--danger);
		border-color: var(--danger);
		color: var(--on-color);
	}
	.klaar {
		display: flex;
		align-items: baseline;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin-bottom: var(--space-3);
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-field);
		border: 1px solid color-mix(in srgb, var(--ok) 45%, transparent);
		background: color-mix(in srgb, var(--ok) 12%, transparent);
		font-size: var(--text-xs);
	}
	.klaar .mini { margin-left: auto; }

	@media (max-width: 640px) {
		.keuzes { grid-template-columns: 1fr; }
		.botsingen li { align-items: flex-start; }
		.herkomst { grid-template-columns: 1fr; }
		.edit,
		.grid { grid-template-columns: 1fr; }
	}
</style>
