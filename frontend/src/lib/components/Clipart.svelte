<script lang="ts">
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

	const SOURCES = [
		{ id: 'wikimedia', label: 'Wikimedia Commons' },
		{ id: 'openclipart', label: 'Openclipart' }
	];

	let query = $state('');
	let chosen = $state<string[]>(['wikimedia', 'openclipart']);
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
				error = (await response.json().catch(() => null))?.detail ?? 'Zoeken mislukte.';
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
			error = `Netwerkfout: ${e instanceof Error ? e.message : e}`;
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
				error = (await response.json().catch(() => null))?.detail ?? 'Invoegen mislukte.';
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

<Dialog title="Clipart zoeken" bind:open width="760px">
	<p class="lead">
		Zoekt in openbare collecties. Wat je vindt is van iemand anders: <strong>de
		licentie staat bij elk resultaat</strong>, en die bepaalt of je het mag
		verkopen wat je ermee snijdt.
	</p>

	<div class="bar">
		<input
			type="search"
			placeholder="bijv. hart, ster, vogel…"
			bind:value={query}
			onkeydown={(e) => {
				if (e.key === 'Enter') search();
			}}
		/>
		<label class="w">
			<span>Breedte</span>
			<input class="mono" type="number" min="1" max="2000" step="5" bind:value={width} />
			<span>mm</span>
		</label>
		<button
			class="btn primary"
			disabled={busy || query.trim().length < 2}
			onclick={() => search()}
		>
			{busy ? 'Zoeken…' : 'Zoeken'}
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
		<p class="warn">{label(source)} {reason}. De rest staat er wel.</p>
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
					title={canEdit ? `Invoegen op ${width} mm breed` : 'Vereist een token'}
					onclick={() => insert(item)}
				>
					<img src={item.thumbnail_url} alt={item.title} loading="lazy" />
					{#if placing === item.id}<span class="busy">bezig…</span>{/if}
				</button>
				<figcaption>
					<span class="title" title={item.title}>{item.title}</span>
					<span class="meta">
						{item.license ?? 'licentie onbekend'}
						{#if item.page_url}
							· <a href={item.page_url} target="_blank" rel="noopener">bron</a>
						{/if}
					</span>
				</figcaption>
			</figure>
		{:else}
			<p class="empty">
				{#if busy}
					Zoeken…
				{:else if searched}
					Niets gevonden. Engelse woorden geven meestal meer resultaat.
				{:else}
					Typ een woord en druk op Enter.
				{/if}
			</p>
		{/each}
	</div>

	{#if results.length}
		<div class="more">
			<span class="count mono">{results.length} getoond</span>
			{#if hasMore}
				<button class="btn" disabled={loadingMore} onclick={() => search(true)}>
					{loadingMore ? 'Ophalen…' : 'Meer resultaten'}
				</button>
			{:else}
				<span class="count">dit is alles</span>
			{/if}
		</div>
	{/if}
</Dialog>

<style>
	.lead { margin: 0 0 var(--space-3); font-size: var(--text-xs); color: var(--text-2); line-height: 1.5; }
	.bar { display: flex; gap: var(--space-2); align-items: center; }
	.bar input[type='search'] { flex: 1; }
	.w { display: flex; align-items: center; gap: 4px; font-size: 10px; color: var(--text-2); }
	.w input { width: 5em; }
	input {
		font: inherit;
		padding: 7px 9px;
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
		padding: 6px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: white;
	}
	.pick:hover:not(:disabled) { border-color: var(--accent); }
	.pick:disabled { opacity: 0.5; cursor: not-allowed; }
	.pick img { max-width: 100%; max-height: 100%; object-fit: contain; }
	.busy {
		position: absolute;
		inset: 0;
		display: grid;
		place-items: center;
		background: rgb(255 255 255 / 0.75);
		font-size: 10px;
		color: var(--text-2);
	}
	figcaption { display: grid; gap: 1px; font-size: 9px; color: var(--text-2); }
	.title {
		color: var(--text-1);
		font-size: 10px;
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
	.count { font-size: 10px; color: var(--text-2); }
	.btn {
		padding: 8px 14px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		font-weight: 500;
	}
	.btn:disabled { opacity: 0.45; cursor: not-allowed; }
	.btn.primary { background: var(--accent); border-color: var(--accent); color: var(--accent-ink); }
</style>
