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
	// Eigen lettertypen: de engine leest alleen .ttf en houdt zijn lijst in een
	// cache, dus een net geïnstalleerde .otf is onzichtbaar tot je hem importeert.
	let importing = $state(false);
	let importable = $state<Font[]>([]);
	let importFilter = $state('');
	let busy = $state<string | null>(null);
	let importError = $state<string | null>(null);

	async function loadFonts(refresh = false) {
		const response = await fetch(`/api/design/fonts${refresh ? '?refresh=true' : ''}`);
		fonts = response.ok ? await response.json() : [];
	}

	async function openImport() {
		importing = !importing;
		if (!importing || importable.length) return;
		const response = await fetch('/api/design/fonts/importable');
		importable = response.ok ? await response.json() : [];
	}

	async function bring(item: Font) {
		busy = item.file;
		importError = null;
		try {
			const token = localStorage.getItem('openkerf.token') ?? '';
			const response = await fetch('/api/design/fonts/import', {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					...(token ? { Authorization: `Bearer ${token}` } : {})
				},
				body: JSON.stringify({ file: item.file })
			});
			if (!response.ok) {
				importError =
					(await response.json().catch(() => null))?.detail ?? 'Importeren mislukte.';
				return;
			}
			const added = await response.json();
			await loadFonts(true);
			font = added.file;
			importable = importable.filter((f) => f.file !== item.file);
			importing = false;
		} finally {
			busy = null;
		}
	}

	let shownImportable = $derived(
		importFilter.trim()
			? importable.filter((f) =>
					f.name.toLowerCase().includes(importFilter.trim().toLowerCase())
				)
			: importable.slice(0, 60)
	);

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
		loadFonts();
	});

	let shown = $derived(
		filter.trim()
			? fonts.filter((f) => f.name.toLowerCase().includes(filter.trim().toLowerCase()))
			: fonts
	);

	// Alleen wat in beeld staat krijgt een voorbeeld: 200 webfonts laden om een
	// lijst te tonen is niet nodig, en .shx/.jhf kan een browser toch niet.
	const PREVIEWABLE = /\.(ttf|otf|woff2?)$/i;
	let familie = $derived(
		new Map(
			shown
				.slice(0, 60)
				.filter((f) => PREVIEWABLE.test(f.file))
				.map((f, i) => [f.file, `ok-preview-${i}`])
		)
	);
	let faces = $derived(
		[...familie]
			.map(
				([file, naam]) =>
					`@font-face{font-family:"${naam}";src:url("/api/design/fonts/file?name=${encodeURIComponent(file)}");font-display:swap;}`
			)
			.join('')
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
	<!-- svelte-ignore -->
	{@html `<style>${faces}</style>`}
	<div class="fonts" role="listbox" aria-label="Lettertype">
		<button
			class="font"
			role="option"
			aria-selected={font === ''}
			class:picked={font === ''}
			onclick={() => (font = '')}
		>
			<span class="naam">Standaard</span>
		</button>
		{#each shown.slice(0, 60) as item (item.file)}
			<button
				class="font"
				role="option"
				aria-selected={font === item.file}
				class:picked={font === item.file}
				onclick={() => (font = item.file)}
			>
				<!-- De naam in zijn eigen letter: kiezen op zicht, niet op naam. -->
				<span
					class="naam"
					style={familie.has(item.file) ? `font-family: "${familie.get(item.file)}", var(--font-ui)` : ''}
				>{item.name}</span>
				<span class="proef" style={familie.has(item.file) ? `font-family: "${familie.get(item.file)}", var(--font-ui)` : ''}
					>{text.trim().slice(0, 18) || 'Handgemaakt 123'}</span>
			</button>
		{/each}
		{#if shown.length > 60}
			<p class="note">Nog {shown.length - 60} andere — typ om te zoeken.</p>
		{/if}
	</div>

	<div class="import">
		<button class="link" onclick={openImport}>
			{importing ? 'Importeren sluiten' : 'Lettertype niet in de lijst?'}
		</button>
		{#if importing}
			<p class="note">
				De engine leest alleen <code>.ttf</code>. Deze staan wél op je computer maar
				worden niet gezien; importeren maakt er een bruikbare kopie van.
			</p>
			<input type="search" bind:value={importFilter} placeholder="Zoek in {importable.length} lettertypen…" />
			{#if importError}<p class="err">{importError}</p>{/if}
			<div class="fonts">
				{#each shownImportable as item (item.file)}
					<button class="font" disabled={busy !== null} onclick={() => bring(item)}>
						{busy === item.file ? 'bezig…' : item.name}
					</button>
				{:else}
					<span class="note">Niets gevonden dat nog ontbreekt.</span>
				{/each}
			</div>
		{/if}
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
		padding: 8px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.fonts {
		display: flex;
		flex-direction: column;
		gap: 2px;
		max-height: 260px;
		overflow-y: auto;
		padding: var(--space-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
	}
	.font {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--space-3);
		width: 100%;
		min-height: 36px;
		padding: 4px var(--space-2);
		border: 1px solid transparent;
		border-radius: var(--radius-field);
		background: transparent;
		color: var(--text-1);
		text-align: left;
	}
	.font .naam { font-size: var(--text-sm); }
	.font .proef {
		font-size: var(--text-md);
		color: var(--text-2);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.font:hover { background: var(--surface-2); }
	.font.picked {
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 10%, transparent);
	}
	.import { margin-top: var(--space-3); display: grid; gap: 6px; }
	.link {
		justify-self: start;
		font-size: var(--text-xs);
		color: var(--accent);
		text-decoration: underline;
	}
	.note { margin: 0; font-size: var(--text-xs); color: var(--text-2); line-height: 1.5; }
	.err { margin: 0; font-size: var(--text-xs); color: var(--danger); }
	.actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--space-2);
		margin-top: var(--space-4);
	}
	.btn {
		padding: 8px 16px;
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
