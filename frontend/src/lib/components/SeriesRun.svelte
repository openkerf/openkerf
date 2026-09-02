<!-- frontend/src/lib/components/SeriesRun.svelte -->
<script lang="ts">
	/**
	 * The plate now on the bed, and the two presses that make the next one.
	 *
	 * A series is a procedure you carry out with your hands on the machine: burn,
	 * take the plate off, put the next one on, press on. So this block says which
	 * plate is coming, what it engraves and how far along the afternoon is, and it
	 * carries nothing that belongs to setting the list up — that is the Series
	 * window, and a second place to change the list is a second answer to what is
	 * about to burn.
	 *
	 * It is `TileRun.svelte`'s shape on purpose, down to the header with the stop
	 * button in it: the two runs are the same kind of thing to the operator, and two
	 * layouts for one job is two things to learn. The *wordings* are deliberately
	 * not shared — see the catalogue.
	 *
	 * **Where the state comes from.** The status payload, `_series_state()` in
	 * `api/openkerf_api/server.py`, adopted into this one store by `+page.svelte`.
	 * Not a route of its own: the top bar, the canvas, the context panel and this
	 * block all have to say the same thing about which row is next, and four
	 * requests for one fact drift apart. The heartbeat is every two seconds, so a
	 * pointer moved from the Series window arrives here without anybody asking.
	 *
	 * **This is the only surface that may call `burn()`.** The window sets the list
	 * up and moves the pointer; the machine is reached from here, by somebody
	 * standing next to it.
	 */
	import { i18n, t } from '$lib/i18n/index.svelte';
	import type { SeriesStore } from '$lib/series.svelte';

	let { series }: { series: SeriesStore } = $props();

	/**
	 * The whole sum, as `Series.state()` answers it.
	 *
	 * Called `sum` and not `state`: a local named `state` shadows the `$state` rune,
	 * and every `$state(…)` in the file then compiles as an auto-subscription to a
	 * store nobody has. Measured in `Series.svelte`, twenty-two errors from one name.
	 */
	const sum = $derived(series.state);
	const run = $derived(sum?.run ?? null);
	/** Which burn is on the bed, counted the way a person counts. */
	const current = $derived(sum?.current_burn ?? null);
	const total = $derived(sum?.burns ?? 0);

	/**
	 * What this plate engraves, in the engine's own words.
	 *
	 * From `uses[].renders` and not from the arithmetic in `$lib/series`: `renders`
	 * is what the engine's own substitution puts on the material for the row the bed
	 * is pointing at, which is precisely this burn. The window works the *other*
	 * rows out itself because the engine can only be asked about the row its pointer
	 * stands on, and moving that pointer is a write.
	 *
	 * A place whose row has run out keeps its `{…}` run standing, because that is
	 * what the engine would engrave. Those are counted and left out of the text, the
	 * same treatment as the burn list in the window: the server's `OverrunMutator`
	 * takes those shapes off the last sheet, so the honest thing to say is that the
	 * place stays empty and not that it burns nine characters of syntax.
	 */
	const engraved = $derived.by(() => {
		const uses = (sum?.uses ?? []).filter((use) => !use.reserved);
		const standing = uses.filter((use) => /\{[^}]+\}/.test(use.renders)).length;
		const parts = uses
			.map((use) => use.renders)
			.filter((text) => text.trim() && !/\{[^}]+\}/.test(text));
		// Several values in one line go through `i18n.list()`, never `join(', ')`: in
		// Dutch the comma is the decimal mark.
		return { text: parts.length ? i18n.list(parts) : '', standing };
	});

	/**
	 * How many of these burns are done — in burns, because that is what you press.
	 *
	 * `done` is kept as row ranges on the server (a nudge to a rectangle can change
	 * how many rows one burn eats, and burn numbers would not survive that), so the
	 * ranges are laid over the partition here. The partition is `series.burns`, the
	 * very function the window's burn list and the server's `_burns` both use.
	 *
	 * It needs the rows, and the rows ride on `GET /api/series` and never in the
	 * heartbeat — a thousand rows down every socket for a number that fits in a word.
	 * `+page.svelte` loads them at mount, but a page that has not managed it yet
	 * would count nought done out of fifty, which is a lie of the worst kind here. So
	 * the line only appears when the browser's own partition agrees with the count
	 * the server sent; the heading above it needs neither.
	 */
	const partition = $derived(series.burns);
	const done = $derived.by(() => {
		if (!run || total === 0 || partition.length !== total) return null;
		const ranges = run.done ?? [];
		return partition.filter((rows) =>
			rows.every((row) => ranges.some((span) => row >= span[0] && row <= span[1]))
		).length;
	});

	/**
	 * The design moved under the run, and which way it moved.
	 *
	 * Two reasons and two sentences, because the punishment differs: shapes that have
	 * moved mean the plates already made belong to another drawing, while a changed
	 * number of places on a sheet means the rows fall into different burns than the
	 * ones that are ticked off. The server refuses a burn for either
	 * (`series.staleGeometry` / `series.stalePlaces`), so the button is off before it
	 * is pressed rather than after.
	 */
	/**
	 * Does anything on the bed take its value from the list?
	 *
	 * A series of fifty identical plates is not a series, and the server refuses to
	 * start one (`series.nothingVariable`). The button is off before it is pressed, with
	 * the reason in its title — a grey button without a reason is a riddle.
	 */
	const reads = $derived((sum?.used_columns ?? []).length > 0);
	const stale = $derived(Boolean(sum?.stale));
	const staleWhy = $derived(
		sum?.stale_reason === 'places' ? t('series.stale.places') : t('series.stale.geometry')
	);

	/** Which burn went to the machine last, so the press says it arrived. */
	let sent = $state<number | null>(null);
	/**
	 * Whether the refusal standing on the store came from a press *here*.
	 *
	 * The store is shared with the Series window, and that window is a dialog over
	 * this panel: a file refused there ("this file is larger than 5 MB") would
	 * otherwise still be sitting in red in the Job panel after the dialog was closed,
	 * about something the panel has nothing to do with. So this block shows only the
	 * answers to its own three presses, and the window shows its own.
	 */
	let pressed = $state(false);
	/** The run ended under our hands: `advance()` answered that nothing is left. */
	let ended = $state(false);

	// A fresh run wipes the closing line: otherwise "every burn is done" sits above a
	// series that has just begun.
	$effect(() => {
		if (run) ended = false;
	});
	// A press that succeeded is no longer a press with an answer to show.
	$effect(() => {
		if (!series.error) pressed = false;
	});

	async function burn(confirm = false) {
		sent = null;
		pressed = true;
		const answer = await series.burn(confirm);
		if (answer?.burned) sent = answer.burned;
	}

	/**
	 * Begin the count of plates.
	 *
	 * Here and not in the window, for the reason the placement rule gives: the window is
	 * where you set a series up, and this is where you work it. It writes the run file
	 * and nothing else — no plan is built and nothing reaches the machine until "Burn
	 * this one" is pressed, which is what the title says before the press.
	 *
	 * Without it the feature could be prepared and never used: the API had `start`, the
	 * store had `start()`, and no surface called either — measured on a bed with a list
	 * attached and five burns waiting, where the Job panel said nothing at all.
	 */
	async function begin() {
		pressed = true;
		await series.start();
		if (!series.error) pressed = false;
	}

	async function next() {
		sent = null;
		pressed = true;
		const answer = await series.advance();
		ended = Boolean(answer?.finished);
	}

	async function stop() {
		sent = null;
		ended = false;
		pressed = true;
		await series.stop();
	}
