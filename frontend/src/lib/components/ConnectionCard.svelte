<script lang="ts">
	/**
	 * What you see when the server drops out.
	 *
	 * Until now only a dot changed colour and a few buttons went grey. That is not a
	 * message but a symptom: the screen looks frozen and nobody knows whether to
	 * wait, reload, or run to the machine. Three things belong in it, in this order:
	 * what is broken, what that means for your work, and what the app is doing about
	 * it right now.
	 *
	 * The safety line is not there for decoration. If the server drops out while the
	 * machine is burning, it burns on and this app can no longer stop it. You should
	 * not have to work that out for yourself at such a moment.
	 */
	import { t } from '$lib/i18n/index.svelte';
	import { connection } from '$lib/connection.svelte';

	let { burns = false }: { burns?: boolean } = $props();

	// Half a second of network hiccup is not a message; the reconnect succeeds
	// before anybody has read it. Only speak up after two seconds.
	const PATIENCE = 2000;
	let late = $state(false);
	$effect(() => {
		if (connection.online) {
			late = false;
			return;
		}
		const t = setTimeout(() => (late = true), PATIENCE);
		return () => clearTimeout(t);
	});

	let gone = $derived(
		connection.since ? Math.round((Date.now() - connection.since) / 1000) : 0
	);
	// Only mentioned when it lasts long enough to worry about.
	let duur = $derived(gone >= 60 ? t('connection.minutes', { n: Math.floor(gone / 60) }) : null);

	/**
	 * This card and the machine alarm form one column, and this is its measure.
	 *
	 * They hung off the same anchor and lay over each other — not fully, which is
	 * worse: the alarm started halfway down this card and cut two sentences off in
	 * the middle ("What you draw or set now d…"). A truncated sentence looks like a
	 * whole one, so you do not know you are missing something, and you act on half
	 * an instruction.
	 *
	 * Two fixed elements can only stack if they know each other's height. No wrapper
	 * element (that would touch `+page.svelte`, where this card and the alarm are
	 * rendered in two different places), so this card passes its height on in a
	 * variable on `:root` and the alarm works out its own `top` with it. Zero as soon
	 * as this card is gone.
	 *
	 * The order is not arbitrary: without our server every report about the machine
	 * is old news by definition — the engine that reported it is the same one that
	 * has stopped answering. So this card belongs on top.
	 */
	let card = $state<HTMLElement | null>(null);
	$effect(() => {
		const root = document.documentElement;
		if (!card) {
			root.style.removeProperty('--notice-column');
			return;
		}
		// Height plus the gap in one number: then the alarm has nothing to add to it
		// and no half a variable can be left behind.
		const measure = () =>
			root.style.setProperty(
				'--notice-column',
				`calc(${Math.ceil(card!.offsetHeight)}px + var(--space-2))`
			);
		measure();
		// The height changes with the text ("3 min already") and with the window width.
		const watch = new ResizeObserver(measure);
		watch.observe(card);
		return () => {
			watch.disconnect();
			root.style.removeProperty('--notice-column');
		};
	});
</script>

{#if !connection.online && late}
	<div class="dropped" role="alert" bind:this={card}>
		<span class="dot" aria-hidden="true"></span>
		<div class="text">
			<strong>{t('connection.lost')}</strong>
			<p>
				{duur ? t('connection.lost.bodyFor', { duration: duur }) : t('connection.lost.body')}
			</p>
			{#if burns}
				<p class="urgent">{t('connection.stillBurning')}</p>
			{/if}
		</div>
		<div class="action">
			<button onclick={() => connection.retryNow()}>{t('connection.retryNow')}</button>
			<span class="klok">
				{#if connection.inSeconds > 0}
					{t('connection.autoIn', { seconds: connection.inSeconds })}
				{:else}
					{t('connection.connecting')}
				{/if}
			</span>
		</div>
	</div>
{/if}

<style>
	.dropped {
		position: fixed;
		/* Below the top bar, against the tool rail: in the direction your eye travels,
		   but above the canvas and not above the right-hand panel. Centred, on a
		   tablet it lay straight across the panel tabs — and that is exactly where
		   what you wanted to operate at that moment sits. */
		top: calc(var(--topbar-height, 46px) + var(--space-3));
		left: calc(var(--rail-width) + var(--space-3));
		z-index: 60;
		display: flex;
		align-items: flex-start;
		gap: var(--space-3);
		/* The same width as the alarm below it, because together they are one column.
		   It was 560 against the alarm's 720, and then two cards with the same left
		   edge read as a mistake instead of as a stack. */
		width: min(620px, calc(100vw - var(--rail-width) - 2 * var(--space-3)));
		padding: var(--space-3) var(--space-4);
		border: 1px solid var(--danger-solid);
		border-radius: var(--radius-card);
		background: var(--surface-1);
		box-shadow: var(--lift-2);
		font-size: var(--text-xs);
		color: var(--text-1);
	}
	.dot {
		flex: none;
		width: 8px;
		height: 8px;
		margin-top: var(--space-1h);
		border-radius: var(--radius-dot);
		background: var(--danger-solid);
	}
	.text { min-width: 0; }
	strong { display: block; font-size: var(--text-sm); margin-bottom: 2px; }
	p { margin: 0; color: var(--text-2); }
	.urgent { margin-top: var(--space-2); color: var(--danger); font-weight: 500; }
	.action {
		flex: none;
		display: flex;
		flex-direction: column;
		align-items: stretch;
		gap: 4px;
	}
	.action button {
		/* 44px tall: this is exactly a button somebody with gloves on, next to a
		   machine, has to hit first time. */
		min-height: 44px;
		padding: 0 var(--space-3);
		white-space: nowrap;
		font: inherit;
		font-weight: 600;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		color: var(--text-1);
	}
	.action button:hover { background: var(--surface-2); }
	.klok {
		text-align: center;
		color: var(--text-2);
		font-variant-numeric: tabular-nums;
	}
	/*
	 * Not on the phone. That screen already says it three times under its own steam
	 * — in the header, below the bed and above the emergency stop — and a floating
	 * card on top of a fixed bottom bar 390 px wide literally lay across it. The
	 * "try again" button lives in that bottom bar itself.
	 */
	/* Tablet: the same 560 as the alarm below it — at 1024 the right-hand panel
	   starts at x≈700 and 620 px would cover the panel tabs. This measure should stay
	   equal to the one in `AlarmCard.svelte`; see the explanation there. */
	@media (min-width: 768px) and (max-width: 1199px) {
		.dropped {
			width: min(560px, calc(100vw - var(--rail-width) - 2 * var(--space-3)));
		}
	}
	@media (max-width: 767px) {
		.dropped { display: none; }
	}
</style>
