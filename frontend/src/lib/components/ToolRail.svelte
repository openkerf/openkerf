<script lang="ts">
	export type Tool = 'select' | 'nodes' | 'measure' | 'pen' | 'rect' | 'circle' | 'line' | 'text';

	import { bewaarBestand } from '$lib/opslaan';
	import { t } from '$lib/i18n/index.svelte';

	let {
		tool = $bindable(),
		canEdit = false,
		compact = false,
		bestanden = false,
		projectInRail = false,
		onOpenGrid,
		onOpenLibrary,
		onPlaceImage,
		onOpenFile,
		onOpenProject,
		onNewProject,
		onSaved,
		onOpenCatalogue,
		onOpenGenerators,
		onOpenClipart
	}: {
		tool: Tool;
		canEdit?: boolean;
		/** Tablet: de rail draagt de tablettaken, de rest zit in het menu. */
		compact?: boolean;
		/** Smalle tablet: de bestandsknoppen passen niet in de bovenbalk en
		 *  wonen dan hier. Boven deze breedte staan ze alleen daar — twee plekken
		 *  voor dezelfde knop is erger dan één plek verderop. */
		bestanden?: boolean;
		/** Onder 850px past de projectknop niet meer in de bovenbalk naast het
		 *  materiaal; dan woont het project hier, mét zijn woord. Daarboven staat
		 *  het in de balk en hoort het hier niet — twee plekken voor dezelfde
		 *  handeling levert alleen de vraag op welke de echte is. */
		projectInRail?: boolean;
		onOpenGrid?: () => void;
		onOpenLibrary?: () => void;
		onPlaceImage?: (file: File) => void;
		onOpenFile?: (file: File) => void;
		onOpenProject?: (file: File) => void;
		/** Opnieuw beginnen. Vraagt zelf om bevestiging als er werk ligt. */
		onNewProject?: () => void;
		/** Na een geslaagde download: de pagina haalt zijn "gewijzigd"-vlag op. */
		onSaved?: () => void;
		onOpenCatalogue?: () => void;
		onOpenGenerators?: () => void;
		onOpenClipart?: () => void;
	} = $props();

	// Every tool draws on a click on the bed; selecting is the resting state.
	// The label comes from the catalogue at read time, not at module load, so it
	// follows the language.
	let TOOLS = $derived<{ id: Tool; label: string; path: string }[]>([
		{ id: 'select', label: t('rail.tool.select'), path: 'M4 3l7 18 2.5-7.5L21 11z' },
		{
			id: 'nodes',
			// Twee keer hetzelfde gereedschap, zei de eerste gebruiker die deze rail
			// echt gebruikte — en hij had gelijk in wat hij zág. Dit icoon was een
			// schuine streep met drie punten van 1,75px eraan; op 18px verdwijnen
			// die punten en blijft er een streep over die niet van "Lijn" (M4 20L20
			// 4) te onderscheiden is. Nu een kromme met vierkante handvatten: de
			// vorm die élk knooppuntgereedschap draagt, en geen streep.
			label: t('rail.tool.nodes'),
			path: 'M5 18C5 8 19 8 19 18M3 16h4v4H3zM17 16h4v4h-4zM10 8.5h4v4h-4z'
		},
		{ id: 'rect', label: t('rail.tool.rect'), path: 'M4 6h16v12H4z' },
		{ id: 'circle', label: t('rail.tool.circle'), path: 'M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16z' },
		{ id: 'line', label: t('rail.tool.line'), path: 'M4 20L20 4' },
		{ id: 'pen', label: t('rail.tool.pen'), path: 'M4 20l4-1 11-11-3-3L5 16z' },
		{ id: 'text', label: t('rail.tool.text'), path: 'M5 6h14M12 6v13' },
		{ id: 'measure', label: t('rail.tool.measure'), path: 'M3 15L15 3l6 6L9 21z M7 11l2 2M11 7l2 2' }
	]);

	const ICON = {
		beeld: 'M3.5 5h17v14h-17z',
		raster: 'M3.5 3.5h17v17h-17z M9.2 3.5v17M14.8 3.5v17M3.5 9.2h17M3.5 14.8h17',
		boeken: 'M4 5h6v14H4zM14 5h6v14h-6zM4 9h6M14 9h6'
	};

	// Op de tablet staat de gereedschapsrail niet in dienst van ontwerpen maar
	// van instellen en starten (DESIGN-SYSTEM v3, "Drie apparaten, drie apps").
	// Materiaal en testraster zijn daar kerntaken en stonden achter een menu;
	// cirkel, lijn en tekst zijn dat niet en staan er nu achter.
	const KERN: Tool[] = ['select', 'rect'];
	// Op een aanraakscherm bestaat hover niet, dus bestaat de tooltip niet: vijf
	// naamloze glyphs zijn daar vijf gokjes. Korte labels passen wél.
	// The explanation belongs in the tooltip, not in a 260px menu row: as a whole
	// sentence the row broke over two lines and the rest sank out of view.
	let SHORT = $derived<Partial<Record<Tool, string>>>({
		select: t('rail.tool.select'),
		rect: t('rail.tool.rect'),
		nodes: t('rail.tool.nodes.short'),
		pen: t('rail.tool.pen.short')
	});
	let meerOpen = $state(false);

	/**
	 * Opslaan via `bewaarBestand`, niet via een kale `<a download>`: de app moet
	 * ná de download weten dat het ontwerp opgeslagen is. Zie `$lib/opslaan`.
	 */
	async function bewaar(event: MouseEvent, url: string, naam: string) {
		event.preventDefault();
		meerOpen = false;
		if (await bewaarBestand(url, naam)) onSaved?.();
	}

	let zichtbaar = $derived(compact ? TOOLS.filter((t) => KERN.includes(t.id)) : TOOLS);
	let verborgen = $derived(compact ? TOOLS.filter((t) => !KERN.includes(t.id)) : []);
	$effect(() => {
		if (!compact) meerOpen = false;
	});
	function kies(id: Tool) {
		tool = id;
		meerOpen = false;
	}