</script>

{#if series.error && pressed}
	<!-- Outside `{#if run}`, the same as the tile run: a refusal that ends the run —
	     `series.noRun` — would otherwise take its own explanation off the screen with
	     it, and a button that 409s then looks like a button that does nothing. -->
	<p class="notice" role="alert">
		{series.error}
		{#if series.errorCode === 'series.alreadyBurned'}
			<!-- The exception and not the ordinary route: only after the refusal, and
			     deliberately not the primary button. Going over work that is already
			     there is only ever right when the last attempt was spoiled. -->
			<button class="btn warn" type="button" disabled={series.busy} onclick={() => burn(true)}>
				{t('series.burnAgain')}
			</button>
		{/if}
	</p>
{/if}

{#if run}
	<section class="seriesRun" aria-label={t('series.run.aria')}>
		<header>
			<strong>{t('series.current', { n: i18n.number(current ?? 0), total: i18n.number(total) })}</strong>
			<button
				class="btn subtle"
				type="button"
				title={t('series.stop.title')}
				disabled={series.busy}
				onclick={stop}
			>
				{t('series.stop')}
			</button>
		</header>

		<!-- On a row of its own and not beside the heading: sharing the header with the
		     stop button left it 122 px of a 245 px card, and "This one engraves …" with
		     the name itself ellipsised away is the one thing this block may not do. -->
		{#if engraved.text}
			<!-- The reader's own data, so the whole string is in the title for the name
			     that still does not fit on a panel this narrow. -->
			<p class="engraves" title={engraved.text}>{t('series.engraves', { what: engraved.text })}</p>
		{:else}
			<p class="engraves">{t('series.burn.blank')}</p>
		{/if}
		{#if engraved.standing}
			<p class="fine">{t('series.burn.short', { n: engraved.standing })}</p>
		{/if}

		{#if done !== null}
			<!-- Where you are in the afternoon. The bar is never the whole message: the
			     sentence under it says the same thing in numbers, because a bar cannot be
			     read out and a colour cannot be counted. -->
			<div
				class="bar"
				role="progressbar"
				aria-valuenow={done}
				aria-valuemin="0"
				aria-valuemax={total}
				aria-label={t('series.progressAria')}
			>
				<span class="vol" style="width: {total ? Math.round((done / total) * 1000) / 10 : 0}%"></span>
			</div>
			<p class="fine">{t('series.progress', { done: i18n.number(done), total: i18n.number(total) })}</p>
		{/if}

		{#if stale}
			<p class="notice stale" role="alert">{staleWhy}</p>
			<p class="fine">{t('series.stale.how')}</p>
		{/if}

		<div class="actions">
			<button
				class="btn primary"
				type="button"
				disabled={series.busy || stale}
				title={stale ? staleWhy : undefined}
				onclick={() => burn()}
			>
				{t('series.burnThis')}
			</button>
			<!-- Moving on burns nothing and marks nothing done — `burn()` does the
			     marking, because that is where the plate is made. The title says so:
			     "next" beside a laser reads as "and go". -->
			<button class="btn" type="button" disabled={series.busy} title={t('series.next.title')} onclick={next}>
				{t('series.next')}
			</button>
		</div>

		{#if sent !== null}
			<p class="fine sent">{t('series.sent', { n: i18n.number(sent) })}</p>
		{/if}
	</section>
{:else if sum?.attached}
	<!-- Attached, and not going yet. The panel orders itself by the phase of the
	     process (DESIGN-SYSTEM.md v5), and this is the phase before the first plate:
	     what is waiting, and the one button that begins it. -->
	<section class="seriesRun ready" aria-label={t('series.ready.aria')}>
		<header>
			<strong>{t('series.ready', { burns: i18n.number(total) })}</strong>
		</header>
		{#if engraved.text}
			<p class="engraves" title={engraved.text}>{t('series.ready.first', { what: engraved.text })}</p>
		{/if}
		{#if !reads}
			<!-- The same refusal the server would answer with, said before the press
			     rather than after it. -->
			<p class="fine">{t('series.nothingReads')}</p>
		{/if}
		<div class="actions">
			<button
				class="btn primary"
				type="button"
				disabled={series.busy || !reads}
				title={reads ? t('series.begin.title') : t('series.nothingReads')}
				onclick={begin}
			>
				{t('series.begin')}
			</button>
		</div>
	</section>
{:else if ended}
	<!-- The run is over and this block is about to vanish with it. Saying nothing
	     would leave the last press looking like the one that failed. -->
	<p class="notice ended">
		{t('series.finished')}
		<button class="btn subtle" type="button" aria-label={t('common.dismiss')} onclick={() => (ended = false)}
			>×</button
		>
	</p>
{/if}

<style>
	.seriesRun {
		display: grid;
		/* `minmax(0, 1fr)` and not the default `auto`: a grid item may not shrink below
		   its content, so one long name blew the column out to 494 px inside a 245 px
		   card (measured) and the whole block scrolled sideways. The name is the
		   reader's own data and can be any length, so the room it gets is fixed here
		   and the ellipsis does the rest. */
		grid-template-columns: minmax(0, 1fr);
		gap: var(--space-2);
		padding: var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		margin-bottom: var(--space-4);
	}
	header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: var(--space-2);
	}
	.engraves {
		margin: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.fine {
		margin: 2px 0 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.bar {
		height: 6px;
		border-radius: 3px;
		background: var(--line);
		overflow: hidden;
	}
	.vol {
		display: block;
		height: 100%;
		background: var(--accent);
	}
	.actions {
		display: flex;
		gap: var(--space-2);
		flex-wrap: wrap;
	}
	.notice {
		color: var(--danger);
		margin: 0 0 var(--space-2);
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
		flex-wrap: wrap;
	}
	.notice.stale {
		color: var(--warn);
		margin: 0;
	}
	.notice.ended {
		color: var(--text-1);
	}
	.sent {
		color: var(--text-1);
	}
	.btn.warn {
		border-color: var(--warn);
		color: var(--warn);
	}
	.btn.subtle {
		flex: none;
		font-size: var(--text-xs);
		color: var(--text-2);
		background: none;
		border: none;
		padding: 4px 8px;
	}
	.btn.subtle:hover:not(:disabled) {
		background: var(--surface-2);
		color: var(--text-1);
	}
</style>
