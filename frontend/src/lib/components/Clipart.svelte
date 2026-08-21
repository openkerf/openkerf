<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
	import Dialog from './Dialog.svelte';

	let {
		open = $bindable(),
		canEdit = false,
		onInserted
	}: {
		open: boolean;
		canEdit?: boolean;
		onInserted?: () => void;
	} = $props();

	type Result = {
		id: string;
		source: string;
		title: string;
		svg_url: string;
		thumbnail_url: string;
		page_url: string | null;
		license: string | null;
		author: string | null;
	};

	// Iconify eerst: iconen zijn voor een laser het meest bruikbare materiaal —
	// gesloten paden, geen kleurverlopen, geen tekst.
	const SOURCES = [
		{ id: 'iconify', label: 'Iconify (iconen)' },
		{ id: 'wikimedia', label: 'Wikimedia Commons' },
		{ id: 'openclipart', label: 'Openclipart' }
	];

	let query = $state('');
	let chosen = $state<string[]>(['iconify', 'wikimedia', 'openclipart']);
	let results = $state<Result[]>([]);
	let unavailable = $state<Record<string, string>>({});
	let busy = $state(false);
	let error = $state<string | null>(null);
	let searched = $state(false);
	let page = $state(1);
	let hasMore = $state(false);
	let loadingMore = $state(false);
	let width = $state('60');
	let placing = $state<string | null>(null);
	let notes = $state<string[]>([]);

	async function search(next = false) {
		if (query.trim().length < 2) return;
		const wanted = next ? page + 1 : 1;
		if (next) loadingMore = true;
		else busy = true;
		error = null;
		notes = [];
		try {
			const params = new URLSearchParams({
				q: query.trim(),
				sources: chosen.join(','),
				page: String(wanted)
			});
			const response = await fetch(`/api/clipart/search?${params}`);
			if (!response.ok) {
				error = (await response.json().catch(() => null))?.detail ?? t('error.searchFailed');
				return;
			}
			const data = await response.json();
			// Bij "meer" aanvullen in plaats van vervangen, zodat je niet
			// kwijtraakt wat je al bekeken had. Op id ontdubbelen: de bronnen
			// leveren soms hetzelfde op een volgende pagina opnieuw.
			const seen = new Set(next ? results.map((r) => r.id) : []);
			const fresh = (data.results as Result[]).filter((r) => !seen.has(r.id));
			results = next ? [...results, ...fresh] : data.results;
			unavailable = data.unavailable;
			hasMore = data.has_more && (!next || fresh.length > 0);
			page = wanted;
			searched = true;
		} catch (e) {
			error = t('error.network', { message: e instanceof Error ? e.message : String(e) });
		} finally {
			busy = false;
			loadingMore = false;
		}
	}

	async function insert(item: Result) {
		placing = item.id;
		error = null;
		notes = [];
		try {
			const token = localStorage.getItem('openkerf.token') ?? '';
			const response = await fetch('/api/clipart/insert', {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					...(token ? { Authorization: `Bearer ${token}` } : {})
				},
				body: JSON.stringify({ url: item.svg_url, width_mm: Number(width) || 60 })
			});
			if (!response.ok) {
				error = (await response.json().catch(() => null))?.detail ?? t('error.insertFailed');
				return;
			}
			notes = (await response.json()).notes ?? [];
			onInserted?.();
			// Blijft open als er iets te melden viel; anders is het klaar.
			if (!notes.length) open = false;
		} finally {
			placing = null;
		}
	}

	function label(source: string) {
		return SOURCES.find((s) => s.id === source)?.label ?? source;
	}
</script>

