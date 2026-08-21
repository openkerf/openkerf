<script lang="ts">
	/**
	 * The context menu — one component for all the places one hangs: on a shape,
	 * on the canvas, and on a row in a list.
	 *
	 * Why one component and not three: the contents differ per place, the
	 * behaviour must not. A menu that closes with Escape here but not there, or
	 * that takes arrow keys in one spot and not the next, costs more than it
	 * gives. What is right here once is right everywhere.
	 *
	 * What it does, and why:
	 * - **Opens at the cursor**, and flips as soon as it meets an edge. A menu
	 *   hanging half outside the window is a menu whose lower half you cannot
	 *   choose.
	 * - **Fully keyboard driven**: arrows walk the choosable rows and skip the
	 *   disabled ones (a tab stop on something that cannot be done is a detour),
	 *   Enter chooses, Escape closes, Home/End jump. Submenus open with → and
	 *   close with ←.
	 * - **Disabled rows stay put**, with the reason in the tooltip. Removing them
	 *   would mean the menu changes shape per selection, and then there is no
	 *   place left to learn where something is.
	 * - **The shortcut is right-aligned** in its own column, because that is where
	 *   you learn it: not from a manual but from the menu.
	 */
	import ArrangeIcon from './ArrangeIcon.svelte';
	import type { Menu, MenuItem } from '$lib/actions';

	let {
		menu,
		x,
		y,
		upward = false,
		onClose
	}: {
		menu: Menu;
		/** Position in screen coordinates; the menu finds its own fitting corner. */
		x: number;
		y: number;
		/** For a menu hanging off a button near the bottom: `y` is then the
		 *  *bottom* edge of the menu instead of the top. A flyout that lands on top
		 *  of its own button covers what you just pointed at. */
		upward?: boolean;
		onClose: () => void;
	} = $props();

	let box = $state<HTMLElement | null>(null);
	let width = $state(240);
	let height = $state(320);
	let viewport = $state({ w: 1440, h: 900 });

	// Flip rather than clip. Measured with the canvas menu at bottom right:
	// without this, 180px fell outside the viewport and the bottom four rows were
	// unreachable.
	let place = $derived({
		left: x + width + 8 > viewport.w ? Math.max(4, x - width) : x,
		top: upward
			? Math.max(4, y - height)
			: y + height + 8 > viewport.h
				? Math.max(4, viewport.h - height - 8)
				: y
	});

	/** Only the rows you can land on. */
	let choosable = $derived(
		menu.flatMap((groep) =>
			groep.items.filter((item): item is MenuItem => item !== 'separator' && !item.off)
		)
	);
	let cursor = $state(-1);
	let openSub = $state<string | null>(null);

	function choose(item: MenuItem) {
		if (item.off) return;
		if ('items' in item) {
			openSub = openSub === item.id ? null : item.id;
			return;
		}
		onClose();
		item.run();
	}

	function step(direction: number) {
		if (!choosable.length) return;
		cursor = (cursor + direction + choosable.length) % choosable.length;
		openSub = null;
	}

	function onKey(event: KeyboardEvent) {
		const keys = ['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter', ' ', 'Escape', 'ArrowRight', 'ArrowLeft'];
		if (!keys.includes(event.key)) return;
		event.preventDefault();
		event.stopPropagation();
		if (event.key === 'Escape') return onClose();
		if (event.key === 'ArrowDown') return step(1);
		if (event.key === 'ArrowUp') return step(-1);
		if (event.key === 'Home') return (cursor = 0);
		if (event.key === 'End') return (cursor = choosable.length - 1);
		const current = choosable[cursor];
		if (!current) return;
		if (event.key === 'ArrowRight') {
			if ('items' in current) openSub = current.id;
			return;
		}
		if (event.key === 'ArrowLeft') {
			openSub = null;
			return;
		}
		choose(current);
	}

	$effect(() => {
		box?.focus();
	});
</script>

<svelte:window bind:innerWidth={viewport.w} bind:innerHeight={viewport.h} />

<!-- Clicking outside closes it. Its own layer underneath, because a document
     listener would also catch the very click that opened the menu. -->
<div class="backdrop" role="presentation" oncontextmenu={(e) => { e.preventDefault(); onClose(); }} onpointerdown={onClose}></div>

<div
	class="menu"
	role="menu"
	tabindex="-1"
	bind:this={box}
	bind:clientWidth={width}
	bind:clientHeight={height}
	style="left: {place.left}px; top: {place.top}px"
	onkeydown={onKey}
	oncontextmenu={(e) => e.preventDefault()}
