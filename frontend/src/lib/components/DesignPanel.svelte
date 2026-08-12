<script lang="ts">
	import { LAYER_COLORS, inktOp, type DesignStore } from '$lib/design.svelte';
	import type { EditController } from '$lib/edits.svelte';
	import NumberField from './NumberField.svelte';
	import Segmented from './Segmented.svelte';
	import ArrangeIcon from './ArrangeIcon.svelte';
	import { untrack } from 'svelte';

	let {
		design,
		edits,
		canEdit = false,
		onHistory,
		onRotate,
		onAssign,
		onLayerChange,
		onEditText,
		onArrange,
		onImage,
		onImageDpi,
		onVectorise,
		onCrop,
		box = null,
		onSetPosition,
		onSetSize,
		image = null,
		onImageSet,
		onImageClear,
		onUncrop,
		show = 'selection',
		bed = null,
		otherSheets = [],
		onMoveToSheet
	}: {
		design: DesignStore;
		edits: EditController;
		canEdit?: boolean;
		onHistory?: (action: 'undo' | 'redo') => void;
		onRotate?: (angleDeg: number) => void;
		onAssign?: (operationId: string, assigned: boolean) => void;
		onLayerChange?: () => void;
		onEditText?: (id: string) => void;
		onArrange?: (action: string) => void;
		onImage?: (adjustment: string) => void;
		onImageDpi?: (dpi: number) => void;
		onVectorise?: () => void;
		onCrop?: () => void;
		/** Live maten tijdens het slepen; valt terug op de selectie zelf. */
		box?: { x: number; y: number; width: number; height: number } | null;
		onSetPosition?: (x: number, y: number) => void;
		onSetSize?: (width: number, height: number) => void;
		/** Wat er op de gekozen afbeelding aanstaat; komt van de API. */
		image?: {
			dpi: number | null;
			dither_types: string[];
			adjustments: {
				name: string;
				label: string;
				enabled: boolean;
				ranges: Record<string, number[]>;
				values: Record<string, string | number | boolean>;
			}[];
		} | null;
		onImageSet?: (
			name: string,
			enabled: boolean,
			values: Record<string, unknown> | null
		) => void;
		onImageClear?: () => void;
		onUncrop?: () => void;
		/** Welk deel getoond wordt. Selectie en lagen naast elkaar in één
		 *  paneel werd te druk om iets in terug te vinden. */
		show?: 'selection' | 'layers';
		/** Bedmaat in mm, om te zien of er iets buiten valt. */
		bed?: { width: number; height: number } | null;
		/** De andere vellen, om de selectie naartoe te verhuizen. */
		otherSheets?: { id: string; name: string }[];
		onMoveToSheet?: (sheetId: string) => void;
	} = $props();

	let elements = $derived(design.elements);
	let operations = $derived(design.operations);
	let selected = $derived(design.selected);
	let size = $derived(design.selectedSize);

	// Wat buiten het bed ligt, brandt niet mee en is lastig te pakken. Beter
	// melden met een uitweg dan de gebruiker laten ontdekken dat er iets mist.
	let strays = $derived.by(() => {
		const perMm = design.design?.units_per_mm;
		if (!bed || !perMm) return [];
		return design.elements.filter((element) => {
			if (!element.bounds) return false;
			const [x0, y0, x1, y1] = element.bounds.map((v) => v / perMm);
			return x0 < -0.5 || y0 < -0.5 || x1 > bed.width + 0.5 || y1 > bed.height + 0.5;
		});
	});
	// Tijdens het slepen laat de canvaslaag een voorbeeldkader zien; die maten
	// horen hier dan ook te staan, anders lopen paneel en canvas uit elkaar.
	let live = $derived(box ?? size);

	// Verhouding vasthouden. Zonder dit vervormt een logo zodra je één maat
	// intikt, en dat merk je pas als het gebrand is.
	let linked = $state(true);

	function commitPosition(axis: 'x' | 'y', raw: string) {
		const value = Number(raw);
		if (!live || !Number.isFinite(value)) return;
		onSetPosition?.(axis === 'x' ? value : live.x, axis === 'y' ? value : live.y);
	}

	function commitSize(axis: 'width' | 'height', raw: string) {
		const value = Number(raw);
		if (!live || !Number.isFinite(value) || value <= 0) return;
		if (linked && live.width > 0 && live.height > 0) {
			const factor = value / (axis === 'width' ? live.width : live.height);
			onSetSize?.(live.width * factor, live.height * factor);
			return;
		}
		onSetSize?.(
			axis === 'width' ? value : live.width,
			axis === 'height' ? value : live.height
		);
	}
	let chosen = $derived(design.selectedElements);
	let selectedIds = $derived(design.selectedIds);

	// ------------------------------------------------------------- de stand
	//
	// Draaien en spiegelen waren tot nu toe blinde handelingen: je kon klikken
	// maar niet zien waar je stond, dus elke klik stapelde op de vorige en de
	// enige weg terug was ongedaan maken. De engine wéét de stand — hij bewaart
	// hem in de matrix van elke node — dus die staat nu in de snapshot en het
	// paneel toont hem. Daarmee wordt elke handeling een waarde in plaats van
	// een stap: hetzelfde getal intikken geeft hetzelfde beeld, hoe vaak je ook
	// geklikt hebt.

	/** De hoek van de selectie, of null als de vormen het oneens zijn. */
	let pose = $derived.by(() => {
		const poses = chosen.map((e) => e.pose).filter(Boolean) as {
			angle_deg: number;
			mirrored: boolean;
		}[];
		if (!poses.length) return { angle: null as number | null, mirrored: false, mixed: false };
		const first = poses[0];
		const mixed = poses.some((p) => Math.abs(p.angle_deg - first.angle_deg) > 0.05);
		return {
			angle: mixed ? null : first.angle_deg,
			// Eén gespiegelde vorm in de selectie is genoeg om het te melden;
			// zwijgen zou betekenen dat je het pas op het werkstuk ziet.
			mirrored: poses.some((p) => p.mirrored),
			mixed
		};
	});

	/**
	 * Waar de selectie stond toen je hem pakte.
	 *
	 * Dit is het anker voor "Terugzetten": zolang een selectie actief is, kun
	 * je in één tik terug naar precies de stand van vóór het schikken — niet
	 * naar de vorige klik, maar naar het origineel. Bewust géén schaduwkopie
	 * van het document: elke tik blijft een gewone, ongedaan te maken bewerking
	 * in de engine, en niets stroomafwaarts (job, pre-flight, autosave) kijkt
	 * naar geometrie die er niet echt is.
	 */
	let anchor = $state<{
		key: string;
		angle: number | null;
		mirrored: boolean;
		box: { x: number; y: number; width: number; height: number };
	} | null>(null);

	$effect(() => {
		const key = selectedIds.join(',');
		const start = design.selectedSize;
		const stand = pose;
		untrack(() => {
			if (!key || !start) {
				anchor = null;
				return;
			}
			// Alleen bij een níeuwe selectie opnieuw ankeren. Zou het anker
			// meelopen met elke bewerking, dan was het geen anker maar een
			// spiegel van de laatste klik.
			if (anchor?.key === key) return;
			anchor = { key, angle: stand.angle, mirrored: stand.mirrored, box: { ...start } };
		});
	});

	function near(a: number, b: number, slack = 0.05) {
		return Math.abs(a - b) < slack;
	}

	/** Staat de selectie ergens anders dan waar je hem pakte? */
	let moved = $derived.by(() => {
		if (!anchor || !size) return false;
		if (pose.mirrored !== anchor.mirrored) return true;
		if (pose.angle !== null && anchor.angle !== null && !near(pose.angle, anchor.angle))
			return true;
		return (
			!near(size.x, anchor.box.x) ||
			!near(size.y, anchor.box.y) ||
			!near(size.width, anchor.box.width) ||
			!near(size.height, anchor.box.height)
		);
	});

	/**
	 * In woorden wat er sinds het aanklikken veranderd is.
	 *
	 * Alleen wat de knop ernaast terugdraait, en niet wat er nú staat: de
	 * maten staan al in de velden erboven, en dat twee keer zeggen maakt de
	 * regel langer zonder hem duidelijker te maken.
	 */
	let movedSummary = $derived.by(() => {
		if (!anchor || !size) return '';
		const parts: string[] = [];
		if (pose.angle !== null && anchor.angle !== null && !near(pose.angle, anchor.angle))
			parts.push(`gedraaid naar ${format(pose.angle)}°`);
		if (pose.mirrored !== anchor.mirrored) parts.push('gespiegeld');
		// Draaien om het midden verandert het omhullende kader, dus grootte en
		// plaats alleen melden als er verder níets veranderd is — anders staat
		// er "verplaatst" bij elke draai en betekent het woord niets meer.
		if (!parts.length) {
			if (!near(size.width, anchor.box.width) || !near(size.height, anchor.box.height))
				parts.push('geschaald');
			else if (!near(size.x, anchor.box.x) || !near(size.y, anchor.box.y))
				parts.push('verplaatst');
		}
		return parts.join(' · ') || 'gewijzigd';
	});

	function format(value: number) {
		return value.toFixed(1).replace('.', ',').replace(',0', '');
	}

	async function setAngle(raw: string) {
		const value = Number(raw.replace(',', '.'));
		if (!Number.isFinite(value) || !selectedIds.length) return;
		if ((await edits.rotate(selectedIds, ((value % 360) + 360) % 360, true)).ok)
			await design.load();
	}

	/** Terug naar de stand van vóór het schikken, in één tik. */
	async function restore() {
		if (!anchor || !selectedIds.length) return;
		const ids = selectedIds;
		// Volgorde telt: spiegelen kantelt het teken van de hoek, dus de hoek
		// gaat er daarna overheen, en het kader als laatste — dat zet ook de
		// verschuiving terug die draaien om het midden achterlaat.
		if (pose.mirrored !== anchor.mirrored) await edits.mirror(ids, 'horizontal');
		if (anchor.angle !== null) await edits.rotate(ids, anchor.angle, true);
		const { x, y, width, height } = anchor.box;
		await edits.resize(ids, x, y, width, height);
		await design.load();
	}

	// Wat er open staat van de zelden gebruikte groepen. Onthouden per paneel,
	// niet per selectie: wie booleans gebruikt, gebruikt ze de hele middag.
	let openGroups = $state<Record<string, boolean>>({});

	let editingLayer = $state<string | null>(null);
	let openGrid = $state<number | null>(null);

	// Rasterlagen zijn geen gewone lagen: ze horen bij één testraster en hun
	// snelheid en vermogen zíjn de test. Eén regel per raster dus.
	let plainLayers = $derived(operations.filter((o) => !o.grid));
	let gridGroups = $derived.by(() => {
		const byGrid = new Map<number, typeof operations>();
		for (const op of operations) {
			if (!op.grid) continue;
			const list = byGrid.get(op.grid.grid_id) ?? [];
			list.push(op);
			byGrid.set(op.grid.grid_id, list);
		}
		return [...byGrid.entries()].map(([id, ops]) => ({ id, ops }));
	});

	async function removeGrid(gridId: number) {
		const token =
			typeof localStorage === 'undefined' ? '' : (localStorage.getItem('openkerf.token') ?? '');
		await fetch(`/api/library/testgrids/${gridId}/remove-from-design`, {
			method: 'POST',
			headers: token ? { Authorization: `Bearer ${token}` } : {}
		});
		onLayerChange?.();
	}
	let newLayerType = $state('cut');
	// Een laag weggooien neemt zijn toewijzingen mee. Dat mag niet op één tik
	// naast de snelheidsvelden gebeuren, dus er komt een bevestiging tussen.
	let confirmDrop = $state<string | null>(null);

	const LAYER_TYPES = [
		{ value: 'cut', label: 'Snijden', noun: 'Snijlaag' },
		{ value: 'engrave', label: 'Graveren', noun: 'Graveerlaag' },
		{ value: 'raster', label: 'Raster', noun: 'Rasterlaag' },
		{ value: 'dots', label: 'Punten', noun: 'Puntenlaag' }
	];
	let newLayerNoun = $derived(
		LAYER_TYPES.find((t) => t.value === newLayerType)?.noun ?? 'Laag'
	);

	async function addLayer() {
		if (await edits.addLayer(newLayerType)) onLayerChange?.();
	}

	async function patchLayer(id: string, fields: Record<string, unknown>) {
		if (await edits.updateLayer(id, fields)) onLayerChange?.();
	}

	async function moveLayer(id: string, direction: 'up' | 'down') {
		if (await edits.moveLayer(id, direction)) onLayerChange?.();
	}

	async function dropLayer(id: string) {
		confirmDrop = null;
		if (await edits.removeLayer(id)) onLayerChange?.();
	}

	/** Het soort bewerking in het Nederlands; de engine noemt ze "op cut". */
	function typeName(type: string): string {
		const soort = type.replace(/^(op|effect) /, '');
		return (
			{
				cut: 'snijden',
				engrave: 'graveren',
				raster: 'rasteren',
				image: 'afbeelding',
				dots: 'punten'
			}[soort] ?? soort
		);
	}

	/** Vermogen zit in de engine op 0–1000; de gebruiker rekent in procenten. */
	function powerPercent(op: { power: number | null }): number | null {
		return op.power === null ? null : Math.round(op.power / 10);
	}

	/**
	 * Een getal uit een veld dat direct in de rij staat.
	 *
	 * Leeg of onzin laten we staan zoals het was in plaats van er nul van te
	 * maken: nul mm/s is een machine die stilstaat met de laser aan.
	 */
	function commitNumber(
		event: Event & { currentTarget: HTMLInputElement },
		id: string,
		field: string,
		was: number | null
	) {
		const value = Number(event.currentTarget.value);
		if (!Number.isFinite(value) || value <= 0) {
			event.currentTarget.value = was === null ? '' : String(was);
			return;
		}
		if (value === was) return;
		patchLayer(id, { [field]: value });
	}

	// Een bewerking is "aan" voor de selectie als élk gekozen element erin zit.
	function membership(operationId: string): 'all' | 'some' | 'none' {
		if (chosen.length === 0) return 'none';
		const inside = chosen.filter((e) => e.operation_ids.includes(operationId)).length;
		if (inside === 0) return 'none';
		return inside === chosen.length ? 'all' : 'some';
	}

	function describe(op: { speed: number | null; power: number | null }) {
		const parts: string[] = [];
		if (op.speed !== null) parts.push(`${op.speed} mm/s`);
		if (op.power !== null) parts.push(`${Math.round((op.power / 1000) * 100)}%`);
		return parts;
	}
