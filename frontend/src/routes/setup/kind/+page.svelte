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
	import Notice from '$components/Notice.svelte';
	import EmptyState from '$components/EmptyState.svelte';
	import { KINDS, kindOfMachine, type CatalogFamily, type ScanResult, type Finding } from '$lib/machines.svelte';
	import { i18n, t, type MessageKey } from '$lib/i18n/index.svelte';
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
	const SLOW = 8;
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

	/** Certainty gets a word *and* a shape — colour alone is not enough. The tone is
	 *  the badge's: a state, so never the accent. */
	const ZEKERHEID: Record<
		string,
		{ woord: MessageKey; hint: MessageKey; icon: string; tone: 'ok' | 'warn' }
	> = {
		zeker: {
			tone: 'ok',
			woord: 'setup.certainty.answered',
			hint: 'setup.certainty.answered.why',
			icon: 'M4 12.5 9 17.5 20 6.5'
		},
		waarschijnlijk: {
			tone: 'ok',
			woord: 'setup.certainty.probable',
			hint: 'setup.certainty.probable.why',
			icon: 'M12 3.5 22 20H2z'
		},
		onzeker: {
			tone: 'warn',
			woord: 'setup.certainty.guess',
			hint: 'setup.certainty.guess.why',
			icon: 'M9 8.5a3 3 0 1 1 3 3.5v2M12 18.5v.01'
		}
	};
</script>

<svelte:head><title>{t('setup.head.kind')}</title></svelte:head>

