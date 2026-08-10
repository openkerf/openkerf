<script lang="ts">
	export type Tool = 'select' | 'rect' | 'circle' | 'line' | 'text';

	let {
		tool = $bindable(),
		canEdit = false,
		onOpenGrid,
		onOpenLibrary,
		onPlaceImage,
		onOpenCatalogue
	}: {
		tool: Tool;
		canEdit?: boolean;
		onOpenGrid?: () => void;
		onOpenLibrary?: () => void;
		onPlaceImage?: (file: File) => void;
		onOpenCatalogue?: () => void;
	} = $props();

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
	<!-- Een afbeelding plaatsen voegt toe aan het ontwerp; "Openen" vervángt het. -->
	<label class="tool file" class:off={!canEdit} title="Afbeelding plaatsen">
		<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><rect x="3.5" y="5" width="17" height="14" rx="1"/><path d="M3.5 16l4.5-4 3.5 3 4-5 5 6"/></svg>
		<input
			type="file"
			accept=".png,.jpg,.jpeg,.gif,.bmp,.webp"
			disabled={!canEdit}
			onchange={(e) => {
				const input = e.currentTarget as HTMLInputElement;
				const file = input.files?.[0];
				input.value = '';
				if (file) onPlaceImage?.(file);
			}}
		/>
	</label>

	<hr />
	<!-- Gereedschappen begin je links; een gereedschap dat alleen rechts te
	     vinden is, vindt niemand. -->
	<button class="tool" title="Testraster" disabled={!canEdit} onclick={() => onOpenGrid?.()}>
		<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" aria-hidden="true"><rect x="3.5" y="3.5" width="17" height="17" rx="1"/><path d="M9.2 3.5v17M14.8 3.5v17M3.5 9.2h17M3.5 14.8h17"/></svg>
	</button>
	<button class="tool" title="Presetariat — gedeelde instellingen" onclick={() => onOpenCatalogue?.()}>
		<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v12"/><path d="M8 11l4 4 4-4"/><path d="M4 18v2h16v-2"/></svg>
	</button>
	<button class="tool" title="Materiaalbibliotheek" onclick={() => onOpenLibrary?.()}>
		<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M4 5h6v14H4zM14 5h6v14h-6z"/><path d="M4 9h6M14 9h6"/></svg>
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
	.tool.file input {
		position: absolute;
		width: 0;
		height: 0;
		opacity: 0;
	}
	.tool.file {
		position: relative;
		cursor: pointer;
	}
	.tool.file.off {
		opacity: 0.35;
		cursor: not-allowed;
	}
	hr {
		width: 28px;
		border: none;
		border-top: 1px solid var(--line);
		margin: var(--space-1) 0;
	}
</style>