</script>

{#if show === 'selection' && strays.length}
	<div class="section stray">
		<p>
			{strays.length}
			{strays.length === 1 ? 'vorm ligt' : 'vormen liggen'} buiten het bed. Die
			branden niet mee.
		</p>
		{#if canEdit}
			<button class="rot" disabled={edits.busy} onclick={() => onArrange?.('rescue')}>
				Terughalen op het bed
			</button>
		{/if}
	</div>
{/if}

<div class="section">
	<!-- Kop, telling en geschiedenis op één regel. Ze stonden op drie, en drie
	     regels boven de selectie zijn drie regels die de selectie naar beneden
	     duwen. -->
	<div class="section-head">
		<h2 class="section-title">Ontwerp</h2>
		{#if elements.length}
			<span class="muted mono tally">
				{elements.length} element{elements.length === 1 ? '' : 'en'}
			</span>
		{/if}
		{#if canEdit}
			<div class="history">
				<button
					class="icon"
					disabled={edits.busy}
					title="Ongedaan maken"
					aria-label="Ongedaan maken"
					onclick={() => onHistory?.('undo')}
				><ArrangeIcon name="undo" /></button>
				<button
					class="icon"
					disabled={edits.busy}
					title="Opnieuw"
					aria-label="Opnieuw"
					onclick={() => onHistory?.('redo')}
				><ArrangeIcon name="redo" /></button>
			</div>
		{/if}
	</div>
	{#if edits.error}
		<p class="edit-error" role="alert">{edits.error}</p>
	{/if}
	{#if elements.length === 0}
		<!-- Hier stond "Gebruik 'Ontwerp laden…' in de Job-tab". Die knop bestaat
		     niet en heeft nooit bestaan (repo-brede grep: deze regel was de enige
		     vindplaats van die naam). Een lege staat die naar een verzonnen knop
		     wijst, is erger dan een lege staat die zwijgt: je gaat zoeken. -->
		<p class="empty">
			Nog niets op het bed. <b>Importeren</b> in de bovenbalk haalt een SVG,
			DXF of afbeelding binnen; met het gereedschap links teken je zelf.
		</p>
	{/if}
</div>

{#if show === 'selection' && selected && size}
	<div class="section">
		<h2 class="section-title">Selectie</h2>
		<div class="selected">
			<div class="head">
				<span class="name" title={chosen.length > 1 ? undefined : selected.label}>
					{chosen.length > 1 ? `${chosen.length} elementen` : selected.label}
				</span>
				<!-- In hoeveel lagen de selectie zit stond als eigen alinea onderaan
				     het paneel, buiten beeld. Het hoort bij de identiteit van wat je
				     vast hebt, dus staat het naast de naam. -->
				<span class="in-layers">
					in {selected.operation_ids.length} laag{selected.operation_ids.length === 1
						? ''
						: 'en'}
				</span>
				<button class="clear" onclick={() => design.select(null)}>Wis</button>
			</div>
			<!-- Maten, positie en hoek als één raster van drie regels: twee
			     kolommen getallen met de eenheid één keer rechts. Ze stonden
			     als vrij wrappende pillen naast elkaar, waardoor X op de eerste
			     regel eindigde en Y in zijn eentje op de tweede — en dan lees je
			     twee paren niet meer als twee paren. -->
			<div class="figures mono">
				{#each [['B', 'width', 'Breedte'], ['H', 'height', 'Hoogte']] as [label, key, naam] (key)}
					<label class="f">
						<span>{label}</span>
						<input
							type="number"
							step="0.1"
							min="0.1"
							aria-label="{naam} in millimeter"
							disabled={!canEdit}
							value={(live ?? size)[key as 'width' | 'height'].toFixed(1)}
							onchange={(e) => commitSize(key as 'width' | 'height', e.currentTarget.value)}
						/>
					</label>
				{/each}
				<button
					class="link"
					aria-pressed={linked}
					disabled={!canEdit}
					title={linked ? 'Verhouding vast — breedte en hoogte schalen samen' : 'Breedte en hoogte los'}
					aria-label={linked ? 'Verhouding vast' : 'Verhouding los'}
					onclick={() => (linked = !linked)}
				>
					<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
						{#if linked}
							<path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1" />
							<path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1" />
						{:else}
							<path d="M9 12H5a3 3 0 0 1 0-6h4M15 12h4a3 3 0 0 1 0 6h-4" />
						{/if}
					</svg>
				</button>
				{#each [['X', 'x', 'Positie X'], ['Y', 'y', 'Positie Y']] as [label, key, naam] (key)}
					<label class="f">
						<span>{label}</span>
						<input
							type="number"
							step="0.1"
							aria-label="{naam} in millimeter"
							disabled={!canEdit}
							value={(live ?? size)[key as 'x' | 'y'].toFixed(1)}
							onchange={(e) => commitPosition(key as 'x' | 'y', e.currentTarget.value)}
						/>
					</label>
				{/each}
				<span class="unit">mm</span>
			</div>

			{#if canEdit}
				<!-- De hoek stond nergens. Je kon draaien per 1° en per 90° maar
				     niet zien waar je stond, dus elke klik was een gok bovenop de
				     vorige. Nu is de hoek een waarde uit de engine: intikbaar,
				     en de stapjes verplaatsen hem in plaats van iets op te
				     stapelen. -->
				<div class="figures mono rotrow">
					<label class="f angle" class:mixed={pose.mixed}>
						<span aria-hidden="true">∠</span>
						<input
							type="number"
							step="1"
							inputmode="decimal"
							aria-label="Hoek in graden"
							title={pose.mixed
								? 'Deze vormen staan onder verschillende hoeken — draai ze met de stapjes'
								: 'De huidige hoek. Tik een getal om er precies naartoe te draaien.'}
							disabled={edits.busy || pose.mixed || pose.angle === null}
							value={pose.angle === null
								? ''
								: Number.isInteger(pose.angle)
									? pose.angle
									: pose.angle.toFixed(1)}
							placeholder={pose.mixed ? '—' : ''}
							onchange={(e) => setAngle(e.currentTarget.value)}
						/>
						<!-- De graad hoort ín het veld. Als eigen kolom stond hij op de
						     tablet drie kolommen verderop, los van het getal waar hij
						     bij hoort. -->
						<span class="suffix" aria-hidden="true">°</span>
					</label>
					{#each [[-90, 'rotate-ccw'], [-1, ''], [1, ''], [90, 'rotate-cw']] as [angle, icon] (angle)}
						<button
							class="icon step"
							disabled={edits.busy}
							title="{Number(angle) > 0 ? '+' : ''}{angle}° draaien"
							aria-label="{Number(angle) > 0 ? '+' : ''}{angle} graden draaien"
							onclick={() => onRotate?.(Number(angle))}
						>
							{#if icon}
								<ArrangeIcon name={String(icon)} size={18} />
							{:else}
								<span class="stepnum">{Number(angle) > 0 ? '+' : '−'}1</span>
							{/if}
						</button>
					{/each}
				</div>
				{#if pose.mixed}
					<p class="tip">
						Deze vormen staan onder verschillende hoeken. De stapjes werken;
						een hoek intikken zou ze allemaal gelijk zetten en dat is zelden
						wat je bedoelt.
					</p>
				{/if}
			{/if}

			{#if canEdit && selected.text}
				<button class="edit-text" onclick={() => onEditText?.(selected.id)}>
					Tekst bewerken — “{selected.text.text}”
				</button>
			{/if}

			{#if canEdit}
				{@const enough = chosen.length > 1}
				{@const why = enough ? 'Uitlijnen op de laatste vorm in de selectie' : 'Selecteer minstens twee vormen'}
				{@const three = chosen.length > 2}
				<!-- Uitlijnen, verdelen, spiegelen en groeperen als drie rijen van
				     vier pictogrammen. Als tekstpillen namen ze acht regels en
				     wrapten ze zo ongelukkig dat de twee knoppen "Midden" — de
				     horizontale en de verticale — naast elkaar konden eindigen,
				     niet uit elkaar te houden. In een raster zegt de rij waar de
				     as ligt: eerste rij horizontaal, tweede verticaal. -->
				<div class="tools" role="group" aria-label="Schikken">
					{#each [['left', 'align-left', 'Links uitlijnen'], ['centerh', 'align-centerh', 'Horizontaal centreren'], ['right', 'align-right', 'Rechts uitlijnen'], ['spaceh', 'space-h', 'Horizontaal verdelen']] as [mode, icon, label] (mode)}
						{@const needsThree = mode === 'spaceh'}
						<button
							class="tool"
							disabled={edits.busy || (needsThree ? !three : !enough)}
							title={needsThree
								? three
									? 'Gelijke tussenruimte, horizontaal'
									: 'Verdelen heeft minstens drie vormen nodig'
								: why}
							aria-label={label}
							onclick={() => onArrange?.(mode)}
						><ArrangeIcon name={icon} /></button>
					{/each}
					{#each [['top', 'align-top', 'Boven uitlijnen'], ['centerv', 'align-centerv', 'Verticaal centreren'], ['bottom', 'align-bottom', 'Onder uitlijnen'], ['spacev', 'space-v', 'Verticaal verdelen']] as [mode, icon, label] (mode)}
						{@const needsThree = mode === 'spacev'}
						<button
							class="tool"
							disabled={edits.busy || (needsThree ? !three : !enough)}
							title={needsThree
								? three
									? 'Gelijke tussenruimte, verticaal'
									: 'Verdelen heeft minstens drie vormen nodig'
								: why}
							aria-label={label}
							onclick={() => onArrange?.(mode)}
						><ArrangeIcon name={icon} /></button>
					{/each}
					<button
						class="tool"
						disabled={edits.busy}
						title="Spiegelen om de verticale as. Nog een keer klikken zet het terug."
						aria-label="Horizontaal spiegelen"
						onclick={() => onArrange?.('mirror-h')}
					><ArrangeIcon name="mirror-h" /></button>
					<button
						class="tool"
						disabled={edits.busy}
						title="Spiegelen om de horizontale as. Nog een keer klikken zet het terug."
						aria-label="Verticaal spiegelen"
						onclick={() => onArrange?.('mirror-v')}
					><ArrangeIcon name="mirror-v" /></button>
					<button
						class="tool"
						disabled={edits.busy || !enough}
						title={enough ? 'Groeperen — de vormen bewegen voortaan samen' : 'Selecteer minstens twee vormen'}
						aria-label="Groeperen"
						onclick={() => onArrange?.('group')}
					><ArrangeIcon name="group" /></button>
					<button
						class="tool"
						disabled={edits.busy || !selected.group_id}
						title={selected.group_id ? 'Groep opheffen' : 'Deze vorm zit niet in een groep'}
						aria-label="Groep opheffen"
						onclick={() => onArrange?.('ungroup')}
					><ArrangeIcon name="ungroup" /></button>
				</div>

				{#if !enough}
					<!-- Vier regels waren te veel om te lezen én genoeg om het paneel
					     op een tablet te laten scrollen. Twee regels zeggen
					     hetzelfde. -->
					<p class="tip">
						Grijs = werkt op meerdere vormen. Sleep een kader, of shift-klik.
					</p>
				{/if}
			{/if}

			{#if canEdit && (moved || pose.mirrored)}
				<!-- Het anker. Zolang deze selectie actief is, is elke draai en elke
				     spiegeling terug te nemen naar de stand van vóór het schikken —
				     niet naar de vorige klik. Wegklikken maakt het definitief; er
				     valt niets vast te leggen, want elke tik stond al in het
				     document en is gewoon ongedaan te maken. -->
				<div class="anchor" class:idle={!moved}>
					<span class="anchor-what">
						{#if moved}
							Sinds je hem pakte: <b>{movedSummary}</b>
						{:else}
							<b>Gespiegeld</b> ten opzichte van het origineel
						{/if}
					</span>
					{#if moved}
						<button
							class="anchor-back"
							disabled={edits.busy}
							title="Terug naar de stand van toen je deze selectie aanklikte"
							onclick={restore}
						><ArrangeIcon name="restore" size={16} /> Terugzetten</button>
					{/if}
				</div>
			{/if}

			{#if selected.effect}
				<p class="hint">Zit in effect: {selected.effect.label}</p>
			{/if}

			{#if canEdit}
				<!-- Wat hieronder staat is er voor de uitzondering, niet voor het
				     werk van elke dag. Ingeklapt, maar wel met hun naam in beeld:
				     een dichtgeklapte regel kun je ontdekken, een verborgen knop
				     niet. -->
				{@const enough = chosen.length > 1}
				<details
					class="fold"
					open={openGroups.boolean}
					ontoggle={(e) => (openGroups.boolean = e.currentTarget.open)}
				>
					<summary>Combineren <span class="fold-note">tot één pad</span></summary>
					<div class="tools four">
						{#each [['union', 'union', 'Verenigen'], ['difference', 'difference', 'Verschil'], ['intersection', 'intersection', 'Doorsnede'], ['xor', 'xor', 'Uitsluiten']] as [op, icon, label] (op)}
							<button
								class="tool"
								disabled={edits.busy || !enough}
								title={enough
									? `${label} — het resultaat is één pad, de vormen verdwijnen`
									: 'Selecteer minstens twee vormen'}
								aria-label={label}
								onclick={() => onArrange?.(op)}
							><ArrangeIcon name={icon} /></button>
						{/each}
					</div>
				</details>

				<details
					class="fold"
					open={openGroups.path}
					ontoggle={(e) => (openGroups.path = e.currentTarget.open)}
				>
					<summary>Pad bewerken <span class="fold-note">offset, vulling, nesten</span></summary>
					<div class="arrange">
						<button
							class="rot"
							disabled={edits.busy || chosen.length < 2}
							title="Leg de selectie dicht op elkaar om materiaal te sparen"
							onclick={() => onArrange?.('nest')}
						>Nesten</button>
						<button class="rot" disabled={edits.busy} onclick={() => onArrange?.('offset')}>Offset…</button>
						<button class="rot" disabled={edits.busy} onclick={() => onArrange?.('simplify')}>Vereenvoudigen</button>
						<button class="rot" disabled={edits.busy} onclick={() => onArrange?.('hatch')}>Vulling</button>
						<button class="rot" disabled={edits.busy} onclick={() => onArrange?.('wobble')}>Wobble</button>
					</div>
				</details>
			{/if}

			{#if canEdit && selected.image}
				<!-- Bewerkingen zijn niet destructief: het recept gaat elke keer
				     opnieuw over het origineel. Vandaar schakelaars met hun
				     waarden erbij, en niet een rij knoppen waarvan je moet
				     onthouden waar je op gedrukt hebt.

				     Wél ingeklapt: acht schakelaars met schuifregelaars zijn in hun
				     eentje langer dan de rest van het paneel bij elkaar, en je zet
				     ze één keer goed in plaats van steeds opnieuw. -->
				<details
					class="fold"
					open={openGroups.image}
					ontoggle={(e) => (openGroups.image = e.currentTarget.open)}
				>
					<summary>
						Afbeelding
						{#if image?.adjustments.some((a) => a.enabled)}
							<span class="fold-note on">
								{image.adjustments.filter((a) => a.enabled).length} aan
							</span>
						{/if}
					</summary>
				<div class="imagefx">
					<div class="fx-head">
						<button
							class="rot"
							disabled={edits.busy || !image?.adjustments.some((a) => a.enabled)}
							onclick={() => onImageClear?.()}
						>Alles wissen</button>
					</div>

					{#each image?.adjustments ?? [] as item (item.name)}
						<div class="fx" class:on={item.enabled}>
							<label class="fx-toggle">
								<input
									type="checkbox"
									checked={item.enabled}
									disabled={edits.busy}
									onchange={(e) => onImageSet?.(item.name, e.currentTarget.checked, null)}
								/>
								<span>{item.label}</span>
							</label>
							{#if item.enabled}
								{#each Object.entries(item.values) as [key, value] (key)}
									{#if item.ranges[key]}
										<label class="fx-value">
											<span>{key}</span>
											<input
												type="range"
												min={item.ranges[key][0]}
												max={item.ranges[key][1]}
												step={key === 'radius' || key === 'factor' ? 0.1 : 1}
												{value}
												disabled={edits.busy}
												onchange={(e) =>
													onImageSet?.(item.name, true, {
														[key]: Number(e.currentTarget.value)
													})}
											/>
											<span class="mono fx-num">{value}</span>
										</label>
									{:else if key === 'type' && item.name === 'dither'}
										<label class="fx-value">
											<span>soort</span>
											<select
												disabled={edits.busy}
												onchange={(e) =>
													onImageSet?.(item.name, true, { type: e.currentTarget.value })}
											>
												{#each image?.dither_types ?? [] as option (option)}
													<option value={option} selected={option === value}>{option}</option>
												{/each}
											</select>
										</label>
									{/if}
								{/each}
							{/if}
						</div>
					{/each}

					<div class="fx-actions">
						<button class="rot" disabled={edits.busy} onclick={() => onVectorise?.()}>
							Vectoriseren
						</button>
						<button class="rot" disabled={edits.busy} onclick={() => onCrop?.()}>
							Bijsnijden
						</button>
						<button class="rot" disabled={edits.busy} onclick={() => onUncrop?.()}>
							Snede terug
						</button>
						<label class="dpi mono">
							DPI
							<input
								type="number"
								min="10"
								max="2000"
								step="10"
								value={selected.image.dpi ?? 96}
								onchange={(e) => onImageDpi?.(Number(e.currentTarget.value))}
							/>
						</label>
					</div>
				</div>
				</details>
			{/if}

			{#if canEdit && otherSheets.length}
				<details
					class="fold"
					open={openGroups.sheet}
					ontoggle={(e) => (openGroups.sheet = e.currentTarget.open)}
				>
					<summary>Naar ander vel</summary>
					<div class="arrange">
						<!-- Verhuizen naar een ander vel: de selectie gaat mee via het
						     klembord van de engine, dus operaties en kleuren blijven. -->
						{#each otherSheets as sheet (sheet.id)}
							<button
								class="rot"
								disabled={edits.busy}
								title="Verplaats de selectie naar {sheet.name}"
								onclick={() => onMoveToSheet?.(sheet.id)}
							>{sheet.name}</button>
						{/each}
					</div>
				</details>
			{/if}

			<p class="hint">
				{#if canEdit}
					Sleep het kader om te verplaatsen, de hoeken om te schalen. Pijltjes:
					0,1 mm, met shift 1 mm.
				{:else}
					Bewerken vereist een token.
				{/if}
			</p>
		</div>
	</div>
{/if}

{#if show === 'selection' && !selected}
	<div class="section">
		<p class="muted">
			Niets geselecteerd. Klik een vorm aan op het canvas, of sleep een kader
			om er meerdere te pakken.
		</p>
	</div>
{/if}

{#if show === 'layers'}
	<div class="section">
		<div class="section-head">
			<h2 class="section-title">Lagen</h2>
			{#if plainLayers.length}
				<!-- Wat het nummer op de chip betekent, staat er één keer bij. Zonder
				     dat leest de lijst als een willekeurige stapel in plaats van als
				     de volgorde waarin de machine werkt. -->
				<span class="order-note mono">1 → {plainLayers.length} = brandvolgorde</span>
			{/if}
		</div>
		{#if !operations.length}
			<p class="muted">
				Nog geen lagen. Een laag is een bewerking — snijden, graveren of
				rasteren — met een eigen snelheid en vermogen. Maak er hieronder
				een aan; selecteer daarna een vorm om hem erin te zetten.
			</p>
		{/if}
		{#each plainLayers as op, index (op.id)}
			{@const open = editingLayer === op.id}
			{@const percent = powerPercent(op)}
			<div
				class="layer"
				class:off={!op.output}
				class:onzichtbaar={design.isLayerHidden(op.id)}
				class:open
			>
				<div class="ident">
					<!-- Het nummer op de chip ís de brandvolgorde. Klikken opent de
					     laag, dus de kleur is ook de weg naar zijn instellingen. -->
					<button
						class="chip mono"
						style="background: {design.colorFor(op.id)}; color: {inktOp(
							design.colorFor(op.id)
						)}"
						disabled={!canEdit}
						title="Laag {index + 1} van {plainLayers.length} — instellingen en kleur"
						aria-expanded={open}
						aria-label="Laag {op.label} openen"
						onclick={() => (editingLayer = open ? null : op.id)}
					>{index + 1}</button>
					<!-- Eén regel voor de identiteit. Het aantal elementen ging naar de
					     waarderegel: als naam en telling onder elkaar staan wordt een
					     rij op een tablet 186 px hoog en passen er drie lagen op een
					     scherm. -->
					<div class="layer-name">{op.label}</div>
					<!-- Het aantal hoort bij de naam, niet bij de waarden: achter de
					     drie velden past het net niet en dan krijgt de ene rij een
					     derde regel en de andere niet. -->
					<span
						class="count"
						title="{op.element_ids.length} vorm{op.element_ids.length === 1
							? ''
							: 'en'} in deze laag"
					>{op.element_ids.length}</span>
					{#if canEdit}
						<!-- Meebranden hoort in de rij: het is de schakelaar waar je
						     tijdens het werk het vaakst aan zit, en verstopt in een
						     submenu kun je niet zien welke lagen uitstaan. -->
						<button
							class="out"
							class:on={op.output}
							role="switch"
							aria-checked={op.output}
							title={op.output ? 'Brandt mee — klik om uit te zetten' : 'Staat uit — klik om mee te branden'}
							aria-label="Meebranden voor {op.label}"
							disabled={edits.busy}
							onclick={() => patchLayer(op.id, { output: !op.output })}
						>
							<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
								<path d="M12 3v9" />
								<path d="M18.4 6.6a9 9 0 1 1-12.8 0" />
							</svg>
						</button>
						<!-- Besluit B4: zichtbaar en meebranden zijn twee dingen. Een
						     uitlijnkader op het canvas houden zonder het te branden is
						     een standaardtruc, en met één schakelaar kan dat niet.
						     Zichtbaarheid is een kijkstand: die gaat niet naar de engine
						     en verandert dus niets aan wat er gebrand wordt. -->
						<button
							class="oog"
							class:uit={design.isLayerHidden(op.id)}
							role="switch"
							aria-checked={!design.isLayerHidden(op.id)}
							title={design.isLayerHidden(op.id)
								? 'Verborgen op het canvas — klik om te tonen. Dit verandert niets aan de job.'
								: 'Zichtbaar op het canvas — klik om te verbergen. Dit verandert niets aan de job.'}
							aria-label="Zichtbaar op het canvas voor {op.label}"
							onclick={() => design.toggleLayer(op.id)}
						>
							{#if design.isLayerHidden(op.id)}
								<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
									<path d="M3 3l18 18" />
									<path d="M10.6 5.1A9.6 9.6 0 0 1 12 5c5 0 9 4.5 9 7a11 11 0 0 1-2.5 3.4" />
									<path d="M6.2 7.4A11.6 11.6 0 0 0 3 12c0 2.5 4 7 9 7a9.7 9.7 0 0 0 3.8-.8" />
								</svg>
							{:else}
								<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
									<path d="M3 12c0-2.5 4-7 9-7s9 4.5 9 7-4 7-9 7-9-4.5-9-7Z" />
									<circle cx="12" cy="12" r="2.6" />
								</svg>
							{/if}
						</button>
						<button
							class="more"
							title={open ? 'Sluiten' : 'Meer instellingen'}
							aria-expanded={open}
							aria-label="Meer instellingen voor {op.label}"
							onclick={() => (editingLayer = open ? null : op.id)}
						>⋯</button>
					{/if}
				</div>

				<!-- Snelheid, vermogen en passes staan als velden in de rij zelf.
				     Dat is de hele reden dat dit paneel bestaat: bijstellen naast
				     een draaiende machine mag geen submenu kosten. -->
				<div class="vals">
					{#if canEdit}
						<label class="val">
							<input
								class="mono"
								type="number"
								step="1"
								min="0.1"
								inputmode="decimal"
								aria-label="Snelheid van {op.label} in mm per seconde"
								value={op.speed ?? ''}
								disabled={edits.busy}
								onchange={(e) => commitNumber(e, op.id, 'speed', op.speed)}
							/><span>mm/s</span>
						</label>
						<label class="val">
							<input
								class="mono"
								type="number"
								step="1"
								min="1"
								max="100"
								inputmode="numeric"
								aria-label="Vermogen van {op.label} in procent"
								value={percent ?? ''}
								disabled={edits.busy}
								onchange={(e) => commitNumber(e, op.id, 'power_percent', percent)}
							/><span>%</span>
						</label>
						<label class="val narrow">
							<input
								class="mono"
								type="number"
								step="1"
								min="1"
								inputmode="numeric"
								aria-label="Aantal passes van {op.label}"
								value={op.passes ?? 1}
								disabled={edits.busy}
								onchange={(e) => commitNumber(e, op.id, 'passes', op.passes ?? 1)}
							/><span>×</span>
						</label>
					{:else}
						{#each describe(op) as value (value)}
							<span class="pill mono">{value}</span>
						{/each}
					{/if}
					{#if !op.output}
						<!-- Kleur alleen is niet genoeg: dit staat er ook in woorden,
						     want dit is het verschil tussen "het is gesneden" en "ik
						     was het vergeten". -->
						<span class="tag">brandt niet mee</span>
					{/if}
					{#if design.isLayerHidden(op.id)}
						<!-- En dit is de andere helft van B4: verborgen zegt niets over
						     branden. Twee aparte woorden, want twee aparte standen. -->
						<span class="tag zicht">verborgen</span>
					{/if}
					{#if canEdit && selectedIds.length}
						<!-- Toewijzen staat achteraan en niet vóór de naam: anders
						     verschuift de hele rij zodra je iets selecteert. -->
						<button
							class="assign"
							class:in={membership(op.id) === 'all'}
							class:partly={membership(op.id) === 'some'}
							aria-pressed={membership(op.id) === 'all'}
							title="Zet de selectie in {op.label}"
							disabled={edits.busy}
							onclick={() => onAssign?.(op.id, membership(op.id) !== 'all')}
						>{membership(op.id) === 'all' ? '✓' : membership(op.id) === 'some' ? '–' : '+'} hierin</button>
					{/if}
				</div>
			</div>

			{#if canEdit && open}
				{@const onthouden = design.memoryFor(design.colorFor(op.id))}
				<div class="layer-edit">
					<div class="swatches" role="group" aria-label="Kleur van {op.label}">
						{#each LAYER_COLORS as swatch (swatch)}
							<button
								class="swatch"
								class:picked={design.colorFor(op.id).toLowerCase() === swatch.toLowerCase()}
								style="background: {swatch}"
								title="Laagkleur {swatch}"
								aria-label="Laagkleur {swatch}"
								aria-pressed={design.colorFor(op.id).toLowerCase() === swatch.toLowerCase()}
								disabled={edits.busy}
								onclick={() => patchLayer(op.id, { color: swatch })}
							></button>
						{/each}
					</div>

					<!-- Wat deze kleur op deze machine onthouden heeft (besluit B2).
					     Het staat er met zoveel woorden bij dat het geen preset is:
					     een preset hoort bij een materiaal en een dikte en zegt dat er
					     iets gebrand is. Dit zegt alleen wat jij hier het laatst deed,
					     en dat mag nooit voor bewijs doorgaan. -->
					<p class="geheugen wide">
						{#if onthouden?.speed_mm_s}
							<span class="mono"
								>{onthouden.speed_mm_s} mm/s{onthouden.power_percent == null
									? ''
									: ` · ${Math.round(onthouden.power_percent)}%`}</span
							>
							onthouden voor deze kleur op {onthouden.machine_name ?? 'deze machine'} —
							daarmee begint een volgende laag in deze kleur. Geen preset: dit
							draagt geen herkomst.
						{:else}
							Deze kleur heeft op deze machine nog niets onthouden. Zodra je
							snelheid of vermogen bijstelt, begint een volgende laag in deze
							kleur daarop.
						{/if}
					</p>

					<label class="wide">
						<span>Naam</span>
						<input
							type="text"
							value={op.label}
							onchange={(e) => patchLayer(op.id, { label: e.currentTarget.value })}
						/>
					</label>

					{#if op.type === 'op raster' || op.type === 'op image'}
						<!-- Alleen rasteren gebruikt deze; bij snijden zijn ze zinloos. -->
						<!-- Elk over de volle breedte: een stepper is twee knoppen van
						     38 px plus een veld, en in een halve kolom van 112 px
						     blijft er voor "2000" niets over. -->
						<div class="steppers wide">
						<NumberField
							label="DPI"
							value={String(op.dpi ?? 500)}
							step={10}
							min={10}
							max={2000}
							disabled={edits.busy}
							onchange={(v) => patchLayer(op.id, { dpi: Number(v) })}
						/>
						<NumberField
							label="Overscan"
							unit="mm"
							value={String(parseFloat(op.overscan ?? '0.5') || 0)}
							step={0.5}
							min={0}
							max={50}
							disabled={edits.busy}
							onchange={(v) => patchLayer(op.id, { overscan_mm: Number(v) })}
						/>
						</div>
						<label class="check wide">
							<input
								type="checkbox"
								checked={op.bidirectional}
								onchange={(e) =>
									patchLayer(op.id, { bidirectional: e.currentTarget.checked })}
							/>
							<span>Heen en weer graveren</span>
						</label>
					{/if}

					<!-- Volgorde is brandvolgorde: eerst graveren, dan pas snijden,
					     anders valt het werkstuk uit het vel voor het opschrift
					     erop staat. -->
					<div class="order wide">
						<span class="rot-label">Volgorde · {typeName(op.type)}</span>
						<button
							class="rot"
							disabled={edits.busy || index === 0}
							title={index === 0 ? 'Deze laag brandt al als eerste' : 'Eerder branden'}
							onclick={() => moveLayer(op.id, 'up')}
						>↑ Eerder</button>
						<button
							class="rot"
							disabled={edits.busy || index === plainLayers.length - 1}
							title={index === plainLayers.length - 1
								? 'Deze laag brandt al als laatste'
								: 'Later branden'}
							onclick={() => moveLayer(op.id, 'down')}
						>↓ Later</button>
					</div>

					{#if confirmDrop === op.id}
						<div class="confirm wide">
							<span>“{op.label}” weggooien? De vormen blijven, de instellingen niet.</span>
							<button class="rot" onclick={() => (confirmDrop = null)}>Annuleren</button>
							<button class="rot drop" onclick={() => dropLayer(op.id)}>Verwijderen</button>
						</div>
					{:else}
						<button class="weg wide" onclick={() => (confirmDrop = op.id)}>
							Laag verwijderen…
						</button>
					{/if}
				</div>
			{/if}
		{/each}

		{#each gridGroups as group (group.id)}
			<div class="layer grid-row">
				<div class="ident">
					<span class="chip mono grid-chip">R</span>
					<div class="layer-name">
						<div class="op">Testraster #{group.id}</div>
						<div class="obj">{group.ops.length} cellen · snelheid en vermogen liggen vast</div>
					</div>
					<button
						class="more"
						aria-expanded={openGrid === group.id}
						aria-label="Cellen van raster {group.id} tonen"
						onclick={() => (openGrid = openGrid === group.id ? null : group.id)}
					>{openGrid === group.id ? '−' : '+'}</button>
				</div>
			</div>

			{#if openGrid === group.id}
				<div class="cells">
					{#each group.ops as op (op.id)}
						<label class="cell" title="rij {op.grid?.row}, kolom {op.grid?.column}">
							<input
								type="checkbox"
								checked={op.output}
								disabled={!canEdit || edits.busy}
								onchange={(e) => patchLayer(op.id, { output: e.currentTarget.checked })}
							/>
							<span class="mono">{op.grid?.speed_mm_s}·{op.grid?.power_percent}%</span>
						</label>
					{/each}
					{#if canEdit}
						<button class="weg cells-remove" onclick={() => removeGrid(group.id)}>
							Raster uit ontwerp verwijderen
						</button>
					{/if}
				</div>
			{/if}
		{/each}
		{#if canEdit}
			<!-- Vier vaste soorten: als één balk, zodat je in één blik ziet wat er
			     te kiezen valt en wat er nu staat. De knop noemt wat er komt —
			     anders leest de balk als een filter over de lijst erboven. Onder
			     de lijst, want de lagen die er al zijn kijk je vaker aan dan dat
			     je er een maakt. -->
			<div class="addrow">
				<span class="addlabel">Nieuwe laag</span>
				<Segmented
					label="Type nieuwe laag"
					bind:value={newLayerType}
					options={LAYER_TYPES.map(({ value, label }) => ({ value, label }))}
				/>
				<button class="add" disabled={edits.busy} onclick={addLayer}>
					{newLayerNoun} toevoegen
				</button>
			</div>
		{/if}
		<p class="hint">
			{#if selected}
				“<strong>hierin</strong>” zet de huidige selectie in die laag.
			{:else}
				Selecteer een vorm op het canvas; dan kun je hem hier met één tik in
				een laag zetten.
			{/if}
		</p>
	</div>
{/if}

<style>
	.section + .section {
		margin-top: var(--space-6);
	}
	.section-title {
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-2);
		margin: 0 0 var(--space-2);
	}
	.empty,
	.muted {
		color: var(--text-2);
		margin: 0;
	}
	/* Twee regels per laag: wie hij is, en wat hij doet. Meer regels en de
	   lijst wordt een stapel kaarten waarin je niets meer terugvindt; minder
	   en de waarden zijn niet meer aan te tikken. */
	.layer {
		display: grid;
		/* minmax(0, 1fr) en niet de impliciete auto-kolom: die groeit mee met
		   de langste laagnaam en duwt dan de hele lijst het paneel uit. */
		grid-template-columns: minmax(0, 1fr);
		gap: var(--space-1);
		padding: var(--space-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
	}
	.layer .ident {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.layer + .layer {
		margin-top: var(--space-1);
	}
	/* Een uitgezette laag dimmen we niet weg: je moet hem nog kunnen lezen en
	   aanzetten. Alleen de waarden vervagen, want die doen even niets. */
	.layer.off .vals .val,
	.layer.off .vals .pill {
		opacity: 0.5;
	}
	.layer.off {
		border-style: dashed;
	}
	.layer.open {
		border-color: var(--accent);
		border-bottom-left-radius: 0;
		border-bottom-right-radius: 0;
	}
	.chip {
		width: 26px;
		height: 26px;
		flex: none;
		border-radius: var(--radius-field);
		display: grid;
		place-items: center;
		font-size: var(--text-xs);
		font-weight: 600;
		/* De inkt komt van inktOp() als inline stijl; dit is alleen de val voor
		   een kleur die niet te ontleden is. */
		color: var(--on-color);
		border: 0;
		padding: 0;
	}
	.chip:not(:disabled):hover {
		box-shadow: 0 0 0 2px var(--surface-1), 0 0 0 4px currentColor;
	}
	/* Meebranden: een knop met een aan-stand, geen vinkje dat je moet raken. */
	.out {
		flex: none;
		display: grid;
		place-items: center;
		width: 28px;
		height: 28px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		color: var(--text-2);
	}
	.out.on {
		border-color: color-mix(in srgb, var(--ok) 55%, var(--line));
		background: color-mix(in srgb, var(--ok) 14%, transparent);
		color: var(--ok);
	}
	.out:hover:not(:disabled) {
		background: var(--surface-2);
	}
	/* Zichtbaarheid staat naast meebranden en ziet er bewust ánders uit: dit is
	   een kijkstand, geen machinestand. Daarom neutraal grijs waar meebranden
	   groen kleurt — kleur is hier gereserveerd voor wat de laser gaat doen. */
	.oog {
		flex: none;
		display: grid;
		place-items: center;
		width: 28px;
		height: 28px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		color: var(--text-2);
	}
	.oog.uit {
		background: var(--surface-2);
		color: var(--text-2);
		opacity: 0.75;
	}
	.oog:hover:not(:disabled) {
		background: var(--surface-2);
		color: var(--text-1);
	}
	/* Een verborgen laag mag je nog wél lezen — hij is niet uitgezet, hij staat
	   alleen even niet op het bed. De naam vervaagt, de knoppen niet. */
	.layer.onzichtbaar .layer-name,
	.layer.onzichtbaar .count {
		opacity: 0.55;
	}
	.tag.zicht {
		color: var(--text-2);
		font-weight: 400;
	}
	.geheugen {
		margin: 0;
		font-size: var(--text-xs);
		line-height: 1.4;
		color: var(--text-2);
		background: var(--surface-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		padding: var(--space-2);
	}
	.geheugen .mono {
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
		color: var(--text-1);
	}
	.more {
		flex: none;
		width: 28px;
		height: 28px;
		border-radius: var(--radius-field);
		color: var(--text-2);
		line-height: 1;
	}
	.more:hover {
		background: var(--surface-2);
		color: var(--text-1);
	}
	.vals {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 4px;
	}
	/* Een waarde met zijn eenheid als één ding: het veld hoort bij "mm/s", dus
	   ze delen een rand en de eenheid is niet aan te klikken. */
	.val {
		display: inline-flex;
		align-items: center;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		overflow: hidden;
	}
	.val:focus-within {
		border-color: var(--accent);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 30%, transparent);
	}
	.val input {
		font: inherit;
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		font-variant-numeric: tabular-nums;
		width: 4.2em;
		min-width: 0;
		text-align: right;
		padding: var(--space-1) 2px var(--space-1) var(--space-2);
		border: 0;
		background: transparent;
		color: var(--text-1);
		outline: none;
	}
	.val.narrow input {
		width: 2.4em;
	}
	/* De eigen spinner van de browser is twee pixels hoog; met handschoenen aan
	   raak je hem niet en hij vreet de breedte die het getal nodig heeft. */
	.val input::-webkit-outer-spin-button,
	.val input::-webkit-inner-spin-button {
		appearance: none;
		margin: 0;
	}
	.val input[type='number'] {
		appearance: textfield;
		-moz-appearance: textfield;
	}
	.val span {
		font-size: var(--text-xs);
		color: var(--text-2);
		padding: 0 var(--space-2) 0 2px;
		white-space: nowrap;
	}
	.tag {
		color: var(--warn);
		font-weight: 500;
	}
	/* De naam mag over twee regels: "Buitensnede 3…" en "Contour grave…" zijn
	   niet uit elkaar te houden, en juist het staartje is wat de gebruiker zelf
	   getypt heeft. Een rij die groeit om een naam is eerlijk; een rij die een
	   naam wegknipt om even hoog te blijven, niet. */
	.layer-name {
		flex: 1;
		min-width: 0;
		font-weight: 500;
		line-height: 1.25;
		overflow: hidden;
		/* break-word en niet anywhere: anywhere hakt "Binnensneden" in
		   "Binnensned / en", ook als het net wél past. */
		overflow-wrap: break-word;
		/* Breekt een te lang woord liever op een lettergreep dan middenin. */
		hyphens: auto;
		display: -webkit-box;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 2;
		line-clamp: 2;
	}
	.layer-name .op {
		font-weight: 500;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.layer-name .obj {
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.count {
		flex: none;
		min-width: 1.6em;
		text-align: center;
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
		font-size: var(--text-xs);
		color: var(--text-2);
		white-space: nowrap;
	}
	.pill {
		font-size: var(--text-xs);
		padding: 4px 8px;
		border-radius: var(--radius-field);
		background: var(--surface-2);
	}
	.hint {
		margin: 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.section-head {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
	}
	.section-head .section-title { margin-bottom: 0; }
	.tally {
		flex: 1;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.history {
		display: flex;
		gap: var(--space-1);
	}
	/* Geen nowrap: op een tablet is deze regel breder dan het paneel, en dan
	   duwt hij de hele lijst zijwaarts uit beeld in plaats van af te breken. */
	.order-note {
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	/* Naast de machine bedien je dit met een vinger, soms met een handschoen.
	   De globale regel maakt knoppen 44 px hoog maar niet breed genoeg, en de
	   invoervelden vallen er helemaal buiten. */
	@media (max-width: 1199px), (pointer: coarse) {
		.chip,
		.out,
		.more {
			width: 44px;
			height: 44px;
			min-height: 44px;
		}
		.val input {
			/* 44 px hoog, ook al is dit geen <button> en pakt de globale regel
			   hem niet. Met een handschoen aan mik je hier anders naast. */
			padding: var(--space-3) 2px var(--space-3) var(--space-2);
			width: 3.6em;
		}
		.val.narrow input {
			width: 2.2em;
		}
		.assign {
			min-height: 44px;
		}
		/* Drie raakdoelen van 44 px naast een naam passen niet in 290 px. Het
		   aantal vormen sneuvelt als eerste: dat staat ook in de tooltip van de
		   chip en in het paneel eronder, de naam staat nergens anders. */
		.count {
			display: none;
		}
		.layer .ident {
			gap: var(--space-1);
		}
		/* Op een vinger moet elk staal de 44 px halen die de rest ook heeft. */
		.swatch {
			height: 44px;
			min-height: 44px;
		}
		/* Volgorde en verwijderen mogen elkaar niet raken: één misgetikte tik
		   verderop kost je een laag met al zijn toewijzingen. */
		.layer-edit .weg,
		.confirm .drop {
			margin-left: var(--space-6);
		}
		.layer-edit .weg {
			margin-top: var(--space-6);
		}
	}
	.edit-error {
		margin: 0 0 var(--space-2);
		padding: var(--space-2);
		border-radius: var(--radius-field);
		background: color-mix(in srgb, var(--danger) 14%, transparent);
		font-size: var(--text-xs);
	}
	.edit-text {
		display: block;
		width: 100%;
		padding: 8px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		font-size: var(--text-xs);
		text-align: left;
		color: var(--accent);
	}
	.edit-text:hover { background: var(--surface-2); }
	.imagefx { display: grid; gap: 4px; }
	.fx-head { display: flex; align-items: center; gap: var(--space-2); }
	.fx {
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		padding: 4px 8px;
	}
	.fx.on { border-color: color-mix(in srgb, var(--accent) 45%, var(--line)); }
	.fx-toggle {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: var(--text-xs);
		color: var(--text-1);
	}
	.fx-value {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-top: 4px;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.fx-value input[type='range'] { flex: 1; }
	.fx-value select {
		flex: 1;
		font: inherit;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.fx-num { min-width: 3em; text-align: right; }
	.fx-actions { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; margin-top: 4px; }
	.dpi { display: flex; align-items: center; gap: 4px; font-size: var(--text-xs); color: var(--text-2); }
	.dpi input {
		width: 4.5em;
		font: inherit;
		padding: 2px 4px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.stray {
		border: 1px solid color-mix(in srgb, var(--warn) 50%, var(--line));
		border-radius: var(--radius-card);
		background: color-mix(in srgb, var(--warn) 8%, transparent);
		display: grid;
		gap: 8px;
	}
	.stray p { margin: 0; font-size: var(--text-xs); color: var(--text-1); }
	.tip {
		margin: 0;
		font-size: var(--text-xs);
		line-height: 1.45;
		color: var(--text-2);
	}
	/* Geen eigen margin meer: de selectiekaart is een grid met één gap, en een
	   groep die daar zijn eigen afstand bovenop zette maakte het ritme grillig
	   én het paneel langer. */
	.arrange {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-1);
	}
	.rot-label {
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-2);
		margin-right: var(--space-1);
	}
	.rot {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		padding: 4px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
	}
	.rot:hover:not(:disabled) {
		background: var(--surface-2);
	}
	.rot:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}
	.grid-row .grid-chip { background: var(--text-2); }
	.cells {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1);
		padding: var(--space-2);
		border: 1px solid var(--line);
		border-top: none;
		border-radius: 0 0 var(--radius-field) var(--radius-field);
		margin-bottom: 8px;
	}
	.cell {
		display: flex;
		align-items: center;
		gap: 4px;
		font-size: var(--text-xs);
		color: var(--text-2);
		padding: 2px 4px;
		border-radius: var(--radius-field);
		background: var(--surface-2);
	}
	.cell input { width: 12px; height: 12px; accent-color: var(--accent); }
	.cells-remove {
		flex-basis: 100%;
		text-align: left;
		font-size: var(--text-xs);
		color: var(--danger);
		margin-top: var(--space-1);
	}
	.addrow { display: grid; gap: var(--space-1); margin: var(--space-3) 0; }
	.addlabel {
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.addrow :global(.segmented) { display: flex; width: 100%; }
	/* De knop noemt de uitkomst, niet de handeling — zie DESIGN-SYSTEM, "de
	   primaire knop zegt wát er komt". */
	.add {
		width: 100%;
		padding: 8px;
		font: inherit;
		font-size: var(--text-xs);
		font-weight: 500;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		color: var(--accent);
	}
	.add:hover:not(:disabled) { background: var(--surface-2); }
	.add:disabled { opacity: 0.45; cursor: not-allowed; }
	.layer-edit {
		display: grid;
		/* minmax(0, 1fr): een 1fr-kolom krimpt niet onder de min-content van
		   wat erin staat, en een stepper met twee knoppen van 38 px duwt de
		   kolom dan breder dan het paneel. */
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: var(--space-2);
		padding: var(--space-3);
		margin: -1px 0 var(--space-1);
		border: 1px solid var(--accent);
		border-top: 0;
		border-radius: 0 0 var(--radius-field) var(--radius-field);
	}
	.layer-edit label { display: grid; gap: 2px; font-size: var(--text-xs); color: var(--text-2); }
	.layer-edit .wide { grid-column: 1 / -1; }
	.steppers { display: grid; gap: var(--space-2); }
	.layer-edit label.check {
		grid-template-columns: auto 1fr;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-xs);
	}
	.layer-edit input[type='text'] {
		font: inherit;
		width: 100%;
		padding: var(--space-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	/* Tien vaste kleuren, want een vrije kleurkiezer levert tinten op die op
	   het canvas niet meer uit elkaar te houden zijn. */
	/* Vijf per regel, ook op de desktop: tien op een rij past net niet in een
	   paneel van 280 px en de laatste valt er dan buiten. */
	.swatches {
		grid-column: 1 / -1;
		display: grid;
		grid-template-columns: repeat(5, minmax(0, 1fr));
		gap: 4px;
	}
	.swatch {
		width: auto;
		height: 24px;
		padding: 0;
		border: 1px solid var(--edge-on-color);
		border-radius: var(--radius-field);
	}
	.swatch.picked {
		box-shadow: 0 0 0 2px var(--surface-1), 0 0 0 4px var(--accent);
	}
	/* Label op zijn eigen regel, de twee knoppen naast elkaar: laat je ze
	   wrappen dan staat er op een tablet één knop per regel. */
	.order {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		align-items: center;
		gap: var(--space-1);
	}
	.order .rot-label {
		grid-column: 1 / -1;
		margin: 0;
	}
	.order .rot {
		text-align: center;
	}
	/* Weggooien staat los van de rest en vraagt door: het neemt de
	   toewijzingen van de laag mee en dat is niet terug te tikken. */
	.confirm {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
		margin-top: var(--space-2);
		padding: var(--space-2);
		border: 1px solid color-mix(in srgb, var(--danger) 45%, var(--line));
		border-radius: var(--radius-field);
		background: color-mix(in srgb, var(--danger) 8%, transparent);
		font-size: var(--text-xs);
		color: var(--text-1);
	}
	.confirm span { flex-basis: 100%; }
	.rot.drop { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 45%, var(--line)); }
	/* Een rode tekstlink, geen gevulde knop: de klasse heet daarom niet
	   `danger` — het vangnet in tokens.css vult elke `button.danger` bij hover
	   solide rood, en dat hoort bij een knop die meteen wist. Deze opent een
	   bevestiging. */
	.layer-edit .weg {
		font-size: var(--text-xs);
		color: var(--danger);
		text-align: left;
		margin-top: var(--space-2);
	}
	/* Toewijzen staat op de waarderegel, niet vóór de naam: anders verschuift
	   de hele rij zodra je iets selecteert. */
	.assign {
		font: inherit;
		font-size: var(--text-xs);
		padding: var(--space-1) var(--space-2);
		border: 1px dashed var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		color: var(--text-2);
	}
	.assign:hover:not(:disabled) { background: var(--surface-2); color: var(--text-1); }
	.assign.in {
		border-style: solid;
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 14%, transparent);
		color: var(--accent);
	}
	.assign.partly {
		border-style: solid;
		border-color: color-mix(in srgb, var(--accent) 45%, var(--line));
		color: var(--text-1);
	}
	.selected {
		border: 1px solid var(--accent);
		border-radius: var(--radius-card);
		padding: var(--space-3);
		display: grid;
		/* Eén ritme voor het hele blok. Elke groep zette eerder zijn eigen
		   margin-top, waardoor de afstanden per rij verschilden en het paneel
		   langer werd dan de inhoud rechtvaardigt. */
		gap: var(--space-3);
	}
	/* Een grid-item krimpt standaard niet onder zijn inhoud. Zonder deze regel
	   duwt een lange elementnaam — de engine plakt id en streekkleur achter
	   "Path", en dat is zo dertig tekens — de hele kopregel de kaart uit, en
	   dan valt "Wis" van het paneel af. Dat stond zo op de screenshot en is
	   niet met het blote oog te zien aankomen. */
	.selected > * {
		min-width: 0;
	}
	.selected .head {
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
	}
	/* De naam mag wijken vóór de rest: hij is het langste en het minst kritiek
	   — wat je vast hebt zie je ook op het canvas, "Wis" nergens anders. */
	.selected .head .name { flex: 0 1 auto; }
	.selected .head .in-layers { flex: 0 1 auto; min-width: 0; overflow: hidden; }
	.selected .name {
		font-weight: 600;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.in-layers {
		font-size: var(--text-xs);
		color: var(--text-2);
		white-space: nowrap;
	}
	.clear {
		font-size: var(--text-xs);
		color: var(--accent);
		flex: none;
		margin-left: auto;
	}

	/* Twee kolommen getallen met de eenheid één keer rechts. Een vast raster in
	   plaats van wrappende pillen: alleen zo staan B boven X en H boven Y, en
	   dat is wat de vier velden als twee paren laat lezen. */
	.figures {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
		align-items: end;
		gap: var(--space-1) var(--space-2);
	}
	.figures .f {
		display: flex;
		align-items: stretch;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		overflow: hidden;
		min-width: 0;
	}
	.figures .f:focus-within {
		border-color: var(--accent);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 30%, transparent);
	}
	/* Het label zit ín het veld en niet erboven: een aparte labelregel boven
	   vier velden kost twee regels hoogte voor twee tekens informatie. */
	.figures .f > span {
		display: grid;
		place-items: center;
		padding: 0 var(--space-1) 0 var(--space-2);
		font-size: var(--text-xs);
		color: var(--text-2);
		flex: none;
	}
	.figures input {
		font: inherit;
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		font-variant-numeric: tabular-nums;
		/* min-width: 0 en flex: 1 — zonder dat houdt een number-input zijn
		   eigen minimumbreedte aan en werd "145.0" tot "145." afgekapt. Dat
		   stond zo op de tablet in beeld. */
		flex: 1;
		width: 100%;
		min-width: 0;
		text-align: right;
		padding: var(--space-1h) var(--space-2) var(--space-1h) 0;
		border: 0;
		background: transparent;
		color: var(--text-1);
		outline: none;
	}
	.figures input::-webkit-outer-spin-button,
	.figures input::-webkit-inner-spin-button {
		appearance: none;
		margin: 0;
	}
	.figures input[type='number'] {
		appearance: textfield;
		-moz-appearance: textfield;
	}
	.figures input:disabled { opacity: 0.6; }
	.figures .unit {
		font-size: var(--text-xs);
		color: var(--text-2);
		padding-bottom: var(--space-1h);
		text-align: center;
		min-width: 1.6em;
	}
	.figures .link {
		display: grid;
		place-items: center;
		width: 100%;
		min-width: 1.6em;
		height: 30px;
		border: 1px solid transparent;
		border-radius: var(--radius-field);
		color: var(--text-2);
	}
	.figures .link[aria-pressed='true'] {
		color: var(--accent);
		border-color: color-mix(in srgb, var(--accent) 40%, transparent);
		background: color-mix(in srgb, var(--accent) 10%, transparent);
	}
	.figures .link:hover:not(:disabled) { background: var(--surface-2); }

	/* Hoek plus vier stapjes op één regel. Het hoekveld krijgt bewust meer
	   ruimte dan een knop: er moet "337,5" in passen, en een afgekapt getal is
	   erger dan geen getal — dan geloof je wat er staat. */
	.rotrow {
		grid-template-columns: minmax(4.6em, 1.6fr) repeat(4, minmax(0, 1fr));
		align-items: center;
	}
	.rotrow .f.angle > span:first-child {
		padding-right: 0;
		font-size: var(--text-sm);
	}
	.rotrow .f.angle input { padding-right: 0; }
	.figures .suffix {
		display: grid;
		place-items: center;
		flex: none;
		padding: 0 var(--space-2) 0 2px;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.figures .f.mixed input { color: var(--text-2); }
	.icon.step {
		width: 100%;
		height: 30px;
	}
	.stepnum {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		font-variant-numeric: tabular-nums;
	}

	/* De pictogramrijen. Vier per rij, want vier van 44 px passen met tussenruimte
	   in een paneel van 279 px en zes niet — en vier laat de indeling bovendien
	   samenvallen met de betekenis: rij één horizontaal, rij twee verticaal. */
	.tools {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: var(--space-2);
	}
	.tool {
		display: grid;
		place-items: center;
		height: 36px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		color: var(--text-1);
	}
	.tool:hover:not(:disabled) {
		background: var(--surface-2);
		border-color: var(--accent);
		color: var(--accent);
	}
	.tool:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
	/* Knoppen zonder rand voor geschiedenis en draaistapjes: die horen bij het
	   veld ernaast, niet bij het raster eronder. */
	.icon {
		display: grid;
		place-items: center;
		width: 30px;
		height: 30px;
		border-radius: var(--radius-field);
		color: var(--text-2);
	}
	.icon:hover:not(:disabled) {
		background: var(--surface-2);
		color: var(--text-1);
	}
	.icon:disabled { opacity: 0.4; cursor: not-allowed; }

	/* Het anker: waar je vandaan kwam, en de weg terug. Neutraal van kleur —
	   dit is geen waarschuwing maar een aantekening. */
	.anchor {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
		padding: var(--space-2);
		border: 1px dashed var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.anchor-what { min-width: 0; }
	.anchor-what b { color: var(--text-1); font-weight: 600; }
	.anchor-back {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		flex: none;
		padding: var(--space-1) var(--space-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		font-size: var(--text-xs);
		color: var(--accent-text);
	}
	.anchor-back:hover:not(:disabled) { border-color: var(--accent); }

	/* Ingeklapte groepen. De samenvatting blijft een gewone leesbare regel met
	   een driehoekje — je kunt hem vinden zonder te weten dat hij er is. */
	.fold {
		border-top: 1px solid var(--line);
		padding-top: var(--space-2);
		margin-top: calc(var(--space-1) * -1);
	}
	.fold + .fold { margin-top: calc(var(--space-3) * -1 + var(--space-1)); }
	.fold summary {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		cursor: pointer;
		font-size: var(--text-xs);
		font-weight: 500;
		color: var(--text-1);
		min-height: 24px;
	}
	/* Eigen driehoekje. `display: flex` op een summary laat de standaardmarker
	   van de browser vallen, en dan is een dichtgeklapte groep niet van een kop
	   te onderscheiden — precies de reden waarom je zo'n groep niet mag
	   verstoppen. */
	.fold summary::-webkit-details-marker { display: none; }
	.fold summary::marker { content: ''; }
	.fold summary::before {
		content: '';
		flex: none;
		width: 0;
		height: 0;
		border-left: 5px solid currentColor;
		border-top: 4px solid transparent;
		border-bottom: 4px solid transparent;
		transition: transform 120ms ease;
	}
	.fold[open] summary::before { transform: rotate(90deg); }
	.fold summary:hover { color: var(--accent); }
	.fold-note {
		font-weight: 400;
		color: var(--text-2);
	}
	.fold-note.on {
		color: var(--accent-text);
		font-variant-numeric: tabular-nums;
	}
	.fold > :not(summary) { margin-top: var(--space-2); }
	.fold .arrange { margin-top: var(--space-2); }

	/* Naast de machine met een vinger. Deze blok staat bewust hélemaal
	   onderaan: de regels hierboven hebben dezelfde specificiteit, dus wie
	   eerder staat verliest — en toen dit blok halverwege stond, hield de
	   draairij zijn zes kolommen van de desktop en liep de kaart aan de
	   rechterkant het paneel uit. */
	@media (max-width: 1199px), (pointer: coarse) {
		/* Dikke vingers: elk doel in de selectiekaart haalt 44 px, met minstens
		   12 px ertussen. Vier van 44 plus drie tussenruimtes van 12 is 212 px
		   en dat past in het paneel van 279 px; zes zou niet passen, en daarom
		   staan de pictogrammen in rijen van vier. */
		.tool,
		.icon,
		.icon.step,
		.figures .link {
			height: 44px;
			min-height: 44px;
		}
		.icon { width: 44px; }
		.tools { gap: var(--space-3); }
		/* De knoppen in een ingeklapte groep stonden 4 px uit elkaar — met een
		   handschoen aan raak je dan "Vereenvoudigen" terwijl je "Offset…"
		   bedoelde. Gemeten en bijgesteld naar 12. */
		.arrange { gap: var(--space-3); }
		.figures { gap: var(--space-2) var(--space-3); }
		.figures input {
			/* 44 en niet 43: het veld haalde het net niet omdat de rand van de
			   omhullende twee pixels opsnoept. */
			min-height: 44px;
			padding-top: var(--space-3);
			padding-bottom: var(--space-3);
		}
		.rotrow {
			/* Het hoekveld en vier knoppen van 44 px passen niet naast elkaar op
			   een tablet. Het veld krijgt daarom de volle breedte; de stapjes
			   houden hun volle raakvlak op de regel eronder. */
			grid-template-columns: repeat(4, minmax(0, 1fr));
		}
		.rotrow .f.angle { grid-column: 1 / -1; }
		.fold summary { min-height: 44px; }
		.anchor-back { min-height: 44px; }
	}
</style>
