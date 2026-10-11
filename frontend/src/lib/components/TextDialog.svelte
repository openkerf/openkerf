<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
	import Dialog from './Dialog.svelte';
	import FontPicker from './FontPicker.svelte';
	import NumberField from './NumberField.svelte';

	let {
		open = $bindable(),
		initial = null,
		onConfirm
	}: {
		open: boolean;
		/** Filled in when editing existing text. */
		initial?: {
			text: string;
			font: string;
			font_size_mm: number | null;
			spacing: number;
			align: string;
		} | null;
		onConfirm: (options: {
			text: string;
			font: string;
			font_size_mm: number;
			spacing: number;
			align: string;
		}) => void;
	} = $props();

	let text = $state('');
	let font = $state('');
	let size = $state('10');
	let spacing = $state('1');
	let align = $state('start');
	let filled = false;

	// When editing, start with what is there, not with empty fields.
	$effect(() => {
		if (!open) {
			filled = false;
			return;
		}
		if (filled || !initial) return;
		filled = true;
		text = initial.text;
		size = String(initial.font_size_mm ?? 10);
		spacing = String(initial.spacing ?? 1);
		align = initial.align ?? 'start';
		font = '';
	});

	function confirm() {
		if (!text.trim()) return;
		onConfirm({
			text: text.trim(),
			font,
			font_size_mm: Number(size) || 10,
			spacing: Number(spacing) || 1,
			align
		});
		text = '';
		open = false;
	}
</script>

<Dialog title={initial ? t('ux.text.editTitle') : t('text.title')} bind:open size="s">
	<label class="field field-label">
		<span>{t('text.label')}</span>
		<!-- svelte-ignore a11y_autofocus -->
		<input
			type="text"
			bind:value={text}
			autofocus
			placeholder={t('text.placeholder')}
			onkeydown={(e) => {
				if (e.key === 'Enter') confirm();
			}}
		/>
	</label>

	<!-- The same stepper as every other number in the app; the unit is already in the
	     height's label, which is where the roomy form puts it. -->
	<div class="row field">
		<NumberField label={t('text.height')} bind:value={size} step={0.5} min={0.5} />
		<NumberField label={t('text.tracking')} bind:value={spacing} step={0.05} min={0.1} />
	</div>

	<label class="field field-label">
		<span>{t('text.alignment')}</span>
		<select bind:value={align}>
			<option value="start">{t('text.left')}</option>
			<option value="middle">{t('text.centred')}</option>
			<option value="end">{t('text.right')}</option>
		</select>
	</label>

	<FontPicker bind:font sample={text} current={initial?.font ?? null} />

	{#snippet footer()}
		<button class="btn" onclick={() => (open = false)}>{t('common.cancel')}</button>
		<button class="btn primary" disabled={!text.trim()} title={t('reason.needsName')} onclick={confirm}>
			{initial ? t('text.update') : t('text.place')}
		</button>
	{/snippet}
</Dialog>

<style>
	.field {
		margin-bottom: var(--space-3);
	}
	.row {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-3);
	}
</style>
