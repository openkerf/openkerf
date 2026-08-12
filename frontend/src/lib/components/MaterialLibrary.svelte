<script lang="ts">
	import { tick, untrack } from 'svelte';
	import NumberField from './NumberField.svelte';
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

	let zichtbaar = $derived(
		library.presetsFor(materialId).filter((p) => raakt(p, zoek.trim()))
	);

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
			if (materialId !== null && materiaal.id !== materialId) continue;
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
	async function koppelen(paar: Voorstel, aan: boolean) {
		// Onthouden vóór het herrekenen: daarna kent de server dit materiaal en
		// draagt hij het voorstel niet meer aan.
		gezien = { ...gezien, [paar.name]: paar };
		koppel = aan
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
	function past(preset: Preset, laag: DesignOperation | null) {
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
	<article class="preset {bron.tone}">
		<div class="head">
			<div class="what">
				<span class="titel"
					>{#if toonMateriaal}<span class="mat">{preset.material_name}</span>{', '}{/if}{#if preset.thickness_mm !== null}<span
							class="mono dikte">{preset.thickness_mm} mm</span
						>&nbsp;{/if}{operationLabel(preset.operation)}</span
				>
				{#if preset.last_used_at}
					<span class="laatst">{toen(preset.last_used_at)} gebruikt</span>
				{/if}
			</div>
			<span class="badge {bron.tone}" title={bron.means}>
				{@render bronIcoon(bron.icon)}
				{bron.text}
			</span>
		</div>

		<div class="cijfers">
			<div class="param">
				<div class="k">Snelheid</div>
				<div class="v mono">{preset.speed_mm_s} <small>mm/s</small></div>
			</div>
			<div class="param">
				<div class="k">Vermogen</div>
				<div class="v mono">{preset.power_percent} <small>%</small></div>
			</div>
			{#if preset.passes > 1}
				<!-- Eén pass is de regel; die kolom op elke kaart herhalen maakt van
				     een uitzondering ruis. -->
				<div class="param">
					<div class="k">Passes</div>
					<div class="v mono">{preset.passes}</div>
				</div>
			{/if}
			{#if preset.interval_mm && preset.operation === 'graveren-raster'}
				<!-- Zonder lijnafstand is een rasterinstelling niet na te branden;
				     bij de andere bewerkingen bestaat hij niet. -->
				<div class="param">
					<div class="k">Lijnafstand</div>
					<div class="v mono">{preset.interval_mm} <small>mm</small></div>
				</div>
			{/if}
			{#if preset.grid_photo}
				<!-- Het bewijs hoort naast de bewering te staan, niet drie schermen
				     verderop. Klikken opent de herkomst met de foto op formaat. -->
				<button
					class="bewijs"
					onclick={() => (herkomst = herkomst === preset.id ? null : preset.id)}
					title={preset.grid_cell
						? `Het testraster, met vakje rij ${preset.grid_cell.row + 1}, kolom ${preset.grid_cell.column + 1} omcirkeld`
						: 'Foto van het testraster waar deze instelling uit komt'}
				>
					<img src={fotoUrl(preset)} alt="" />
				</button>
			{/if}
		</div>

		<!-- Twijfel hoort niet in een badge alleen. Elke bron krijgt dezelfde
		     regel op dezelfde plek, zodat het verschil zit in wat er staat en
		     niet in of er iets staat — dát is wat je niet over het hoofd ziet. -->
		<p class="raad {bron.tone}">
			{@render bronIcoon(bron.icon)}
			<span>
				{bron.means}{#if preset.source === 'testraster' && preset.grid_date}{' '}({toen(
						preset.grid_date
					)}){/if}.{#if bron.advice}{' '}{bron.advice}{/if}
			</span>
		</p>

		{#if canEdit && !past(preset, chosenOperation)}
			<p class="botst">
				Let op: dit zijn waarden voor {operationLabel(preset.operation).toLowerCase()}. Laag
				{laagNummer} is daar niet voor bedoeld.
			</p>
		{/if}

		{#if canEdit}
			<div class="foot">
				<button
					class="btn primary"
					disabled={library.busy || !chosenOperation}
					title={chosenOperation ? undefined : 'Maak eerst een laag aan in de Lagen-tab'}
					onclick={() => apply(preset)}
				>
					{chosenOperation ? `Toepassen op laag ${laagNummer}` : 'Toepassen'}
				</button>
				<button
					class="mini"
					aria-expanded={herkomst === preset.id}
					onclick={() => (herkomst = herkomst === preset.id ? null : preset.id)}
				>
					{herkomst === preset.id ? 'Herkomst sluiten' : 'Herkomst'}
				</button>
				<button
					class="mini"
					aria-expanded={editing === preset.id}
					onclick={() => (editing = editing === preset.id ? null : preset.id)}
				>
					{editing === preset.id ? 'Klaar met bewerken' : 'Bewerken'}
				</button>
				<span class="rek"></span>
				{#if weghalen === preset.id}
					<span class="zeker">Weg?</span>
					<button class="mini gevaar" onclick={() => library.removePreset(preset.id)}>Ja</button>
					<button class="mini" onclick={() => (weghalen = null)}>Nee</button>
				{:else}
					<button class="mini stil" onclick={() => (weghalen = preset.id)}>Verwijderen</button>
				{/if}
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
						<p class="onder">
							Geen testraster: deze waarden zijn niet gemeten maar ingevoerd.
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
	<select class="picker" aria-label="Materiaal filteren" bind:value={materialId}>
		<option value={null}>Alle materialen</option>
		{#each library.materials as material (material.id)}
			<option value={material.id}>{material.name}</option>
		{/each}
	</select>
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
	{#if operations.length > 1}
		<label class="doel">
			<span>Toepassen op</span>
			<select bind:value={targetOperation}>
				{#each operations as op, index (op.id)}
					<option value={op.id}>Laag {index + 1} · {op.label}</option>
				{/each}
			</select>
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
	<!-- Onlangs gebruikt is een snelkoppeling voor wie bladert. Wie zoekt of
	     al op één materiaal gefilterd heeft, krijgt er alleen dubbele kaarten
	     van. -->
	{#if recent.length && !zoek.trim() && materialId === null}
		<section>
			<h2 class="kop">
				Onlangs gebruikt <span class="hint">— staan hieronder ook bij hun materiaal</span>
			</h2>
			{#each recent as preset (preset.id)}
				{@render kaart(preset, true)}
			{/each}
		</section>
	{/if}

	{#each groepen as groep (groep.materialId)}
		<section>
			<div class="band {textuur(groep.naam)}">
				<div class="bandtekst">
					<span class="naam">{groep.naam}</span>
					<span class="aantal mono">
						{groep.presets.length === 0
							? 'nog geen instellingen'
							: `${groep.presets.length} ${groep.presets.length === 1 ? 'instelling' : 'instellingen'}`}
					</span>
				</div>
			</div>
			{#if groep.presets.length === 0}
				<!-- Waar de vraag ontstaat: niemand denkt "ik wil een testraster",
				     men denkt "ik weet niet wat 3 mm berk nodig heeft". -->
				<p class="leeg">
					Een testraster brandt een reeks vakjes op dit materiaal; van het beste vakje
					maak je een instelling die hier komt te staan.
				</p>
				{#if canEdit}
					<button class="btn primary" onclick={() => onMakeGrid?.(groep.materialId)}>
						Testraster maken
					</button>
				{/if}
			{:else}
				{#each groep.presets as preset (preset.id)}
					{@render kaart(preset, false)}
				{/each}
				{#if canEdit}
					<button class="mini raster" onclick={() => onMakeGrid?.(groep.materialId)}>
						Testraster maken voor {groep.naam}
					</button>
				{/if}
			{/if}
		</section>
	{/each}
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
					<li>
						<span>{machine.name}</span>
						<span class="mono">{machine.power_watt ? `${machine.power_watt} W` : ''}</span>
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
	.picker { flex: none; max-width: 40%; }
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
	section + section { margin-top: var(--space-4); }
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
	.mini.raster { margin-top: var(--space-2); }
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
	.band {
		position: relative;
		height: 56px;
		border-radius: var(--radius-card) var(--radius-card) 0 0;
		border: 1px solid var(--line);
		border-bottom: 0;
		overflow: hidden;
		background-color: var(--surface-2);
	}
	.bandtekst {
		position: absolute;
		inset: auto 0 0 0;
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--space-2);
		padding: var(--space-1h) var(--space-3);
		/* Zonder deze sluier haalt witte tekst op een houtnerf geen AA. */
		background: linear-gradient(to top, rgb(0 0 0 / 0.72), rgb(0 0 0 / 0.42) 70%, transparent);
		color: var(--on-color);
	}
	.bandtekst .naam { font-weight: 600; font-size: var(--text-md); }
	.bandtekst .aantal { font-size: var(--text-xs); opacity: 0.85; }
	/* Nerf: twee lagen strepen onder een lichte hoek, met een warme ondergrond. */
	.band.hout {
		background-color: var(--mat-hout);
		background-image:
			repeating-linear-gradient(97deg, rgb(0 0 0 / 0.1) 0 1px, transparent 1px 7px),
			repeating-linear-gradient(93deg, rgb(255 255 255 / 0.13) 0 2px, transparent 2px 15px);
	}
	/* Acryl: glad, met één schuine glans. */
	.band.acryl {
		background-color: var(--mat-acryl);
		background-image: linear-gradient(103deg, rgb(255 255 255 / 0.45) 0 18%, transparent 40%);
	}
	/* Leer: onregelmatige korrel uit gestapelde radiale vlekken. */
	.band.leer {
		background-color: var(--mat-leer);
		background-image:
			radial-gradient(circle at 20% 40%, rgb(0 0 0 / 0.18) 0 2px, transparent 3px),
			radial-gradient(circle at 62% 70%, rgb(0 0 0 / 0.14) 0 3px, transparent 4px),
			radial-gradient(circle at 85% 25%, rgb(255 255 255 / 0.12) 0 2px, transparent 3px);
		background-size: 26px 22px, 33px 29px, 19px 17px;
		background-position: 0 0, 11px 7px, 5px 13px;
	}
	/* Karton: golfprofiel, van opzij gezien. */
	.band.karton {
		background-color: var(--mat-karton);
		background-image: repeating-linear-gradient(90deg, rgb(0 0 0 / 0.13) 0 1px, transparent 1px 9px);
	}
	/* Metaal: geborsteld, met een lopende glans. */
	.band.metaal {
		background-color: var(--mat-metaal);
		background-image:
			repeating-linear-gradient(90deg, rgb(255 255 255 / 0.35) 0 1px, transparent 1px 4px),
			linear-gradient(100deg, transparent 30%, rgb(255 255 255 / 0.4) 48%, transparent 62%);
	}
	.band.onbekend {
		background-image: repeating-linear-gradient(45deg, rgb(0 0 0 / 0.04) 0 6px, transparent 6px 12px);
	}

	.preset {
		position: relative;
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-1);
		box-shadow: var(--lift-1);
		margin-top: var(--space-2);
		padding: var(--space-2) var(--space-3) var(--space-2) calc(var(--space-3) + 4px);
	}
	/* De bron zit ook in de rand van de kaart: bij het scrollen zie je aan de
	   linkerkant welke instellingen gemeten zijn en welke gegokt. */
	.preset::before {
		content: '';
		position: absolute;
		left: 0;
		top: -1px;
		bottom: -1px;
		width: 4px;
		border-radius: var(--radius-card) 0 0 var(--radius-card);
		background: var(--line);
	}
	.preset.ok::before { background: var(--ok); }
	.preset.warn::before { background: var(--warn-solid); }
	/* Direct onder een materiaalband: één doorlopend blok. */
	.band + .preset {
		margin-top: 0;
		border-radius: 0 0 var(--radius-card) var(--radius-card);
	}
	.band + .preset::before { border-radius: 0 0 0 var(--radius-card); }
	.preset + .preset { margin-top: var(--space-2); }

	.head { display: flex; align-items: flex-start; gap: var(--space-2); }
	.what { flex: 1; min-width: 0; }
	.titel { font-weight: 600; }
	.titel .mat { font-weight: 600; }
	.titel .dikte { font-weight: 500; }
	.laatst { display: block; font-size: var(--text-xs); color: var(--text-2); }
	.badge {
		flex: none;
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-size: var(--text-xs);
		font-weight: 600;
		padding: 2px 8px;
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

	.cijfers {
		display: flex;
		align-items: center;
		gap: var(--space-4);
		margin-top: var(--space-2);
	}
	.param { min-width: 0; }
	.param .k {
		font-size: var(--text-xs);
		color: var(--text-2);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.param .v { font-size: var(--text-md); }
	.param .v small { font-size: var(--text-xs); color: var(--text-2); }
	.bewijs {
		margin-left: auto;
		flex: none;
		width: 44px;
		height: 44px;
		padding: 0;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		overflow: hidden;
		background: var(--surface-2);
	}
	.bewijs img { width: 100%; height: 100%; object-fit: cover; display: block; }

	/* Eigen invoer is geen waarschuwing: wel dezelfde regel op dezelfde plek,
	   maar zonder vlak. Wat risico draagt, houdt zijn kleurvlak. */
	.raad.neutral {
		color: var(--text-2);
		background: none;
		padding: 2px 0 0;
	}
	.raad.ok {
		color: var(--ok);
		background: color-mix(in srgb, var(--ok) 9%, transparent);
	}
	.raad,
	.botst {
		display: flex;
		align-items: flex-start;
		gap: var(--space-1h);
		margin: var(--space-2) 0 0;
		padding: var(--space-1h) 8px;
		border-radius: var(--radius-field);
		font-size: var(--text-xs);
		color: var(--warn);
		background: color-mix(in srgb, var(--warn) 10%, transparent);
	}
	.raad .ico { margin-top: 2px; }

	.foot {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		flex-wrap: wrap;
		margin-top: var(--space-2);
	}
	/* Toepassen en verwijderen hebben tegengestelde gevolgen; die horen niet
	   naast elkaar te staan (design system: ≥24px ertussen). */
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
		justify-content: space-between;
		padding: 8px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		margin-bottom: 4px;
		font-size: var(--text-xs);
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
	   deelt daarom hetzelfde raster: wat, van mij, van het bestand. */
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