>
	{#each menu as group, groupIndex (group.title ?? groupIndex)}
		{#if groupIndex > 0}<hr />{/if}
		{#if group.title}<p class="head">{group.title}</p>{/if}
		{#each group.items as item, i (item === 'separator' ? `s${i}` : item.id)}
			{#if item === 'separator'}
				<hr />
			{:else}
				{@const index = choosable.indexOf(item)}
				<div class="rowwrap" class:sub={'items' in item}>
					<button
						class="row"
						class:here={index >= 0 && index === cursor}
						class:danger={item.danger}
						role={'items' in item ? 'menuitem' : item.on === undefined ? 'menuitem' : 'menuitemcheckbox'}
						aria-haspopup={'items' in item ? 'menu' : undefined}
						aria-expanded={'items' in item ? openSub === item.id : undefined}
						aria-checked={item.on === undefined ? undefined : item.on}
						disabled={Boolean(item.off)}
						title={item.off || item.explain}
						onpointerenter={() => {
							if (index >= 0) cursor = index;
							openSub = 'items' in item ? item.id : null;
						}}
						onclick={() => choose(item)}
					>
						<span class="check" aria-hidden="true">
							{#if item.on}✓{/if}
						</span>
						<span class="text">{item.label}</span>
						{#if 'items' in item}
							<span class="arrow" aria-hidden="true">›</span>
						{:else if item.key}
							<span class="key mono">{item.key}</span>
						{/if}
					</button>

					{#if 'items' in item && openSub === item.id}
						<!-- The submenu opens to the right, or to the left when there is no
						     room. `grid` is for aligning: eight icons in two rows of four,
						     exactly as they stood in the panel, so the muscle-memory order
						     survives. -->
						<div
							class="submenu"
							class:grid={item.grid}
							class:leftward={place.left + width + 220 > viewport.w}
							role="menu"
						>
							{#each item.items as child (child.id)}
								<button
									class="row"
									class:tile={item.grid}
									role="menuitem"
									disabled={Boolean(child.off)}
									title={child.off || child.label}
									aria-label={child.label}
									onclick={() => {
										onClose();
										child.run();
									}}
								>
									{#if item.grid && child.icon}
										<ArrangeIcon name={child.icon} size={19} />
									{:else}
										<span class="check" aria-hidden="true">{#if child.on}✓{/if}</span>
										<span class="text">{child.label}</span>
										{#if child.key}<span class="key mono">{child.key}</span>{/if}
									{/if}
								</button>
							{/each}
						</div>
					{/if}
				</div>
			{/if}
		{/each}
	{/each}
</div>

<style>
	.backdrop {
		position: fixed;
		inset: 0;
		z-index: 90;
	}
	.menu {
		position: fixed;
		z-index: 91;
		min-width: 232px;
		max-width: 320px;
		padding: 4px;
		background: var(--surface-1);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		box-shadow: var(--shadow-float);
		font-size: var(--text-sm);
	}
	.menu:focus-visible {
		outline: none;
	}
	.head {
		margin: 4px 8px 2px;
		font-size: var(--text-xs);
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--text-2);
	}
	hr {
		margin: 4px 6px;
		border: none;
		border-top: 1px solid var(--line);
	}
	.rowwrap {
		position: relative;
	}
	.row {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		width: 100%;
		padding: 6px 8px;
		border-radius: var(--radius-field);
		text-align: left;
		color: var(--text-1);
		background: none;
		border: none;
	}
	/* Hover and keyboard get the same marking: there is one "you are here", not a
	   mouse version and a keyboard version. */
	.row.here:not(:disabled) {
		background: var(--surface-2);
	}
	.row:disabled {
		color: var(--text-2);
		opacity: 0.5;
		cursor: default;
	}
	.row.danger:not(:disabled) {
		color: var(--danger);
	}
	.row.danger.here:not(:disabled) {
		background: color-mix(in srgb, var(--danger) 10%, var(--surface-1));
	}
	.check {
		flex: none;
		width: 12px;
		font-size: 12px;
		color: var(--accent);
	}
	.text {
		flex: 1;
		min-width: 0;
	}
	/* The shortcut sits right, in its own column, and is grey: it is a hint, not
	   the name of the row. */
	.key {
		flex: none;
		font-size: var(--text-xs);
		color: var(--text-2);
		letter-spacing: 0.02em;
	}
	.arrow {
		flex: none;
		color: var(--text-2);
	}
	.submenu {
		position: absolute;
		left: 100%;
		top: -4px;
		min-width: 200px;
		padding: 4px;
		background: var(--surface-1);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		box-shadow: var(--shadow-float);
		z-index: 2;
	}
	.submenu.leftward {
		left: auto;
		right: 100%;
	}
	.submenu.grid {
		display: grid;
		grid-template-columns: repeat(4, 34px);
		gap: 2px;
		min-width: 0;
	}
	.row.tile {
		display: grid;
		place-items: center;
		width: 34px;
		height: 34px;
		padding: 0;
		color: var(--text-1);
	}
</style>
