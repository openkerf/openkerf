<script lang="ts">
	import type { DesignStore } from '$lib/design.svelte';
	import type { EditController } from '$lib/edits.svelte';

	let {
		design,
		edits,
		canEdit = false,
		onHistory,
		onRotate,
		onAssign
	}: {
		design: DesignStore;
		edits: EditController;
		canEdit?: boolean;
		onHistory?: (action: 'undo' | 'redo') => void;
		onRotate?: (angleDeg: number) => void;
		onAssign?: (operationId: string, assigned: boolean) => void;
	} = $props();

	let elements = $derived(design.elements);
	let operations = $derived(design.operations);
	let selected = $derived(design.selected);
	let size = $derived(design.selectedSize);
	let chosen = $derived(design.selectedElements);
	let selectedIds = $derived(design.selectedIds);

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
			<dl class="figures mono">
				<div><dt>Breedte</dt><dd>{size.width.toFixed(1)} mm</dd></div>
				<div><dt>Hoogte</dt><dd>{size.height.toFixed(1)} mm</dd></div>
				<div><dt>X</dt><dd>{size.x.toFixed(1)} mm</dd></div>
				<div><dt>Y</dt><dd>{size.y.toFixed(1)} mm</dd></div>
			</dl>
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
		<h2 class="section-title">Lagen</h2>
		{#each operations as op, index (op.id)}
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
			</div>
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
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-2);
		margin: var(--space-3) 0 0;
	}
	.figures dt {
		font-family: var(--font-ui);
		font-size: 10px;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-2);
	}
	.figures dd {
		margin: 1px 0 0;
	}
</style>
