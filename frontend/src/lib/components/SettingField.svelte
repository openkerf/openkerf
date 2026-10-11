<script lang="ts">
	import type { SettingField } from '$lib/machines.svelte';
	import NumberField from './NumberField.svelte';

	let { field, value = $bindable() }: { field: SettingField; value: unknown } = $props();

	/**
	 * A number is NumberField, like every other number in the app.
	 *
	 * This file had a stepper of its own — 40 px buttons, a browser spinner hidden by hand,
	 * its own well — that looked almost like the shared one and stepped a float by 0.1
	 * where nothing else did. The shared field takes the step and hands back a string,
	 * which is what this setting stored already.
	 */
	let text = $derived(String(value ?? 0));
</script>

{#if field.type === 'int' || field.type === 'float'}
	<div class="field">
		<NumberField
			label={field.label}
			value={text}
			step={field.type === 'int' ? 1 : 0.1}
			onchange={(fresh) => (value = fresh)}
		/>
		{#if field.tip}
			<p class="help">{field.tip}</p>
		{/if}
	</div>
{:else}
	<label class="field" class:bool={field.type === 'bool'}>
		<span class="field-label">{field.label}</span>

		{#if field.type === 'bool'}
			<input type="checkbox" checked={Boolean(value)} onchange={(e) => (value = e.currentTarget.checked)} />
		{:else if field.options?.length}
			<select value={String(value ?? '')} onchange={(e) => (value = e.currentTarget.value)}>
				{#each field.options as option (option)}
					<option value={option}>{option}</option>
				{/each}
			</select>
		{:else}
			<input class="mono" type="text" value={String(value ?? '')} onchange={(e) => (value = e.currentTarget.value)} />
		{/if}

		{#if field.tip}
			<span class="help">{field.tip}</span>
		{/if}
	</label>
{/if}

<style>
	.field {
		display: grid;
		gap: var(--space-1);
		margin-bottom: var(--space-3);
	}
	.field.bool > input {
		justify-self: start;
	}
</style>
