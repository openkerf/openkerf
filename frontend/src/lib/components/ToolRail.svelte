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

	import { t } from '$lib/i18n/index.svelte';
	import Menu from './Menu.svelte';
	import type { Action, Menu as MenuList } from '$lib/actions';

	let {
		tool = $bindable(),
		canEdit = false,
		writeOff = undefined,
		compact = false,
		files = false,
		projectInRail = false,
		projectMenu = [],
		onOpenGrid,
		onOpenLibrary,
		onPlaceImage,
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
		/** Tablet: Import… and Export get a File group in the More menu as well, because
		 *  the empty bed's tablet sentence sends you to More for them. */
		files?: boolean;
		/** Below 880px the project button no longer fits in the top bar beside the
		 *  material; then the whole project menu lives here, *with* its words. Above
		 *  that it is in the bar and does not belong here — two places for the same
		 *  action only raises the question which one is the real one. */
		projectInRail?: boolean;
		/** The rows the top bar's project menu shows — New, Open…, Save, Save as…,
		 *  Download, Upload…, Import…, Export — read from `$lib/actions`'
		 *  `projectActions` so a narrow screen reaches the server the same way the bar
		 *  does, and not through a second, hand-built copy of the same verbs. */
		projectMenu?: MenuList;
		onOpenGrid?: () => void;
		onOpenLibrary?: () => void;
		onPlaceImage?: (file: File) => void;
		onOpenGenerators?: () => void;
		onOpenClipart?: () => void;
		onOpenSeries?: () => void;
	} = $props();

	let projectRows = $derived(
		projectMenu
			.flatMap((group) => group.items)
			.filter((item): item is Action => item !== 'separator' && !('items' in item))
	);

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

	/** Why this mode cannot be chosen now, or nothing. One rule for the rail and its menu. */
	function toolOff(item: { id: Tool; label: string }): string | undefined {
		if (item.id === 'select') return undefined;
		if (!canEdit) return t('rail.needsToken', { label: item.label });
		if (MAKES.includes(item.id) && writeOff) return writeOff;
		return undefined;
	}
	/** Why a window that writes cannot be opened now. */
	let launchOff = $derived(!canEdit ? t('reason.needsToken') : writeOff);

	/** The one hidden file field behind "Place image", on the rail and in its menu. */
	let imageInput = $state<HTMLInputElement | null>(null);

	let visible = $derived(compact ? TOOLS.filter((t) => CORE.includes(t.id)) : TOOLS);
	let hidden = $derived(compact ? TOOLS.filter((t) => !CORE.includes(t.id)) : []);

	/**
	 * The More menu is the app's one menu (`Menu.svelte`): the same rows, the same arrow
	 * keys, Escape, and a tap outside to close it. It used to be a hand-built copy that
	 * looked like it and walked like nothing — Tab was the only way through it.
	 */
	let more = $state<{ x: number; y: number } | null>(null);
	$effect(() => {
		if (!compact) more = null;
	});

	let moreMenu = $derived.by<MenuList>(() => {
		const groups: MenuList = [
			{
				title: t('rail.group.tools'),
				items: hidden.map((item) => ({
					id: `tool-${item.id}`,
					label: SHORT[item.id] ?? item.label,
					explain: item.label,
					on: tool === item.id,
					off: toolOff(item),
					run: () => (tool = item.id)
				}))
			},
			{
				title: t('rail.group.add'),
				items: [
					{
						id: 'place-image',
						label: t('rail.placeImage'),
						off: canEdit ? undefined : t('reason.needsToken'),
						run: () => imageInput?.click()
					},
					{ id: 'generators', label: t('rail.generators.short'), explain: t('rail.generators'), off: launchOff, run: () => onOpenGenerators?.() },
					{ id: 'clipart', label: t('rail.clipart.short'), explain: t('rail.clipart'), off: launchOff, run: () => onOpenClipart?.() },
					// Series has to be here as well, and not only in the wide rail: on a
					// tablet the canvas menu is the only other door to it, and there is no
					// long press on the canvas — so without this row the window has no door
					// at all on a touch screen, while all four of its neighbours have one.
					{ id: 'series', label: t('rail.series.short'), explain: t('rail.series'), off: launchOff, run: () => onOpenSeries?.() }
				]
			}
		];
		// Below 880px the whole project menu; between that and 1200 only the two rows
		// that work on the sheet, because the project button in the bar has the rest.
		const fileRows = projectInRail
			? projectMenu.flatMap((group) => group.items)
			: projectRows.filter((row) => row.id === 'sheet.import' || row.id === 'sheet.export');
		if (files && fileRows.length) groups.push({ title: t('rail.group.file'), items: fileRows });
		return groups;
	});

	function openMore(button: HTMLElement) {
		if (more) {
			more = null;
			return;
		}
		const box = button.getBoundingClientRect();
		// Beside the rail, its bottom edge level with the button: the menu sits next to
		// the finger that opened it and does not cover the sheet bar above.
		more = { x: box.right + 8, y: box.bottom };
	}
