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
	let named = $derived(ariaLabel ?? label);

	// The label has to hang off the input explicitly. A <label> that wraps its controls
	// picks the *first* labelable descendant — and here that is the − button, not the
	// field. Consequence before this fix: clicking the words "Width (mm)" lowered the
	// width by one step, and the field itself had no accessible name at all ("textbox:
	// 609.6").
	const id = $props.id();

	/**
	 * The last value in the box that was a number.
	 *
	 * The box holds a string so that a half-typed number does not jump away, and a string
	 * can be `abc`. Stepping from that used to fall back to 0 and clamp to `min`:
	 * measured, a raster layer at 500 dpi went to 10 on one click of `+`, committed, with
	 * no refusal and no notice. So nonsense stays in this component and the number that
	 * was there comes back.
	 */
	let lastGood = $state(value);
	$effect(() => {
		if (Number.isFinite(Number(value))) lastGood = value;
	});

	/** Nothing to step from, and nothing to send on: put the last number back. */
	function refuse() {
		value = lastGood;
	}

	function set(direction: number) {
		if (onstep) {
			onstep(direction);
			return;
		}
		const now = Number(value);
		if (!Number.isFinite(now)) {
			refuse();
			return;
		}
		let fresh = now + direction * step;
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
	function commit() {
		if (!Number.isFinite(Number(value))) {
			refuse();
			return;
		}
		onchange?.(value);
	}

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
		>{label}{#if unit && !compact}{' '}<span class="eenheid">({unit})</span>{/if}</label
	>
	<span class="stepper">
		<button
			type="button"
			tabindex="-1"
			disabled={stepsOff}
			title={stepsOff ? why : stepLabel?.(-1).title}
			aria-label={stepLabel?.(-1).aria ?? t('field.decrease', { label: named })}
			onclick={() => set(-1)}>−</button
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
			onchange={commit}
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
			onclick={() => set(1)}>+</button
		>
	</span>
</div>

<style>
	/* min-width: 0 at all three levels. Without that the input keeps its own width of
	   ~20 characters and the stepper runs out of a narrow column — in the layers panel it
	   stuck 28px outside the panel. */
	.field { display: grid; grid-template-columns: minmax(0, 1fr); gap: 4px; min-width: 0; }
	.name { font-size: var(--text-xs); color: var(--text-2); }
	.eenheid { color: var(--text-2); }
	.stepper { display: flex; min-width: 0; }
	.stepper input {
		flex: 1;
		min-width: 0;
		text-align: center;
		font: inherit;
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		padding: 8px 4px;
		border: 1px solid var(--line);
		border-left: 0;
		border-right: 0;
		background: var(--surface-2);
		color: var(--text-1);
	}
	.stepper button {
		flex: none;
		width: 38px;
		font: inherit;
		font-size: var(--text-lg);
		line-height: 1;
		border: 1px solid var(--line);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.stepper button:first-child { border-radius: var(--radius-field) 0 0 var(--radius-field); }
	.stepper button:last-child { border-radius: 0 var(--radius-field) var(--radius-field) 0; }
	.stepper button:hover:not(:disabled) { background: var(--surface-1); }
	.stepper button:disabled, .stepper input:disabled { opacity: 0.5; }

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
	.field.compact.off .name { opacity: 0.5; }
	/* Where the label is a letter the unit belongs *in* the box, behind the number. As a
	   column of its own beside the grid it stood three columns from the number it belongs
	   to. The roomy form writes it in its label instead, because there it fits and a cap
	   would repeat the box's own edge; see the `unit` prop for the rule. */
	.stepper .suffix {
		display: grid;
		place-items: center;
		flex: none;
		padding: 0 var(--space-2) 0 2px;
		font-size: var(--text-xs);
		color: var(--text-2);
		border: 1px solid var(--line);
		border-left: 0;
		border-right: 0;
		background: var(--surface-2);
	}
	.field.off .suffix { opacity: 0.5; }
	.field.compact .stepper input { padding-right: 2px; }
</style>
