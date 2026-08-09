<script lang="ts">
	// Fase 1 heeft nog geen canvas-gereedschap; de rail staat er zodat de
	// layout-anatomie klopt en fase 3 er alleen gedrag in hoeft te hangen.
	let active = $state('select');
	const tools = [
		{ id: 'select', label: 'Selecteren', path: 'M4 3l7 18 2.5-7.5L21 11z' },
		{ id: 'draw', label: 'Tekenen', path: 'M17 3l4 4L8 20l-5 1 1-5z' },
		{ id: 'text', label: 'Tekst', path: 'M5 5h14M12 5v14' }
	];
</script>

<nav class="rail" aria-label="Gereedschap">
	{#each tools as tool (tool.id)}
		<button
			class="tool"
			aria-pressed={active === tool.id}
			title="{tool.label} — beschikbaar in fase 3"
			onclick={() => (active = tool.id)}
		>
			<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
				<path d={tool.path} />
			</svg>
		</button>
	{/each}
	<hr />
	<button class="tool" title="Testraster — beschikbaar in fase 4">
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
	.tool:hover {
		background: var(--surface-2);
		color: var(--text-1);
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
