<script lang="ts">
	import type { DesignStore } from '$lib/design.svelte';

	let { design }: { design: DesignStore } = $props();

	let elements = $derived(design.elements);
	let operations = $derived(design.operations);

	function describe(op: { speed: number | null; power: number | null }) {
		const parts: string[] = [];
		if (op.speed !== null) parts.push(`${op.speed} mm/s`);
		if (op.power !== null) parts.push(`${Math.round((op.power / 1000) * 100)}%`);
		return parts;
	}
</script>

<div class="section">
	<h2 class="section-title">Ontwerp</h2>
	{#if elements.length === 0}
		<p class="empty">
			Nog geen ontwerp geladen. Gebruik “Ontwerp laden…” in de Job-tab.
		</p>
	{:else}
		<p class="muted mono">{elements.length} element{elements.length === 1 ? '' : 'en'}</p>
	{/if}
</div>

{#if operations.length}
	<div class="section">
		<h2 class="section-title">Lagen</h2>
		{#each operations as op, index (op.id)}
			<div class="layer" class:muted-row={!op.output}>
				<span class="chip mono" style="background: {design.colorFor(op.id)}">{index + 1}</span>
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
</style>
