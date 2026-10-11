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
	<section class="card welcome">
		<div class="mark"><Logo /><span>OpenKerf</span></div>

		<h1>{t('welcome.title')}</h1>
		<p class="lead">{t('welcome.lead')}</p>

		<ol class="vraagt">
			{#each VRAAGT as step, index (step.head)}
				<li>
					<span class="number mono">{index + 1}</span>
					<span class="text">
						<strong>{step.head}</strong>
						<span class="help">{step.hint}</span>
					</span>
				</li>
			{/each}
		</ol>

		<a class="btn primary big go" href="/setup/kind">{t('setup.crumb')}</a>

		<!-- The arrows inherit the text colour of the line. They used to be on --line
		     and got 1.41 that way: practically invisible, so
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
			<button type="button" class="link" onclick={onrondkijken}
				>{t('welcome.lookAround')}</button
			>
			<span class="help">{t('welcome.lookAround.body')}</span>
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
	/* The shared card, given room: it is the whole screen's one question. The dashed
	   accent line that ran along its top edge is gone — the kerf line means the laser is
	   working, and the accent means an action; on a welcome card it was neither. */
	.welcome {
		width: 100%;
		max-width: 520px;
		box-shadow: var(--lift-2);
		padding: var(--space-6);
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
	/* A sequence number, not a choice: a raised grey disc and ink figures, not the
	   accent tint that means "chosen". */
	.number {
		flex: none;
		width: 22px;
		height: 22px;
		display: grid;
		place-items: center;
		border-radius: var(--radius-dot);
		background: var(--surface-2);
		color: var(--text-1);
		font-size: var(--text-xs);
	}
	.text {
		display: grid;
		gap: 2px;
		min-width: 0;
	}
	/* The shared primary at its big size, across the card. */
	.go {
		display: flex;
		width: 100%;
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
		gap: var(--space-1);
	}
	.uitweg .link {
		justify-self: start;
	}
</style>
