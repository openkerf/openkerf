<script lang="ts">
	/**
	 * What this sheet is burned into.
	 *
	 * Decision B1: material and thickness hang off the sheet, not off a filter in a dialog
	 * you close again. Everything downstream reads it here: the library filters on it, the
	 * test grid starts with it, and the pre-flight can test a setting against it.
	 *
	 * Staying empty is allowed. Anybody putting an offcut of unknown origin in the machine
	 * should not have to invent a name and a number first in order to work.
	 */
	import { i18n, t } from '$lib/i18n/index.svelte';
	import type { LibraryStore } from '$lib/library.svelte';
	import type { Sheet, SheetStore } from '$lib/sheets.svelte';

	let {
		sheets,
		library,
		sheet,
		onDone
	}: {
		sheets: SheetStore;
		library: LibraryStore;
		sheet: Sheet;
		onDone?: () => void;
	} = $props();

	let fresh = $state('');
	let toevoegen = $state(false);

	// The thicknesses that lie on every saw table. One tap instead of typing a number —
	// on a tablet beside the machine that saves a keyboard.
	const GANGBAAR = [1, 2, 3, 4, 5, 6, 8, 10];

	let thickness = $derived(sheet.thickness_mm);

	let settings = $derived(
		sheet.material_id === null
			? []
			: library.presets.filter(
					(p) =>
						p.material_id === sheet.material_id &&
						(thickness === null ||
							p.thickness_mm === null ||
							Math.abs(p.thickness_mm - thickness) < 0.51)
				)
	);

	function pickMaterial(value: string) {
		sheets.update(sheet.id, { material_id: value ? Number(value) : null });
	}

	function pickThickness(mm: number | null) {
		sheets.update(sheet.id, { thickness_mm: mm });
	}

	async function makeMaterial() {
		if (!fresh.trim()) return;
		const created = await library.addMaterial(fresh.trim());
		if (created) {
			await sheets.update(sheet.id, { material_id: created.id });
			fresh = '';
			toevoegen = false;
		}
	}
</script>

<div class="wrap">
	<p class="hint">
		{t('sheetMat.applies', {
			sheet: sheet.name,
			size: `${sheet.width_mm} × ${sheet.height_mm} mm`
		})}
	</p>

	<label class="field">
		<span>{t('library.material')}</span>
		<select
			value={sheet.material_id === null ? '' : String(sheet.material_id)}
			disabled={sheets.busy}
			onchange={(e) => pickMaterial(e.currentTarget.value)}
		>
			<option value="">{t('sheetMat.notFilled')}</option>
			{#each library.materials as material (material.id)}
				<option value={String(material.id)}>{material.name}</option>
			{/each}
		</select>
	</label>

	{#if toevoegen}
		<div class="fresh">
			<input
				type="text"
				bind:value={fresh}
				placeholder={t('library.material.placeholder')}
				aria-label={t('gen.text')}
			/>
			<button class="btn primary" disabled={!fresh.trim() || library.busy} onclick={makeMaterial}>
				{t('sheetMat.add')}
			</button>
			<button class="btn" onclick={() => (toevoegen = false)}>{t('common.cancel')}</button>
		</div>
	{:else}
		<button class="link" onclick={() => (toevoegen = true)}>{t('sheetMat.notListed')}</button>
	{/if}

	<div class="field">
		<!-- The unit in the label, not behind the input: otherwise there is a row of
		     bare numbers whose measure only becomes clear on the right. -->
		<span>{t('sheetMat.thickness')}</span>
		<div class="thicknesses">
			{#each GANGBAAR as mm (mm)}
				<button
					class="chip"
					aria-pressed={thickness === mm}
					disabled={sheets.busy}
					onclick={() => pickThickness(thickness === mm ? null : mm)}
				>{mm}</button>
			{/each}
			<input
				class="mono anders"
				type="number"
				step="0.1"
				min="0.1"
				max="500"
				placeholder={t('sheetMat.other')}
				aria-label={t('sheetMat.otherAria')}
				value={thickness !== null && !GANGBAAR.includes(thickness) ? thickness : ''}
				onchange={(e) =>
					pickThickness(e.currentTarget.value === '' ? null : Number(e.currentTarget.value))}
			/>
		</div>
	</div>

	{#if sheets.error}
		<p class="error" role="alert">{sheets.error}</p>
	{/if}

	<!-- What this yields, visible at once: the library filters on it later, so the
	     count says whether it is any use to you. -->
	<p class="opbrengst">
		{#if sheet.material_id === null}
			{t('sheetMat.noMaterial')}
		{:else if settings.length === 0}
			{t('sheetMat.noPresets')}
		{:else}
			{thickness === null
				? t('sheetMat.presets', { n: settings.length })
				: t('sheetMat.presetsAround', {
						n: settings.length,
						thickness: i18n.number(thickness)
					})}
		{/if}
	</p>

	<div class="actions">
		<button class="btn primary" onclick={() => onDone?.()}>{t('common.done')}</button>
	</div>
</div>

<style>
	.wrap {
		display: grid;
		gap: var(--space-3);
	}
	.hint {
		margin: 0;
		color: var(--text-2);
		font-size: var(--text-sm);
	}
	.field {
		display: grid;
		gap: var(--space-1h);
	}
	.field > span {
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	select,
	input[type='text'],
	input[type='number'] {
		font: inherit;
		padding: 8px var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		color: var(--text-1);
	}
	.fresh {
		display: flex;
		gap: var(--space-2);
	}
	.fresh input { flex: 1; min-width: 0; }
	.link {
		justify-self: start;
		color: var(--text-2);
		font-size: var(--text-xs);
		text-decoration: underline;
		text-underline-offset: 3px;
	}
	.link:hover { color: var(--text-1); }
	.thicknesses {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-1h);
	}
	.chip {
		min-width: 40px;
		padding: 8px var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		font-variant-numeric: tabular-nums;
	}
	.chip:hover:not(:disabled) { background: var(--surface-2); }
	/* The same double encoding as the sheet bar: border *and* tint *and* aria-pressed,
	   never colour alone. */
	.chip[aria-pressed='true'] {
		border-color: var(--accent);
		font-weight: 600;
		background: color-mix(in srgb, var(--accent) 10%, transparent);
	}
	.anders { width: 6em; }
	.opbrengst {
		margin: 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.error { margin: 0; color: var(--danger); font-size: var(--text-sm); }
	.actions {
		display: flex;
		justify-content: flex-end;
	}
	.btn {
		padding: 8px 16px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		font-weight: 500;
	}
	.btn:hover:not(:disabled) { background: var(--surface-2); }
	.btn.primary {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
	}
	.btn:disabled { opacity: 0.45; cursor: not-allowed; }
</style>
