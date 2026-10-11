<script lang="ts">
	import { page } from '$app/stores';
	import Logo from '$components/Logo.svelte';
	import { t } from '$lib/i18n/index.svelte';

	let { children } = $props();

	// Every step is a route of its own, so the browser's back button works and a
	// refresh does not throw you back to step 1.
	// "Machines" used to be the first step here, but that is an overview of *all*
	// machines — a destination, not a step within one machine. Two levels in one row
	// of pills reads as a mistake, and it was one.
	const STEPS = [
		{ path: '/setup/kind', title: t('setup.step.kind') },
		{ path: '/setup/type', title: t('setup.step.model') },
		{ path: '/setup/name', title: t('setup.step.name') },
		{ path: '/setup/settings', title: t('setup.step.settings') },
		{ path: '/setup/done', title: t('setup.step.done') }
	];

	let current = $derived(STEPS.findIndex((s) => s.path === $page.url.pathname));

	// Steps with little on screen get a narrower card. Otherwise a 460px column sits
	// on the left of a 900px card with the right half empty — which reads as a page
	// something has fallen off.
	const SMAL = ['/setup/name', '/setup/done'];
	let narrow = $derived(SMAL.includes($page.url.pathname));
</script>

<header class="topbar">
	<div class="brand"><Logo />OpenKerf</div>
	<span class="crumb">{t('setup.crumb')}</span>
	<div class="spacer"></div>
	<!-- One sentence, not "Back" glued to "to the work area": two halves only make a
	     sentence in languages that put the words in the same order. -->
	<a class="btn" href="/">{t('setup.backToWorkArea')}</a>
</header>

<main class:narrow>
	{#if current >= 0}
	<nav class="steps" aria-label={t('setup.progress')}>
		<!-- Five pills without a count do not say how far you are; when they wrap, the
		     highlighted pill is the only foothold. The sentence before it always works. -->
		<p class="help stepper">{t('setup.stepOf', { n: current + 1, total: STEPS.length })}</p>
		<ol>
			{#each STEPS as step, index (step.path)}
				<li class:current={index === current} class:done={current > index}>
					{#if current > index}
						<a href={step.path}>{step.title}</a>
					{:else}
						<span aria-current={index === current ? 'step' : undefined}>{step.title}</span>
					{/if}
				</li>
			{/each}
		</ol>
	</nav>
	{/if}

	<!-- The steps sat as bare text in an empty window: at 1440 by 900 two thirds of the
	     screen was nothing. A card makes it a screen rather than a document. Inside it
	     a step uses `.card.inset` for a block of its own — never a second card. -->
	<div class="card sheetcard">
		{@render children()}
	</div>
</main>

<style>
	.topbar {
		height: var(--topbar-height);
		flex: none;
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: 0 var(--space-3);
		background: var(--surface-1);
		border-bottom: 1px solid var(--line);
	}
	.brand {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-weight: 600;
		font-size: var(--text-md);
	}
	.crumb {
		color: var(--text-2);
	}
	.spacer {
		flex: 1;
	}
	main {
		flex: 1;
		overflow-y: auto;
		padding: var(--space-6);
		max-width: 900px;
		width: 100%;
		margin: 0 auto;
	}
	main.narrow {
		max-width: 560px;
	}
	.sheetcard {
		box-shadow: var(--lift-1);
		padding: var(--space-6);
	}
	.stepper {
		margin: 0 0 var(--space-2);
	}
	.steps ol {
		display: flex;
		gap: var(--space-2);
		list-style: none;
		margin: 0 0 var(--space-4);
		padding: 0;
		font-size: var(--text-xs);
		flex-wrap: wrap;
	}
	/* A completed step is a link back, so it is a touch target beside the machine. */
	.steps li span,
	.steps li a {
		display: flex;
		align-items: center;
		min-height: max(24px, var(--target-min));
		padding: var(--space-1) var(--space-3);
		border-radius: var(--radius-dot);
		background: var(--surface-2);
		color: var(--text-2);
		text-decoration: none;
	}
	/* A completed step sits on --surface-2; --accent is deep enough to reach 5.09
	   there (tokens.css, D7), so it is safe as text. */
	.steps li.done a {
		color: var(--accent);
	}
	.steps li.done a:hover {
		text-decoration: underline;
		text-underline-offset: 3px;
	}
	/* The current step is the selection, and the one pill that takes the accent. */
	.steps li.current span {
		background: var(--accent);
		color: var(--accent-ink);
	}
	/* Shared by all the steps — those are separate routes, so scoped styles per page
	   would repeat the same thing five times. Where things sit, not what they look like. */
	:global(.setup h1.title) {
		margin-bottom: var(--space-2);
	}
	:global(.setup .ask-actions) {
		margin-top: var(--space-6);
	}
</style>
