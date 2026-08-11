<script lang="ts">
	import { page } from '$app/stores';
	import Logo from '$components/Logo.svelte';

	let { children } = $props();

	// Elke stap is een eigen route, zodat de browser-terugknop werkt en een
	// verversing je niet terug naar stap 1 gooit.
	const STEPS = [
		{ path: '/setup', title: 'Machines' },
		{ path: '/setup/type', title: 'Type' },
		{ path: '/setup/naam', title: 'Naam' },
		{ path: '/setup/instellen', title: 'Instellen' },
		{ path: '/setup/klaar', title: 'Klaar' }
	];

	let current = $derived(STEPS.findIndex((s) => s.path === $page.url.pathname));
</script>

<header class="topbar">
	<div class="brand"><Logo />OpenKerf</div>
	<span class="crumb">Machine instellen</span>
	<div class="spacer"></div>
	<a class="btn" href="/">Terug<span class="lang"> naar werkgebied</span></a>
</header>

<main>
	<nav class="steps" aria-label="Voortgang">
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

	{@render children()}
</main>

<style>
	/* Op 390 pixels breekt deze kop over drie regels en valt de knop van het
	   scherm. Dan maar korter: de bestemming staat er nog. */
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
	.steps ol {
		display: flex;
		gap: var(--space-2);
		list-style: none;
		margin: 0 0 var(--space-6);
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
	.steps li.done a {
		color: var(--accent);
	}
	.steps li.done a:hover {
		background: var(--line);
	}
	.steps li.current span {
		background: var(--accent);
		color: var(--accent-ink);
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
	:global(.setup.narrow) {
		max-width: 460px;
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
