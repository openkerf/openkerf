<script lang="ts">
	/**
	 * Choosing a typeface, with a preview in the typeface itself.
	 *
	 * This lived in `TextDialog`. The arc text generator makes the same text with the same
	 * engine and could *not* choose a typeface for it — it always got the default.
	 * Building a second choice mechanism would mean the same list can drift apart in two
	 * places (and the import button only sits on one of them), so this is one component
	 * both dialogs use.
	 */

	import { t } from '$lib/i18n/index.svelte';
	import Notice from './Notice.svelte';

	type Font = { file: string; name: string };

	let {
		font = $bindable(''),
		/**
		 * The readable name of the chosen typeface. `font` is the file, and for system
		 * fonts that is a whole path — "/System/Library/Fonts/Apple Braille" is no answer
		 * to "which typeface is set now".
		 */
		fontName = $bindable(''),
		/** What the sample line is filled with: preferably your own text. */
		sample = '',
		/** When editing: the typeface it currently carries. */
		current = null
	}: {
		font?: string;
		fontName?: string;
		sample?: string;
		current?: string | null;
	} = $props();

	function pick(item: { file: string; name: string } | null) {
		font = item?.file ?? '';
		fontName = item?.name ?? '';
	}

	let fonts = $state<Font[]>([]);
	let filter = $state('');
	// Your own typefaces: the engine only reads .ttf and keeps its list in a cache, so a
	// freshly installed .otf is invisible until you import it.
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
			pick(added);
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

	// Only what is on screen gets a preview: loading 200 web fonts to show a list is
	// unnecessary, and a browser cannot handle .shx/.jhf anyway.
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
				([file, name]) =>
					`@font-face{font-family:"${name}";src:url("/api/design/fonts/file?name=${encodeURIComponent(file)}");font-display:swap;}`
			)
			.join('')
	);
</script>

<label class="field field-label">
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
		class="listrow font"
		role="option"
		aria-selected={font === ''}
		onclick={() => pick(null)}
	>
		<span class="name">{t('font.default')}</span>
	</button>
	{#each shown.slice(0, 60) as item (item.file)}
		<button
			class="listrow font"
			role="option"
			aria-selected={font === item.file}
			onclick={() => pick(item)}
		>
			<!--
				The name on the left in the interface font, the sample on the right in the
				font itself. They both used to be in the font, and then a font without a
				readable Latin alphabet — Aurebesh, Wingdings, a symbol set — can no longer
				be found: you cannot read the name and you cannot read the sample either.
				The name is the key to finding something back, the sample is what you choose
				on; those two tasks do not tolerate the same font.
			-->
			<span class="name">{item.name}</span>
			<span class="proef" style={familie.has(item.file) ? `font-family: "${familie.get(item.file)}", var(--font-ui)` : ''}
				>{sample.trim().slice(0, 18) || t('font.sample')}</span>
		</button>
	{/each}
	{#if shown.length > 60}
		<p class="help">{t('font.more', { n: shown.length - 60 })}</p>
	{/if}
</div>

<div class="import">
	<button class="link" onclick={openImport}>
		{importing ? t('font.import.close') : t('font.import.open')}
	</button>
	{#if importing}
		<p class="help">{t('font.import.why')}</p>
		<input
			type="search"
			bind:value={importFilter}
			placeholder={t('font.import.search', { n: importable.length })}
		/>
		{#if importError}<Notice tone="danger" live>{importError}</Notice>{/if}
		<div class="fonts">
			{#each shownImportable as item (item.file)}
				<button
					class="listrow font"
					disabled={busy !== null}
					title={busy === null ? undefined : t('reason.busy')}
					onclick={() => bring(item)}
				>
					{busy === item.file ? t('common.busy') : item.name}
				</button>
			{:else}
				<span class="help">{t('font.import.nothing')}</span>
			{/each}
		</div>
	{/if}
</div>

<style>
	.field {
		margin-bottom: var(--space-3);
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
	/* The shared list row; this only says that its name and its sample stand apart. */
	.font {
		align-items: baseline;
		justify-content: space-between;
		gap: var(--space-3);
		padding-inline: var(--space-2);
	}
	/* Emphatically the interface typeface: the name is the key by which you find a
	   typeface again and therefore has to stay readable. */
	.font .name {
		font-family: var(--font-ui);
		font-size: var(--text-sm);
		/* A long name must not push the preview off the row. */
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
	.import { margin-top: var(--space-3); display: grid; gap: var(--space-1h); }
	.import .link {
		justify-self: start;
		font-size: var(--text-xs);
	}
</style>