</script>

<nav class="rail" class:compact aria-label={t('rail.aria')}>
	<!-- The modes: what the next click on the bed does. One of them is always chosen. -->
	<div class="group modes" role="group" aria-label={t('rail.group.tools')}>
		{#each visible as item (item.id)}
			{@const off = toolOff(item)}
			<button
				class="tool"
				aria-pressed={tool === item.id}
				title={!off ? item.label : off === writeOff ? `${item.label} — ${off}` : off}
				disabled={Boolean(off)}
				onclick={() => (tool = item.id)}
			>
				<svg class="icon-svg" width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
					<path d={item.path} />
				</svg>
				{#if compact}<span class="name">{SHORT[item.id] ?? item.label}</span>{/if}
			</button>
		{/each}
	</div>

	<!-- The windows: places you open, not modes you are in. Below a rule and at the foot
	     of the rail, so the column reads as two kinds of thing and not as fifteen of one.
	     On a tablet the two tasks beside the machine are here directly; the rest of the
	     modes, the adders and the files are behind More. -->
	<div class="group windows" role="group" aria-label={t('rail.group.windows')}>
		<hr />
		{#if compact}
			<button class="tool" title={writeOff ? `${t('library.title')} — ${writeOff}` : t('library.title')} disabled={Boolean(writeOff)} onclick={() => onOpenLibrary?.()}>
				<svg class="icon-svg" width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><path d={ICON.boeken} /></svg>
				<span class="name">{t('rail.library.short')}</span>
			</button>
			<button class="tool" title={launchOff ? `${t('testgrid.title')} — ${launchOff}` : t('testgrid.title')} disabled={Boolean(launchOff)} onclick={() => onOpenGrid?.()}>
				<svg class="icon-svg" width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><path d={ICON.grid} /></svg>
				<span class="name">{t('testgrid.title')}</span>
			</button>
			<hr />
			<button
				class="tool"
				class:on={more !== null}
				aria-expanded={more !== null}
				aria-haspopup="menu"
				title={t('rail.more')}
				onclick={(e) => openMore(e.currentTarget as HTMLElement)}
			>
				<svg class="icon-svg" width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1.6" fill="currentColor" /><circle cx="12" cy="12" r="1.6" fill="currentColor" /><circle cx="19" cy="12" r="1.6" fill="currentColor" /></svg>
				<span class="name">{t('rail.more')}</span>
			</button>
		{:else}
			<!-- Placing an image adds to the design; "Open" *replaces* it. -->
			<button class="tool" title={canEdit ? t('rail.placeImage') : t('rail.needsToken', { label: t('rail.placeImage') })} disabled={!canEdit} onclick={() => imageInput?.click()}>
				<svg class="icon-svg" width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="5" width="17" height="14" rx="1"/><path d="M3.5 16l4.5-4 3.5 3 4-5 5 6"/></svg>
			</button>
			<!-- Tools start on the left; a tool that can only be found on the right is
			     found by nobody. -->
			<button class="tool" title={launchOff ? `${t('rail.generators')} — ${launchOff}` : t('rail.generators')} disabled={Boolean(launchOff)} onclick={() => onOpenGenerators?.()}>
				<svg class="icon-svg" width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l7 4v10l-7 4-7-4V7z"/><path d="M12 3v18M5 7l7 4 7-4"/></svg>
			</button>
			<button class="tool" title={launchOff ? `${t('rail.clipart')} — ${launchOff}` : t('rail.clipart')} disabled={Boolean(launchOff)} onclick={() => onOpenClipart?.()}>
				<svg class="icon-svg" width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21"/><path d="M8 10.5h5M10.5 8v5"/></svg>
			</button>
			<!-- One design burned once per row of a list: a workspace you search and
			     compare in, so a window of its own — like the four beside it. No shortcut:
			     none of those four has one either, and keys are scarce. -->
			<button class="tool" title={launchOff ? `${t('rail.series')} — ${launchOff}` : t('rail.series')} disabled={Boolean(launchOff)} onclick={() => onOpenSeries?.()}>
				<svg class="icon-svg" width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><path d="M7.5 3.5h13v6h-13z"/><path d="M3.5 11.5h13v9h-13z"/><path d="M6.5 16h7"/></svg>
			</button>
			<button class="tool" title={launchOff ? `${t('testgrid.title')} — ${launchOff}` : t('testgrid.title')} disabled={Boolean(launchOff)} onclick={() => onOpenGrid?.()}>
				<svg class="icon-svg" width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><path d={ICON.grid} /></svg>
			</button>
			<!-- The shared catalogue used to have a button of its own here, the fifteenth on
			     this rail and the same size and weight as Rectangle. A rail is where the
			     modes live — what the next click on the bed does — plus the workspaces you
			     design in; a catalogue you consult once per machine is neither. It is now a
			     card at the top of the material library, one button along. -->
			<button class="tool" title={writeOff ? `${t('library.title')} — ${writeOff}` : t('library.title')} disabled={Boolean(writeOff)} onclick={() => onOpenLibrary?.()}>
				<svg class="icon-svg" width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><path d={ICON.boeken} /></svg>
			</button>
		{/if}
	</div>

	<input
		bind:this={imageInput}
		class="hidden-file"
		type="file"
		tabindex="-1"
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
</nav>

{#if more}
	<Menu menu={moreMenu} x={more.x} y={more.y} upward onClose={() => (more = null)} />
{/if}

<style>
	.rail {
		width: var(--rail-width);
		flex: none;
		display: flex;
		flex-direction: column;
		align-items: center;
		padding: var(--space-2) 0;
		background: var(--surface-1);
		border-right: 1px solid var(--line);
		position: relative;
	}
	.group {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-1);
	}
	/* The windows stand at the foot of the rail, so the free room falls between the two
	   kinds and not inside either. */
	.windows {
		margin-top: auto;
		padding-top: var(--space-2);
	}
	/* With a glove on you do not hit the middle. 4px between two 44px targets makes
	   the neighbour as likely as the target; DESIGN-SYSTEM demands 12. Tablet only:
	   on the desktop there are fifteen of them in the same column. */
	/* The width itself lives in tokens.css (--rail-width, 84px below 1200): the
	   camera bar in +page.svelte reckons with it too. */
	.rail.compact .group {
		gap: var(--space-3);
	}
	.rail.compact .tool {
		flex-direction: column;
		gap: 2px;
		width: 76px;
		height: auto;
		min-height: max(52px, var(--target-min));
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
	/* Drained, not faded: the icon is mixed toward the panel instead of made
	   see-through (3:1 is not asked of a disabled control), the reason is in the
	   tooltip, and the label under it on a tablet stays readable in --text-2. */
	.tool:disabled {
		color: color-mix(in srgb, var(--text-2) 45%, var(--surface-1));
		cursor: not-allowed;
	}
	.tool:disabled .name {
		color: var(--text-2);
	}
	.tool[aria-pressed='true'],
	.tool.on {
		background: var(--accent-tint);
		color: var(--accent);
	}
	/* The icon may be accent — that is a graphical element and 1.4.11 asks 3:1
	   there, which it makes. The label may not: accent on a 12% accent tint comes
	   out at 3.76:1 and 13px text asks 4.5. The active state stays doubly encoded
	   through the tint, the icon and aria-pressed (c2-pixels). */
	.tool[aria-pressed='true'] .name,
	.tool.on .name {
		color: var(--text-1);
	}
	.hidden-file {
		position: absolute;
		width: 0;
		height: 0;
		opacity: 0;
		pointer-events: none;
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
</style>