<script lang="ts">
	/**
	 * The alarm: what the engine reports about the connection, loudly on screen.
	 *
	 * Pinned at the top, above everything, impossible to scroll away — that is the
	 * whole point. It sits below the top bar, so the buttons that stop the machine stay reachable. An alarm
	 * that covers the emergency stop is not an alarm but an obstacle.
	 *
	 * What is *not* there: a judgement we cannot back up. The text quotes the
	 * engine and says beside it what you have to check yourself — we cannot see the
	 * machine (decision B3).
	 */
	import { t } from '$lib/i18n/index.svelte';
	import Icon from './Icon.svelte';
	import type { Watchdog } from '$lib/notifications.svelte';

	let { watchdog }: { watchdog: Watchdog } = $props();
</script>

{#if watchdog.show && watchdog.alarm}
	<div class="alarm" role="alert" aria-live="assertive">
		<span class="sign"><Icon name="warn" size={20} /></span>
		<div class="words">
			<strong>{watchdog.alarm.title}</strong>
			<p>{watchdog.alarm.body}</p>
			<p>{watchdog.alarm.advice}</p>
			{#if watchdog.alarm.source}
				<!-- Verbatim what the engine said. We translate, but we do not hide
				     where it came from — that is the difference between a report and
				     an assertion. -->
				<details class="fold technical"><summary>{t('alarm.details')}</summary>
					<p class="source mono">{watchdog.alarm.source.trim()}</p>
				</details>
			{/if}
		</div>
		<button class="seen" onclick={() => watchdog.dismiss()}>{t('alarm.seen')}</button>
	</div>
{/if}

<style>
	.technical { margin-top: var(--space-1); }
	.technical > summary { color: inherit; }
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
		   `+page.svelte`; zero as long as there are no bars. */
		top: calc(
			var(--topbar-height) + var(--topedge-height, 0px) + var(--space-3) +
				var(--notice-column, 0px)
		);
		left: calc(var(--rail-width) + var(--space-3));
		width: min(620px, calc(100vw - var(--rail-width) - 2 * var(--space-3)));
		border-radius: var(--radius-card);
		/* An alarm belongs behind nothing — not behind a dialog, and not behind the
		   transport either. The three that have to be compared are in `tokens.css`. */
		z-index: var(--z-alarm);
		display: flex;
		align-items: flex-start;
		gap: var(--space-3);
		padding: var(--space-3) var(--space-4);
		background: var(--danger-solid);
		color: var(--on-color);
		box-shadow: var(--lift-2);
	}
	/**
	 * Out of the way while a window is open — still on top, still readable.
	 *
	 * The alarm outranks everything, and that stays true; what it may not do is lie
	 * across a window whose whole content is one picture. Measured on the cut-path
	 * window: 620 x 111 px of alarm over a drawing of 1006 x 522, with contour number 1
	 * underneath it. `data-modal` is set by Dialog.svelte for as long as any dialog is
	 * open, so the card moves to the bottom edge instead of being demoted.
	 *
	 * It does still lie over the bottom of the window — there is no free strip on a
	 * 900 px screen with a dialog of 760 in the middle of it. What is down there is
	 * text that scrolls, and "Seen" stays where the thumb expects it; what is up there
	 * is a picture you cannot scroll back into view.
	 */
	:global(html[data-modal]) .alarm {
		top: auto;
		bottom: calc(var(--statusbar-height, 0px) + var(--space-3));
	}
	.sign {
		flex: none;
		display: grid;
		margin-top: 2px;
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
	 * Measured: white on `--danger-solid` reaches 5.60. Every step of opacity
	 * spends that margin, and on the very line that says what to do. The hierarchy
	 * here comes from size and font (24 px bold / 15 px / 13 px mono), not from
	 * fading.
	 */
	.source {
		font-size: var(--text-xs);
	}
	/* The one button drawn here rather than taken from `.btn`: it sits on the red,
	   so its ink and its outline are the white the rest of the card is written in. */
	.seen {
		flex: none;
		min-height: max(36px, var(--target-min));
		padding: 0 var(--space-3);
		border: 1px solid var(--on-color);
		border-radius: var(--radius-field);
		color: var(--on-color);
		font-weight: 600;
		transition: background var(--transition);
	}
	.seen:hover {
		background: color-mix(in srgb, var(--on-color) 15%, transparent);
	}
	/* The global ring is the accent, and teal on this red is barely a ring at all; on
	   this one surface it is drawn in the card's white instead. */
	.seen:focus-visible {
		outline-color: var(--on-color);
	}

	/* Tablet: at 1024 the right-hand panel starts at x≈700, so 620 px from the rail
	   would cover the "Design" and "Layers" tabs again — exactly what you wanted to
	   operate at that moment. 560 keeps the card entirely above the canvas. The same
	   560 sits in `ConnectionCard.svelte`; those two should stay equal, because
	   together they are one column. Without a wrapper element (which would touch
	   `+page.svelte`, where these two are rendered in different places) this is the
	   price: one measure in two places, with this reference as the link. */
	@media (max-width: 1199px) {
		.alarm {
			width: min(560px, calc(100vw - var(--rail-width) - 2 * var(--space-3)));
		}
	}
</style>
