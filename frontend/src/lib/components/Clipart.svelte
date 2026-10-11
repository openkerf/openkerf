<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
	import Dialog from './Dialog.svelte';
	import NumberField from './NumberField.svelte';
	import Notice from './Notice.svelte';

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

	// Iconify first: for a laser, icons are the most usable material — closed paths, no
	// gradients, no text.
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
			// On "more", append rather than replace, so that you do not lose what you had
			// already looked at. Deduplicate on id: the sources sometimes deliver the same
			// thing again on a following page.
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
			// Stays open when there was something to report; otherwise it is done.
			if (!notes.length) open = false;
		} finally {
			placing = null;
		}
	}

	function label(source: string) {
		return SOURCES.find((s) => s.id === source)?.label ?? source;
	}
</script>

<Dialog title={t('clipart.title')} bind:open size="l">
	<p class="help lead">{t('clipart.lead')}</p>

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
		<div class="w">
			<NumberField label={t('clipart.width')} bind:value={width} step={5} min={1} max={2000} />
		</div>
		<button
			class="btn primary"
			disabled={busy || query.trim().length < 2}
			title={busy ? t('reason.busy') : t('reason.needsQuery')}
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
		<div class="said"><Notice tone="danger" live>{error}</Notice></div>
	{/if}
	{#each Object.entries(unavailable) as [source, reason] (source)}
		<p class="help warn said">{t('clipart.unavailable', { source: label(source), reason })}</p>
	{/each}
	{#each notes as note (note)}
		<p class="help warn said">{note}</p>
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
			<p class="help empty">
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
				<button
					class="btn"
					disabled={loadingMore}
					title={loadingMore ? t('reason.busy') : undefined}
					onclick={() => search(true)}
				>
					{loadingMore ? t('clipart.fetching') : t('clipart.more')}
				</button>
			{:else}
				<span class="count">{t('clipart.thatIsAll')}</span>
			{/if}
		</div>
	{/if}
</Dialog>

<style>
	.lead { margin: 0 0 var(--space-3); }
	/* Align along the bottom, not in the middle: the fields now have a label above them
	   and the search field does not, so "middle" would set the search button askew. */
	.bar { display: flex; gap: var(--space-2); align-items: flex-end; }
	.bar input[type='search'] { flex: 1; }
	/* Two step buttons and "2000": the stepper needs this much and no more. */
	.w { width: 11em; flex: none; }
	.sources {
		display: flex;
		gap: var(--space-3);
		margin: var(--space-2) 0 var(--space-3);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.sources label { display: flex; align-items: center; gap: var(--space-1h); }
	.said { margin: 0 0 var(--space-2); }
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
		gap: var(--space-3);
		max-height: 52vh;
		overflow-y: auto;
	}
	figure { margin: 0; display: grid; gap: var(--space-1); }
	.pick {
		position: relative;
		display: grid;
		place-items: center;
		aspect-ratio: 1;
		padding: var(--space-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--on-color);
	}
	.pick:hover:not(:disabled) { border-color: var(--accent); }
	/* Off is drained: the raised grey under a grey picture, nothing faded. */
	.pick:disabled { background: var(--surface-2); cursor: not-allowed; }
	.pick:disabled img { filter: grayscale(1); }
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
	.empty { grid-column: 1 / -1; padding: var(--space-6) 0; }
	.more {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		margin-top: var(--space-3);
	}
	.more .btn { margin-left: auto; }
	.count { font-size: var(--text-xs); color: var(--text-2); }
</style>
