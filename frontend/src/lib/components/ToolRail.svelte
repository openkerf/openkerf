<script lang="ts">
	export type Tool =
		| 'select'
		| 'nodes'
		| 'measure'
		| 'pen'
		| 'rect'
		| 'circle'
		| 'line'
		| 'point'
		| 'text';

	import { saveFile } from '$lib/saving';
	import { t } from '$lib/i18n/index.svelte';

	let {
		tool = $bindable(),
		canEdit = false,
		writeOff = undefined,
		compact = false,
		files = false,
		projectInRail = false,
		onOpenGrid,
		onOpenLibrary,
		onPlaceImage,
		onOpenFile,
		onOpenProject,
		onNewProject,
		onSaved,
		onOpenGenerators,
		onOpenClipart,
		onOpenSeries
	}: {
		tool: Tool;
		canEdit?: boolean;
		/** Why a write cannot be sent now — `writeRefusal` in `$lib/actions`, worked out
		 *  once by the page so the rail, the bar and the menu say the same thing. */
		writeOff?: string;
		/** Tablet: the rail carries the tablet tasks, the rest lives in the menu. */
		compact?: boolean;
		/** Narrow tablet: the file buttons do not fit in the top bar and live here
		 *  instead. Above this width they are only there — two places for the same
		 *  button is worse than one place further away. */
		files?: boolean;
		/** Below 850px the project button no longer fits in the top bar beside the
		 *  material; then the project lives here, *with* its word. Above that it is
		 *  in the bar and does not belong here — two places for the same action only
		 *  raises the question which one is the real one. */
		projectInRail?: boolean;
		onOpenGrid?: () => void;
		onOpenLibrary?: () => void;
		onPlaceImage?: (file: File) => void;
		onOpenFile?: (file: File) => void;
		onOpenProject?: (file: File) => void;
		/** Start over. Asks for confirmation itself when there is work. */
		onNewProject?: () => void;
		/** After a successful download: the page fetches its "changed" flag. */
		onSaved?: () => void;
		onOpenGenerators?: () => void;
		onOpenClipart?: () => void;
		onOpenSeries?: () => void;
	} = $props();

	// Every tool draws on a click on the bed; selecting is the resting state.
	// The label comes from the catalogue at read time, not at module load, so it
	// follows the language.
	/**
	 * Which tools make something, and which only look.
	 *
	 * A mode is free to choose; what costs a write is what the mode then does. With no
	 * server behind the app, choosing "rectangle" leads to a drag that cannot arrive —
	 * so those go dead and say why. Selecting, dragging a node and measuring need
	 * nothing from the server and stay, because an app that greys everything looks
	 * broken when only the connection is.
	 */
	const MAKES: Tool[] = ['rect', 'circle', 'line', 'point', 'pen', 'text'];

	let TOOLS = $derived<{ id: Tool; label: string; path: string }[]>([
		{ id: 'select', label: t('rail.tool.select'), path: 'M4 3l7 18 2.5-7.5L21 11z' },
		{
			id: 'nodes',
			// The same tool twice, said the first user who really used this rail — and
			// they were right about what they *saw*. This icon was a diagonal stroke
			// with three 1.75px dots on it; at 18px those dots vanish and what is left
			// is a stroke indistinguishable from "Line" (M4 20L20 4). Now a curve with
			// square handles: the shape every node tool carries, and not a stroke.
			label: t('rail.tool.nodes'),
			path: 'M5 18C5 8 19 8 19 18M3 16h4v4H3zM17 16h4v4h-4zM10 8.5h4v4h-4z'
		},
		{ id: 'rect', label: t('rail.tool.rect'), path: 'M4 6h16v12H4z' },
		{ id: 'circle', label: t('rail.tool.circle'), path: 'M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16z' },
		{ id: 'line', label: t('rail.tool.line'), path: 'M4 20L20 4' },
		// A ring around a filled centre, and not a plain dot: at 18 px a single dot is a
		// smudge, and the ring says "one spot" the way a crosshair does. Beside Line
		// because a point is what is left of a line.
		{
			id: 'point',
			label: t('rail.tool.point'),
			path: 'M12 5a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM12 10.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3z'
		},
		{ id: 'pen', label: t('rail.tool.pen'), path: 'M4 20l4-1 11-11-3-3L5 16z' },
		{ id: 'text', label: t('rail.tool.text'), path: 'M5 6h14M12 6v13' },
		{ id: 'measure', label: t('rail.tool.measure'), path: 'M3 15L15 3l6 6L9 21z M7 11l2 2M11 7l2 2' }
	]);

	const ICON = {
		beeld: 'M3.5 5h17v14h-17z',
		grid: 'M3.5 3.5h17v17h-17z M9.2 3.5v17M14.8 3.5v17M3.5 9.2h17M3.5 14.8h17',
		boeken: 'M4 5h6v14H4zM14 5h6v14h-6zM4 9h6M14 9h6'
	};

	// On the tablet the tool rail is not in service of designing but of setting up
	// and starting (DESIGN-SYSTEM v3, "Three devices, three apps"). Material and
	// test grid are core tasks there and used to sit behind a menu; circle, line and
	// text are not and now sit behind it.
	const CORE: Tool[] = ['select', 'rect'];
	// On a touch screen hover does not exist, so the tooltip does not exist: five
	// nameless glyphs are five guesses there. Short labels do fit.
	// The explanation belongs in the tooltip, not in a 260px menu row: as a whole
	// sentence the row broke over two lines and the rest sank out of view.
	let SHORT = $derived<Partial<Record<Tool, string>>>({
		select: t('rail.tool.select'),
		rect: t('rail.tool.rect'),
		nodes: t('rail.tool.nodes.short'),
		pen: t('rail.tool.pen.short')
	});
	let moreOpen = $state(false);

	/**
	 * Saving through `saveFile`, not through a bare `<a download>`: after the
	 * download the app has to know the design has been saved. See `$lib/saving`.
	 */
	async function save(event: MouseEvent, url: string, name: string) {
		event.preventDefault();
		moreOpen = false;
		if (await saveFile(url, name)) onSaved?.();
	}

	let visible = $derived(compact ? TOOLS.filter((t) => CORE.includes(t.id)) : TOOLS);
	let hidden = $derived(compact ? TOOLS.filter((t) => !CORE.includes(t.id)) : []);
	$effect(() => {
		if (!compact) moreOpen = false;
	});
	function pick(id: Tool) {
		tool = id;
		moreOpen = false;
	}
