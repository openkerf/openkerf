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
	<a class="btn" href="/">{t('common.back')}<span class="lang">{t('setup.backToWorkArea')}</span></a>
</header>

<main class:narrow>
	{#if current >= 0}
	<nav class="steps" aria-label={t('setup.progress')}>
		<!-- Five pills without a count do not say how far you are; on a phone they
		     wrap as well, and then the highlighted pill is the only foothold. The
		     sentence before it always works. -->
		<p class="stepper">{t('setup.stepOf', { n: current + 1, total: STEPS.length })}</p>
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
	     screen was nothing. A card makes it a screen rather than a document. -->
	<div class="sheetcard">
		{@render children()}
	</div>
</main>

<style>
	/* At 390 pixels this heading breaks over three lines and the button falls off the
	   screen. Shorter, then: the destination is still there. */
	/* The space between "Back" and the rest comes from a margin: in a flexbox a written
	   space between two items disappears. */
	.lang { margin-left: 0.3em; }
	@media (max-width: 560px) {
		.crumb { display: none; }
		.lang { display: none; }
	}

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
		background: var(--surface-1);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		box-shadow: var(--lift-1);
		padding: var(--space-6);
	}
	@media (max-width: 560px) {
		.sheetcard {
			padding: var(--space-4);
		}
	}
	.stepper {
		margin: 0 0 var(--space-2);
		font-size: var(--text-xs);
		color: var(--text-2);
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
	.steps li span,
	.steps li a {
		display: block;
		padding: 4px 8px;
		border-radius: var(--radius-dot);
		background: var(--surface-2);
		color: var(--text-2);
		text-decoration: none;
	}
	/* A completed step sits on --surface-2, and there --accent stays at 4.33
	   short; --accent-text is the same colour one shade deeper and reaches 5.09. On hover
	   as well, because that lays --line underneath. */
	.steps li.done a {
		color: var(--accent-text);
	}
	/* The hover set --line as the fill, and that is a border colour, not a surface: in
	   light the pill drops to 4.14 with it and in dark to 3.42 — both below the bound, and
	   precisely at the moment you *want* to click the step. The surface now stays; the
	   indication is a stripe, and that cannot cost contrast. */
	.steps li.done a:hover {
		text-decoration: underline;
		text-underline-offset: 2px;
	}
	.steps li.current span {
		background: var(--accent);
		color: var(--accent-ink);
	}
	/* A completed step is a link back, so a touch target. Measured at 27px tall on tablet
	   and phone; the design system demands 44. */
	@media (max-width: 1199px) {
		.steps li span,
		.steps li a {
			min-height: 44px;
			display: flex;
			align-items: center;
			padding: 4px 12px;
		}
	}
	/* Shared by all the steps — those are separate routes, so scoped styles per page
	   would repeat the same thing five times. */
	:global(.setup h1) {
		font-size: var(--text-lg);
		font-weight: 600;
		letter-spacing: -0.01em;
		margin: 0 0 var(--space-2);
	}
	:global(.setup .muted) {
		color: var(--text-2);
	}
	/* The width now lives on the card (main.narrow), not in the content: otherwise a 460px
	   column sat on the left of a 900 card. */
	:global(.setup.narrow) {
		max-width: none;
	}
	:global(.setup .actions) {
		display: flex;
		gap: var(--space-2);
		margin-top: var(--space-6);
	}
	:global(.setup .error) {
		padding: var(--space-3);
		border-radius: var(--radius-field);
		background: color-mix(in srgb, var(--danger) 14%, transparent);
		margin: 0 0 var(--space-4);
	}
	.btn,
	:global(.setup .btn) {
		display: inline-flex;
		align-items: center;
		padding: 8px 16px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		font-weight: 500;
		text-decoration: none;
		color: inherit;
		transition: background var(--transition);
	}
	.btn:hover,
	:global(.setup .btn:hover:not(:disabled)) {
		background: var(--surface-2);
	}
	:global(.setup .btn:disabled) {
		opacity: 0.45;
		cursor: not-allowed;
	}
	:global(.setup .btn.primary) {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
	}
	:global(.setup .btn.subtle) {
		color: var(--text-2);
	}
</style>
