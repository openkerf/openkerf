<script lang="ts">
	import { onMount } from 'svelte';
	import { replaceState } from '$app/navigation';
	import { page } from '$app/stores';
	import { machineState } from '$lib/api';
	import { Controller } from '$lib/control.svelte';
	import { DesignStore, isDesignSignal } from '$lib/design.svelte';
	import { EditController } from '$lib/edits.svelte';
	import { LibraryStore } from '$lib/library.svelte';
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
	const token = () =>
		typeof localStorage === 'undefined' ? '' : (localStorage.getItem('openkerf.token') ?? '');
	const library = new LibraryStore(token);
	const edits = new EditController(() =>
		typeof localStorage === 'undefined' ? '' : (localStorage.getItem('openkerf.token') ?? '')
	);

	let canEdit = $derived(!control.needsToken);
	let hasSelection = $derived(design.selectedIds.length > 0);

	// Undo gooit de id's van de engine weg (herstelde nodes komen terug zonder
	// id en krijgen bij hernummeren andere). Een bewaarde selectie zou daarna
	// een ánder element kunnen aanwijzen, dus die laten we los.
	async function history(action: 'undo' | 'redo') {
		const result = action === 'undo' ? await edits.undo() : await edits.redo();
		if (result.idsInvalidated) design.select(null);
		await design.load();
	}

	async function setPosition(x: number, y: number) {
		const box = design.selectedSize;
		if (!box || !hasSelection || !canEdit) return;
		await edits.move(design.selectedIds, x - box.x, y - box.y);
		await design.load();
	}

	async function setSize(width: number, height: number) {
		const box = design.selectedSize;
		if (!box || !hasSelection || !canEdit) return;
		await edits.resize(design.selectedIds, box.x, box.y, width, height);
		await design.load();
	}

	async function nudge(dx: number, dy: number) {
		if (!hasSelection || !canEdit) return;
		await edits.move(design.selectedIds, dx, dy);
		await design.load();
	}

	async function rotate(angleDeg: number) {
		if (!hasSelection || !canEdit) return;
		await edits.rotate(design.selectedIds, angleDeg);
		await design.load();
	}

	async function assign(operationId: string, assigned: boolean) {
		if (!hasSelection || !canEdit) return;
		const result = assigned
			? await edits.assign(design.selectedIds, operationId)
			: await edits.unassign(design.selectedIds, operationId);
		if (result.ok) await design.load();
	}
	// De tab staat in de URL, zodat de terugknop en een bladwijzer werken.
	// Lokale state is de bron van waarheid, de URL volgt. Andersom werkt niet:
	// replaceState maakt $page.url niet reactief, waardoor het paneel op de
	// oude tab bleef staan terwijl de URL wél meeliep.
	let tab = $state<'design' | 'job'>('job');

	function selectTab(next: 'design' | 'job') {
		tab = next;
		syncUrl();
	}

	function syncUrl() {
		const url = new URL(window.location.href);
		url.searchParams.set('tab', tab);
		if (design.selectedIds.length) url.searchParams.set('select', design.selectedIds.join(','));
		else url.searchParams.delete('select');
		replaceState(url, {});
	}

	let preflight = $state(false);

	let device = $derived(status.device);
	// Niet `state` noemen: `$state` zou dan als store-referentie gelezen worden.
	let machine = $derived(machineState(device, status.connected));

	onMount(() => {
		status.connect();
		control.refreshCapabilities();
		library.load();
		if ($page.url.searchParams.get('tab') === 'design') tab = 'design';
		design.load().then(() => {
			const wanted = $page.url.searchParams.get('select');
			if (wanted) {
				const ids = wanted.split(',').filter(Boolean);
				design.select(ids[0] ?? null);
				ids.slice(1).forEach((id) => design.toggle(id));
			}
		});
		// Pas ná mount koppelen: replaceState vóórdat de router klaar is breekt
		// de render. De URL volgt daarom de actie, niet een effect.
		design.onSelect = () => syncUrl();
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

<svelte:window
	onkeydown={(e) => {
		if (e.key === 'Escape') {
			design.select(null);
			return;
		}
		// Pijltjes verplaatsen 0,1 mm; met shift 1 mm (toegankelijkheidseis).
		const step = e.shiftKey ? 1 : 0.1;
		const moves: Record<string, [number, number]> = {
			ArrowLeft: [-step, 0],
			ArrowRight: [step, 0],
			ArrowUp: [0, -step],
			ArrowDown: [0, step]
		};
		const move = moves[e.key];
		if (move && hasSelection && canEdit) {
			e.preventDefault();
			nudge(move[0], move[1]);
		}
	}}
/>

<TopBar
	{device}
	state={machine}
	canStart={(control.capabilities?.actions.start ?? false) && !control.needsToken}
	canStop={(control.capabilities?.actions.stop ?? false) && !control.needsToken}
	box={design.liveBox}
	canEdit={canEdit && design.preview === null}
	onSetPosition={setPosition}
	onSetSize={setSize}
	onStart={requestStart}
	onStop={() => control.stop()}
	onToggleTheme={toggleTheme}
/>

<div class="main">
	<ToolRail />
	<Canvas {device} {design} {edits} {canEdit} onEdited={() => design.load()} />

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
				<DesignPanel
					{design}
					{edits}
					{canEdit}
					{library}
					onHistory={history}
					onRotate={rotate}
					onAssign={assign}
					onApplied={() => design.load()}
				/>
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