<section class="setup">
	{#if store.error}<Notice tone="danger" live>{store.error}</Notice>{/if}

	<h1 class="title">{t('setup.whatKind')}</h1>
	<p>{t('setup.whatKind.body')}</p>

	<section class="card inset search" aria-labelledby="zoekkop">
		<div class="head">
			<h2 class="label-section" id="zoekkop">{t('setup.scan.title')}</h2>
			{#if !zoekt}
				<!-- The step's primary until there is something to add; then "Add this one"
				     is the point of the screen and searching again is a plain verb. -->
				<button class="btn" class:primary={!resultaat} onclick={zoek}>
					{resultaat ? t('setup.scan.again') : t('setup.scan.start')}
				</button>
			{/if}
		</div>

		{#if zoekt}
			<div class="busy" role="status" aria-live="polite">
				<span class="ring" aria-hidden="true"></span>
				<div class="busytext">
					<div class="bezigkop">{t('setup.scan.running', { seconds: verstreken })}</div>
					<p class="help">{t('setup.scan.what')}</p>
					{#if verstreken >= SLOW}
						<!-- This ought to be done within three seconds. If it takes longer,
						     something is going on and the user deserves a way forward instead of
						     a spinning circle. -->
						<Notice tone="warn">{t('setup.scan.slow')}</Notice>
					{/if}
				</div>
				<button class="btn" onclick={afbreken}>{t('setup.scan.stop')}</button>
			</div>
		{/if}

		<!-- The promise stays put while searching too: that is exactly when you wonder
		     what is happening to your machine. -->
		<p class="help promise">
			<svg class="icon-svg" width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
				<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" /><circle cx="12" cy="12" r="3" />
			</svg>
			{t('setup.scan.promise')}
		</p>

		{#if resultaat && !zoekt}
			{#if resultaat.candidates.length}
				<h3 class="label-section uitslag">{t('setup.scan.found', { n: resultaat.candidates.length })}</h3>
				<ul class="vondsten">
					{#each resultaat.candidates as vondst (vondst.id)}
						{@const zeker = ZEKERHEID[vondst.confidence] ?? ZEKERHEID.onzeker}
						<li class="vondst">
							<!-- Stacked, not side by side: in a narrow card the title otherwise
							     became a column two words wide and an IP address broke in the
							     middle. -->
							<div class="row">
								<span class="badge">{transport(vondst.transport)}</span>
								<span class="badge {zeker.tone}" title={t(zeker.hint)}>
									<svg class="icon-svg" width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
										<path d={zeker.icon} />
									</svg>
									{t(zeker.woord)}
								</span>
							</div>
							<div class="vondsttitel">{vondst.title}</div>
							<div class="help mono waar">
								{vondst.where}{vondst.detail ? ` · ${vondst.detail}` : ''}
							</div>

							<p class="help">{vondst.why}</p>

							{#if vondst.suggestions.length > 1}
								<div class="model">
									<span class="field-label">{t('setup.whichModel.short')}</span>
									{#if vondst.suggestions.length <= 4}
										<Segmented
											label={t('setup.model')}
											options={vondst.suggestions.map((s) => ({ value: s.key, label: s.label }))}
											bind:value={choice[vondst.id]}
										/>
									{:else}
										<select bind:value={choice[vondst.id]} aria-label={t('setup.model')}>
											{#each vondst.suggestions as suggestie (suggestie.key)}
												<option value={suggestie.key}>{suggestie.label}</option>
											{/each}
										</select>
									{/if}
								</div>
							{:else if vondst.suggestions.length === 1}
								<p class="model enkel">
									{t('setup.suggestion', { label: vondst.suggestions[0].label })}
									<span class="help">({vondst.suggestions[0].family})</span>
								</p>
							{/if}

							<div class="doen">
								{#if vondst.suggestions.length}
									<button class="btn primary" onclick={() => bevestig(vondst)}>
										{t('setup.addThis')}
									</button>
								{:else}
									<p class="help">{t('setup.noModel')}</p>
								{/if}
							</div>
						</li>
					{/each}
				</ul>
			{:else}
				<EmptyState title={t('setup.nothing')} text={t('setup.nothing.body')} />
				{#if resultaat.notes.length === 1}
					<p class="help">{resultaat.notes[0]}</p>
				{:else if resultaat.notes.length}
					<ul class="help notities">
						{#each resultaat.notes as notitie}<li>{notitie}</li>{/each}
					</ul>
				{/if}
				<!-- Where it looked belongs with it: without that "nothing found" cannot be
				     checked and so cannot be trusted. -->
				<p class="help herkomst">
					{t('setup.searchedIn', {
						where: resultaat.searched.join(', ') || t('setup.searchedIn.nothing'),
						seconds: i18n.number(resultaat.duration_ms / 1000, 1)
					})}
				</p>
			{/if}
		{/if}
	</section>

	<h2 class="label-section zelfkop">{t('setup.orPick')}</h2>
	<p>{t('setup.orPick.body')}</p>

	<ul class="soorten">
		{#each aantallen as kind (kind.id)}
			<li>
				<a
					class="card inset kind"
					class:empty={kind.count === 0}
					href={kind.count ? `/setup/type?kind=${kind.id}` : undefined}
					aria-disabled={kind.count === 0}
					title={kind.count === 0 ? t('reason.noneYet') : undefined}
				>
					<svg class="icon-svg" width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
						<path d={kind.icon} />
					</svg>
					<span class="name">{kind.label}</span>
					<span class="help">{kind.blurb}</span>
					<span class="help hoeveel">
						{kind.count === 0 ? t('setup.models.none') : t('setup.models', { n: kind.count })}
					</span>
				</a>
			</li>
		{/each}
	</ul>

	<p class="help anders">
		{t('setup.notListed')}
		<a class="link" href="/setup/type">{t('setup.fullList')}</a>
	</p>
</section>

<style>
	/* ------------------------------------------------------------ search block */
	.search {
		display: grid;
		gap: var(--space-3);
		margin: var(--space-4) 0 var(--space-8);
	}
	.head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-3);
		flex-wrap: wrap;
	}
	/* The promise from the decision is on the screen, not only in a document: anybody
	   pressing a button that could touch a laser should know that this one does not. */
	.promise {
		display: flex;
		align-items: flex-start;
		gap: var(--space-2);
	}

	.busy {
		display: flex;
		align-items: flex-start;
		flex-wrap: wrap;
		gap: var(--space-3);
	}
	.busytext {
		flex: 1 1 260px;
		min-width: 0;
		display: grid;
		gap: var(--space-1);
	}
	.bezigkop {
		font-weight: 500;
		font-variant-numeric: tabular-nums;
	}
	/* Beside a block of several lines a centred ring hangs in mid-air; it belongs with
	   the heading "Searching…". */
	.ring {
		flex: none;
		width: 20px;
		height: 20px;
		border-radius: var(--radius-dot);
		border: 2px solid var(--line);
		border-top-color: var(--accent);
		animation: turn var(--duration-slow) linear infinite;
	}
	@keyframes turn {
		to {
			transform: rotate(360deg);
		}
	}

	.vondsten {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	/* The findings sit in the search block on a hairline each, not in cards of their own:
	   a card in a card in a card said nothing the hairline does not. Certainty is the
	   badge — a word and a shape — rather than a stripe down the side. */
	.vondst {
		display: grid;
		gap: var(--space-1);
		padding: var(--space-3) 0;
	}
	.vondst + .vondst {
		border-top: 1px solid var(--line);
	}
	.row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin-bottom: var(--space-1);
	}
	.vondsttitel {
		font-weight: 600;
	}
	.waar {
		overflow-wrap: anywhere;
	}

	.model {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		flex-wrap: wrap;
		margin-top: var(--space-2);
	}
	.model.enkel {
		margin: var(--space-1) 0 0;
		font-size: var(--text-xs);
	}
	/* Segmented gives every box `flex: 1` — and that is `1 1 0%`, so all the boxes become
	   equally wide and the longest label is truncated ("GRBL (generi"). Elsewhere there
	   are only labels of equal length in it, so we fix this here rather than in the shared
	   component. */
	.model :global(.segmented button) {
		flex: 0 1 auto;
	}
	.doen {
		margin-top: var(--space-2);
	}
	.notities {
		margin: 0;
		padding-left: var(--space-4);
	}

	/* --------------------------------------------------------- eigen choice */
	.zelfkop {
		margin-bottom: var(--space-1);
	}
	.soorten {
		list-style: none;
		margin: var(--space-4) 0 0;
		padding: 0;
		display: grid;
		/* Four cards in three columns leave a two-column hole on the second row; at 320 it
		   becomes 2×2 and the grid is full. */
		grid-template-columns: repeat(auto-fill, minmax(min(320px, 100%), 1fr));
		gap: var(--space-3);
	}
	.kind {
		display: grid;
		gap: var(--space-1);
		/* Equal height, whatever the text does: a ragged grid of cards reads as a list
		   with mistakes in it. */
		height: 100%;
		align-content: start;
		color: inherit;
		text-decoration: none;
		transition: border-color var(--transition), background var(--transition);
	}
	.kind[href]:hover {
		border-color: var(--accent-edge);
		background: var(--accent-tint);
	}
	.kind svg {
		color: var(--text-2);
		margin-bottom: var(--space-1);
	}
	.kind[href]:hover svg {
		color: var(--accent);
	}
	.name { font-weight: 600; }
	.hoeveel { margin-top: var(--space-1); font-variant-numeric: tabular-nums; }
	/* Nothing to pick behind it: drained, not faded — and still pointable, so the
	   tooltip can say why. */
	.kind.empty {
		color: var(--text-2);
		cursor: not-allowed;
	}
	.anders { margin-top: var(--space-4); }
</style>
