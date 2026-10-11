<!-- frontend/src/lib/components/TileRun.svelte -->
<script lang="ts">
	/**
	 * One step at a time, because this is a procedure you carry out with your
	 * hands on the machine. Anything that is not up next is not on screen.
	 *
	 * The two marks of a non-first tile ask for "Here" twice, but the server only
	 * accepts a call with exactly one point (the corner) or exactly two (both
	 * marks) — `TileRun.align` (`api/openkerf_api/tilerun.py`) raises on a single
	 * mark. The first tap is therefore only remembered locally (the current head
	 * position from the status), and only the second tap goes to the server, which
	 * adds its own head position to it.
	 */
	import { i18n, t } from '$lib/i18n/index.svelte';
	import type { TilingStore } from '$lib/tiling.svelte';
	import Icon from './Icon.svelte';
	import Notice from './Notice.svelte';

	// No `device` prop any more: since the two-sources bug the head position comes
	// from the server via `tiling.liveHead()`, not from the status snapshot.
	let { tiling }: { tiling: TilingStore } = $props();

	let tapped = $state<{ x_mm: number; y_mm: number }[]>([]);
	/** Failure while recording a tap locally; separate from `tiling.error`, which
	 *  is only ever about a server call. */
	let localError = $state<string | null>(null);

	const run = $derived(tiling.run);
	const first = $derived(run?.current === 0);
	const needed = $derived(first ? 1 : 2);
	/**
	 * How far the plate has to move, and in which direction.
	 *
	 * The distance comes from the server (`shift_mm`): working it out ourselves
	 * went wrong, because the gap between two burn areas is half an overlap larger
	 * than the gap between two windows, and with that larger number you shift the
	 * marks off the bed.
	 *
	 * The direction is **fixed per axis**, and that is not a simplification: the
	 * windows run upwards, so the shift is always positive. There used to be a
	 * choice here between "up" and "down" as if both could occur — worked through
	 * for plates from 500 to 1200 mm the step is positive in every case, so that
	 * second branch was unreachable and suggested a care that was not there.
	 *
	 * If the plate exceeds the bed in height it goes **up** — the direction
	 * Jelle's 5030 needs, and the only one a machine without side feed can do. For
	 * a plate that is too wide it says "left"; that is not confirmed on a machine
	 * and stands until someone measures otherwise.
	 */
	const shift = $derived.by(() => {
		const step = tiling.layout?.tiles?.[run?.current ?? 0]?.shift_mm;
		if (!step) return null;
		if (Math.abs(step.y) >= Math.abs(step.x)) {
			return { mm: Math.abs(step.y), direction: t('tiles.up') };
		}
		return { mm: Math.abs(step.x), direction: t('tiles.left') };
	});

	/**
	 * Which mark is up next — by number, not by place.
	 *
	 * This used to say "the left" or "the top mark", derived from how the two lie
	 * relative to each other. That word depended on `flip_x`, `swap_xy` and the
	 * home corner of the machine, and so could be the wrong way round without
	 * anyone noticing. A number depends on nothing, and it is burned in next to
	 * the circle — which is why it can be found on the plate at all, something a
	 * number without that engraving could not be.
	 */
	const whichMark = $derived(t('tiles.mark', { n: tapped.length + 1 }));

	// Matched against the wording the server sends, not against the translation:
	// this is the engine's own message, and it does not follow the interface
	// language. It becomes a code as soon as the API carries one.
	const mayRetry = $derived(
		typeof tiling.error === 'string' && tiling.error.includes('already burned')
	);

	async function burnAgain() {
		await tiling.burn(true);
	}

	async function here() {
		localError = null;
		// On a non-first tile the first tap is never a server call: with one point
		// it would fail straight away. Remember it locally and wait for the second.
		if (!first && tapped.length < needed - 1) {
			// Ask the server for the live position rather than the status snapshot:
			// that one is up to two seconds old, and the second tap does use the
			// live position. Two sources for one measurement gave a 230 mm
			// difference (measured).
			const point = await tiling.liveHead();
			if (!point) {
				localError = t('tiles.noPosition');
				return;
			}
			tapped = [...tapped, point];
			return;
		}
		const ok = await tiling.alignHere(first ? 'plate_corner' : 'markers', tapped);
		if (!ok) return;
		tapped = [];
	}

	async function next() {
		await tiling.advance();
		tapped = [];
	}
</script>

