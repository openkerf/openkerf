<script lang="ts">
	import { LAYER_COLORS, inktOp, type DesignStore } from '$lib/design.svelte';
	import type { EditController } from '$lib/edits.svelte';
	import NumberField from './NumberField.svelte';
	import Segmented from './Segmented.svelte';

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
	<div class="section-head">
		<h2 class="section-title">Ontwerp</h2>
		{#if canEdit}
			<div class="history">
				<button class="mini" disabled={edits.busy} onclick={() => onHistory?.('undo')}>
					Ongedaan maken
				</button>
				<button class="mini" disabled={edits.busy} onclick={() => onHistory?.('redo')}>
					Opnieuw
				</button>
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
	{:else}
		<p class="muted mono">{elements.length} element{elements.length === 1 ? '' : 'en'}</p>
	{/if}
</div>

{#if show === 'selection' && selected && size}
	<div class="section">
		<h2 class="section-title">Selectie</h2>
		<div class="selected">
			<div class="head">
				<span class="name">
					{chosen.length > 1 ? `${chosen.length} elementen` : selected.label}
				</span>
				<button class="clear" onclick={() => design.select(null)}>Wis</button>
			</div>
			<!-- Maten en positie horen bij de selectie, dus hier en niet in de
			     bovenbalk: alles wat je met het gekozen object doet, staat bij
			     elkaar. Lezen tijdens het slepen, bewerken zodra je loslaat. -->
			<div class="figures mono">
				{#each [['B', 'width'], ['H', 'height']] as [label, key] (key)}
					<label>
						<span>{label}</span>
						<input
							type="number"
							step="0.1"
							min="0.1"
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
					title={linked ? 'Verhouding vast' : 'Breedte en hoogte los'}
					onclick={() => (linked = !linked)}
				>
					<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
						{#if linked}
							<path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1" />
							<path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1" />
						{:else}
							<path d="M9 12H5a3 3 0 0 1 0-6h4M15 12h4a3 3 0 0 1 0 6h-4" />
						{/if}
					</svg>
				</button>
				{#each [['X', 'x'], ['Y', 'y']] as [label, key] (key)}
					<label>
						<span>{label}</span>
						<input
							type="number"
							step="0.1"
							disabled={!canEdit}
							value={(live ?? size)[key as 'x' | 'y'].toFixed(1)}
							onchange={(e) => commitPosition(key as 'x' | 'y', e.currentTarget.value)}
						/>
					</label>
				{/each}
				<span class="unit">mm</span>
			</div>
			{#if canEdit && selected.text}
				<button class="edit-text" onclick={() => onEditText?.(selected.id)}>
					Tekst bewerken — “{selected.text.text}”
				</button>
			{/if}

			{#if canEdit}
				<div class="arrange">
					<span class="rot-label">Pad</span>
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
			{/if}

			{#if canEdit && selected.image}
				<!-- Bewerkingen zijn niet destructief: het recept gaat elke keer
				     opnieuw over het origineel. Vandaar schakelaars met hun
				     waarden erbij, en niet een rij knoppen waarvan je moet
				     onthouden waar je op gedrukt hebt. -->
				<div class="imagefx">
					<div class="fx-head">
						<span class="rot-label">Afbeelding</span>
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
			{/if}

			{#if selected.effect}
				<p class="hint">Zit in effect: {selected.effect.label}</p>
			{/if}

			{#if canEdit}
				<div class="arrange">
					<span class="rot-label">Spiegelen</span>
					<button class="rot" disabled={edits.busy} onclick={() => onArrange?.('mirror-h')}>Horizontaal</button>
					<button class="rot" disabled={edits.busy} onclick={() => onArrange?.('mirror-v')}>Verticaal</button>
				</div>
			{/if}

			<!-- Deze groepen blijven staan bij één selectie, uitgeschakeld met de
			     reden erbij. Verborgen knoppen kun je niet ontdekken: wie nooit
			     twee vormen tegelijk selecteert, weet niet dat combineren en
			     uitlijnen bestaan. -->
			{#if canEdit}
				{@const enough = chosen.length > 1}
				{@const why = enough ? undefined : 'Selecteer minstens twee vormen'}
				<div class="arrange">
					<!-- Booleaans: het resultaat is één pad, de vormen verdwijnen. -->
					<span class="rot-label">Combineren</span>
					{#each [['union', 'Verenigen'], ['difference', 'Verschil'], ['intersection', 'Doorsnede'], ['xor', 'Uitsluiten']] as [op, label] (op)}
						<button
							class="rot"
							disabled={edits.busy || !enough}
							title={why}
							onclick={() => onArrange?.(op)}
						>{label}</button>
					{/each}
				</div>

				<div class="arrange">
					<span class="rot-label">Uitlijnen</span>
					{#each [['left', 'Links'], ['centerh', 'Midden'], ['right', 'Rechts'], ['top', 'Boven'], ['centerv', 'Midden'], ['bottom', 'Onder']] as [mode, label] (mode)}
						<button
							class="rot"
							disabled={edits.busy || !enough}
							title={why}
							onclick={() => onArrange?.(mode)}
						>{label}</button>
					{/each}
					<span class="rot-label">Verdelen</span>
					<button
						class="rot"
						disabled={edits.busy || chosen.length < 3}
						title={chosen.length < 3 ? 'Selecteer minstens drie vormen' : undefined}
						onclick={() => onArrange?.('spaceh')}
					>Horizontaal</button>
					<button
						class="rot"
						disabled={edits.busy || chosen.length < 3}
						title={chosen.length < 3 ? 'Selecteer minstens drie vormen' : undefined}
						onclick={() => onArrange?.('spacev')}
					>Verticaal</button>
				</div>

				{#if !enough}
					<p class="tip">
						Combineren en uitlijnen werken op meerdere vormen: sleep een kader
						om ze heen, of houd shift ingedrukt terwijl je klikt.
					</p>
				{/if}
			{/if}

			{#if canEdit}
				{#if otherSheets.length}
					<div class="arrange">
						<!-- Verhuizen naar een ander vel: de selectie gaat mee via het
						     klembord van de engine, dus operaties en kleuren blijven. -->
						<span class="rot-label">Naar vel</span>
						{#each otherSheets as sheet (sheet.id)}
							<button
								class="rot"
								disabled={edits.busy}
								title="Verplaats de selectie naar {sheet.name}"
								onclick={() => onMoveToSheet?.(sheet.id)}
							>{sheet.name}</button>
						{/each}
					</div>
				{/if}

				<div class="arrange">
					<button
						class="rot"
						disabled={edits.busy || chosen.length < 2}
						title={chosen.length < 2 ? 'Selecteer minstens twee vormen' : undefined}
						onclick={() => onArrange?.('group')}
					>Groeperen</button>
					<button
						class="rot"
						disabled={edits.busy || !selected.group_id}
						title={selected.group_id ? undefined : 'Deze vorm zit niet in een groep'}
						onclick={() => onArrange?.('ungroup')}
					>Groep opheffen</button>
				</div>
			{/if}

			{#if canEdit}
				<div class="rotate">
					<span class="rot-label">Draaien</span>
					{#each [-90, -1, 1, 90] as angle (angle)}
						<button
							class="rot"
							disabled={edits.busy}
							onclick={() => onRotate?.(angle)}
						>{angle > 0 ? `+${angle}` : angle}°</button>
					{/each}
				</div>
			{/if}

			<p class="hint">
				{chosen.length > 1 ? 'Samen' : 'Zit'} in {selected.operation_ids.length} laag{selected
					.operation_ids.length === 1
					? ''
					: 'en'}.
				{#if canEdit}
					Sleep het kader om te verplaatsen, de hoeken om te schalen. Pijltjes: 0,1 mm,
					met shift 1 mm.
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
			<div class="layer" class:off={!op.output} class:open>
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
		margin: var(--space-3) 0 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.section-head {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--space-2);
	}
	.history {
		display: flex;
		gap: var(--space-3);
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
	.mini {
		font-size: var(--text-xs);
		color: var(--accent);
	}
	.mini:disabled {
		opacity: 0.45;
		cursor: not-allowed;
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
		margin-top: var(--space-3);
		padding: 8px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		font-size: var(--text-xs);
		text-align: left;
		color: var(--accent);
	}
	.edit-text:hover { background: var(--surface-2); }
	.imagefx { display: grid; gap: 4px; margin-top: var(--space-3); }
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
		margin: 2px 0 0;
		font-size: var(--text-xs);
		line-height: 1.45;
		color: var(--text-2);
	}
	.arrange {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-1);
		margin-top: var(--space-3);
	}
	.rotate {
		display: flex;
		align-items: center;
		gap: var(--space-1);
		margin-top: var(--space-3);
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
	}
	.selected .head {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: var(--space-2);
	}
	.selected .name {
		font-weight: 600;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.clear {
		font-size: var(--text-xs);
		color: var(--accent);
		flex: none;
	}
	.figures {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		gap: 4px 8px;
		margin-bottom: var(--space-3);
	}
	.figures label { display: grid; gap: 1px; font-size: var(--text-xs); color: var(--text-2); }
	.figures input {
		font: inherit;
		width: 4.6em;
		padding: 4px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.figures input:disabled { opacity: 0.6; }
	.figures .unit { font-size: var(--text-xs); color: var(--text-2); padding-bottom: 5px; }
	.figures .link {
		display: grid;
		place-items: center;
		width: 24px;
		height: 26px;
		border-radius: var(--radius-field);
		color: var(--text-2);
	}
	.figures .link[aria-pressed='true'] { color: var(--accent); }
	.figures .link:hover:not(:disabled) { background: var(--surface-2); }
</style>