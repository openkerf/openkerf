<script lang="ts">
	export type Tool = 'select' | 'rect' | 'circle' | 'line' | 'text';

	let {
		tool = $bindable(),
		canEdit = false
	}: { tool: Tool; canEdit?: boolean } = $props();

	// Elk gereedschap tekent bij een klik op het bed; selecteren is de rust-stand.
	const TOOLS: { id: Tool; label: string; path: string }[] = [
		{ id: 'select', label: 'Selecteren', path: 'M4 3l7 18 2.5-7.5L21 11z' },
		{ id: 'rect', label: 'Rechthoek', path: 'M4 6h16v12H4z' },
		{ id: 'circle', label: 'Cirkel', path: 'M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16z' },
		{ id: 'line', label: 'Lijn', path: 'M4 20L20 4' },
		{ id: 'text', label: 'Tekst', path: 'M5 6h14M12 6v13' }
	];
</script>

<nav class="rail" aria-label="Gereedschap">
	{#each TOOLS as item (item.id)}
		<button
			class="tool"
			aria-pressed={tool === item.id}
			title={item.id === 'select' || canEdit ? item.label : `${item.label} — vereist een token`}
			disabled={item.id !== 'select' && !canEdit}
			onclick={() => (tool = item.id)}
		>
			<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
				<path d={item.path} />
			</svg>
		</button>
	{/each}
	<hr />
	<button class="tool" title="Testraster — via het paneel rechts" disabled>
		<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" aria-hidden="true"><rect x="3.5" y="3.5" width="17" height="17" rx="1"/><path d="M9.2 3.5v17M14.8 3.5v17M3.5 9.2h17M3.5 14.8h17"/></svg>
	</button>
</nav>

<style>
	.rail {
		width: var(--rail-width);
		flex: none;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-1);
		padding: var(--space-2) 0;
		background: var(--surface-1);
		border-right: 1px solid var(--line);
	}
	.tool {
		display: grid;
		place-items: center;
		width: 40px;
		height: 40px;
		border-radius: var(--radius-field);
		color: var(--text-2);
		transition: background var(--transition);
	}
	.tool:hover:not(:disabled) {
		background: var(--surface-2);
		color: var(--text-1);
	}
	.tool:disabled {
		opacity: 0.35;
		cursor: not-allowed;
	}
	.tool[aria-pressed='true'] {
		background: color-mix(in srgb, var(--accent) 12%, transparent);
		color: var(--accent);
	}
	hr {
		width: 28px;
		border: none;
		border-top: 1px solid var(--line);
		margin: var(--space-1) 0;
	}
</style>