<Dialog title={t('clipart.title')} bind:open width="760px">
	<p class="lead">{t('clipart.lead')}</p>

	<div class="bar">
		<input
			type="search"
			placeholder={t('clipart.placeholder')}
			bind:value={query}
			onkeydown={(e) => {
				if (e.key === 'Enter') search();
			}}
		/>
		<!-- Form rule v4: the label goes *above* the field, even in a row with a search
		     box. Before this "Width" was in front of it and "mm" behind, which made this
		     the only field in the app with a label on the left. -->
		<label class="w">
			<span>{t('clipart.width')}</span>
			<input class="mono" type="number" min="1" max="2000" step="5" bind:value={width} />
		</label>
		<button
			class="btn primary"
			disabled={busy || query.trim().length < 2}
			onclick={() => search()}
		>
			{busy ? t('clipart.searching') : t('clipart.search')}
		</button>
	</div>

	<div class="sources">
		{#each SOURCES as source (source.id)}
			<label>
				<input
					type="checkbox"
					checked={chosen.includes(source.id)}
					onchange={(e) => {
						chosen = e.currentTarget.checked
							? [...chosen, source.id]
							: chosen.filter((s) => s !== source.id);
					}}
				/>
				<span>{source.label}</span>
			</label>
		{/each}
	</div>

	{#if error}
		<p class="error" role="alert">{error}</p>
	{/if}
	{#each Object.entries(unavailable) as [source, reason] (source)}
		<p class="warn">{t('clipart.unavailable', { source: label(source), reason })}</p>
	{/each}
	{#each notes as note (note)}
		<p class="warn">{note}</p>
	{/each}

	<div class="grid">
		{#each results as item (item.id)}
			<figure>
				<button
					class="pick"
					disabled={!canEdit || placing !== null}
					title={canEdit ? t('clipart.insert', { width }) : t('reason.needsToken')}
					onclick={() => insert(item)}
				>
					<img src={item.thumbnail_url} alt={item.title} loading="lazy" />
					{#if placing === item.id}<span class="busy">{t('common.busy')}</span>{/if}
				</button>
				<figcaption>
					<span class="title" title={item.title}>{item.title}</span>
					<span class="meta">
						{item.license ?? t('clipart.licenceUnknown')}
						{#if item.page_url}
							· <a href={item.page_url} target="_blank" rel="noopener">{t('clipart.source')}</a>
						{/if}
					</span>
				</figcaption>
			</figure>
		{:else}
			<p class="empty">
				{#if busy}
					{t('clipart.searching')}
				{:else if searched}
					{t('clipart.nothing')}
				{:else}
					{t('clipart.typeWord')}
				{/if}
			</p>
		{/each}
	</div>

	{#if results.length}
		<div class="more">
			<span class="count mono">{t('clipart.shown', { n: results.length })}</span>
			{#if hasMore}
				<button class="btn" disabled={loadingMore} onclick={() => search(true)}>
					{loadingMore ? t('clipart.fetching') : t('clipart.more')}
				</button>
			{:else}
				<span class="count">{t('clipart.thatIsAll')}</span>
			{/if}
		</div>
	{/if}
</Dialog>

<style>
	.lead { margin: 0 0 var(--space-3); font-size: var(--text-xs); color: var(--text-2); line-height: 1.5; }
	/* Onderlangs uitlijnen, niet in het midden: de velden hebben nu een label
	   erboven en het zoekveld niet, dus "midden" zou de zoekknop scheef zetten. */
	.bar { display: flex; gap: var(--space-2); align-items: flex-end; }
	.bar input[type='search'] { flex: 1; }
	.w { display: grid; gap: 2px; font-size: var(--text-xs); color: var(--text-2); }
	.w input { width: 7em; }
	input {
		font: inherit;
		padding: 8px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.sources {
		display: flex;
		gap: var(--space-3);
		margin: var(--space-2) 0 var(--space-3);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.sources label { display: flex; align-items: center; gap: 5px; }
	.sources input { padding: 0; }
	.error { font-size: var(--text-xs); color: var(--danger); margin: 0 0 var(--space-2); }
	.warn { font-size: var(--text-xs); color: var(--warn); margin: 0 0 var(--space-2); }
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
		gap: var(--space-3);
		max-height: 52vh;
		overflow-y: auto;
	}
	figure { margin: 0; display: grid; gap: 4px; }
	.pick {
		position: relative;
		display: grid;
		place-items: center;
		aspect-ratio: 1;
		padding: 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--on-color);
	}
	.pick:hover:not(:disabled) { border-color: var(--accent); }
	.pick:disabled { opacity: 0.5; cursor: not-allowed; }
	.pick img { max-width: 100%; max-height: 100%; object-fit: contain; }
	.busy {
		position: absolute;
		inset: 0;
		display: grid;
		place-items: center;
		background: color-mix(in srgb, var(--on-color) 75%, transparent);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	figcaption { display: grid; gap: 1px; font-size: var(--text-xs); color: var(--text-2); }
	.title {
		color: var(--text-1);
		font-size: var(--text-xs);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.meta a { color: var(--accent); }
	.empty { grid-column: 1 / -1; font-size: var(--text-xs); color: var(--text-2); padding: var(--space-5) 0; }
	.more {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		margin-top: var(--space-3);
	}
	.more .btn { margin-left: auto; }
	.count { font-size: var(--text-xs); color: var(--text-2); }
	.btn {
		padding: 8px 16px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		font-weight: 500;
	}
	.btn:disabled { opacity: 0.45; cursor: not-allowed; }
	.btn.primary { background: var(--accent); border-color: var(--accent); color: var(--accent-ink); }
</style>
