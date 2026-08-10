<script lang="ts">
	import { onMount } from 'svelte';
	import { replaceState } from '$app/navigation';
	import { page } from '$app/stores';
	import { machineState } from '$lib/api';
	import { Controller } from '$lib/control.svelte';
	import { DesignStore, isDesignSignal } from '$lib/design.svelte';
	import { EditController } from '$lib/edits.svelte';
	import type { Tool } from '$components/ToolRail.svelte';
	import { LibraryStore } from '$lib/library.svelte';
	import { StatusConnection } from '$lib/status.svelte';
	import Canvas from '$components/Canvas.svelte';
	import DesignPanel from '$components/DesignPanel.svelte';
	import JobPanel from '$components/JobPanel.svelte';
	import StatusBar from '$components/StatusBar.svelte';
	import ToolRail from '$components/ToolRail.svelte';
	import Dialog from '$components/Dialog.svelte';
	import MaterialLibrary from '$components/MaterialLibrary.svelte';
	import TestGrid from '$components/TestGrid.svelte';
	import TestGridResult from '$components/TestGridResult.svelte';
	import TextDialog from '$components/TextDialog.svelte';
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
	let tool = $state<Tool>('select');
	let libraryOpen = $state(false);
	let pendingFile = $state<File | null>(null);
	let textOpen = $state(false);
	let textAt = $state<{ x: number; y: number } | null>(null);
	let editingText = $state<string | null>(null);
	let estimate = $state<number | null>(null);
	let gridOpen = $state(false);

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

	/**
	 * Openen vervangt, het voegt niet toe.
	 *
	 * De engine laadt een bestand bovenop wat er al staat. Dat is soms handig
	 * maar het is niet wat "openen" betekent, dus maken we eerst leeg — en
	 * vragen we het eerst als daarmee onopgeslagen werk zou verdwijnen.
	 */
	async function openFile(file: File) {
		if (!canEdit) return;
		if (!design.isEmpty && design.dirty) {
			pendingFile = file;
			return;
		}
		await replaceWith(file);
	}

	async function replaceWith(file: File) {
		if (!design.isEmpty) {
			if (!(await edits.clear()).ok) return;
		}
		if (await control.load(file)) {
			design.select(null);
			await design.load();
		}
	}

	async function saveThenOpen() {
		const file = pendingFile;
		pendingFile = null;
		if (!file) return;
		// Downloaden telt als opslaan: de API markeert het ontwerp schoon.
		window.location.href = '/api/design/export.svg';
		setTimeout(() => replaceWith(file), 800);
	}

	async function draw(shape: Record<string, unknown>) {
		if (!canEdit) return;
		const result = await edits.draw(shape);
		if (result.ok) {
			await design.load();
			// Terug naar selecteren: één vorm per klik is voorspelbaarder dan
			// per ongeluk een rij vormen achterlaten.
			tool = 'select';
		}
	}

	async function removeSelection() {
		if (!hasSelection || !canEdit) return;
		if (await edits.remove(design.selectedIds)) {
			design.select(null);
			await design.load();
		}
	}

	async function duplicateSelection() {
		if (!hasSelection || !canEdit) return;
		if (await edits.duplicate(design.selectedIds)) await design.load();
	}

	async function arrange(action: string) {
		if (!canEdit || !hasSelection) return;
		const ids = design.selectedIds;
		const result =
			action === 'group'
				? await edits.group(ids)
				: action === 'ungroup'
					? await edits.ungroup(ids)
					: action === 'mirror-h'
						? await edits.mirror(ids, 'horizontal')
						: action === 'mirror-v'
							? await edits.mirror(ids, 'vertical')
							: ['union', 'difference', 'intersection', 'xor'].includes(action)
								? await edits.boolean(ids, action)
								: await edits.align(ids, action);
		if (result.ok) {
			// Booleaans levert een nieuw pad op; de oude selectie bestaat niet meer.
			if (action === 'ungroup' || ['union', 'difference', 'intersection', 'xor'].includes(action))
				design.select(null);
			await design.load();
		}
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
		const typing = (e.target as HTMLElement | null)?.closest('input, textarea, select');
		if (typing) return;
		if ((e.key === 'Delete' || e.key === 'Backspace') && hasSelection && canEdit) {
			e.preventDefault();
			removeSelection();
			return;
		}
		if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'd' && hasSelection && canEdit) {
			e.preventDefault();
			duplicateSelection();
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
	onOpenFile={openFile}
	onToggleTheme={toggleTheme}
/>

<div class="main">
	<ToolRail
		bind:tool
		{canEdit}
		onOpenGrid={() => (gridOpen = true)}
		onOpenLibrary={() => (libraryOpen = true)}
	/>
	<Canvas
		{device}
		{design}
		{edits}
		{canEdit}
		{tool}
		onEdited={() => design.load()}
		onDrawn={draw}
		onTextAt={(at) => {
			textAt = at;
			textOpen = true;
		}}
	/>

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
					onHistory={history}
					onRotate={rotate}
					onAssign={assign}
					onLayerChange={() => design.load()}
					onArrange={arrange}
					onEditText={(id) => {
						editingText = id;
						textOpen = true;
					}}
				/>
			{:else}
				<JobPanel
					{device}
					events={status.events}
					{control}
					activeJob={status.activeJob}
					bind:preflight
					onJog={async (dx, dy) => {
						await edits.jog(dx, dy);
					}}
					onHome={async () => {
						await edits.home();
					}}
					onUnlock={async () => {
						await edits.unlock();
					}}
				/>
			{/if}
		</div>
	</aside>
</div>

<StatusBar {device} state={machine} job={status.activeJob} connected={status.connected} />

<!-- Bibliotheken en gereedschappen als eigen venster: in 280px kun je niet
     zoeken en vergelijken. Zie DESIGN-SYSTEM.md. -->
<TextDialog
	bind:open={textOpen}
	initial={editingText ? (design.elements.find((e) => e.id === editingText)?.text ?? null) : null}
	onConfirm={async (options) => {
		if (editingText) {
			// Tekst is een pad, maar de engine bewaart de bron en rendert opnieuw.
			if ((await edits.updateText(editingText, options)).ok) await design.load();
			editingText = null;
		} else if (textAt) {
			draw({ type: 'text', x_mm: textAt.x, y_mm: textAt.y, ...options });
		}
		textAt = null;
	}}
/>

<!-- Openen zou werk weggooien: eerst vragen. -->
<Dialog
	title="Niet-opgeslagen wijzigingen"
	open={pendingFile !== null}
	width="420px"
>
	<p class="ask">
		Dit ontwerp is gewijzigd sinds de laatste keer opslaan. Openen vervangt wat er nu staat.
	</p>
	<div class="ask-actions">
		<button class="btn" onclick={() => (pendingFile = null)}>Annuleren</button>
		<button
			class="btn"
			onclick={() => {
				const file = pendingFile;
				pendingFile = null;
				if (file) replaceWith(file);
			}}
		>Zonder opslaan openen</button>
		<button class="btn primary" onclick={saveThenOpen}>Opslaan en openen</button>
	</div>
</Dialog>

<Dialog title="Materiaalbibliotheek" bind:open={libraryOpen} width="640px">
	<MaterialLibrary
		{library}
		operations={design.operations}
		{canEdit}
		onApplied={() => design.load()}
	/>
</Dialog>

<Dialog title="Testraster" bind:open={gridOpen} width="640px">
	<TestGrid {library} {canEdit} onGenerated={() => design.load()} />
	<TestGridResult {library} {canEdit} />
</Dialog>

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
	:global(.ask) { margin: 0 0 var(--space-4); }
	:global(.ask-actions) {
		display: flex;
		gap: var(--space-2);
		justify-content: flex-end;
		flex-wrap: wrap;
	}
	:global(.ask-actions .btn) {
		padding: 8px 14px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		font-weight: 500;
	}
	:global(.ask-actions .btn:hover) { background: var(--surface-2); }
	:global(.ask-actions .btn.primary) {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
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
