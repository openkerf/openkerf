<script lang="ts">
	import type { SheetStore } from '$lib/sheets.svelte';
	import type { LibraryStore } from '$lib/library.svelte';

	let {
		sheets,
		library,
		canEdit = false,
		onSwitched
	}: {
		sheets: SheetStore;
		library: LibraryStore;
		canEdit?: boolean;
		onSwitched?: () => void;
	} = $props();

	let editing = $state<string | null>(null);

	async function go(id: string) {
		if (sheets.active?.id === id) {
			editing = editing === id ? null : id;
			return;
		}
		if (await sheets.activate(id)) onSwitched?.();
	}

	function materialName(id: number | null) {
		return library.materials.find((m) => m.id === id)?.name ?? null;
	}
</script>

<div class="sheets">
	<!-- Eén rij vellen, zoals de platen van een slicer. Elk vel is een eigen
	     document: wat je ziet is precies wat er gebrand wordt. -->
	{#each sheets.sheets as sheet (sheet.id)}
		<button
			class="sheet"
			aria-pressed={sheet.active}
			disabled={sheets.busy}
			title="{sheet.name} — {sheet.width_mm} × {sheet.height_mm} mm{materialName(
				sheet.material_id
			)
				? ` · ${materialName(sheet.material_id)}`
				: ''}"
			onclick={() => go(sheet.id)}
		>
			<span class="name">{sheet.name}</span>
			<span class="size mono">{sheet.width_mm}×{sheet.height_mm}</span>
		</button>
	{/each}

	{#if canEdit}
		<button
			class="sheet add"
			disabled={sheets.busy}
			title="Vel toevoegen"
			onclick={() => sheets.add()}
		>+</button>
	{/if}

	{#if sheets.error}
		<span class="error">{sheets.error}</span>
	{/if}
</div>

{#if editing && sheets.active && canEdit}
	{@const sheet = sheets.active}
	<div class="editor">
		<label>
			<span>Naam</span>
			<input
				type="text"
				value={sheet.name}
				onchange={(e) => sheets.update(sheet.id, { name: e.currentTarget.value })}
			/>
		</label>
		<label>
			<span>Breedte</span>
			<input
				class="mono"
				type="number"
				step="10"
				min="5"
				value={sheet.width_mm}
				onchange={(e) => sheets.update(sheet.id, { width_mm: Number(e.currentTarget.value) })}
			/>
		</label>
		<label>
			<span>Hoogte</span>
			<input
				class="mono"
				type="number"
				step="10"
				min="5"
				value={sheet.height_mm}
				onchange={(e) => sheets.update(sheet.id, { height_mm: Number(e.currentTarget.value) })}
			/>
		</label>
		<label class="wide">
			<span>Materiaal</span>
			<select
				onchange={(e) =>
					sheets.update(sheet.id, {
						material_id: e.currentTarget.value ? Number(e.currentTarget.value) : null
					})}
			>
				<option value="" selected={sheet.material_id === null}>geen</option>
				{#each library.materials as material (material.id)}
					<option value={material.id} selected={material.id === sheet.material_id}>
						{material.name}
					</option>
				{/each}
			</select>
		</label>
		<button
			class="drop"
			disabled={sheets.sheets.length < 2 || sheets.busy}
			title={sheets.sheets.length < 2 ? 'Een project heeft minstens één vel' : undefined}
			onclick={async () => {
				if (await sheets.remove(sheet.id)) {
					editing = null;
					onSwitched?.();
				}
			}}
		>Vel verwijderen</button>
		<button class="close" onclick={() => (editing = null)}>Klaar</button>
	</div>
{/if}

<style>
	.sheets {
		flex: none;
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 4px var(--space-3);
		background: var(--surface-1);
		border-bottom: 1px solid var(--line);
		overflow-x: auto;
	}
	.sheet {
		flex: none;
		display: flex;
		align-items: baseline;
		gap: 8px;
		padding: 4px 8px;
		border-radius: 999px;
		border: 1px solid var(--line);
		background: var(--surface-1);
		color: var(--text-1);
		font-size: var(--text-xs);
	}
	.sheet:hover:not(:disabled) { background: var(--surface-2); color: var(--text-1); }
	.sheet[aria-pressed='true'] {
		/* Het accent zit in de rand en de tint, niet in de tekst: accentkleur op
		   een accenttint haalt maar 4,24:1 en dit zijn de kleinste letters in
		   beeld. De actieve staat is nog steeds dubbel gecodeerd (rand + tint +
		   aria-pressed). */
		border-color: var(--accent);
		color: var(--text-1);
		font-weight: 600;
		background: color-mix(in srgb, var(--accent) 10%, transparent);
	}
	/* Geen opacity op tekst: dat verlaagt het contrast onvoorspelbaar. De maat
	   is secundair, maar moet leesbaar blijven. */
	.sheet .size { font-size: var(--text-xs); color: var(--text-2); }
	.sheet.add { padding: 3px 10px; font-weight: 600; }
	.error { font-size: var(--text-xs); color: var(--danger); }
	.editor {
		flex: none;
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		gap: var(--space-2);
		padding: var(--space-2) var(--space-3);
		background: var(--surface-2);
		border-bottom: 1px solid var(--line);
	}
	.editor label { display: grid; gap: 2px; font-size: var(--text-xs); color: var(--text-2); }
	.editor input,
	.editor select {
		font: inherit;
		font-size: var(--text-xs);
		padding: 4px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		color: var(--text-1);
	}
	.editor input[type='text'] { width: 9em; }
	.editor input[type='number'] { width: 5em; }
	.drop,
	.close {
		font-size: var(--text-xs);
		padding: 4px 8px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
	}
	.drop { color: var(--danger); }
	.drop:disabled { opacity: 0.45; cursor: not-allowed; }
	.close { margin-left: auto; }
</style>