</script>

<svelte:window
	onkeydown={(e) => {
		if (e.key === 'Escape' && moreOpen) moreOpen = false;
	}}
/>

<nav class="rail" class:compact aria-label={t('rail.aria')}>
	{#each visible as item (item.id)}
		<button
			class="tool"
			aria-pressed={tool === item.id}
			title={item.id === 'select'
				? item.label
				: !canEdit
					? t('rail.needsToken', { label: item.label })
					: MAKES.includes(item.id) && writeOff
						? `${item.label} — ${writeOff}`
						: item.label}
			disabled={item.id !== 'select' &&
				(!canEdit || (MAKES.includes(item.id) && Boolean(writeOff)))}
			onclick={() => (tool = item.id)}
		>
			<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
				<path d={item.path} />
			</svg>
			{#if compact}<span class="name">{SHORT[item.id] ?? item.label}</span>{/if}
		</button>
	{/each}

	{#if compact}
		<!-- The two tablet tasks from DESIGN-SYSTEM are here directly, not in the
		     menu: on the tablet beside the machine *this* is the work. -->
		<hr />
		<button class="tool" title={writeOff ? `${t('library.title')} — ${writeOff}` : t('library.title')} disabled={Boolean(writeOff)} onclick={() => { moreOpen = false; onOpenLibrary?.(); }}>
			<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d={ICON.boeken} /></svg>
			<span class="name">{t('rail.library.short')}</span>
		</button>
		<button class="tool" title={writeOff ? `${t('testgrid.title')} — ${writeOff}` : t('testgrid.title')} disabled={!canEdit || Boolean(writeOff)} onclick={() => { moreOpen = false; onOpenGrid?.(); }}>
			<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" aria-hidden="true"><path d={ICON.grid} /></svg>
			<span class="name">{t('testgrid.title')}</span>
		</button>
		<hr />
		<button
			class="tool"
			class:on={moreOpen}
			aria-expanded={moreOpen}
			aria-haspopup="menu"
			title={t('rail.more')}
			onclick={() => (moreOpen = !moreOpen)}
		>
			<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>
			<span class="name">{t('rail.more')}</span>
		</button>
	{/if}

	{#if compact && moreOpen}
		<!-- A column of ten nameless glyphs is a guessing game with gloves on. Here
		     the words are beside them, and the menu opens *next to* the rail rather
		     than over it. -->
		<!-- On a touch screen there is no Escape key: tapping outside the menu has to
		     close it, otherwise you are stuck with it until you find "More" again. -->
		<div
			class="cover"
			role="presentation"
			onclick={() => (moreOpen = false)}
		></div>
		<div class="menu" role="menu" tabindex="-1">
			<p class="head">{t('rail.group.tools')}</p>
			{#each hidden as item (item.id)}
				<button class="row" role="menuitemradio" title={item.label} aria-checked={tool === item.id} disabled={!canEdit} onclick={() => pick(item.id)}>
					<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d={item.path} /></svg>
					<span>{SHORT[item.id] ?? item.label}</span>
				</button>
			{/each}

			<p class="head">{t('rail.group.add')}</p>
			<label class="row" class:off={!canEdit}>
				<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><rect x="3.5" y="5" width="17" height="14" rx="1"/><path d="M3.5 16l4.5-4 3.5 3 4-5 5 6"/></svg>
				<span>{t('rail.placeImage')}</span>
				<input type="file" aria-label={t('rail.placeImage')} accept=".png,.jpg,.jpeg,.gif,.bmp,.webp" disabled={!canEdit}
					onchange={(e) => { const i = e.currentTarget as HTMLInputElement; const f = i.files?.[0]; i.value = ''; moreOpen = false; if (f) onPlaceImage?.(f); }} />
			</label>
			<button class="row" role="menuitem" title={writeOff} disabled={!canEdit || Boolean(writeOff)} onclick={() => { moreOpen = false; onOpenGenerators?.(); }}>
				<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l7 4v10l-7 4-7-4V7z"/><path d="M12 3v18M5 7l7 4 7-4"/></svg>
				<span>{t('rail.generators.short')}</span>
			</button>
			<button class="row" role="menuitem" title={writeOff} disabled={!canEdit || Boolean(writeOff)} onclick={() => { moreOpen = false; onOpenClipart?.(); }}>
				<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21"/><path d="M8 10.5h5M10.5 8v5"/></svg>
				<span>{t('rail.clipart.short')}</span>
			</button>
			<!-- Series has to be here as well, and not only in the wide rail: on a tablet
			     the canvas menu is the only other door to it, and there is no long press
			     on the canvas — so without this row the window has no door at all on a
			     touch screen, while all four of its neighbours have one. -->
			<button class="row" role="menuitem" title={writeOff} disabled={!canEdit || Boolean(writeOff)} onclick={() => { moreOpen = false; onOpenSeries?.(); }}>
				<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M7.5 3.5h13v6h-13z"/><path d="M3.5 11.5h13v9h-13z"/><path d="M6.5 16h7"/></svg>
				<span>{t('rail.series.short')}</span>
			</button>
			<!-- The shared catalogue had a row here, under ADD, and it does not belong in
			     either: browsing somebody else's speeds and powers adds nothing to the
			     drawing, and it is consulted once per machine rather than once per design.
			     It now stands where the settings it is about live — at the top of the
			     material library, and on a tablet that is one of the visible buttons on
			     the rail rather than a row in here. -->

			{#if files}
				<p class="head">{t('rail.group.file')}</p>
				<label class="row">
					<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M3 7h6l2 2h10v10H3z"/><path d="M12 17v-5m0 0-2 2m2-2 2 2"/></svg>
					<span>{t('rail.importHere')}</span>
					<input type="file" aria-label={t('topbar.import.aria')} accept=".svg,.dxf,.rd,.egv,.gcode,.nc,.lbrn,.lbrn2,.ezd,.xcs,.png,.jpg,.jpeg,.gif,.bmp"
						onchange={(e) => { const i = e.currentTarget as HTMLInputElement; const f = i.files?.[0]; i.value = ''; moreOpen = false; if (f) onOpenFile?.(f); }} />
				</label>
				{#if projectInRail}
					<!-- Only below 850px: above that "Project" is in the top bar. -->
					<button class="row" role="menuitem" type="button"
						onclick={() => { moreOpen = false; onNewProject?.(); }}>
						<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M5 3h9l5 5v13H5z"/><path d="M14 3v5h5"/><path d="M12 11v6m-3-3h6"/></svg>
						<span>{t('topbar.project.new')}</span>
					</button>
					<label class="row">
						<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18v4H3z"/><path d="M5 10v9h14v-9"/><path d="M12 18v-5m0 0-2 2m2-2 2 2"/></svg>
						<span>{t('topbar.project.open')}</span>
						<input type="file" aria-label={t('topbar.project.pick')} accept=".openkerf,.zip"
							onchange={(e) => { const i = e.currentTarget as HTMLInputElement; const f = i.files?.[0]; i.value = ''; moreOpen = false; if (f) onOpenProject?.(f); }} />
					</label>
					<a class="row" role="menuitem" href="/api/project/export.openkerf" download="project.openkerf" onclick={(e) => save(e, '/api/project/export.openkerf', 'project.openkerf')}>
						<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18v4H3z"/><path d="M5 10v9h14v-9"/><path d="M12 13v5m0 0-2-2m2 2 2-2"/></svg>
						<span>{t('topbar.project.save')}</span>
					</a>
				{/if}
				<a class="row" role="menuitem" href="/api/design/export.svg" download="design.svg" onclick={(e) => save(e, '/api/design/export.svg', 'design.svg')}>
					<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M5 4h11l3 3v13H5z"/><path d="M12 9v6m0 0-2.5-2.5M12 15l2.5-2.5"/></svg>
					<span>{t('rail.sheetAsSvg')}</span>
				</a>
			{/if}
		</div>
	{/if}

	{#if !compact}
		<!-- Placing an image adds to the design; "Open" *replaces* it. -->
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
		<!-- Tools start on the left; a tool that can only be found on the right is
		     found by nobody. -->
		<button class="tool" title={writeOff ? `${t('rail.generators')} — ${writeOff}` : t('rail.generators')} disabled={!canEdit || Boolean(writeOff)} onclick={() => onOpenGenerators?.()}>
			<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l7 4v10l-7 4-7-4V7z"/><path d="M12 3v18M5 7l7 4 7-4"/></svg>
		</button>
		<button class="tool" title={writeOff ? `${t('rail.clipart')} — ${writeOff}` : t('rail.clipart')} disabled={!canEdit || Boolean(writeOff)} onclick={() => onOpenClipart?.()}>
			<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21"/><path d="M8 10.5h5M10.5 8v5"/></svg>
		</button>
		<!-- One design burned once per row of a list: a workspace you search and
		     compare in, so a window of its own — like the four beside it. No shortcut:
		     none of those four has one either, and keys are scarce. -->
		<button class="tool" title={writeOff ? `${t('rail.series')} — ${writeOff}` : t('rail.series')} disabled={!canEdit || Boolean(writeOff)} onclick={() => onOpenSeries?.()}>
			<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M7.5 3.5h13v6h-13z"/><path d="M3.5 11.5h13v9h-13z"/><path d="M6.5 16h7"/></svg>
		</button>
		<button class="tool" title={writeOff ? `${t('testgrid.title')} — ${writeOff}` : t('testgrid.title')} disabled={!canEdit || Boolean(writeOff)} onclick={() => onOpenGrid?.()}>
			<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" aria-hidden="true"><path d={ICON.grid} /></svg>
		</button>
		<!-- The shared catalogue used to have a button of its own here, the fifteenth on
		     this rail and the same size and weight as Rectangle. A rail is where the
		     modes live — what the next click on the bed does — plus the workspaces you
		     design in; a catalogue you consult once per machine is neither. It is now a
		     card at the top of the material library, one button along. -->
		<button class="tool" title={writeOff ? `${t('library.title')} — ${writeOff}` : t('library.title')} disabled={Boolean(writeOff)} onclick={() => onOpenLibrary?.()}>
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
	/* With a glove on you do not hit the middle. 4px between two 44px targets makes
	   the neighbour as likely as the target; DESIGN-SYSTEM demands 12. Tablet only:
	   on the desktop there are thirteen of them in the same column. */
	/* The width itself lives in tokens.css (--rail-width, 84px below 1200): the
	   camera bar in +page.svelte reckons with it too. */
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
	.name {
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
	.tool.on {
		background: color-mix(in srgb, var(--accent) 12%, transparent);
		color: var(--accent);
	}
	/* The icon may be accent — that is a graphical element and 1.4.11 asks 3:1
	   there, which it makes. The label may not: accent on a 12% accent tint comes
	   out at 3.76:1 in the light theme and 13px text asks 4.5. The active state stays
	   doubly encoded through the tint, the icon and aria-pressed. Reported by the
	   dark surface (c2-pixels). */
	.tool[aria-pressed='true'] .name,
	.tool.on .name {
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

	/* The menu starts below the rail button that opened it, so it does not cover the
	   sheet bar above it, and it scrolls when it does not fit. */
	.cover {
		position: fixed;
		inset: 0;
		z-index: 19;
	}
	.menu {
		position: absolute;
		left: calc(var(--rail-width) + var(--space-2));
		/* Built up from the bottom, because "More" is the lowest rail button: that way
		   the menu sits beside the finger that opened it, and does not cover the sheet
		   bar above it. */
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
	.head {
		margin: var(--space-2) 0 var(--space-1);
		padding: 0 var(--space-2);
		font-size: var(--text-xs);
		font-weight: 600;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--text-2);
	}
	.head:first-child {
		margin-top: 0;
	}
	.row {
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
	.row svg {
		flex: none;
		color: var(--text-2);
	}
	.row:hover:not(:disabled),
	.row:focus-visible {
		background: var(--surface-2);
	}
	.row:disabled,
	.row.off {
		opacity: 0.35;
		cursor: not-allowed;
	}
	.row[aria-checked='true'] {
		background: color-mix(in srgb, var(--accent) 12%, transparent);
		color: var(--text-1);
	}
	.row[aria-checked='true'] svg {
		color: var(--accent);
	}
	.row input[type='file'] {
		position: absolute;
		width: 0;
		height: 0;
		opacity: 0;
	}
</style>
