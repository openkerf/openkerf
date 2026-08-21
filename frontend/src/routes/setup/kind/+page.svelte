<script lang="ts">
	/**
	 * Step 1: what kind of machine do you have?
	 *
	 * MeerK40t's catalogue counts forty board names. Someone starting out knows none
	 * of them, but does know whether there is a glass tube with water cooling in it.
	 * This step translates that into a handful of models in the next one.
	 *
	 * And when the machine is on, that translation is not needed at all: then
	 * OpenKerf finds it (decision B6). Searching is reading — nothing is created,
	 * connected or activated until you press "add" here.
	 */
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import Segmented from '$components/Segmented.svelte';
	import { KINDS, kindOfMachine, type CatalogFamily, type ScanResult, type Finding } from '$lib/machines.svelte';
	import { t, type MessageKey } from '$lib/i18n/index.svelte';
	import { createStore } from '$lib/setup.svelte';

	const store = createStore();
	onMount(() => store.loadCatalog());

	// How many models sit behind each kind; a kind without models should not be
	// clickable.
	let aantallen = $derived(
		KINDS.map((kind) => ({
			...kind,
			count: store.catalog.reduce(
				(n: number, f: CatalogFamily) =>
					n + f.machines.filter((m) => kindOfMachine(m) === kind.id).length,
				0
			)
		}))
	);

	// ------------------------------------------------------------------ search

	let zoekt = $state(false);
	let resultaat = $state<ScanResult | null>(null);
	let verstreken = $state(0);
	/** Past this bound "just a moment" has become an assumption. */
	const TRAAG = 8;
	let choice = $state<Record<string, string>>({});
	let controller: AbortController | null = null;
	let tikker: ReturnType<typeof setInterval> | null = null;

	function stopTikker() {
		if (tikker) clearInterval(tikker);
		tikker = null;
	}

	async function zoek() {
		zoekt = true;
		resultaat = null;
		verstreken = 0;
		// A counter instead of a bar: we do not know how long it takes, and a bar that
		// does not know how far it is lies. Elapsed time is true.
		stopTikker();
		tikker = setInterval(() => (verstreken += 1), 1000);
		controller = new AbortController();
		try {
			const found = await store.scan({ signal: controller.signal });
			if (found) {
				resultaat = found;
				choice = Object.fromEntries(
					found.candidates
						.filter((v) => v.suggestions.length)
						.map((v) => [v.id, v.suggestions[0].key])
				);
			}
		} finally {
			zoekt = false;
			controller = null;
			stopTikker();
		}
	}

	function afbreken() {
		controller?.abort();
	}

	/**
	 * Confirming. Only here does the creating begin — and even then not at once: you
	 * land in the ordinary "name" step, where you can still go back.
	 */
	function bevestig(vondst: Finding) {
		const key = choice[vondst.id] ?? vondst.suggestions[0]?.key;
		if (!key) return;
		const params = new URLSearchParams({ type: key });
		if (Object.keys(vondst.settings).length) {
			// The connection travels along as a parameter, so the back button and a
			// refresh keep working — the same rule as for the rest of the wizard.
			params.set('connection', JSON.stringify(vondst.settings));
			params.set('found', `${vondst.title} · ${vondst.where}`);
		}
		goto(`/setup/name?${params}`);
	}

	// Short: the pill says by which route, the line below says exactly where. A pill
	// of three words also pushes the titles apart.
	const TRANSPORT: Record<string, MessageKey> = {
		usb: 'setup.transport.usb',
		serieel: 'setup.transport.serial',
		netwerk: 'setup.transport.network'
	};

	function transport(kind: string): string {
		return kind in TRANSPORT ? t(TRANSPORT[kind]) : kind;
	}

	/** Certainty gets a word *and* a shape — colour alone is not enough. */
	const ZEKERHEID: Record<string, { woord: MessageKey; hint: MessageKey; icon: string }> = {
		zeker: {
			woord: 'setup.certainty.answered',
			hint: 'setup.certainty.answered.why',
			icon: 'M4 12.5 9 17.5 20 6.5'
		},
		waarschijnlijk: {
			woord: 'setup.certainty.probable',
			hint: 'setup.certainty.probable.why',
			icon: 'M12 3.5 22 20H2z'
		},
		onzeker: {
			woord: 'setup.certainty.guess',
			hint: 'setup.certainty.guess.why',
			icon: 'M9 8.5a3 3 0 1 1 3 3.5v2M12 18.5v.01'
		}
	};
