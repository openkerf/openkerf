<script lang="ts" generics="T">
	/**
	 * One choice from a short, fixed row — as one block, not as separate buttons.
	 *
	 * Separate buttons leave open whether two can be on at once, and which group belongs
	 * together. A continuous bar says both without words. For more than five options a
	 * `<select>` is right (see DESIGN-SYSTEM, pattern guide).
	 */
	let {
		options,
		value = $bindable(),
		label,
		mono = false,
		disabled = false,
		why = undefined
	}: {
		options: { value: T; label: string; title?: string }[];
		value: T;
		label: string;
		mono?: boolean;
		disabled?: boolean;
		/** Why the whole row is off. The options keep their own titles; this is the one
		 *  the reader needs when none of them can be pressed. */
		why?: string;
	} = $props();

	let row: HTMLDivElement | undefined = $state();
	let chosen = $derived(Math.max(0, options.findIndex((option) => option.value === value)));

	/**
	 * A radio group is one stop in the Tab order, and the arrows move the choice — the
	 * way the browser's own radios and the panel's tabs behave. Tabbing through every
	 * answer to one question was the odd one out.
	 */
	function onKey(event: KeyboardEvent, index: number) {
		const forward = event.key === 'ArrowRight' || event.key === 'ArrowDown';
		const back = event.key === 'ArrowLeft' || event.key === 'ArrowUp';
		if (!forward && !back) return;
		event.preventDefault();
		const count = options.length;
		const next = (index + (forward ? 1 : -1) + count) % count;
		value = options[next].value;
		row?.querySelectorAll<HTMLButtonElement>('button')[next]?.focus();
	}
</script>

<div class="segmented" class:mono role="radiogroup" aria-label={label} bind:this={row}>
	{#each options as option, index (option.label)}
		<button
			type="button"
			role="radio"
			aria-checked={value === option.value}
			class:on={value === option.value}
			tabindex={index === chosen ? 0 : -1}
			title={disabled ? why : option.title}
			{disabled}
			onkeydown={(event) => onKey(event, index)}
			onclick={() => (value = option.value)}
		>{option.label}</button>
	{/each}
</div>

<style>
	.segmented {
		display: inline-flex;
		/* One border around the whole, hairlines in between: it is one thing. */
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
	}
	.segmented.mono button { font-family: var(--font-mono); }
	button {
		flex: 1;
		min-width: 0;
		min-height: var(--target-min);
		padding: var(--space-2) var(--space-3);
		font: inherit;
		font-size: var(--text-xs);
		color: var(--text-2);
		background: transparent;
		border: 0;
		border-left: 1px solid var(--line);
		white-space: nowrap;
	}
	/* The ends follow the row's corner themselves, rather than the row clipping them:
	   a clipped row would cut the focus ring off its outer segments. */
	button:first-child { border-left: 0; border-radius: calc(var(--radius-field) - 1px) 0 0 calc(var(--radius-field) - 1px); }
	button:last-child { border-radius: 0 calc(var(--radius-field) - 1px) calc(var(--radius-field) - 1px) 0; }
	button:only-child { border-radius: calc(var(--radius-field) - 1px); }
	button:focus-visible { position: relative; z-index: 1; }
	button:hover:not(:disabled) { background: var(--surface-2); color: var(--text-1); }
	/* Off is drained, not faded: the muted ink on the raised grey, and the chosen one
	   keeps a fill — in ink, not in teal — so it still says which it is. */
	button:disabled { background: var(--surface-2); color: var(--text-2); cursor: not-allowed; }
	/* The chosen state is filled, not outlined: then nothing jumps and it can be seen
	   from a metre away too. */
	button.on {
		background: var(--accent);
		color: var(--accent-ink);
		font-weight: 500;
	}
	button.on:hover { background: var(--accent); color: var(--accent-ink); }
	button.on:disabled { background: var(--text-2); color: var(--on-color); }
</style>