{#if tiling.error}
	<!-- Outside `{#if run}`: a failed start (the offer on the canvas, say, before
	     a run exists) has to be visible when there is no tile yet either.
	     Otherwise a button that 409s looks like it does nothing. -->
	<div class="failure"><Notice tone="danger" live>{tiling.error}</Notice></div>
{/if}

{#if run}
	<section class="tiles card" aria-label={t('tiles.aria')}>
		<header>
			<div>
				<strong>{t('tiles.current', { n: run.current + 1, total: run.tiles })}</strong>
				<!-- The assumption you cannot see as a user: during a tile run the
				     marks decide where the burning happens, not the zero point set
				     for the sheet. -->
				<p class="help origin">{t('tiles.originIgnored')}</p>
			</div>
			<button class="btn ghost mini stop" type="button" onclick={() => tiling.cancel()}>
				{t('tiles.stop')}
			</button>
		</header>

			<!-- Where you are in the run, in one line. The canvas ticks off the tiles
			     that are done, but someone working in the panel should be able to
			     read it there as well. -->
			<ol class="progressPart" aria-label={t('tiles.progressAria')}>
				{#each Array(run.tiles) as _, i (i)}
					<li class:ready={run.done.includes(i)} class:now={i === run.current}>
						<span class="mono">{i + 1}</span>{#if run.done.includes(i)}<Icon name="check" />{/if}
					</li>
				{/each}
			</ol>

		{#if run.stale}
			<Notice tone="warn" live>{run.message}</Notice>
		{:else if !run.aligned}
			<p>
				{#if first}
					{t('tiles.layPlate')}
				{:else}
					{#if shift}
						{t('tiles.shift', { mm: i18n.number(shift.mm, 0), direction: shift.direction })}
					{:else}
						{t('tiles.shiftUnknown')}
					{/if}
					{t('tiles.jogTo', { mark: whichMark })}
				{/if}
			</p>
			<!-- This button says what it records too: with two circles in front of
			     you, "Here" on its own is not enough to know which of the two you
			     are confirming. -->
			<button class="btn primary" type="button" onclick={here} disabled={tiling.busy} title={tiling.busy ? t('reason.busy') : undefined}>
				{#if first}
					{t('tiles.hereCorner')}
				{:else}
					{t('tiles.hereMark', { mark: whichMark, total: needed })}
				{/if}
			</button>
			{#if !first && tapped.length > 0}
				<!-- The tapped marks live only in this page's memory; a refresh does
				     not know them any more. The geometry itself is not at risk, but
				     someone who just set a tap should not silently end up back at 0. -->
				<p class="help warn">{t('tiles.refreshWarning')}</p>
			{/if}
		{:else}
			<p class="uitgelijnd">
				{t('tiles.aligned')}
				{#if run.angle_deg != null}· {t('tiles.skew', { degrees: i18n.number(run.angle_deg, 2) })}{/if}
				{#if run.distance_error_mm != null}
					· {t('tiles.distanceError', { mm: i18n.number(run.distance_error_mm, 1) })}
				{/if}
			</p>
			<div class="actions">
				<button class="btn primary" type="button" onclick={() => tiling.burn()} disabled={tiling.busy} title={tiling.busy ? t('reason.busy') : undefined}>
					{t('tiles.burnThis')}
				</button>
				<button class="btn" type="button" onclick={next} disabled={tiling.busy} title={tiling.busy ? t('reason.busy') : undefined}>
					{t('tiles.next')}
				</button>
				{#if mayRetry}
					<!-- The exception, not the ordinary route: only visible after the
					     refusal, and deliberately not the primary button. -->
					<button class="btn warn" type="button" onclick={burnAgain} disabled={tiling.busy} title={tiling.busy ? t('reason.busy') : undefined}>
						{t('tiles.burnAgain')}
					</button>
				{/if}
			</div>
		{/if}

		{#if localError}
			<Notice tone="danger" live>{localError}</Notice>
		{/if}
	</section>
{/if}

<style>
	.failure {
		margin-bottom: var(--space-2);
	}
	.tiles {
		display: grid;
		gap: var(--space-2);
		padding: var(--space-3);
		margin-bottom: var(--space-4);
	}
	header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: var(--space-2);
	}
	.origin {
		margin-top: 2px;
	}
	.stop {
		flex: none;
	}
	.progressPart {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		list-style: none;
		margin: 0;
		padding: 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.progressPart li {
		display: inline-flex;
		align-items: center;
		gap: 2px;
	}
	/* Done and up next are states, so ink and weight rather than the accent. */
	.progressPart .ready {
		color: var(--ok);
	}
	.progressPart .now {
		color: var(--text-1);
		font-weight: 600;
		text-decoration: underline;
		text-underline-offset: 3px;
	}
	.uitgelijnd {
		margin: 0;
		color: var(--text-1);
	}
	.actions {
		display: flex;
		gap: var(--space-2);
		flex-wrap: wrap;
	}
	.btn.warn {
		border-color: var(--warn-edge);
		color: var(--warn);
	}
</style>
