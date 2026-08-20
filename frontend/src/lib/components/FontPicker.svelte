<script lang="ts">
	/**
	 * Een lettertype kiezen, met voorbeeld in de letter zelf.
	 *
	 * Stond in `TextDialog`. De boogtekstgenerator maakt dezelfde tekst met
	 * dezelfde engine en kon er géén letter bij kiezen — hij kreeg altijd de
	 * standaard. Een tweede keuzemechanisme bouwen zou betekenen dat dezelfde
	 * lijst op twee plekken uiteen kan gaan lopen (en de importknop maar op één
	 * ervan zit), dus is dit één component die beide vensters gebruiken.
	 */

	import { t } from '$lib/i18n/index.svelte';

	type Font = { file: string; name: string };

	let {
		font = $bindable(''),
		/**
		 * De leesbare naam van de gekozen letter. `font` is het bestand, en dat
		 * is bij systeemlettertypen een heel pad — "/System/Library/Fonts/Apple
		 * Braille" is geen antwoord op "welke letter staat er nu".
		 */
		fontName = $bindable(''),
		/** Waarmee de proefregel gevuld wordt: liever je eigen tekst. */
		sample = '',
		/** Bij bewerken: de letter die er nu op staat. */
		current = null
	}: {
		font?: string;
		fontName?: string;
		sample?: string;
		current?: string | null;
	} = $props();

	function kies(item: { file: string; name: string } | null) {
		font = item?.file ?? '';
		fontName = item?.name ?? '';
	}

	let fonts = $state<Font[]>([]);
	let filter = $state('');
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

	loadFonts();

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
					(await response.json().catch(() => null))?.detail ?? t('error.importFailed');
				return;
			}
			const added = await response.json();
			await loadFonts(true);
			kies(added);
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
</script>

<label class="field">
	<span>
		{current
			? t('font.label.current', { n: fonts.length, current })
			: t('font.label', { n: fonts.length })}
	</span>
	<input type="search" bind:value={filter} placeholder={t('font.search')} />
</label>
<!-- svelte-ignore -->
{@html `<style>${faces}</style>`}
<div class="fonts" role="listbox" aria-label={t('font.listAria')}>
	<button
		class="font"
		role="option"
		aria-selected={font === ''}
		class:picked={font === ''}
		onclick={() => kies(null)}
	>
		<span class="naam">{t('font.default')}</span>
	</button>
	{#each shown.slice(0, 60) as item (item.file)}
		<button
			class="font"
			role="option"
			aria-selected={font === item.file}
			class:picked={font === item.file}
			onclick={() => kies(item)}
		>
			<!--
				The name on the left in the interface font, the sample on the right in the
				font itself. They both used to be in the font, and then a font without a
				readable Latin alphabet — Aurebesh, Wingdings, a symbol set — can no longer
				be found: you cannot read the name and you cannot read the sample either.
				The name is the key to finding something back, the sample is what you choose
				on; those two tasks do not tolerate the same font.
			-->
			<span class="naam">{item.name}</span>
			<span class="proef" style={familie.has(item.file) ? `font-family: "${familie.get(item.file)}", var(--font-ui)` : ''}
				>{sample.trim().slice(0, 18) || t('font.sample')}</span>
		</button>
	{/each}
	{#if shown.length > 60}
		<p class="note">{t('font.more', { n: shown.length - 60 })}</p>
	{/if}
</div>

<div class="import">
	<button class="link" onclick={openImport}>
		{importing ? t('font.import.close') : t('font.import.open')}
	</button>
	{#if importing}
		<p class="note">{t('font.import.why')}</p>
		<input
			type="search"
			bind:value={importFilter}
			placeholder={t('font.import.search', { n: importable.length })}
		/>
		{#if importError}<p class="err">{importError}</p>{/if}
		<div class="fonts">
			{#each shownImportable as item (item.file)}
				<button class="font" disabled={busy !== null} onclick={() => bring(item)}>
					{busy === item.file ? t('common.busy') : item.name}
				</button>
			{:else}
				<span class="note">{t('font.import.nothing')}</span>
			{/each}
		</div>
	{/if}
</div>

<style>
	.field {
		display: grid;
		gap: 2px;
		margin-bottom: var(--space-3);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	input {
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
	/* Nadrukkelijk het interfacelettertype: de naam is de sleutel waarmee je
	   een letter terugvindt en moet dus altijd leesbaar zijn. */
	.font .naam {
		font-family: var(--font-ui);
		font-size: var(--text-sm);
		/* Een lange naam mag het voorbeeld niet van de rij duwen. */
		flex: 0 1 auto;
		min-width: 0;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.font .proef {
		flex: 1 1 auto;
		min-width: 0;
		text-align: right;
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
</style>
