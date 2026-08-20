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
		{ path: '/setup/soort', title: t('setup.step.kind') },
		{ path: '/setup/type', title: t('setup.step.model') },
		{ path: '/setup/naam', title: t('setup.step.name') },
		{ path: '/setup/instellen', title: t('setup.step.settings') },
		{ path: '/setup/klaar', title: t('setup.step.done') }
	];

	let current = $derived(STEPS.findIndex((s) => s.path === $page.url.pathname));

	// Steps with little on screen get a narrower card. Otherwise a 460px column sits
	// on the left of a 900px card with the right half empty — which reads as a page
	// something has fallen off.
	const SMAL = ['/setup/naam', '/setup/klaar'];
	let smal = $derived(SMAL.includes($page.url.pathname));
</script>

<header class="topbar">
	<div class="brand"><Logo />OpenKerf</div>
	<span class="crumb">{t('setup.crumb')}</span>
	<div class="spacer"></div>
	<a class="btn" href="/">{t('common.back')}<span class="lang">{t('setup.backToWorkArea')}</span></a>
</header>

<main class:smal>
	{#if current >= 0}
	<nav class="steps" aria-label={t('setup.progress')}>
		<!-- Five pills without a count do not say how far you are; on a phone they
		     wrap as well, and then the highlighted pill is the only foothold. The
		     sentence before it always works. -->
		<p class="teller">{t('setup.stepOf', { n: current + 1, total: STEPS.length })}</p>
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

	<!-- De stappen stonden als kale tekst in een leeg venster: op 1440 bij 900
	     was tweederde van het scherm niets. Een kaart maakt er een scherm van
	     in plaats van een document. -->
	<div class="blad">
		{@render children()}
	</div>
</main>

<style>
	/* Op 390 pixels breekt deze kop over drie regels en valt de knop van het
	   scherm. Dan maar korter: de bestemming staat er nog. */
	/* De ruimte tussen "Terug" en de rest komt van een marge: in een flexbox
	   valt een geschreven spatie tussen twee items weg. */
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
	main.smal {
		max-width: 560px;
	}
	.blad {
		background: var(--surface-1);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		box-shadow: var(--lift-1);
		padding: var(--space-6);
	}
	@media (max-width: 560px) {
		.blad {
			padding: var(--space-4);
		}
	}
	.teller {
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
	/* Een afgeronde stap staat op --surface-2, en daar blijft --accent op 4,33
	   steken; --accent-text is dezelfde kleur één tint dieper en haalt 5,09.
	   Ook bij hover, want die legt --line eronder. */
	.steps li.done a {
		color: var(--accent-text);
	}
	/* De hover zette --line als vulling, en dat is een randkleur, geen vlak: in
	   licht zakt de pil daarmee naar 4,14 en in donker naar 3,42 — allebei
	   onder de grens, en juist op het moment dat je de stap wílt aanklikken.
	   Het vlak blijft nu staan; de aanwijzing is een streep, en die kan geen
	   contrast kosten. */
	.steps li.done a:hover {
		text-decoration: underline;
		text-underline-offset: 2px;
	}
	.steps li.current span {
		background: var(--accent);
		color: var(--accent-ink);
	}
	/* Een afgeronde stap is een link terug, dus een raakdoel. Gemeten op 27px
	   hoog op tablet en telefoon; het design system eist er 44. */
	@media (max-width: 1199px) {
		.steps li span,
		.steps li a {
			min-height: 44px;
			display: flex;
			align-items: center;
			padding: 4px 12px;
		}
	}
	/* Gedeeld door alle stappen — die zijn losse routes, dus scoped styles
	   per pagina zouden hetzelfde vijf keer herhalen. */
	:global(.setup h1) {
		font-size: var(--text-lg);
		font-weight: 600;
		letter-spacing: -0.01em;
		margin: 0 0 var(--space-2);
	}
	:global(.setup .muted) {
		color: var(--text-2);
	}
	/* De breedte zit nu in de kaart (main.smal), niet in de inhoud: anders
	   stond een kolom van 460px links in een kaart van 900. */
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
