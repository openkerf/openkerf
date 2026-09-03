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
		onchange
	}: {
		label: string;
		/** As a string, so that a half-typed number ("1.") does not jump away. */
		value: string;
		step?: number;
		min?: number | null;
		max?: number | null;
		unit?: string | null;
		disabled?: boolean;
		/** Why it is off. A stepper that greys without a word is the same riddle as a
		 *  grey button, and there is more of it here: three controls go dead at once. */
		why?: string;
		/** For fields that have to go straight to the machine rather than to a form that
		 *  is saved later. Does not fire while typing. */
		onchange?: (value: string) => void;
	} = $props();

	// The label has to hang off the input explicitly. A <label> that wraps its controls
	// picks the *first* labelable descendant — and here that is the − button, not the
	// field. Consequence before this fix: clicking the words "Width (mm)" lowered the
	// width by one step, and the field itself had no accessible name at all ("textbox:
	// 609.6").
	const id = $props.id();

	function set(direction: number) {
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
	 * step. So anybody not using a mouse loses nothing: Home and End jump to the bounds
	 * where there are any, and the buttons keep their names and stay operable with a screen
	 * reader or pointer — just not with Tab any more.
	 */
	function onKey(event: KeyboardEvent) {
		if (disabled) return;
		if (event.key === 'ArrowUp') set(1);
		else if (event.key === 'ArrowDown') set(-1);
		else if (event.key === 'Home' && min !== null) value = String(min);
		else if (event.key === 'End' && max !== null) value = String(max);
		else return;
		// Otherwise the caret also jumps to the start or end of the text, and on Arrow Up
		// the window below scrolls along.
		event.preventDefault();
		if (event.key === 'Home' || event.key === 'End') onchange?.(value);
	}
</script>

<div class="field" title={disabled ? why : undefined}>
	<label class="name" for={id}>{label}{#if unit}{' '}<span class="eenheid">({unit})</span>{/if}</label>
	<span class="stepper">
		<button
			type="button"
			tabindex="-1"
			{disabled}
			aria-label={t('field.decrease', { label })}
			onclick={() => set(-1)}>−</button
		>
		<input
			{id}
			class="mono"
			type="text"
			inputmode="decimal"
			bind:value
			{disabled}
			title={disabled ? why : undefined}
			onkeydown={onKey}
			onchange={() => onchange?.(value)}
		/>
		<button
			type="button"
			tabindex="-1"
			{disabled}
			aria-label={t('field.increase', { label })}
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
</style>
