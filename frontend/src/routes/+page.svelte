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
	import Presetariat from '$components/Presetariat.svelte';
	import Generators from '$components/Generators.svelte';
	import CameraCalibration from '$components/CameraCalibration.svelte';
	import Clipart from '$components/Clipart.svelte';
	import SheetTabs from '$components/SheetTabs.svelte';
	import SheetMaterial from '$components/SheetMaterial.svelte';
	import PhoneView from '$components/PhoneView.svelte';
	import JobStart from '$components/JobStart.svelte';
	import { SheetStore } from '$lib/sheets.svelte';
	import { CameraStore } from '$lib/camera.svelte';
	import { PresetariatStore } from '$lib/presetariat.svelte';
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
	// Bijsnijden: het volgende sleepkader knipt de geselecteerde afbeelding bij.
	let cropping = $state(false);

	// Drie apparaten, drie apps (DESIGN-SYSTEM v2). Geen gekrompen desktop maar
	// een eigen gedaante: onder 768px is dit een monitor met een noodrem.
	let breedte = $state(1440);
	let telefoon = $derived(breedte < 768);
	let tablet = $derived(breedte >= 768 && breedte < 1200);
	// Onder deze breedte passen de bestandsknoppen niet meer náást de
	// machinebediening in de bovenbalk; ze verhuizen dan naar het railmenu.
	// Sinds het materiaal van het vel in de balk staat (besluit B1) ligt die
	// grens niet meer op 950 maar op de hele tabletbreedte: gemeten liep de
	// balk op 1024 anders 99px over de rand, en dan staat de startknop buiten
	// beeld. Waarín je brandt weegt zwaarder dan een bestandsknop die één tik
	// verderop in het railmenu staat.
	let smal = $derived(tablet);
	// Eén stap eerder: op een gewoon laptopscherm blijven de bestandsknoppen
	// staan, maar zonder hun woord. Gemeten grens; boven 1500px past alles.
	let krap = $derived(!telefoon && breedte < 1500);
	let paneelOpen = $state(true);
	// De muispositie leeft in het canvas maar hoort in de statusbalk: dat is
	// waar je hem zoekt.
	let muisMm = $state<{ x: number; y: number } | null>(null);
	/** Materiaal waarmee het testrastervenster opent, als je er vanuit de
	    bibliotheek naartoe springt. */
	let gridMateriaal = $state<number | null>(null);

	// Het wauw-moment. Alleen op de flank van niet-draaiend naar draaiend, en
	// daarna weer weg — anders is het decoratie in plaats van een bericht.
	let wauw = $state(false);
	let liep = false;
	function vier() {
		wauw = true;
		setTimeout(() => (wauw = false), 900);
	}
	control.onStarted = vier;
	$effect(() => {
		const nu = Boolean(status.activeJob?.running);
		// Ook als iemand anders startte (telefoon, console) hoort het te vieren.
		if (nu && !liep) vier();
		liep = nu;
	});
	// Wat er op de gekozen afbeelding aanstaat. Komt van de API, want het recept
	// leeft op de node in de engine — niet in de browser.
	let imageState = $state<Record<string, unknown> | null>(null);

	async function loadImageState() {
		const id = design.selectedId;
		const element = design.elements.find((e) => e.id === id);
		if (!id || !element?.image) {
			imageState = null;
			return;
		}
		const response = await fetch(`/api/design/elements/${encodeURIComponent(id)}/image`);
		imageState = response.ok ? await response.json() : null;
	}

	async function setImage(body: Record<string, unknown>) {
		const id = design.selectedId;
		if (!id) return;
		await post(`/api/design/elements/${encodeURIComponent(id)}/image`, body);
		await design.load();
		await loadImageState();
	}
	let libraryOpen = $state(false);
	let catalogueOpen = $state(false);
	let generatorsOpen = $state(false);
	let clipartOpen = $state(false);
	const sheets = new SheetStore(() => localStorage.getItem('openkerf.token') ?? '');
	let calibrateOpen = $state(false);
	const camera = new CameraStore(() => localStorage.getItem('openkerf.token') ?? '');
	const catalogue = new PresetariatStore(() => localStorage.getItem('openkerf.token') ?? '');
	let pendingFile = $state<File | null>(null);
	// Werk van een vorige sessie. Nooit stilzwijgend terugladen: wie met een
	// leeg canvas wil beginnen, moet dat kunnen.
	let recovery = $state<{ exists: boolean; when: string | null } | null>(null);
	let textOpen = $state(false);
	let textAt = $state<{ x: number; y: number } | null>(null);
	let editingText = $state<string | null>(null);
	let estimate = $state<number | null>(null);
	let gridOpen = $state(false);
	let versRaster = $state<number | null>(null);
	/** Het materiaal van het huidige vel wijzigen (besluit B1). */
	let materiaalOpen = $state(false);
	let velMateriaal = $derived(
		library.materials.find((m) => m.id === sheets.active?.material_id)?.name ?? null
	);

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

	function authHeaders(): Record<string, string> {
		const token = localStorage.getItem('openkerf.token') ?? '';
		return token ? { Authorization: `Bearer ${token}` } : {};
	}

	/** Schrijfroutes dragen het token; één plek in plaats van bij elke aanroep. */
	async function post(path: string, body: unknown) {
		const token = localStorage.getItem('openkerf.token') ?? '';
		return fetch(path, {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
				...(token ? { Authorization: `Bearer ${token}` } : {})
			},
			body: JSON.stringify(body)
		});
	}

	/** Een project draagt ook de bibliotheek-context, dus eigen route. */
	async function openProject(file: File) {
		if (!canEdit) return;
		const form = new FormData();
		form.append('file', file);
		const token = localStorage.getItem('openkerf.token') ?? '';
		const response = await fetch('/api/project/open', {
			method: 'POST',
			headers: token ? { Authorization: `Bearer ${token}` } : {},
			body: form
		});
		if (response.ok) {
			design.select(null);
			await Promise.all([design.load(), library.load(), sheets.load()]);
		}
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

	/** Plaatsen voegt toe: de engine laadt bovenop wat er al staat. */
	async function placeImage(file: File) {
		if (!canEdit) return;
		if (await control.load(file)) await design.load();
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
		// 'rescue' werkt op het hele ontwerp; de rest op de selectie.
		if (!canEdit || (!hasSelection && action !== 'rescue')) return;
		const ids = design.selectedIds;
		if (action === 'offset') {
			const answer = prompt('Offset in mm (negatief = naar binnen)', '2');
			if (!answer) return;
			if ((await edits.offset(ids, Number(answer))).ok) await design.load();
			return;
		}
		if (action === 'rescue') {
			// Alles op het bed leggen, ook wat je niet kunt aanwijzen omdat het
			// buiten beeld ligt.
			await post('/api/design/nest', {
				ids: design.elements.filter((e) => !e.hidden).map((e) => e.id),
				margin_mm: 5
			});
			await design.load();
			return;
		}
		if (action === 'nest') {
			await post('/api/design/nest', { ids, margin_mm: 3 });
			await design.load();
			return;
		}
		if (action === 'simplify' || action === 'hatch' || action === 'wobble') {
			const result =
				action === 'simplify' ? await edits.simplify(ids) : await edits.effect(ids, action);
			if (result.ok) await design.load();
			return;
		}
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
	let tab = $state<'design' | 'layers' | 'job'>('job');

	function selectTab(next: 'design' | 'layers' | 'job') {
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
	let telefoonPositie = $derived(
		device?.position.mm
			? `${device.position.mm[0].toFixed(1)}, ${device.position.mm[1].toFixed(1)} mm`
			: '—'
	);
	// Niet `state` noemen: `$state` zou dan als store-referentie gelezen worden.
	let machine = $derived(machineState(device, status.connected));

	onMount(() => {
		status.connect();
		control.refreshCapabilities();
		camera.load();
		sheets.load();
		library.load();
		const wantedTab = $page.url.searchParams.get('tab');
		if (wantedTab === 'design' || wantedTab === 'layers') tab = wantedTab;
		design.load().then(async () => {
			// Alleen aanbieden als er niets staat: over bestaand werk heen
			// terugzetten geeft een mengelmoes, en dat weigert de API ook.
			if (design.isEmpty) {
				const response = await fetch('/api/design/autosave');
				if (response.ok) {
					const state = await response.json();
					if (state.exists) recovery = state;
				}
			}
			const wanted = $page.url.searchParams.get('select');
			if (wanted) {
				const ids = wanted.split(',').filter(Boolean);
				design.select(ids[0] ?? null);
				ids.slice(1).forEach((id) => design.toggle(id));
			}
		});
		// Pas ná mount koppelen: replaceState vóórdat de router klaar is breekt
		// de render. De URL volgt daarom de actie, niet een effect.
		design.onSelect = () => {
			syncUrl();
			loadImageState();
		};
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
	bind:innerWidth={breedte}
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
		if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'a') {
			e.preventDefault();
			design.selectMany(design.elements.filter((el) => !el.hidden).map((el) => el.id));
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

{#if telefoon}
	<!-- De telefoon is een eigen app: monitor en noodrem. Zie DESIGN-SYSTEM v2,
	     "Drie apparaten, drie apps". -->
	<PhoneView
		{device}
		state={machine}
		job={status.activeJob}
		{control}
		{camera}
		connected={status.connected}
		position={telefoonPositie}
	/>
{:else}
<TopBar
	{device}
	state={machine}
	canStart={(control.capabilities?.actions.start ?? false) &&
		!control.needsToken &&
		machine !== 'busy' &&
		machine !== 'paused'}
	canStop={(control.capabilities?.actions.stop ?? false) && !control.needsToken}
	stopArmed={machine === 'busy' || machine === 'paused'}
	canEdit={canEdit && design.preview === null}
	{tablet}
	{smal}
	{krap}
	canPause={(control.capabilities?.actions.pause ?? false) && !control.needsToken}
	canResume={(control.capabilities?.actions.resume ?? false) && !control.needsToken}
	paused={machine === 'paused'}
	onPause={() => control.pause()}
	onResume={() => control.resume()}
	onStart={requestStart}
	onStop={() => control.stop()}
	onOpenFile={openFile}
	onOpenProject={openProject}
	material={velMateriaal}
	thicknessMm={sheets.active?.thickness_mm ?? null}
	onOpenMaterial={() => (materiaalOpen = true)}
	canFrame={(design.elements?.length ?? 0) > 0 &&
		(control.capabilities?.motion?.move ?? false) &&
		!control.needsToken}
	onFrame={() => {
		// Geen dialoog: dit is een controlebeweging, geen onomkeerbare stap.
		// Via de controller, zodat een klagende machine in beeld komt.
		control.frame();
	}}
	onToggleTheme={toggleTheme}
/>

<div class="main">
	<ToolRail
		compact={tablet}
		bestanden={smal || krap}
		bind:tool
		{canEdit}
		onOpenGrid={() => (gridOpen = true)}
		onOpenLibrary={() => (libraryOpen = true)}
		onOpenCatalogue={() => (catalogueOpen = true)}
		onOpenGenerators={() => (generatorsOpen = true)}
		onOpenClipart={() => (clipartOpen = true)}
		onPlaceImage={placeImage}
		onOpenFile={openFile}
		onOpenProject={openProject}
	/>
	<!-- Vellen boven het canvas: elk vel is een eigen document, dus dit is
	     ook de plek waar je ziet welk stuk materiaal je nu bewerkt. -->
	<div class="stage">
		<SheetTabs
			{sheets}
			{library}
			{canEdit}
			onEditMaterial={() => (materiaalOpen = true)}
			onSwitched={async () => {
				design.select(null);
				await design.load();
			}}
		/>
		<Canvas
			onPointerMm={(punt) => (muisMm = punt)}
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
			cameraSrc={camera.src}
			cameraOpacity={camera.opacity}
			sheet={sheets.active
				? {
						name: sheets.active.name,
						width: sheets.active.width_mm,
						height: sheets.active.height_mm
					}
				: null}
			onPath={async (points, closed) => {
				if (!canEdit) return;
				await post('/api/design/path', { points, closed });
				await design.load();
			}}
			bind:cropping
			onCrop={async (rect) => {
				const id = design.selectedId;
				if (!id) return;
				await post(`/api/design/elements/${encodeURIComponent(id)}/crop`, {
					x_mm: rect.x,
					y_mm: rect.y,
					width_mm: rect.width,
					height_mm: rect.height
				});
				await design.load();
				await loadImageState();
			}}
		/>
		{#if wauw}
			<!-- Eén keer, bij het starten: daar gebeurt het ook echt. -->
			<JobStart label={status.activeJob?.label ?? null} />
		{/if}
	</div>

	{#if tablet}
	<!-- Op een tablet is 280 van 1024 pixels een kwart van je werkblad. Het
	     paneel mag weg als je aan het tekenen bent; de machineknoppen staan
	     in de bovenbalk, dus je raakt de laser nooit kwijt. -->
	<button
		class="paneelgreep"
		aria-expanded={paneelOpen}
		onclick={() => (paneelOpen = !paneelOpen)}
	>{paneelOpen ? '›' : '‹'}<span class="vw">Paneel {paneelOpen ? 'inklappen' : 'uitklappen'}</span></button>
{/if}
<aside class="panel" class:weg={tablet && !paneelOpen} aria-label="Eigenschappen">
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
						><line x1="0" y1="1" x2="100%" y2="1" stroke="var(--accent)" stroke-width="1" stroke-dasharray="6 4" class="kerf-anim" /></svg
					>
				{/if}
			</button>
			<button
				class="tab"
				role="tab"
				aria-selected={tab === 'layers'}
				onclick={() => selectTab('layers')}
			>
				Lagen
				{#if tab === 'layers'}
					<svg aria-hidden="true"
						><line x1="0" y1="1" x2="100%" y2="1" stroke="var(--accent)" stroke-width="1" stroke-dasharray="6 4" class="kerf-anim" /></svg
					>
				{/if}
			</button>
			<button class="tab" role="tab" aria-selected={tab === 'job'} onclick={() => selectTab('job')}>
				Job
				{#if tab === 'job'}
					<svg aria-hidden="true"
						><line x1="0" y1="1" x2="100%" y2="1" stroke="var(--accent)" stroke-width="1" stroke-dasharray="6 4" class="kerf-anim" /></svg
					>
				{/if}
			</button>
		</div>
		<div class="panel-scroll">
			{#if tab === 'design' || tab === 'layers'}
				<DesignPanel
					show={tab === 'layers' ? 'layers' : 'selection'}
					bed={device?.bed?.width_mm && device?.bed?.height_mm
						? { width: device.bed.width_mm, height: device.bed.height_mm }
						: null}
					{design}
					{edits}
					{canEdit}
					onHistory={history}
					onRotate={rotate}
					onAssign={assign}
					onLayerChange={() => design.load()}
					box={design.liveBox}
					onSetPosition={setPosition}
					onSetSize={setSize}
					otherSheets={sheets.sheets.filter((s) => !s.active)}
					onMoveToSheet={async (id) => {
						if (await sheets.move(design.selectedIds, id)) {
							design.select(null);
							await design.load();
						}
					}}
					onArrange={arrange}
					onCrop={() => (cropping = true)}

					onVectorise={async () => {
						const id = design.selectedId;
						if (!id) return;
						await post(`/api/design/elements/${encodeURIComponent(id)}/vectorise`, { method: 'vectrace' });
						await design.load();
					}}
					image={imageState as never}
					onImageSet={(name, enabled, values) =>
						setImage({ adjustment: name, enabled, values })}
					onImageClear={() => setImage({ clear: true })}
					onUncrop={async () => {
						const id = design.selectedId;
						if (!id) return;
						await fetch(`/api/design/elements/${encodeURIComponent(id)}/crop`, {
							method: 'DELETE',
							headers: authHeaders()
						});
						await design.load();
						await loadImageState();
					}}
					onImageDpi={async (dpi) => {
						const id = design.selectedId;
						if (!id) return;
						await post(`/api/design/elements/${encodeURIComponent(id)}/image`, { dpi });
						await design.load();
					}}
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
					profile={library.activeMachine}
					onFrame={() => control.frame()}
					colorFor={(id) => design.colorFor(id)}
		onFocus={async (mm) => {
						await post('/api/machine/focus', { distance_mm: mm });
					}}
				/>
			{/if}
		</div>
	</aside>
</div>

<!-- Camerabediening bij het canvas, niet in het rechterpaneel: je kijkt naar
     het bed terwijl je hem aanzet. -->
{#if camera.state.available}
	<div class="camstrip">
		<button
			class="cam"
			aria-pressed={camera.shown && camera.state.running}
			disabled={camera.busy || !canEdit}
			title={canEdit ? 'Camerabeeld van het bed' : 'Vereist een token'}
			onclick={() => (camera.state.running && camera.shown ? camera.stop() : camera.start())}
		>
			<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M3 8h4l2-2h6l2 2h4v11H3z"/><circle cx="12" cy="13" r="3.5"/></svg>
			Camera
		</button>
		{#if camera.shown && camera.state.running}
			<input
				type="range"
				min="0.1"
				max="1"
				step="0.05"
				aria-label="Doorzichtigheid camerabeeld"
				bind:value={camera.opacity}
			/>
			<button class="cam" onclick={() => (calibrateOpen = true)}>
				{camera.state.calibrated ? 'Opnieuw ijken' : 'IJken'}
			</button>
		{/if}
	</div>
	{#if camera.error}
		<!-- Een lange melding hoort niet in een pilvormige balk: die wordt dan een
		     blob. Eigen kader, leesbare regelbreedte, en zelf weg te klikken. -->
		<div class="camerror" role="alert">
			<p class="wrap">{camera.error}</p>
			<button aria-label="Melding sluiten" onclick={() => (camera.error = null)}>×</button>
		</div>
	{/if}
{/if}

<StatusBar
	pointerMm={muisMm}
	{device}
	state={machine}
	job={status.activeJob}
	connected={status.connected}
	{control}
	acties={!tablet}
/>
{/if}

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

<!-- Werk van een vorige sessie: aanbieden, niet opdringen. -->
<Dialog
	title="Werk van een vorige sessie"
	open={recovery?.exists === true}
	width="420px"
>
	<p class="ask">
		Er staat een automatisch bewaard ontwerp van {recovery?.when}. Terugzetten?
	</p>
	<div class="ask-actions">
		<button
			class="btn weg"
			onclick={async () => {
				await fetch('/api/design/autosave', { method: 'DELETE', headers: authHeaders() });
				recovery = null;
			}}
		>Weggooien</button>
		<button class="btn" onclick={() => (recovery = null)}>Later</button>
		<button
			class="btn primary"
			onclick={async () => {
				recovery = null;
				await post('/api/design/autosave/restore', {});
				await design.load();
			}}
		>Terugzetten</button>
	</div>
</Dialog>

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

<Presetariat bind:open={catalogueOpen} {catalogue} {library} {canEdit} />

<CameraCalibration bind:open={calibrateOpen} {camera} />

<Clipart bind:open={clipartOpen} {canEdit} onInserted={() => design.load()} />

<Generators
	bind:open={generatorsOpen}
	hasSelection={design.selectedIds.length > 0}
	busy={edits.busy}
	onGenerate={async (what, body) => {
		const response = await post(`/api/design/generate/${what}`, {
			...body,
			ids: design.selectedIds
		});
		if (!response.ok) {
			const detail = await response.json().catch(() => null);
			return { error: detail?.detail ?? 'Dat lukte niet.' };
		}
		const result = await response.json().catch(() => null);
		await Promise.all([design.load(), sheets.load()]);
		// Een vel dat er stilzwijgend bijkomt is een verrassing; zeg het.
		const used = result?.sheets ?? 1;
		return {
			notice:
				used > 1
					? `Dit past niet op één vel: het staat nu op ${used} vellen. ` +
						`Kijk in de vellenbalk boven het canvas.`
					: null
		};
	}}
/>

<!-- Materiaal van het vel: klein venster, twee keuzes. In de bovenbalk kan het
     niet — die scrollt horizontaal en knipt elk uitklapmenu af — en op een
     tablet is een venster bovendien met een vinger te bedienen. -->
<Dialog title="Materiaal van dit vel" bind:open={materiaalOpen} width="440px">
	{#if sheets.active}
		<SheetMaterial
			{sheets}
			{library}
			sheet={sheets.active}
			onDone={() => (materiaalOpen = false)}
		/>
	{/if}
</Dialog>

<Dialog title="Materiaalbibliotheek" bind:open={libraryOpen} width="640px">
	<MaterialLibrary
		{library}
		operations={design.operations}
		sheetMaterialId={sheets.active?.material_id ?? null}
		sheetMaterialName={velMateriaal}
		{canEdit}
		onApplied={() => design.load()}
		token={token()}
		onMakeGrid={(id) => {
			// Vanuit het materiaal naar het raster: dat is waar de vraag ontstaat.
			libraryOpen = false;
			gridMateriaal = id;
			gridOpen = true;
		}}
	/>
</Dialog>

<Dialog title="Testraster" bind:open={gridOpen} width="860px">
	<TestGrid
		{library}
		{canEdit}
		materialId={gridMateriaal ?? sheets.active?.material_id ?? null}
		thicknessMm={sheets.active?.thickness_mm ?? null}
		onGenerated={(id) => {
			// Vers gebrand raster: stap 3 hoort er meteen op te staan in plaats van
			// op "kies een raster…" te blijven hangen.
			versRaster = id;
			design.load();
		}}
	/>
	<TestGridResult {library} {canEdit} focusGrid={versRaster} />
</Dialog>

<style>
	.stage {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		/* Het startmoment legt zich over het bed; dat vraagt een anker. */
		position: relative;
	}
	.camstrip {
		position: absolute;
		left: calc(var(--rail-width) + var(--space-4));
		bottom: calc(var(--statusbar-height) + var(--space-3));
		z-index: 5;
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: 4px 8px;
		border-radius: 999px;
		border: 1px solid var(--line);
		background: color-mix(in srgb, var(--surface-1) 92%, transparent);
		backdrop-filter: blur(6px);
		box-shadow: var(--shadow-float);
	}
	/* Op tablet is er onderin geen ruimte náást de zoombalk: de camerapil lag er
	   op 768 half overheen. Hij gaat er dan boven staan. */
	@media (max-width: 1199px) {
		.camstrip {
			left: calc(var(--rail-width) + var(--space-3));
			bottom: calc(var(--statusbar-height) + var(--space-3) + 56px);
		}
		.camerror {
			left: calc(var(--rail-width) + var(--space-3));
			bottom: calc(var(--statusbar-height) + var(--space-3) + 108px);
		}
	}
	.cam {
		display: flex;
		align-items: center;
		gap: 4px;
		font-size: var(--text-xs);
		padding: 4px 8px;
		border-radius: 999px;
		color: var(--text-2);
	}
	.cam:hover:not(:disabled) { background: var(--surface-2); color: var(--text-1); }
	.cam:disabled { opacity: 0.45; cursor: not-allowed; }
	.cam[aria-pressed='true'] { color: var(--accent); }
	.camstrip input[type='range'] { width: 90px; }
	.camerror {
		position: absolute;
		left: calc(var(--rail-width) + var(--space-4));
		bottom: calc(var(--statusbar-height) + var(--space-3) + 40px);
		z-index: 5;
		display: flex;
		align-items: flex-start;
		gap: var(--space-2);
		max-width: 42ch;
		padding: var(--space-3);
		border: 1px solid color-mix(in srgb, var(--danger) 40%, var(--line));
		border-radius: var(--radius-card);
		background: var(--surface-1);
		box-shadow: var(--shadow-float);
	}
	.camerror p {
		margin: 0;
		font-size: var(--text-xs);
		line-height: 1.5;
		color: var(--text-1);
	}
	/* De melding bevat een commando op een eigen regel; dat mag niet als één
	   lange lap tekst aan elkaar geplakt worden. */
	.camerror .wrap { white-space: pre-wrap; }
	.camerror button {
		flex: none;
		width: 20px;
		height: 20px;
		border-radius: var(--radius-field);
		color: var(--text-2);
		font-size: 15px;
		line-height: 1;
	}
	.camerror button:hover { background: var(--surface-2); color: var(--text-1); }

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
	/* Op tablet en telefoon staat de tekst een stap groter (15px in plaats van
	   13), maar het paneel bleef 280px — daarmee past er een vijfde minder op
	   een regel dan op de desktop en breken laagnamen middenin een woord.
	   280 × 15/13 ≈ 323: hetzelfde aantal tekens per regel als op de desktop. */
	@media (max-width: 1199px), (pointer: coarse) {
		.panel {
			width: 324px;
		}
	}
	.panel.weg { display: none; }
	/* De greep zit tegen de rand van het canvas, waar je duim al is. */
	.paneelgreep {
		align-self: stretch;
		flex: none;
		width: 20px;
		/* Ingeklapt was dit een naadloze witte kolom van 44px tegen de rand — dat
		   leest als een renderfout, niet als een greep. De lijn links markeert
		   waar het paneel zat en waar je moet duwen om het terug te halen. */
		border-left: 1px solid var(--line);
		background: var(--surface-1);
		color: var(--text-2);
		font-size: var(--text-md);
	}
	.paneelgreep:hover { background: var(--surface-2); color: var(--text-1); }
	.vw {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip-path: inset(50%);
	}
	.tabs {
		display: flex;
		flex: none;
		border-bottom: 1px solid var(--line);
	}
	.tab {
		flex: 1;
		padding: 8px 0 8px;
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
		padding: 8px 16px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		font-weight: 500;
	}
	:global(.ask-actions .btn:hover) { background: var(--surface-2); }
	/* "Weggooien" verwijdert het automatisch bewaarde ontwerp definitief en stond
	   op 8px van "Later". Dit venster verschijnt ongevraagd bij het openen —
	   precies wanneer je nog niet kijkt — en met een handschoen aan raak je het
	   midden van een doel niet. 24px ertussen, alleen op aanraakschermen; de
	   muisindeling op de desktop blijft zoals hij was. Zie DESIGN-SYSTEM,
	   "Touch als eersteklas input". */
	@media (max-width: 1199px), (pointer: coarse) {
		:global(.ask-actions .btn.weg) { margin-right: var(--space-4); }
	}
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
