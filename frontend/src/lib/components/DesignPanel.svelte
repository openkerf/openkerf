<script lang="ts">
	import type { DesignStore } from '$lib/design.svelte';
	import type { EditController } from '$lib/edits.svelte';

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
		onUncrop
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
	} = $props();

	let elements = $derived(design.elements);
	let operations = $derived(design.operations);
	let selected = $derived(design.selected);
	let size = $derived(design.selectedSize);
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

	async function addLayer() {
		if (await edits.addLayer(newLayerType)) onLayerChange?.();
	}

	async function patchLayer(id: string, fields: Record<string, unknown>) {
		if (await edits.updateLayer(id, fields)) onLayerChange?.();
	}

	async function dropLayer(id: string) {
		if (await edits.removeLayer(id)) onLayerChange?.();
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
		<p class="empty">
			Nog geen ontwerp geladen. Gebruik “Ontwerp laden…” in de Job-tab.
		</p>
	{:else}
		<p class="muted mono">{elements.length} element{elements.length === 1 ? '' : 'en'}</p>
	{/if}
</div>

{#if selected && size}
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

			{#if canEdit && chosen.length > 1}
				<div class="arrange">
					<!-- Booleaans: het resultaat is één pad, de vormen verdwijnen. -->
					<span class="rot-label">Combineren</span>
					{#each [['union', 'Verenigen'], ['difference', 'Verschil'], ['intersection', 'Doorsnede'], ['xor', 'Uitsluiten']] as [op, label] (op)}
						<button class="rot" disabled={edits.busy} onclick={() => onArrange?.(op)}>{label}</button>
					{/each}
				</div>

				<div class="arrange">
					<span class="rot-label">Uitlijnen</span>
					{#each [['left', 'Links'], ['centerh', 'Midden'], ['right', 'Rechts'], ['top', 'Boven'], ['centerv', 'Midden'], ['bottom', 'Onder']] as [mode, label] (mode)}
						<button class="rot" disabled={edits.busy} onclick={() => onArrange?.(mode)}>{label}</button>
					{/each}
					<span class="rot-label">Verdelen</span>
					<button class="rot" disabled={edits.busy} onclick={() => onArrange?.('spaceh')}>Horizontaal</button>
					<button class="rot" disabled={edits.busy} onclick={() => onArrange?.('spacev')}>Verticaal</button>
				</div>
			{/if}

			{#if canEdit && (chosen.length > 1 || selected.group_id)}
				<div class="arrange">
					{#if chosen.length > 1}
						<button class="rot" disabled={edits.busy} onclick={() => onArrange?.('group')}>Groeperen</button>
					{/if}
					{#if selected.group_id}
						<button class="rot" disabled={edits.busy} onclick={() => onArrange?.('ungroup')}>Groep opheffen</button>
					{/if}
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

{#if operations.length}
	<div class="section">
		<div class="section-head">
			<h2 class="section-title">Lagen</h2>
			{#if canEdit}
				<div class="addrow">
					<select bind:value={newLayerType} aria-label="Type nieuwe laag">
						{#each [['cut', 'Snijden'], ['engrave', 'Graveren'], ['raster', 'Raster'], ['dots', 'Punten']] as [value, label] (value)}
							<option {value}>{label}</option>
						{/each}
					</select>
					<button class="mini" disabled={edits.busy} onclick={addLayer}>Toevoegen</button>
				</div>
			{/if}
		</div>
		{#each plainLayers as op, index (op.id)}
			<div class="layer" class:muted-row={!op.output}>
				<span class="chip mono" style="background: {design.colorFor(op.id)}">{index + 1}</span>
				{#if canEdit && selectedIds.length}
					<!-- Toewijzen: de selectie in of uit deze bewerking halen. -->
					<input
						type="checkbox"
						class="assign"
						title="Selectie in deze bewerking"
						aria-label="Selectie toewijzen aan {op.label}"
						checked={membership(op.id) === 'all'}
						indeterminate={membership(op.id) === 'some'}
						disabled={edits.busy}
						onchange={(e) => onAssign?.(op.id, e.currentTarget.checked)}
					/>
				{/if}
				<div class="layer-name">
					<div class="op">{op.label}</div>
					<div class="obj">
						{op.element_ids.length} element{op.element_ids.length === 1 ? '' : 'en'}
						{#if !op.output}· uit{/if}
					</div>
				</div>
				<div class="layer-vals">
					{#each describe(op) as value (value)}
						<span class="pill mono">{value}</span>
					{/each}
				</div>
				{#if canEdit}
					<button
						class="eye"
						title={editingLayer === op.id ? 'Sluiten' : 'Laag bewerken'}
						aria-label="Laag {op.label} bewerken"
						onclick={() => (editingLayer = editingLayer === op.id ? null : op.id)}
					>⋯</button>
				{/if}
			</div>

			{#if canEdit && editingLayer === op.id}
				<div class="layer-edit">
					<label>
						<span>Naam</span>
						<input
							type="text"
							value={op.label}
							onchange={(e) => patchLayer(op.id, { label: e.currentTarget.value })}
						/>
					</label>
					<label>
						<span>Snelheid (mm/s)</span>
						<input
							class="mono"
							type="number"
							step="1"
							min="0.1"
							value={op.speed ?? ''}
							onchange={(e) => patchLayer(op.id, { speed: Number(e.currentTarget.value) })}
						/>
					</label>
					<label>
						<span>Vermogen (%)</span>
						<input
							class="mono"
							type="number"
							step="1"
							min="1"
							max="100"
							value={op.power !== null ? Math.round(op.power / 10) : ''}
							onchange={(e) =>
								patchLayer(op.id, { power_percent: Number(e.currentTarget.value) })}
						/>
					</label>
					<label>
						<span>Passes</span>
						<input
							class="mono"
							type="number"
							step="1"
							min="1"
							value={op.passes ?? 1}
							onchange={(e) => patchLayer(op.id, { passes: Number(e.currentTarget.value) })}
						/>
					</label>
					{#if op.type === 'op raster' || op.type === 'op image'}
						<!-- Alleen rasteren gebruikt deze; bij snijden zijn ze zinloos. -->
						<label>
							<span>DPI</span>
							<input
								class="mono"
								type="number"
								step="10"
								min="10"
								max="2000"
								value={op.dpi ?? 500}
								onchange={(e) => patchLayer(op.id, { dpi: Number(e.currentTarget.value) })}
							/>
						</label>
						<label>
							<span>Overscan (mm)</span>
							<input
								class="mono"
								type="number"
								step="0.5"
								min="0"
								max="50"
								value={parseFloat(op.overscan ?? '0.5') || 0}
								onchange={(e) =>
									patchLayer(op.id, { overscan_mm: Number(e.currentTarget.value) })}
							/>
						</label>
						<label class="check">
							<input
								type="checkbox"
								checked={op.bidirectional}
								onchange={(e) =>
									patchLayer(op.id, { bidirectional: e.currentTarget.checked })}
							/>
							<span>Heen en weer graveren</span>
						</label>
					{/if}
					<label class="check">
						<input
							type="checkbox"
							checked={op.output}
							onchange={(e) => patchLayer(op.id, { output: e.currentTarget.checked })}
						/>
						<span>Meebranden</span>
					</label>
					<button class="danger" onclick={() => dropLayer(op.id)}>Laag verwijderen</button>
				</div>
			{/if}
		{/each}

		{#each gridGroups as group (group.id)}
			<div class="layer grid-row">
				<span class="chip mono grid-chip">R</span>
				<div class="layer-name">
					<div class="op">Testraster #{group.id}</div>
					<div class="obj">{group.ops.length} cellen · snelheid en vermogen liggen vast</div>
				</div>
				<button
					class="eye"
					aria-label="Cellen van raster {group.id} tonen"
					onclick={() => (openGrid = openGrid === group.id ? null : group.id)}
				>{openGrid === group.id ? '−' : '+'}</button>
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
						<button class="danger cells-remove" onclick={() => removeGrid(group.id)}>
							Raster uit ontwerp verwijderen
						</button>
					{/if}
				</div>
			{/if}
		{/each}
		<p class="hint">
			Lagen bewerken en elementen verslepen komt later in fase 3; dit is wat de engine nu heeft.
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
	.layer {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: 7px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
	}
	.layer + .layer {
		margin-top: 6px;
	}
	.layer.muted-row {
		opacity: 0.55;
	}
	.chip {
		width: 20px;
		height: 20px;
		flex: none;
		border-radius: 4px;
		display: grid;
		place-items: center;
		font-size: 10px;
		font-weight: 500;
		color: #fff;
	}
	.layer-name {
		flex: 1;
		min-width: 0;
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
	.layer-vals {
		display: flex;
		gap: var(--space-1);
	}
	.pill {
		font-size: var(--text-xs);
		padding: 3px 7px;
		border-radius: 4px;
		background: var(--surface-2);
	}
	.hint {
		margin: var(--space-3) 0 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.section-head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--space-2);
	}
	.history {
		display: flex;
		gap: var(--space-1);
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
		padding: 6px 8px;
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
		padding: 5px 7px;
	}
	.fx.on { border-color: color-mix(in srgb, var(--accent) 45%, var(--line)); }
	.fx-toggle {
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: var(--text-xs);
		color: var(--text-1);
	}
	.fx-value {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-top: 3px;
		font-size: 10px;
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
	.dpi { display: flex; align-items: center; gap: 4px; font-size: 10px; color: var(--text-2); }
	.dpi input {
		width: 4.5em;
		font: inherit;
		padding: 2px 4px;
		border: 1px solid var(--line);
		border-radius: 4px;
		background: var(--surface-2);
		color: var(--text-1);
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
		font-size: 10px;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-2);
		margin-right: var(--space-1);
	}
	.rot {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		padding: 3px 7px;
		border: 1px solid var(--line);
		border-radius: 4px;
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
		margin-bottom: 6px;
	}
	.cell {
		display: flex;
		align-items: center;
		gap: 3px;
		font-size: 10px;
		color: var(--text-2);
		padding: 2px 4px;
		border-radius: 3px;
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
	.addrow { display: flex; gap: var(--space-1); align-items: center; }
	.addrow select {
		font: inherit;
		font-size: var(--text-xs);
		padding: 2px 4px;
		border: 1px solid var(--line);
		border-radius: 4px;
		background: var(--surface-2);
		color: var(--text-1);
	}
	.layer-edit {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-2);
		padding: var(--space-3);
		margin-top: -1px;
		border: 1px solid var(--accent);
		border-radius: 0 0 var(--radius-field) var(--radius-field);
	}
	.layer-edit label { display: grid; gap: 2px; font-size: 10px; color: var(--text-2); }
	.layer-edit label.check {
		grid-template-columns: auto 1fr;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-xs);
	}
	.layer-edit input[type='text'],
	.layer-edit input[type='number'] {
		font: inherit;
		width: 100%;
		padding: 4px 6px;
		border: 1px solid var(--line);
		border-radius: 4px;
		background: var(--surface-2);
		color: var(--text-1);
	}
	.layer-edit .danger {
		grid-column: 1 / -1;
		font-size: var(--text-xs);
		color: var(--danger);
		text-align: left;
	}
	.eye {
		color: var(--text-2);
		width: 20px;
		flex: none;
	}
	.assign {
		width: 15px;
		height: 15px;
		flex: none;
		accent-color: var(--accent);
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
		gap: 4px 6px;
		margin-bottom: var(--space-3);
	}
	.figures label { display: grid; gap: 1px; font-size: 9px; color: var(--text-2); }
	.figures input {
		font: inherit;
		width: 4.6em;
		padding: 4px 6px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.figures input:disabled { opacity: 0.6; }
	.figures .unit { font-size: 9px; color: var(--text-2); padding-bottom: 5px; }
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