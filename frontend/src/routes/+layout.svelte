<script lang="ts">
	import '$lib/tokens.css';
	import { page } from '$app/stores';
	import Welcome from '$components/Welcome.svelte';
	import { i18n, t } from '$lib/i18n/index.svelte';

	let { children } = $props();

	/**
	 * The document's language follows the interface.
	 *
	 * `app.html` ships `lang="en"` because English is the source language and the
	 * static build has no idea who will open it. The moment the client knows
	 * better — a stored choice, or the browser's preference — this puts it right.
	 * It matters: screen readers pick their voice from this attribute, and the
	 * browser hyphenates by it. A page claiming English while showing Dutch is
	 * read out as gibberish.
	 */
	$effect(() => {
		document.documentElement.lang = i18n.language;
	});

	/**
	 * The cold start has a screen of its own.
	 *
	 * MeerK40t boots with an invented default device, so that the kernel always has
	 * something to talk to. Without the gate below, OpenKerf opened on a work area that
	 * reported "lihuiyu-device — Ready — Connected to the laser" to somebody who had never
	 * set up a machine, and there was no route to /setup anywhere. Anybody who does not
	 * type the wizard into the address bar does not find it. Hence: no configured machine,
	 * then this screen first.
	 *
	 * The gate lives in the root layout and not on the work area page, because it covers
	 * *all* routes except the wizard itself.
	 */
	type Machine = { path: string; label: string; configured?: boolean };

	let stand = $state<'onbekend' | 'nodig' | 'klaar'>('onbekend');
	// Looking around is a choice for this session, not for good: starting up next time
	// should begin at the question again.
	let rondkijken = $state(false);

	let inWizard = $derived($page.url.pathname.startsWith('/setup'));

	/**
	 * The wizard changes the answer, so ask again after the wizard.
	 *
	 * This was the bug Jelle found: anybody starting on the work area gets `stand =
	 * 'nodig'` here, goes into the wizard, creates their machine and clicks "To the work
	 * area" — and lands on the welcome gate again, because that `stand` from before the
	 * wizard was still there. Only a manual refresh helped, and that is precisely the
	 * action this gate is supposed to save.
	 *
	 * Not a `$state`: this flag must not set the effect going again by itself. It only
	 * changes along with the route, and the effect already hangs off that through
	 * `inWizard`.
	 */
	let opnieuwVragen = false;

	$effect(() => {
		if (inWizard) {
			// Whatever happens here — creating, deleting, renaming — on return the answer
			// from a moment ago is worth nothing.
			opnieuwVragen = true;
			return;
		}
		if (stand !== 'onbekend' && !opnieuwVragen) return;
		opnieuwVragen = false;
		(async () => {
			try {
				const response = await fetch('/api/machines');
				if (!response.ok) return (stand = 'klaar');
				const machines: Machine[] = await response.json();
				// An older server does not know `configured`. Then better to let everybody
				// through than to strand them on a welcome screen.
				const kent = machines.some((m) => 'configured' in m);
				stand = kent && !machines.some((m) => m.configured) ? 'nodig' : 'klaar';
			} catch {
				stand = 'klaar';
			}
		})();
	});
</script>

<!-- Since v3.3 the fonts come from the build itself (@font-face in tokens.css, six woff2
     files totalling 128 KB). The link to fonts.googleapis.com that used to be here added
     nothing to that and was the app's *only* external request; without a network it
     produced ERR_FAILED in the console. -->

{#if inWizard || rondkijken || stand === 'klaar'}
	{@render children()}
{:else if stand === 'nodig'}
	<Welcome onrondkijken={() => (rondkijken = true)} />
{:else}
	<!-- As long as `stand` is unknown we do not draw the work area: that would flash up
	     with the message that the laser is ready. But an entirely blank page cannot be
	     told apart from a broken screen, and on a slow server "one moment" took
	     noticeably longer than a moment. So this line only appears after 400 ms: if the
	     server is fast you never see it; if it is slow, it says what we are waiting
	     for. -->
	<p class="wachten" role="status">{t('layout.lookingForMachine')}</p>
{/if}

<style>
	:global(body) {
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}
	.wachten {
		flex: 1;
		display: grid;
		place-items: center;
		margin: 0;
		color: var(--text-2);
		background: var(--surface-0);
		/* Delayed on screen: a fast server should not flash text up here, a slow one has
		   to account for itself. */
		opacity: 0;
		/* Duration and timing written out separately: --transition is "150ms ease-out",
		   so in an animation shorthand it produces a second timing function and the whole
		   rule is dropped as invalid. Measured: opacity stayed 0. */
		animation: opdoemen 150ms ease-out 400ms forwards;
	}
	@keyframes opdoemen {
		to {
			opacity: 1;
		}
	}
	/* Anybody who switches motion off gets the line at once: it is a message, not
	   decoration, and must not disappear entirely. */
	@media (prefers-reduced-motion: reduce) {
		.wachten {
			opacity: 1;
			animation: none;
		}
	}
</style>
