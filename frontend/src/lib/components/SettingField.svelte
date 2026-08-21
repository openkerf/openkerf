<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
	import type { SettingField } from '$lib/machines.svelte';

	let { field, value = $bindable() }: { field: SettingField; value: unknown } = $props();

	/** One step: whole numbers for int, tenths for float. */
	function step(direction: number) {
		const grootte = field.type === 'int' ? 1 : 0.1;
		const now = Number(value ?? 0);
		const fresh = now + direction * grootte;
		// Floating point turns 0.1 + 0.2 into something with seventeen digits.
		value = field.type === 'int' ? String(Math.round(fresh)) : String(Math.round(fresh * 1000) / 1000);
	}
</script>

<label class="field">
	<span class="label">{field.label}</span>

	{#if field.type === 'bool'}
		<input type="checkbox" checked={Boolean(value)} onchange={(e) => (value = e.currentTarget.checked)} />
	{:else if field.options?.length}
		<select value={String(value ?? '')} onchange={(e) => (value = e.currentTarget.value)}>
			{#each field.options as option (option)}
				<option value={option}>{option}</option>
			{/each}
		</select>
	{:else if field.type === 'int' || field.type === 'float'}
		<!-- A number with buttons: on a touch screen the browser's own spinner is two
		     pixels tall, and unusable with gloves on. -->
		<div class="teller">
			<button type="button" aria-label={t('field.decrease', { label: field.label })} onclick={() => step(-1)}>−</button>
			<input
				class="mono"
				type="number"
				step={field.type === 'int' ? 1 : 'any'}
				value={Number(value ?? 0)}
				onchange={(e) => (value = e.currentTarget.value)}
			/>
			<button type="button" aria-label={t('field.increase', { label: field.label })} onclick={() => step(1)}>+</button>
		</div>
	{:else}
		<input class="mono" type="text" value={String(value ?? '')} onchange={(e) => (value = e.currentTarget.value)} />
	{/if}

	{#if field.tip}
		<span class="tip">{field.tip}</span>
	{/if}
</label>

<style>
	.field {
		display: grid;
		gap: var(--space-1);
		margin-bottom: var(--space-3);
	}
	.label {
		font-weight: 500;
	}
	.tip {
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	input[type='text'],
	input[type='number'],
	select {
		font: inherit;
		padding: 8px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
		width: 100%;
	}
	/* The browser's spinner gone: it sits *beside* our buttons and confuses. */
	.teller { display: flex; }
	.teller input {
		border-radius: 0;
		border-left: 0;
		border-right: 0;
		text-align: center;
		-moz-appearance: textfield;
		appearance: textfield;
	}
	.teller input::-webkit-outer-spin-button,
	.teller input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
	.teller button {
		flex: none;
		width: 40px;
		font: inherit;
		font-size: var(--text-md);
		border: 1px solid var(--line);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.teller button:first-child { border-radius: var(--radius-field) 0 0 var(--radius-field); }
	.teller button:last-child { border-radius: 0 var(--radius-field) var(--radius-field) 0; }
	.teller button:hover { background: var(--surface-1); }

	input[type='checkbox'] {
		width: 18px;
		height: 18px;
		accent-color: var(--accent);
		justify-self: start;
	}
</style>
