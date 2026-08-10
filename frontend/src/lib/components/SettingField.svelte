<script lang="ts">
	import type { SettingField } from '$lib/machines.svelte';

	let { field, value = $bindable() }: { field: SettingField; value: unknown } = $props();
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
		<input
			class="mono"
			type="number"
			step={field.type === 'int' ? 1 : 'any'}
			value={Number(value ?? 0)}
			onchange={(e) => (value = e.currentTarget.value)}
		/>
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
		padding: 7px 9px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
		width: 100%;
	}
	input[type='checkbox'] {
		width: 18px;
		height: 18px;
		accent-color: var(--accent);
		justify-self: start;
	}
</style>
