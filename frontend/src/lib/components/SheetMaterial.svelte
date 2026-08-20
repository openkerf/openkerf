<script lang="ts">
	/**
	 * Waarin dit vel gebrand wordt.
	 *
	 * Besluit B1: materiaal en dikte hangen aan het vel, niet aan een filter in
	 * een venster dat je weer sluit. Alles stroomafwaarts leest het hier: de
	 * bibliotheek filtert erop, het testraster begint ermee, en de pre-flight
	 * kan er een instelling aan toetsen.
	 *
	 * Leeg blijven mag. Wie een restje van onbekende herkomst in de machine legt,
	 * moet niet eerst een naam en een getal hoeven verzinnen om te kunnen werken.
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

	let nieuw = $state('');
	let toevoegen = $state(false);

	// De diktes die op elke zaagtafel liggen. Eén tik in plaats van een getal
	// typen — op een tablet naast de machine scheelt dat een toetsenbord.
	const GANGBAAR = [1, 2, 3, 4, 5, 6, 8, 10];

	let dikte = $derived(sheet.thickness_mm);

	let instellingen = $derived(
		sheet.material_id === null
			? []
			: library.presets.filter(
					(p) =>
						p.material_id === sheet.material_id &&
						(dikte === null ||
							p.thickness_mm === null ||
							Math.abs(p.thickness_mm - dikte) < 0.51)
				)
	);

	function kiesMateriaal(waarde: string) {
		sheets.update(sheet.id, { material_id: waarde ? Number(waarde) : null });
	}

	function kiesDikte(mm: number | null) {
		sheets.update(sheet.id, { thickness_mm: mm });
	}

	async function maakMateriaal() {
		if (!nieuw.trim()) return;
		const created = await library.addMaterial(nieuw.trim());
		if (created) {
			await sheets.update(sheet.id, { material_id: created.id });
			nieuw = '';
			toevoegen = false;
		}
	}
</script>

<div class="wrap">
	<p class="uitleg">
		{t('sheetMat.applies', {
			sheet: sheet.name,
			size: `${sheet.width_mm} × ${sheet.height_mm} mm`
		})}
	</p>

	<label class="veld">
		<span>{t('library.material')}</span>
		<select
			value={sheet.material_id === null ? '' : String(sheet.material_id)}
			disabled={sheets.busy}
			onchange={(e) => kiesMateriaal(e.currentTarget.value)}
		>
			<option value="">{t('sheetMat.notFilled')}</option>
			{#each library.materials as material (material.id)}
				<option value={String(material.id)}>{material.name}</option>
			{/each}
		</select>
	</label>

	{#if toevoegen}
		<div class="nieuw">
			<input
				type="text"
				bind:value={nieuw}
				placeholder={t('library.material.placeholder')}
				aria-label={t('gen.text')}
			/>
			<button class="btn primary" disabled={!nieuw.trim() || library.busy} onclick={maakMateriaal}>
				{t('sheetMat.add')}
			</button>
			<button class="btn" onclick={() => (toevoegen = false)}>{t('common.cancel')}</button>
		</div>
	{:else}
		<button class="link" onclick={() => (toevoegen = true)}>{t('sheetMat.notListed')}</button>
	{/if}

	<div class="veld">
		<!-- The unit in the label, not behind the input: otherwise there is a row of
		     bare numbers whose measure only becomes clear on the right. -->
		<span>{t('sheetMat.thickness')}</span>
		<div class="diktes">
			{#each GANGBAAR as mm (mm)}
				<button
					class="chip"
					aria-pressed={dikte === mm}
					disabled={sheets.busy}
					onclick={() => kiesDikte(dikte === mm ? null : mm)}
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
				value={dikte !== null && !GANGBAAR.includes(dikte) ? dikte : ''}
				onchange={(e) =>
					kiesDikte(e.currentTarget.value === '' ? null : Number(e.currentTarget.value))}
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
		{:else if instellingen.length === 0}
			{t('sheetMat.noPresets')}
		{:else}
			{dikte === null
				? t('sheetMat.presets', { n: instellingen.length })
				: t('sheetMat.presetsAround', {
						n: instellingen.length,
						thickness: i18n.number(dikte)
					})}
		{/if}
	</p>

	<div class="acties">
		<button class="btn primary" onclick={() => onDone?.()}>{t('common.done')}</button>
	</div>
</div>

<style>
	.wrap {
		display: grid;
		gap: var(--space-3);
	}
	.uitleg {
		margin: 0;
		color: var(--text-2);
		font-size: var(--text-sm);
	}
	.veld {
		display: grid;
		gap: var(--space-1h);
	}
	.veld > span {
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
	.nieuw {
		display: flex;
		gap: var(--space-2);
	}
	.nieuw input { flex: 1; min-width: 0; }
	.link {
		justify-self: start;
		color: var(--text-2);
		font-size: var(--text-xs);
		text-decoration: underline;
		text-underline-offset: 3px;
	}
	.link:hover { color: var(--text-1); }
	.diktes {
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
	/* Dezelfde dubbele codering als de vellenbalk: rand én tint én aria-pressed,
	   nooit kleur alleen. */
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
	.acties {
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
