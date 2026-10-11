<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';

	/**
	 * A number with − and +.
	 *
	 * The browser's own spinner is two pixels tall and unusable with gloves on; beside a
	 * running laser you would rather not type. See DESIGN-SYSTEM, "Number input is a
	 * stepper everywhere".
	 */
	let {
		label,
		value = $bindable(),
		step = 1,
		min = null,
		max = null,
		unit = null,
		disabled = false,
		why = undefined,
		compact = false,
		ariaLabel = undefined,
		placeholder = undefined,
		note = undefined,
		stepsDisabled = undefined,
		stepLabel = undefined,
		onstep = undefined,
		onchange
	}: {
		label: string;
		/** As a string, so that a half-typed number ("1.") does not jump away. */
		value: string;
		step?: number;
		min?: number | null;
		max?: number | null;
		/**
		 * The unit, which stands with the label and never in a column of its own.
		 *
		 * Where the label is a word it stands in the label — "Length per bridge (mm)"; where
		 * the label is a letter the label has no room for it and it stands in the box,
		 * behind the number, as a cap — "W [ 120.0 |mm ]". Two placements, one rule, and the
		 * form of the field decides which: `compact` is the letter case. What it replaced
		 * was four placements with no rule at all — an "mm" column three columns from its
		 * number, a "°" in the box, a "(mm)" in a label and a DPI with nothing.
		 */
		unit?: string | null;
		disabled?: boolean;
		/** Why it is off. A stepper that greys without a word is the same riddle as a
		 *  grey button, and there is more of it here: three controls go dead at once. */
		why?: string;
		/**
		 * The narrow form: the label stands beside the field instead of above it, and the
		 * unit moves into the box behind the number.
		 *
		 * For a label that is one letter — W, H, X, Y, ∠ — a label row of its own costs a
		 * whole line for two characters. Everything else stays the same as the roomy form:
		 * one type size, one field height, the same two buttons. That is the point: the
		 * card used to hold three unrelated number fields, and now it holds one component
		 * whose label sits where the label's own length puts it.
		 */
		compact?: boolean;
		/** The name a screen reader hears where the visible label is a letter. */
		ariaLabel?: string;
		/** What stands in the box when there is no one value to show. */
		placeholder?: string;
		/** The title while the field is live; `why` takes over as soon as it is off. */
		note?: string;
		/** The buttons on while the field itself is off — the angle of a selection whose
		 *  shapes disagree can be stepped, but not typed. Defaults to `disabled`. */
		stepsDisabled?: boolean;
		/**
		 * What the two buttons are called, where "increase this value" is not what they do.
		 *
		 * Stepping the angle of several shapes turns each of them by a degree; the field
		 * beside it is then empty and shows "—", so "Increase Angle in degrees" names a
		 * value that is not there. A caller that hands the step on (see `onstep`) says in
		 * its own words what the button does, and the words stand in the tooltip as well as
		 * in the screen reader.
		 */
		stepLabel?: (direction: number) => { title: string; aria: string };
		/**
		 * The step, handed to the caller instead of applied here.
		 *
		 * For a value that is not simply this field's own number: stepping the angle of
		 * several shapes turns each of them by a degree, which is not the same as writing
		 * one angle over all of them.
		 */
		onstep?: (direction: number) => void;
		/** For fields that have to go straight to the machine rather than to a form that
		 *  is saved later. Does not fire while typing. */
		onchange?: (value: string) => void;
	} = $props();

	let stepsOff = $derived(stepsDisabled ?? disabled);
	// The − and + are Icon's own paths, drawn inline: this field is rendered on its own
	// by `tests/numberfield.test.ts`, which compiles this one file and nothing it imports.
	let named = $derived(ariaLabel ?? label);

	// The label has to hang off the input explicitly. A <label> that wraps its controls
	// picks the *first* labelable descendant — and here that is the − button, not the
	// field. Consequence before this fix: clicking the words "Width (mm)" lowered the
	// width by one step, and the field itself had no accessible name at all ("textbox:
	// 609.6").
	const id = $props.id();

	function set(direction: number) {
		if (onstep) {
			onstep(direction);
			return;
		}
		const now = Number(value);
		const basis = Number.isFinite(now) ? now : 0;
		let fresh = basis + direction * step;
		if (min !== null) fresh = Math.max(min, fresh);
		if (max !== null) fresh = Math.min(max, fresh);
		// Floating point leaves 0.1 + 0.2 as 0.30000000000000004.
		value = String(Math.round(fresh * 1000) / 1000);
		onchange?.(value);
	}

	/**
	 * Arrow keys on the field itself increase and decrease.
	 *
	 * This is the counterpart of `tabindex="-1"` on the two buttons below. Were those in
	 * the tab order, one field further would cost three Tabs and on the way you would land
	 * on the + of the field you just left and on the − of the next one. In a form with six
	 * measures that is eighteen Tabs to fill in six of them.
	 *
	 * Taking them out is only allowed because their work can be done here: an ordinary
	 * `<input type=number>` does exactly this — its spinner is not focusable and the arrows
	 * step. The buttons keep their names and stay operable with a screen reader or
	 * pointer — just not with Tab any more.
	 *
	 * Home and End do *not* jump to the bounds, and that is deliberate. This is a text box
	 * with `inputmode="decimal"`, so Home is what it is everywhere else on the machine:
	 * the caret before the first digit — what you press to correct the 1 of "142.5".
	 * Measured while it wrote `min`: one Home in the width of a 60 × 40 mm rectangle left
	 * the shape 0.1 × 0.067 mm, committed, with no refusal and no sentence; End in the
	 * image DPI set 2000. A keystroke that resizes the work has no undo you knew to reach
	 * for.
	 */
	function onKey(event: KeyboardEvent) {
		if (disabled) return;
		if (event.key === 'ArrowUp') set(1);
		else if (event.key === 'ArrowDown') set(-1);
		else return;
		// Otherwise the window below scrolls along with Arrow Up.
		event.preventDefault();
	}