</script>

<svelte:head><title>{t('setup.head.kind')}</title></svelte:head>

<section class="setup">
	{#if store.error}<p class="error" role="alert">{store.error}</p>{/if}

	<h1>{t('setup.whatKind')}</h1>
	<p class="muted">{t('setup.whatKind.body')}</p>

	<section class="search" aria-labelledby="zoekkop">
		<div class="head">
			<h2 id="zoekkop">{t('setup.scan.title')}</h2>
			{#if !zoekt}
				<button class="btn primary" onclick={zoek}>
					{resultaat ? t('setup.scan.again') : t('setup.scan.start')}
				</button>
			{/if}
		</div>

		{#if zoekt}
			<div class="busy" role="status" aria-live="polite">
				<span class="ring" aria-hidden="true"></span>
				<div>
					<div class="bezigkop">{t('setup.scan.running', { seconds: verstreken })}</div>
					<p class="muted">{t('setup.scan.what')}</p>
					{#if verstreken >= TRAAG}
						<!-- This ought to be done within three seconds. If it takes longer,
						     something is going on and the user deserves a way forward instead of
						     a spinning circle. -->
						<p class="traag">{t('setup.scan.slow')}</p>
					{/if}
				</div>
				<button class="btn subtle" onclick={afbreken}>{t('setup.scan.stop')}</button>
			</div>
		{/if}

		<!-- The promise stays put while searching too: that is exactly when you wonder
		     what is happening to your machine. -->
		<p class="promise">
			<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
				<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" /><circle cx="12" cy="12" r="3" />
			</svg>
			{t('setup.scan.promise')}
		</p>

		{#if resultaat && !zoekt}
			{#if resultaat.candidates.length}
				<h3 class="uitslag">{t('setup.scan.found', { n: resultaat.candidates.length })}</h3>
				<ul class="vondsten">
					{#each resultaat.candidates as vondst (vondst.id)}
						{@const zeker = ZEKERHEID[vondst.confidence] ?? ZEKERHEID.onzeker}
						<li class="vondst" class:gok={vondst.confidence === 'onzeker'}>
							<!-- Stacked, not side by side: at 390 px the title otherwise became a
							     column two words wide and an IP address broke in the middle. -->
							<div class="row">
								<span class="transport">{transport(vondst.transport)}</span>
								<span class="certainty" title={t(zeker.hint)}>
									<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
										<path d={zeker.icon} />
									</svg>
									{t(zeker.woord)}
								</span>
							</div>
							<div class="title">{vondst.title}</div>
							<div class="waar mono">
								{vondst.where}{vondst.detail ? ` · ${vondst.detail}` : ''}
							</div>

							<p class="why">{vondst.why}</p>

							{#if vondst.suggestions.length > 1}
								<div class="model">
									<span class="modelkop">{t('setup.whichModel.short')}</span>
									{#if vondst.suggestions.length <= 4}
										<Segmented
											label={t('setup.model')}
											options={vondst.suggestions.map((s) => ({ value: s.key, label: s.label }))}
											bind:value={choice[vondst.id]}
										/>
									{:else}
										<select bind:value={choice[vondst.id]}>
											{#each vondst.suggestions as suggestie (suggestie.key)}
												<option value={suggestie.key}>{suggestie.label}</option>
											{/each}
										</select>
									{/if}
								</div>
							{:else if vondst.suggestions.length === 1}
								<p class="model enkel">
									{t('setup.suggestion', { label: vondst.suggestions[0].label })}
									<span class="muted">({vondst.suggestions[0].family})</span>
								</p>
							{/if}

							<div class="doen">
								{#if vondst.suggestions.length}
									<button class="btn primary" onclick={() => bevestig(vondst)}>
										{t('setup.addThis')}
									</button>
								{:else}
									<p class="muted geenmodel">{t('setup.noModel')}</p>
								{/if}
							</div>
						</li>
					{/each}
				</ul>
			{:else}
				<div class="none">
					<h3>{t('setup.nothing')}</h3>
					<p>{t('setup.nothing.body')}</p>
					{#if resultaat.notes.length === 1}
						<p class="muted">{resultaat.notes[0]}</p>
					{:else if resultaat.notes.length}
						<ul class="notities">
							{#each resultaat.notes as notitie}<li>{notitie}</li>{/each}
						</ul>
					{/if}
					<!-- Where it looked belongs with it: without that "nothing found" cannot be
					     checked and so cannot be trusted. -->
					<p class="muted herkomst mono">
						{t('setup.searchedIn', {
							where: resultaat.searched.join(', ') || t('setup.searchedIn.nothing'),
							seconds: (resultaat.duration_ms / 1000).toFixed(1)
						})}
					</p>
				</div>
			{/if}
		{/if}
	</section>

	<h2 class="zelfkop">{t('setup.orPick')}</h2>
	<p class="muted">{t('setup.orPick.body')}</p>

	<ul class="soorten">
		{#each aantallen as kind (kind.id)}
			<li>
				<a
					class="kind"
					class:empty={kind.count === 0}
					href={kind.count ? `/setup/type?kind=${kind.id}` : undefined}
					aria-disabled={kind.count === 0}
				>
					<svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
						<path d={kind.icon} />
					</svg>
					<span class="name">{kind.label}</span>
					<span class="hint">{kind.blurb}</span>
					<span class="hoeveel mono">
						{kind.count === 0 ? t('setup.models.none') : t('setup.models', { n: kind.count })}
					</span>
				</a>
			</li>
		{/each}
	</ul>

	<p class="anders">
		{t('setup.notListed')}
		<a href="/setup/type">{t('setup.fullList')}</a>
	</p>
</section>

<style>
	/* ------------------------------------------------------------ search block */
	.search {
		margin: var(--space-4) 0 var(--space-8);
		padding: var(--space-4);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-2);
	}
	.head {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		flex-wrap: wrap;
	}
	.search h2 {
		flex: 1;
		margin: 0;
		font-size: var(--text-md);
		font-weight: 600;
		letter-spacing: -0.01em;
	}
	/* The promise from the decision is on the screen, not only in a document: anybody
	   pressing a button that could touch a laser should know that this one does not. */
	.promise {
		display: flex;
		align-items: flex-start;
		gap: var(--space-2);
		margin: var(--space-3) 0 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.promise svg {
		flex: none;
		margin-top: 1px;
	}

	.busy {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		margin-top: var(--space-3);
	}
	.bezigkop {
		font-weight: 500;
	}
	.busy p {
		margin: 2px 0 0;
		font-size: var(--text-xs);
	}
	.busy .traag {
		color: var(--text-1);
		border-left: 3px solid var(--warn);
		padding-left: var(--space-2);
		margin-top: var(--space-2);
	}
	.busy > div {
		flex: 1;
		min-width: 0;
	}
	.ring {
		flex: none;
		width: 20px;
		height: 20px;
		border-radius: 999px;
		border: 2px solid var(--line);
		border-top-color: var(--accent);
		animation: draai 900ms linear infinite;
	}
	@keyframes draai {
		to {
			transform: rotate(360deg);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.ring {
			animation-duration: 3s;
		}
	}

	.uitslag,
	.none h3 {
		margin: var(--space-4) 0 var(--space-2);
		font-size: var(--text-sm);
		font-weight: 600;
	}

	.vondsten {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: var(--space-2);
	}
	.vondst {
		padding: var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-1);
		/* An edge stripe in the colour of the certainty: visible while scrolling, without
		   reading as well (DESIGN-SYSTEM v3.1, "certainty is a sentence"). */
		border-left: 3px solid var(--ok);
		box-shadow: var(--lift-1);
	}
	.vondst.gok {
		border-left-color: var(--warn);
	}
	.row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
		margin-bottom: var(--space-2);
	}
	.title {
		font-weight: 600;
	}
	.waar {
		font-size: var(--text-xs);
		color: var(--text-2);
		overflow-wrap: anywhere;
	}
	.transport {
		font-size: var(--text-xs);
		padding: var(--space-1) var(--space-2);
		border-radius: var(--radius-dot);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.certainty {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1h);
		font-size: var(--text-xs);
		color: var(--text-1);
	}
	.certainty svg {
		color: var(--ok);
	}
	.gok .certainty svg {
		color: var(--warn);
	}
	.why {
		margin: var(--space-2) 0 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}

	.model {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		flex-wrap: wrap;
		margin-top: var(--space-3);
	}
	.modelkop {
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.model.enkel {
		margin: var(--space-2) 0 0;
		font-size: var(--text-xs);
	}
	/* Segmented gives every box `flex: 1` — and that is `1 1 0%`, so all the boxes become
	   equally wide and the longest label is truncated ("GRBL (generi"). Elsewhere there
	   are only labels of equal length in it, so we fix this here rather than in the shared
	   component. */
	.model :global(.segmented button) {
		flex: 0 1 auto;
	}
	.model select {
		font: inherit;
		font-size: var(--text-xs);
		padding: var(--space-1h) var(--space-2);
		min-height: 40px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.doen {
		margin-top: var(--space-3);
	}
	.geenmodel {
		margin: 0;
		font-size: var(--text-xs);
	}

	.none {
		margin-top: var(--space-3);
		padding: var(--space-3);
		border: 1px dashed var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-1);
	}
	.none p {
		margin: 0 0 var(--space-2);
		font-size: var(--text-xs);
	}
	.none p:last-child {
		margin-bottom: 0;
	}
	.herkomst {
		font-size: var(--text-xs);
	}
	.notities {
		margin: var(--space-2) 0;
		padding-left: 1.1em;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.notities li {
		margin-bottom: 4px;
	}

	/* --------------------------------------------------------- eigen choice */
	.zelfkop {
		margin: 0 0 var(--space-2);
		font-size: var(--text-md);
		font-weight: 600;
		letter-spacing: -0.01em;
	}
	.soorten {
		list-style: none;
		margin: var(--space-4) 0 0;
		padding: 0;
		display: grid;
		/* Four cards in three columns leave a two-column hole on the second row; at 320 it
		   becomes 2×2 and the grid is full. */
		grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
		gap: var(--space-3);
	}
	.kind {
		display: grid;
		gap: var(--space-2);
		/* Equal height, whatever the text does: a ragged grid of cards reads as a list
		   with mistakes in it. */
		height: 100%;
		align-content: start;
		padding: var(--space-4);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-1);
		color: inherit;
		text-decoration: none;
		box-shadow: var(--lift-1);
	}
	.kind:hover { border-color: var(--accent); }
	.kind svg { color: var(--accent); }
	.name { font-weight: 600; }
	.hint { font-size: var(--text-xs); color: var(--text-2); }
	.hoeveel { font-size: var(--text-xs); color: var(--text-2); margin-top: 4px; }
	.kind.empty { opacity: 0.5; pointer-events: none; }
	.anders { margin-top: var(--space-4); font-size: var(--text-xs); color: var(--text-2); }
	.anders a { color: var(--accent-text); }

	/* Raakdoelen op tablet en telefoon. */
	@media (max-width: 1199px) {
		.model select {
			min-height: 44px;
		}
		.search :global(.btn) {
			min-height: 44px;
		}
	}
	/* At 390 px "Let OpenKerf search" broke over three lines beside the button, and that
	   button sat askew in the remaining hole. Better stacked, then. */
	@media (max-width: 560px) {
		.head {
			display: grid;
		}
		.search :global(.btn) {
			justify-content: center;
		}
		.busy {
			display: grid;
			gap: var(--space-2);
			grid-template-columns: auto 1fr;
			/* Beside a block of four lines a centred ring hangs in mid-air; it belongs with
			   the heading "Searching…". */
			align-items: start;
		}
		.ring {
			margin-top: 2px;
		}
		.busy > button {
			grid-column: 1 / -1;
			justify-content: center;
		}
	}
</style>
