<script lang="ts">
	/**
	 * The first screen of a fresh installation.
	 *
	 * One question, one answer: there is no machine yet, and this is the button.
	 * Beside it stands what the wizard asks and what happens afterwards, because most
	 * "what now?" moments arise from not knowing how long something takes and where
	 * it goes.
	 */
	import Logo from '$components/Logo.svelte';
	import { t } from '$lib/i18n/index.svelte';

	let { onrondkijken }: { onrondkijken: () => void } = $props();

	// This list is the same series as the step bar in the wizard, and counts as far.
	// It used to say "3 questions" here against "Step 1 of 5" further on, and then
	// you immediately no longer know which is which.
	const VRAAGT = [
		{ head: t('setup.step.kind'), hint: t('welcome.asks.kind') },
		{ head: t('setup.step.model'), hint: t('welcome.asks.model') },
		{ head: t('setup.step.name'), hint: t('welcome.asks.name') },
		{ head: t('welcome.asks.workarea'), hint: t('welcome.asks.workarea.body') }
	];

	const DAARNA = [t('welcome.after.design'), t('job.frame'), t('welcome.after.cut')];
</script>

<main>
	<section class="card">
		<div class="mark"><Logo /><span>OpenKerf</span></div>

		<h1>{t('welcome.title')}</h1>
		<p class="lead">{t('welcome.lead')}</p>

		<ol class="vraagt">
			{#each VRAAGT as step, index (step.head)}
				<li>
					<span class="number mono">{index + 1}</span>
					<span class="text">
						<strong>{step.head}</strong>
						<span class="muted">{step.hint}</span>
					</span>
				</li>
			{/each}
		</ol>

		<a class="button primary" href="/setup/kind">{t('setup.crumb')}</a>

		<!-- The arrows inherit the text colour of the line. They used to be on --line
		     and got 1.41 in light and 1.62 in dark that way: practically invisible, so
		     this read as three loose words instead of as the sequence it is. --line is
		     tuned for borders *against* a surface, not for something to be read. -->
		<p class="daarna">
			{t('welcome.after')}
			{#each DAARNA as step, index (step)}<span class="step">{step}</span>{#if index < DAARNA.length - 1}<span
					aria-hidden="true">→</span
				>{/if}{/each}
		</p>

		<hr />

		<p class="uitweg">
			<button type="button" class="tekstknop" onclick={onrondkijken}
				>{t('welcome.lookAround')}</button
			>
			<span class="muted">{t('welcome.lookAround.body')}</span>
		</p>
	</section>
</main>

<style>
	main {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		display: grid;
		place-items: center;
		padding: var(--space-6) var(--space-4);
		background: var(--surface-0);
	}
	.card {
		position: relative;
		width: 100%;
		max-width: 520px;
		background: var(--surface-1);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		box-shadow: var(--lift-2);
		padding: var(--space-6);
	}
	/* The kerf line as a cut across the top edge of the card. Static: in DESIGN-SYSTEM the
	   animated variant is reserved for selection, job progress and the active tab, and a
	   welcome screen should be quiet. */
	.card::before {
		content: '';
		position: absolute;
		left: var(--space-6);
		right: var(--space-6);
		/* On the edge itself, not above it: at -1px the line floated free of the card and
		   in the dark theme read as a stripe that was there by accident. */
		top: 0;
		height: 1px;
		background: repeating-linear-gradient(
			to right,
			color-mix(in srgb, var(--accent) 80%, transparent) 0 6px,
			transparent 6px 10px
		);
	}
	.mark {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-weight: 600;
		font-size: var(--text-md);
		margin-bottom: var(--space-6);
	}
	h1 {
		font-size: var(--text-lg);
		font-weight: 600;
		letter-spacing: -0.01em;
		margin: 0 0 var(--space-2);
	}
	.lead {
		margin: 0 0 var(--space-4);
		color: var(--text-2);
	}
	.vraagt {
		list-style: none;
		margin: 0 0 var(--space-6);
		padding: 0;
		display: grid;
		gap: var(--space-3);
	}
	.vraagt li {
		display: flex;
		align-items: flex-start;
		gap: var(--space-3);
	}
	.number {
		flex: none;
		width: 22px;
		height: 22px;
		display: grid;
		place-items: center;
		border-radius: var(--radius-dot);
		background: color-mix(in srgb, var(--accent) 14%, transparent);
		/* See the badge on /setup: accent on an accent tint does not make AA, and an 11px
		   sequence number is ordinary text. The tint stays, the figures do not. */
		color: var(--text-1);
		font-size: var(--text-xs);
	}
	.text {
		display: grid;
		gap: 2px;
		min-width: 0;
	}
	.text .muted {
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.button {
		display: block;
		text-align: center;
		padding: 12px var(--space-4);
		border-radius: var(--radius-field);
		border: 1px solid var(--accent);
		background: var(--accent);
		color: var(--accent-ink);
		font-weight: 500;
		text-decoration: none;
		transition: filter var(--transition);
	}
	/* No colour change on hover: a generic .btn:hover made the main button white on light
	   grey elsewhere (X1 in FEATURE-GAPS). Darker is enough. */
	.button.primary:hover {
		filter: brightness(0.92);
	}
	.daarna {
		margin: var(--space-3) 0 0;
		font-size: var(--text-xs);
		color: var(--text-2);
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-1h);
	}
	hr {
		border: 0;
		border-top: 1px solid var(--line);
		margin: var(--space-6) 0 var(--space-4);
	}
	.uitweg {
		margin: 0;
		display: grid;
		gap: 4px;
	}
	.uitweg .muted {
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.tekstknop {
		justify-self: start;
		font: inherit;
		padding: 0;
		border: 0;
		background: none;
		color: var(--accent);
		text-decoration: underline;
		text-underline-offset: 3px;
		cursor: pointer;
	}
	/* The type scale already shifts along in tokens.css; here only the touch targets,
	   because 44px suits a glove and 40 does not. */
	@media (max-width: 1199px) {
		.button,
		.tekstknop {
			min-height: 44px;
		}
		.tekstknop {
			display: inline-flex;
			align-items: center;
		}
	}
</style>
