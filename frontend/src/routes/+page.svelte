<script lang="ts">
	import { onMount } from 'svelte';
	import { replaceState } from '$app/navigation';
	import { page } from '$app/stores';
	import { machineState } from '$lib/api';
	import { Controller } from '$lib/control.svelte';
	import { DesignStore, isDesignSignal } from '$lib/design.svelte';
	import { StatusConnection } from '$lib/status.svelte';
	import Canvas from '$components/Canvas.svelte';
	import DesignPanel from '$components/DesignPanel.svelte';
	import JobPanel from '$components/JobPanel.svelte';
	import StatusBar from '$components/StatusBar.svelte';
	import ToolRail from '$components/ToolRail.svelte';
	import TopBar from '$components/TopBar.svelte';

	const status = new StatusConnection();
	const control = new Controller();
	const design = new DesignStore();
	// De tab staat in de URL, zodat de terugknop en een bladwijzer werken.
	let tab = $derived<'design' | 'job'>($page.url.searchParams.get('tab') === 'design' ? 'design' : 'job');

	function selectTab(next: 'design' | 'job') {
		const url = new URL($page.url);
		url.searchParams.set('tab', next);
		replaceState(url, {});
	}
	let preflight = $state(false);

	let device = $derived(status.device);
	// Niet `state` noemen: `$state` zou dan als store-referentie gelezen worden.
	let machine = $derived(machineState(device, status.connected));

	onMount(() => {
		status.connect();
		control.refreshCapabilities();
		design.load();
		// De beschikbare acties hangen af van het actieve device, dus opnieuw
		// ophalen zodra de gebruiker in MeerK40t van machine wisselt.
		const poll = setInterval(() => control.refreshCapabilities(), 10_000);
		return () => {
			clearInterval(poll);
			status.close();
		};
	});

	// De engine seint dat de elementenboom wijzigde; dan pas opnieuw ophalen.
	// De store slikt bursts zelf, dus een signaal per wijziging is prima.
	$effect(() => {
		const latest = status.events[0];
		if (latest && isDesignSignal(latest.code)) design.load();
	});

	function requestStart() {
		selectTab('job');
		preflight = true;
	}

	function toggleTheme() {
		const root = document.documentElement;
		root.dataset.theme = root.dataset.theme === 'light' ? 'dark' : 'light';
	}
</script>

<TopBar
	{device}
	state={machine}
	canStart={(control.capabilities?.actions.start ?? false) && !control.needsToken}
	canStop={(control.capabilities?.actions.stop ?? false) && !control.needsToken}
	onStart={requestStart}
	onStop={() => control.stop()}
	onToggleTheme={toggleTheme}
/>

<div class="main">
	<ToolRail />
	<Canvas {device} {design} />

	<aside class="panel" aria-label="Eigenschappen">
		<div class="tabs" role="tablist">
			<button
				class="tab"
				role="tab"
				aria-selected={tab === 'design'}
				onclick={() => selectTab('design')}
			>
				Bewerken
				{#if tab === 'design'}
					<svg aria-hidden="true"
						><line x1="0" y1="1" x2="100%" y2="1" stroke="var(--accent)" stroke-width="2" stroke-dasharray="6 4" class="kerf-anim" /></svg
					>
				{/if}
			</button>
			<button class="tab" role="tab" aria-selected={tab === 'job'} onclick={() => selectTab('job')}>
				Job
				{#if tab === 'job'}
					<svg aria-hidden="true"
						><line x1="0" y1="1" x2="100%" y2="1" stroke="var(--accent)" stroke-width="2" stroke-dasharray="6 4" class="kerf-anim" /></svg
					>
				{/if}
			</button>
		</div>
		<div class="panel-scroll">
			{#if tab === 'design'}
				<DesignPanel {design} />
			{:else}
				<JobPanel
					{device}
					events={status.events}
					{control}
					activeJob={status.activeJob}
					bind:preflight
				/>
			{/if}
		</div>
	</aside>
</div>

<StatusBar {device} state={machine} job={status.activeJob} connected={status.connected} />

<style>
	.main {
		flex: 1;
		display: flex;
		min-height: 0;
	}
	.panel {
		width: 280px;
		flex: none;
		background: var(--surface-1);
		border-left: 1px solid var(--line);
		display: flex;
		flex-direction: column;
		min-height: 0;
	}
	.tabs {
		display: flex;
		flex: none;
		border-bottom: 1px solid var(--line);
	}
	.tab {
		flex: 1;
		padding: 10px 0 8px;
		font-weight: 500;
		color: var(--text-2);
		position: relative;
	}
	.tab[aria-selected='true'] {
		color: var(--text-1);
	}
	.tab svg {
		position: absolute;
		left: var(--space-4);
		bottom: -1px;
		width: calc(100% - var(--space-8));
		height: 2px;
	}
	.panel-scroll {
		flex: 1;
		overflow-y: auto;
		padding: var(--space-4);
	}

	/* Op tablet/telefoon is de app primair monitor + foto-invoer: het paneel
	   klapt onder het canvas, de rail verdwijnt. */
	@media (max-width: 720px) {
		.main {
			flex-direction: column;
		}
		.panel {
			width: 100%;
			border-left: none;
			border-top: 1px solid var(--line);
			max-height: 45vh;
		}
	}
</style>