</script>

<svelte:window
	onkeydown={(e) => {
		if (e.key === 'Escape' && meerOpen) meerOpen = false;
	}}
/>

<nav class="rail" class:compact aria-label={t('rail.aria')}>
	{#each zichtbaar as item (item.id)}
		<button
			class="tool"
			aria-pressed={tool === item.id}
			title={item.id === 'select' || canEdit
				? item.label
				: t('rail.needsToken', { label: item.label })}
			disabled={item.id !== 'select' && !canEdit}
			onclick={() => (tool = item.id)}
		>
			<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
				<path d={item.path} />
			</svg>
			{#if compact}<span class="naam">{SHORT[item.id] ?? item.label}</span>{/if}
		</button>
	{/each}

	{#if compact}
		<!-- De twee tablettaken uit DESIGN-SYSTEM staan hier direct, niet in het
		     menu: op de tablet naast de machine is dít het werk. -->
		<hr />
		<button class="tool" title={t('library.title')} onclick={() => { meerOpen = false; onOpenLibrary?.(); }}>
			<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d={ICON.boeken} /></svg>
			<span class="naam">{t('rail.library.short')}</span>
		</button>
		<button class="tool" title={t('testgrid.title')} disabled={!canEdit} onclick={() => { meerOpen = false; onOpenGrid?.(); }}>
			<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" aria-hidden="true"><path d={ICON.raster} /></svg>
			<span class="naam">{t('testgrid.title')}</span>
		</button>
		<hr />
		<button
			class="tool"
			class:aan={meerOpen}
			aria-expanded={meerOpen}
			aria-haspopup="menu"
			title={t('rail.more')}
			onclick={() => (meerOpen = !meerOpen)}
		>
			<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>
			<span class="naam">{t('rail.more')}</span>
		</button>
	{/if}

	{#if compact && meerOpen}
		<!-- Een kolom van tien naamloze glyphs is een raadspel met handschoenen
		     aan. Hier staan de woorden erbij, en het menu opent náást de rail in
		     plaats van eroverheen. -->
		<!-- Op een aanraakscherm is er geen Escape-toets: buiten het menu tikken
		     moet het sluiten, anders zit je eraan vast tot je "Meer" terugvindt. -->
		<div
			class="afdek"
			role="presentation"
			onclick={() => (meerOpen = false)}
		></div>
		<div class="menu" role="menu" tabindex="-1">
			<p class="kop">{t('rail.group.tools')}</p>
			{#each verborgen as item (item.id)}
				<button class="regel" role="menuitemradio" title={item.label} aria-checked={tool === item.id} disabled={!canEdit} onclick={() => kies(item.id)}>
					<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d={item.path} /></svg>
					<span>{SHORT[item.id] ?? item.label}</span>
				</button>
			{/each}

			<p class="kop">{t('rail.group.add')}</p>
			<label class="regel" class:off={!canEdit}>
				<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><rect x="3.5" y="5" width="17" height="14" rx="1"/><path d="M3.5 16l4.5-4 3.5 3 4-5 5 6"/></svg>
				<span>{t('rail.placeImage')}</span>
				<input type="file" aria-label={t('rail.placeImage')} accept=".png,.jpg,.jpeg,.gif,.bmp,.webp" disabled={!canEdit}
					onchange={(e) => { const i = e.currentTarget as HTMLInputElement; const f = i.files?.[0]; i.value = ''; meerOpen = false; if (f) onPlaceImage?.(f); }} />
			</label>
			<button class="regel" role="menuitem" disabled={!canEdit} onclick={() => { meerOpen = false; onOpenGenerators?.(); }}>
				<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l7 4v10l-7 4-7-4V7z"/><path d="M12 3v18M5 7l7 4 7-4"/></svg>
				<span>{t('rail.generators.short')}</span>
			</button>
			<button class="regel" role="menuitem" disabled={!canEdit} onclick={() => { meerOpen = false; onOpenClipart?.(); }}>
				<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21"/><path d="M8 10.5h5M10.5 8v5"/></svg>
				<span>{t('rail.clipart.short')}</span>
			</button>
			<button class="regel" role="menuitem" onclick={() => { meerOpen = false; onOpenCatalogue?.(); }}>
				<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v12"/><path d="M8 11l4 4 4-4"/><path d="M4 18v2h16v-2"/></svg>
				<span>{t('rail.presetariat.short')}</span>
			</button>

			{#if bestanden}
				<p class="kop">{t('rail.group.file')}</p>
				<label class="regel">
					<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M3 7h6l2 2h10v10H3z"/><path d="M12 17v-5m0 0-2 2m2-2 2 2"/></svg>
					<span>{t('rail.importHere')}</span>
					<input type="file" aria-label={t('topbar.import.aria')} accept=".svg,.dxf,.rd,.egv,.gcode,.nc,.lbrn,.lbrn2,.ezd,.xcs,.png,.jpg,.jpeg,.gif,.bmp"
						onchange={(e) => { const i = e.currentTarget as HTMLInputElement; const f = i.files?.[0]; i.value = ''; meerOpen = false; if (f) onOpenFile?.(f); }} />
				</label>
				{#if projectInRail}
					<!-- Alleen onder 850px: daarboven staat "Project" in de bovenbalk. -->
					<button class="regel" role="menuitem" type="button"
						onclick={() => { meerOpen = false; onNewProject?.(); }}>
						<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M5 3h9l5 5v13H5z"/><path d="M14 3v5h5"/><path d="M12 11v6m-3-3h6"/></svg>
						<span>{t('topbar.project.new')}</span>
					</button>
					<label class="regel">
						<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18v4H3z"/><path d="M5 10v9h14v-9"/><path d="M12 18v-5m0 0-2 2m2-2 2 2"/></svg>
						<span>{t('topbar.project.open')}</span>
						<input type="file" aria-label={t('topbar.project.pick')} accept=".openkerf,.zip"
							onchange={(e) => { const i = e.currentTarget as HTMLInputElement; const f = i.files?.[0]; i.value = ''; meerOpen = false; if (f) onOpenProject?.(f); }} />
					</label>
					<a class="regel" role="menuitem" href="/api/project/export.openkerf" download="project.openkerf" onclick={(e) => bewaar(e, '/api/project/export.openkerf', 'project.openkerf')}>
						<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18v4H3z"/><path d="M5 10v9h14v-9"/><path d="M12 13v5m0 0-2-2m2 2 2-2"/></svg>
						<span>{t('topbar.project.save')}</span>
					</a>
				{/if}
				<a class="regel" role="menuitem" href="/api/design/export.svg" download="ontwerp.svg" onclick={(e) => bewaar(e, '/api/design/export.svg', 'ontwerp.svg')}>
					<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M5 4h11l3 3v13H5z"/><path d="M12 9v6m0 0-2.5-2.5M12 15l2.5-2.5"/></svg>
					<span>{t('rail.sheetAsSvg')}</span>
				</a>
			{/if}
		</div>
	{/if}

	{#if !compact}
		<!-- Een afbeelding plaatsen voegt toe aan het ontwerp; "Openen" vervángt het. -->
		<label class="tool file" class:off={!canEdit} title={t('rail.placeImage')}>
			<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><rect x="3.5" y="5" width="17" height="14" rx="1"/><path d="M3.5 16l4.5-4 3.5 3 4-5 5 6"/></svg>
			<input
				type="file"
				aria-label={t('rail.placeImage')}
				accept=".png,.jpg,.jpeg,.gif,.bmp,.webp"
				disabled={!canEdit}
				onchange={(e) => {
					const input = e.currentTarget as HTMLInputElement;
					const file = input.files?.[0];
					input.value = '';
					if (file) onPlaceImage?.(file);
				}}
			/>
		</label>

		<hr />
		<!-- Gereedschappen begin je links; een gereedschap dat alleen rechts te
		     vinden is, vindt niemand. -->
		<button class="tool" title={t('rail.generators')} disabled={!canEdit} onclick={() => onOpenGenerators?.()}>
			<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l7 4v10l-7 4-7-4V7z"/><path d="M12 3v18M5 7l7 4 7-4"/></svg>
		</button>
		<button class="tool" title={t('rail.clipart')} disabled={!canEdit} onclick={() => onOpenClipart?.()}>
			<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21"/><path d="M8 10.5h5M10.5 8v5"/></svg>
		</button>
		<button class="tool" title={t('testgrid.title')} disabled={!canEdit} onclick={() => onOpenGrid?.()}>
			<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" aria-hidden="true"><path d={ICON.raster} /></svg>
		</button>
		<button class="tool" title={t('rail.presetariat')} onclick={() => onOpenCatalogue?.()}>
			<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v12"/><path d="M8 11l4 4 4-4"/><path d="M4 18v2h16v-2"/></svg>
		</button>
		<button class="tool" title={t('library.title')} onclick={() => onOpenLibrary?.()}>
			<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d={ICON.boeken} /></svg>
		</button>
	{/if}
</nav>

<style>
	.rail {
		width: var(--rail-width);
		flex: none;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-1);
		padding: var(--space-2) 0;
		background: var(--surface-1);
		border-right: 1px solid var(--line);
		position: relative;
	}
	/* Met een handschoen aan raak je niet het midden. 4px tussen twee doelen van
	   44px maakt de buurman even waarschijnlijk als het doel; DESIGN-SYSTEM eist
	   12. Alleen op tablet: op de desktop staan er dertien in dezelfde kolom. */
	/* De breedte zelf staat in tokens.css (--rail-width, 84px onder 1200): de
	   camerabalk in +page.svelte rekent er ook mee. */
	.rail.compact {
		gap: var(--space-3);
	}
	.rail.compact .tool {
		flex-direction: column;
		gap: 2px;
		width: 76px;
		height: auto;
		min-height: 52px;
		padding: var(--space-1h) 2px;
	}
	.naam {
		font-size: var(--text-xs);
		line-height: 1.1;
		text-align: center;
	}
	.tool {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 40px;
		height: 40px;
		border-radius: var(--radius-field);
		color: var(--text-2);
		transition: background var(--transition);
	}
	.tool:hover:not(:disabled) {
		background: var(--surface-2);
		color: var(--text-1);
	}
	.tool:disabled {
		opacity: 0.35;
		cursor: not-allowed;
	}
	.tool[aria-pressed='true'],
	.tool.aan {
		background: color-mix(in srgb, var(--accent) 12%, transparent);
		color: var(--accent);
	}
	/* Het icoon mag accent zijn — dat is een grafisch element en 1.4.11 vraagt
	   daar 3:1, wat het haalt. Het label niet: accent op een accenttint van 12%
	   komt in het lichte thema op 3,76:1 en tekst van 13px vraagt 4,5. De
	   actieve staat blijft dubbel gecodeerd via de tint, het icoon en
	   aria-pressed. Gemeld door het donker-oppervlak (c2-pixels). */
	.tool[aria-pressed='true'] .naam,
	.tool.aan .naam {
		color: var(--text-1);
	}
	.tool.file input {
		position: absolute;
		width: 0;
		height: 0;
		opacity: 0;
	}
	.tool.file {
		position: relative;
		cursor: pointer;
	}
	.tool.file.off {
		opacity: 0.35;
		cursor: not-allowed;
	}
	.rail.compact hr {
		width: 56px;
	}
	hr {
		width: 28px;
		border: none;
		border-top: 1px solid var(--line);
		margin: 0;
	}

	/* Het menu begint onder de rail-knop die het opende, zodat het de vellenbalk
	   erboven niet afdekt, en het scrollt als het niet past. */
	.afdek {
		position: fixed;
		inset: 0;
		z-index: 19;
	}
	.menu {
		position: absolute;
		left: calc(var(--rail-width) + var(--space-2));
		/* Van onderen opgebouwd, want "Meer" is de onderste railknop: zo staat het
		   menu naast de vinger die het opende, en dekt het de vellenbalk erboven
		   niet af. */
		bottom: var(--space-2);
		width: 260px;
		max-height: calc(100vh - var(--topbar-height) - var(--statusbar-height) - 64px);
		overflow-y: auto;
		padding: var(--space-2);
		background: var(--surface-1);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		box-shadow: var(--shadow-float);
		z-index: 20;
	}
	.kop {
		margin: var(--space-2) 0 var(--space-1);
		padding: 0 var(--space-2);
		font-size: var(--text-xs);
		font-weight: 600;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--text-2);
	}
	.kop:first-child {
		margin-top: 0;
	}
	.regel {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		width: 100%;
		min-height: 44px;
		padding: 0 var(--space-2);
		border-radius: var(--radius-field);
		color: var(--text-1);
		text-align: left;
		text-decoration: none;
		cursor: pointer;
		transition: background var(--transition);
	}
	.regel svg {
		flex: none;
		color: var(--text-2);
	}
	.regel:hover:not(:disabled),
	.regel:focus-visible {
		background: var(--surface-2);
	}
	.regel:disabled,
	.regel.off {
		opacity: 0.35;
		cursor: not-allowed;
	}
	.regel[aria-checked='true'] {
		background: color-mix(in srgb, var(--accent) 12%, transparent);
		color: var(--text-1);
	}
	.regel[aria-checked='true'] svg {
		color: var(--accent);
	}
	.regel input[type='file'] {
		position: absolute;
		width: 0;
		height: 0;
		opacity: 0;
	}
</style>