</script>

<div class="field" class:compact class:off={disabled} title={disabled ? why : note}>
	<label class="name" for={id}
		>{label}{#if unit && !compact}{' '}({unit}){/if}</label
	>
	<span class="stepper">
		<button
			type="button"
			tabindex="-1"
			disabled={stepsOff}
			title={stepsOff ? why : stepLabel?.(-1).title}
			aria-label={stepLabel?.(-1).aria ?? t('field.decrease', { label: named })}
			onclick={() => set(-1)}><svg class="icon-svg" width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14" /></svg></button
		>
		<input
			{id}
			class="mono"
			type="text"
			inputmode="decimal"
			bind:value
			{disabled}
			{placeholder}
			aria-label={ariaLabel}
			title={disabled ? why : note}
			onkeydown={onKey}
			onchange={() => onchange?.(value)}
		/>
		{#if unit && compact}
			<span class="suffix" aria-hidden="true">{unit}</span>
		{/if}
		<button
			type="button"
			tabindex="-1"
			disabled={stepsOff}
			title={stepsOff ? why : stepLabel?.(1).title}
			aria-label={stepLabel?.(1).aria ?? t('field.increase', { label: named })}
			onclick={() => set(1)}><svg class="icon-svg" width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg></button
		>
	</span>
</div>

<style>
	/* min-width: 0 at all three levels. Without that the input keeps its own width of
	   ~20 characters and the stepper runs out of a narrow column — in the layers panel it
	   stuck 28px outside the panel. */
	.field { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-1); min-width: 0; }
	.name { font-size: var(--text-xs); color: var(--text-2); }

	/*
	 * One object: the well of the global field drawn once around all three parts, with
	 * hairlines between them. The input inside gives up its own well — two borders and
	 * two radii side by side read as three controls — and its focus ring moves to the
	 * whole, so the ring is the global one and goes round what you are typing into.
	 */
	.stepper {
		display: flex;
		min-width: 0;
		min-height: max(32px, var(--target-min));
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		transition: border-color var(--transition);
	}
	.stepper:hover:not(:focus-within) { border-color: color-mix(in srgb, var(--text-2) 50%, var(--line)); }
	.stepper:has(input:focus-visible) {
		outline: 2px solid var(--accent);
		outline-offset: 1px;
		border-color: var(--accent);
	}
	.stepper input {
		flex: 1;
		min-width: 0;
		min-height: 0;
		text-align: center;
		font-size: var(--text-sm);
		padding: var(--space-1h) var(--space-1);
		border: 0;
		border-radius: 0;
		background: transparent;
	}
	.stepper input:focus-visible { outline: none; background: transparent; }
	.stepper button {
		flex: none;
		display: grid;
		place-items: center;
		width: max(32px, var(--target-min));
		color: var(--text-1);
		transition: background var(--transition);
	}
	.stepper button:first-child {
		border-inline-end: 1px solid var(--line);
		border-radius: var(--radius-field) 0 0 var(--radius-field);
	}
	.stepper button:last-child {
		border-inline-start: 1px solid var(--line);
		border-radius: 0 var(--radius-field) var(--radius-field) 0;
	}
	.stepper button:hover:not(:disabled) { background: var(--hover); }
	/* Off is drained, like every control: the muted ink, no fill change, nothing faded. */
	.stepper button:disabled { color: var(--text-2); cursor: not-allowed; }
	.field.off .stepper:not(:hover) { border-color: var(--line); }

	/* ── The narrow form ──────────────────────────────────────────────────────
	   Label beside the field, unit behind the number, and nothing else different:
	   same type size, same padding, same buttons, so a card that holds both forms
	   still holds one kind of number field. */
	.field.compact {
		grid-template-columns: auto minmax(0, 1fr);
		align-items: center;
		gap: var(--space-2);
	}
	.field.compact .name {
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		text-align: center;
		min-width: 1.1em;
	}
	/* Where the label is a letter the unit belongs *in* the box, behind the number. As a
	   column of its own beside the grid it stood three columns from the number it belongs
	   to. The roomy form writes it in its label instead, because there it fits and a cap
	   would repeat the box's own edge; see the `unit` prop for the rule. */
	.stepper .suffix {
		display: grid;
		place-items: center;
		flex: none;
		padding-inline: 0 var(--space-2);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.stepper:has(.suffix) input { padding-inline-end: var(--space-1); text-align: right; }
</style>
