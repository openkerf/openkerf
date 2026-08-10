<script lang="ts">
	import Dialog from './Dialog.svelte';

	let {
		open = $bindable(),
		initial = null,
		onConfirm
	}: {
		open: boolean;
		/** Gevuld bij bewerken van bestaande tekst. */
		initial?: {
			text: string;
			font: string;
			font_size_mm: number | null;
			spacing: number;
			align: string;
		} | null;
		onConfirm: (options: {
			text: string;
			font: string;
			font_size_mm: number;
			spacing: number;
			align: string;
		}) => void;
	} = $props();

	type Font = { file: string; name: string };

	let fonts = $state<Font[]>([]);
	let filter = $state('');
	let text = $state('');
	let font = $state('');
	let size = $state('10');
	let spacing = $state('1');
	let align = $state('start');
	let loaded = false;
	let filled = false;

	// Bij bewerken beginnen met wat er staat, niet met lege velden.
	$effect(() => {
		if (!open) {
			filled = false;
			return;
		}
		if (filled || !initial) return;
		filled = true;
		text = initial.text;
		size = String(initial.font_size_mm ?? 10);
		spacing = String(initial.spacing ?? 1);
		align = initial.align ?? 'start';
		font = '';
	});

	// Pas laden als het venster voor het eerst opengaat: 200+ systeemfonts
	// ophalen bij het starten van de app is verspilling.
	$effect(() => {
		if (!open || loaded) return;
		loaded = true;
		fetch('/api/design/fonts')
			.then((r) => (r.ok ? r.json() : []))
			.then((list) => (fonts = list));
	});

	let shown = $derived(
		filter.trim()
			? fonts.filter((f) => f.name.toLowerCase().includes(filter.trim().toLowerCase()))
			: fonts
	);

	function confirm() {
		if (!text.trim()) return;
		onConfirm({
			text: text.trim(),
			font,
			font_size_mm: Number(size) || 10,
			spacing: Number(spacing) || 1,
			align
		});
		text = '';
		open = false;
	}
</script>

<Dialog title="Tekst plaatsen" bind:open width="480px">
	<label class="field">
		<span>Tekst</span>
		<!-- svelte-ignore a11y_autofocus -->
		<input
			type="text"
			bind:value={text}
			autofocus
			placeholder="bijv. Stellendam"
			onkeydown={(e) => {
				if (e.key === 'Enter') confirm();
			}}
		/>
	</label>

	<div class="row">
		<label class="field">
			<span>Hoogte (mm)</span>
			<input class="mono" type="number" step="0.5" min="0.5" bind:value={size} />
		</label>
		<label class="field">
			<span>Letterspatiëring</span>
			<input class="mono" type="number" step="0.05" min="0.1" bind:value={spacing} />
		</label>
	</div>

	<label class="field">
		<span>Uitlijning</span>
		<select bind:value={align}>
			<option value="start">Links</option>
			<option value="middle">Gecentreerd</option>
			<option value="end">Rechts</option>
		</select>
	</label>

	<label class="field">
		<span>
			Lettertype ({fonts.length} beschikbaar){initial?.font ? ` — nu: ${initial.font}` : ''}
		</span>
		<input type="search" bind:value={filter} placeholder="Zoek een lettertype…" />
	</label>
	<div class="fonts">
		<button class="font" class:picked={font === ''} onclick={() => (font = '')}>
			Standaard
		</button>
		{#each shown.slice(0, 200) as item (item.file)}
			<button
				class="font"
				class:picked={font === item.file}
				onclick={() => (font = item.file)}
			>{item.name}</button>
		{/each}
	</div>

	<div class="actions">
		<button class="btn" onclick={() => (open = false)}>Annuleren</button>
		<button class="btn primary" disabled={!text.trim()} onclick={confirm}>
			{initial ? 'Bijwerken' : 'Plaatsen'}
		</button>
	</div>
</Dialog>

<style>
	.field {
		display: grid;
		gap: 2px;
		margin-bottom: var(--space-3);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.row {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-3);
	}
	input,
	select {
		font: inherit;
		width: 100%;
		padding: 7px 9px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.fonts {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		max-height: 180px;
		overflow-y: auto;
		padding: var(--space-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
	}
	.font {
		font-size: var(--text-xs);
		padding: 3px 8px;
		border: 1px solid var(--line);
		border-radius: 999px;
		background: var(--surface-1);
		color: var(--text-2);
	}
	.font:hover { background: var(--surface-2); color: var(--text-1); }
	.font.picked {
		border-color: var(--accent);
		color: var(--accent);
		background: color-mix(in srgb, var(--accent) 10%, transparent);
	}
	.actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--space-2);
		margin-top: var(--space-4);
	}
	.btn {
		padding: 8px 14px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		font-weight: 500;
	}
	.btn:hover:not(:disabled) { background: var(--surface-2); }
	.btn:disabled { opacity: 0.45; cursor: not-allowed; }
	.btn.primary {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
	}
</style>
