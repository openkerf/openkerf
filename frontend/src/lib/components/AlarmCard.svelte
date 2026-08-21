<script lang="ts">
	/**
	 * The alarm: what the engine reports about the connection, loudly on screen.
	 *
	 * Pinned at the top, above everything, impossible to scroll away — that is the
	 * whole point. On the phone it sits against the top edge; on the desktop below
	 * the top bar, so the buttons that stop the machine stay reachable. An alarm
	 * that covers the emergency stop is not an alarm but an obstacle.
	 *
	 * What is *not* there: a judgement we cannot back up. The text quotes the
	 * engine and says beside it what you have to check yourself — we cannot see the
	 * machine (decision B3).
	 */
	import { t } from '$lib/i18n/index.svelte';
	import type { Watchdog } from '$lib/notifications.svelte';

	let { watchdog, large = false }: { watchdog: Watchdog; large?: boolean } = $props();
</script>

{#if watchdog.show && watchdog.alarm}
	<div class="alarm" class:large role="alert" aria-live="assertive">
		<svg class="sign" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"
			stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
			<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
			<path d="M12 9v4" />
			<path d="M12 17h.01" />
		</svg>
		<div class="words">
			<strong>{watchdog.alarm.title}</strong>
			<p>{watchdog.alarm.body}</p>
			<p>{watchdog.alarm.advice}</p>
			{#if watchdog.alarm.source}
				<!-- Verbatim what the engine said. We translate, but we do not hide
				     where it came from — that is the difference between a report and
				     an assertion. -->
				<p class="source mono">{watchdog.alarm.source.trim()}</p>
			{/if}
		</div>
		<button class="seen" onclick={() => watchdog.dismiss()}>{t('alarm.seen')}</button>
	</div>
{/if}

<style>
	.alarm {
		position: fixed;
		/*
		 * One column with the connection card, and that one sits above it.
		 *
		 * This was centred on 50% while `ConnectionCard.svelte` hangs against the
		 * rail, at the same height. At 1440 this alarm therefore started at x≈360,
		 * straight across that card, and cut off two sentences — not fully covered
		 * but half, and that is worse: a truncated sentence looks like a whole
		 * sentence, so you do not know you are missing half of it.
		 *
		 * Now the same left edge and the same width, with `--notice-column` as the
		 * offset: the connection card sets that on `:root` with its own measured
		 * height, and it is absent as soon as that card is gone. Why that card
		 * belongs *above* this alarm: without our server every report about the
		 * machine is old news by definition — it is the same engine that has stopped
		 * answering.
		 *
		 * The original objection to left alignment was the control error message in
		 * the top right (Notice.svelte, z-index 60). That is still there, and left
		 * alignment actually helps: this way those two do not touch.
		 */
		/* Below the bars that sit above the canvas (action bar + sheet bar), not
		   over them: it used to cover those, and those are exactly the buttons you
		   need while a notice is up. `--topedge-height` is measured in
		   `+page.svelte`; zero as long as there are no bars (phone). */
		top: calc(
			var(--topbar-height) + var(--topedge-height, 0px) + var(--space-3) +
				var(--notice-column, 0px)
		);
		left: calc(var(--rail-width) + var(--space-3));
		width: min(620px, calc(100vw - var(--rail-width) - 2 * var(--space-3)));
		border-radius: var(--radius-card);
		/* Above everything: dialogs sit at 60, the scrim at 50. An alarm belongs
		   behind nothing. */
		z-index: 200;
		display: flex;
		align-items: flex-start;
		gap: var(--space-3);
		padding: var(--space-3) var(--space-4);
		background: var(--danger-solid);
		color: var(--on-color);
		box-shadow: var(--lift-2);
	}
	.sign {
		flex: none;
		width: 22px;
		height: 22px;
		margin-top: 1px;
	}
	.words {
		flex: 1;
		min-width: 0;
	}
	strong {
		display: block;
		font-size: var(--text-md);
		font-weight: 600;
		letter-spacing: -0.01em;
	}
	p {
		margin: var(--space-1) 0 0;
		font-size: var(--text-sm);
		/* White on red must not fade: this is the text that carries the fact. */
		color: var(--on-color);
	}
	/*
	 * No transparency as hierarchy on this surface.
	 *
	 * Measured at 390 px: white on `--danger-solid` reaches 5.60 in light and 4.67
	 * in dark, but at opacity 0.9 the advice drops to 4.05 in dark and at 0.75 the
	 * source line drops to 3.23 — both below AA, and on the very line that says
	 * what to do. The hierarchy here comes from size and font (24 px bold / 15 px /
	 * 13 px mono), not from fading.
	 */
	.source {
		font-size: var(--text-xs);
	}
	.seen {
		flex: none;
		min-height: 36px;
		padding: 0 var(--space-3);
		border: 1px solid var(--on-color);
		border-radius: var(--radius-field);
		color: var(--on-color);
		font-weight: 600;
	}
	.seen:hover {
		background: rgb(255 255 255 / 0.15);
	}

	/* Tablet: at 1024 the right-hand panel starts at x≈700, so 620 px from the rail
	   would cover the "Design" and "Layers" tabs again — exactly what you wanted to
	   operate at that moment. 560 keeps the card entirely above the canvas. The same
	   560 sits in `ConnectionCard.svelte`; those two should stay equal, because
	   together they are one column. Without a wrapper element (which would touch
	   `+page.svelte`, where these two are rendered in different places) this is the
	   price: one measure in two places, with this reference as the link. */
	@media (min-width: 768px) and (max-width: 1199px) {
		.alarm:not(.large) {
			width: min(560px, calc(100vw - var(--rail-width) - 2 * var(--space-3)));
		}
	}

	/* Phone: not an overlay but a block at the top that pushes the rest down. It
	   sits outside the scroll area, so it cannot be scrolled away — and at the same
	   time it cuts nothing off. Bigger, and the button below the text instead of
	   beside it: with a thumb you do not aim at a 36 px button in a corner. */
	.alarm.large {
		position: static;
		/* The floating variant hangs off the rail and no longer has a transform, but
		   these rules stay as a lock on the door: `transform` and `left` work on a
		   static element too, and when the floating variant still carried
		   `translateX(-50%)` this block slid half a screen width out of view with
		   it. */
		transform: none;
		left: auto;
		right: auto;
		top: auto;
		flex: none;
		width: 100%;
		border-radius: 0;
		flex-wrap: wrap;
		padding: max(var(--space-3), env(safe-area-inset-top)) var(--space-3) var(--space-3);
	}
	.alarm.large .sign {
		width: 28px;
		height: 28px;
	}
	.alarm.large strong {
		font-size: var(--text-lg);
	}
	.alarm.large .seen {
		width: 100%;
		min-height: 48px;
		margin-top: var(--space-2);
	}
</style>
