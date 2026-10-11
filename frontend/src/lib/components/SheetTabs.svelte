<script lang="ts">
	import NumberField from './NumberField.svelte';
	import Icon from './Icon.svelte';
	import Why from './Why.svelte';
	import { i18n, t } from '$lib/i18n/index.svelte';
	import type { SheetStore } from '$lib/sheets.svelte';
	import type { LibraryStore } from '$lib/library.svelte';

	let {
		sheets,
		library,
		canEdit = false,
		elements = 0,
		onSwitched,
		onEditMaterial
	}: {
		sheets: SheetStore;
		library: LibraryStore;
		canEdit?: boolean;
		/** How much is on the active sheet — the design on screen. Only that sheet
		 *  can be deleted (the editor opens nowhere else). Serves as a fallback here:
		 *  at the moment of deleting, `count()` asks the server, because this value
		 *  lags briefly after a sheet switch. */
		elements?: number;
		onSwitched?: () => void;
		/** Opens the top bar's material dialog — the same place, because that is where
		 *  this choice belongs (decision B1). */
		onEditMaterial?: () => void;
	} = $props();

	let editing = $state<string | null>(null);
	/**
	 * Confirmation before throwing work away.
	 *
	 * Deleting a sheet took the design on it along without a single question —
	 * exactly the kind of loss you only find out about once it has happened. On an
	 * empty sheet it stays one click: there is nothing to lose then, and asking a
	 * question about nothing only teaches you to click them away.
	 */
	let bevestigen = $state<string | null>(null);
	$effect(() => {
		// Close the editor or switch sheets and the question is off the table.
		void editing;
		bevestigen = null;
	});

	/** How much goes away, recorded at the moment of asking. */
	let toRemove = $state(0);

	function telling(n: number) {
		return t('sheets.elements', { n });
	}

	/**
	 * Counting at the source, not in the shop window.
	 *
	 * `elements` comes from the design on screen and lags a few hundred ms behind a
	 * sheet switch. That is exactly long enough to mistake a sheet *with* work for an
	 * empty one and throw it away without asking — the failure this repair has to
	 * prevent. If the server drops out, the prop is the best there is.
	 */
	async function countOnServer() {
		try {
			const response = await fetch('/api/design');
			if (!response.ok) return elements;
			const data = await response.json();
			return Array.isArray(data.elements) ? data.elements.length : elements;
		} catch {
			return elements;
		}
	}

	async function askOrGo(id: string) {
		const count = await countOnServer();
		// Empty sheet: no question. There is nothing to lose, and a question about
		// nothing only teaches you to click them away.
		if (count === 0) {
			await verwijder(id);
			return;
		}
		toRemove = count;
		bevestigen = id;
	}

	async function verwijder(id: string) {
		if (await sheets.remove(id)) {
			bevestigen = null;
			editing = null;
			onSwitched?.();
		}
	}

	/**
	 * Adding a sheet leaves you on the current sheet — today.
	 *
	 * That is why there was no `onSwitched` here. But that is an assumption about the
	 * API, not something this component sees: if `/api/sheets` ever does activate the
	 * new sheet, the canvas shows the contents of the *previous* sheet while the tab
	 * points at the new one — a screen that agrees with itself and not with the
	 * engine. So we simply check whether the active sheet has changed.
	 */
	async function voegToe() {
		const was = sheets.active?.id ?? null;
		if (await sheets.add()) {
			if ((sheets.active?.id ?? null) !== was) onSwitched?.();
		}
	}

	async function go(id: string) {
		if (sheets.active?.id === id) {
			editing = editing === id ? null : id;
			return;
		}
		if (await sheets.activate(id)) onSwitched?.();
	}

	function materialName(id: number | null) {
		return library.materials.find((m) => m.id === id)?.name ?? null;
	}
</script>

<div class="sheets">
	<!-- One row of sheets, like a slicer's plates. Every sheet is a document of its
	     own: what you see is exactly what gets burned. -->
	{#each sheets.sheets as sheet (sheet.id)}
		<button
			class="chip sheet"
			aria-pressed={sheet.active}
			disabled={sheets.busy}
			title="{sheet.name} — {i18n.number(sheet.width_mm)} × {i18n.number(sheet.height_mm)} mm{materialName(
				sheet.material_id
			)
				? ` · ${materialName(sheet.material_id)}`
				: ''}"
			onclick={() => go(sheet.id)}
		>
			<span class="name">{sheet.name}</span>
			<span class="size mono">{i18n.number(sheet.width_mm)}×{i18n.number(sheet.height_mm)}</span>
		</button>
	{/each}

	{#if canEdit}
		<button
			class="chip sheet add"
			disabled={sheets.busy}
			title={t('sheets.addSheet')}
			aria-label={t('sheets.addSheet')}
			onclick={voegToe}
		><Icon name="plus" /></button>
	{/if}

	{#if sheets.error}
		<span class="refusal">{sheets.error}</span>
	{/if}
</div>

{#if editing && sheets.active && canEdit}
	{@const sheet = sheets.active}
	<div class="editor">
		<label class="field-label">
			<span>{t('panel.name')}</span>
			<input
				type="text"
				value={sheet.name}
				onchange={(e) => sheets.update(sheet.id, { name: e.currentTarget.value })}
			/>
		</label>
		<label class="field-label">
			<span>{t('gen.width')}</span>
			<input
				class="mono"
				type="number"
				step="10"
				min="5"
				value={sheet.width_mm}
				onchange={(e) => sheets.update(sheet.id, { width_mm: Number(e.currentTarget.value) })}
			/>
		</label>
		<label class="field-label">
			<span>{t('gen.height')}</span>
			<input
				class="mono"
				type="number"
				step="10"
				min="5"
				value={sheet.height_mm}
				onchange={(e) => sheets.update(sheet.id, { height_mm: Number(e.currentTarget.value) })}
			/>
		</label>
		<!--
			What a plate larger than the bed costs in room.

			The engine layer has validated these three since tiling existed, and refuses
			with sentences like "Make the overlap at least 12 mm" — an instruction for
			something no screen offered. They belong here, beside the size they are about:
			a value you set and read back, on the sheet it applies to.

			Steppers, not bare number inputs: DESIGN-SYSTEM, "number input is a stepper
			everywhere" — you set these standing at a machine.
		-->
		<p class="label-section wide">{t('sheets.tiling.head')}</p>
		<div class="wide"><Why>{t('sheets.tiling.why')}</Why></div>
		<div class="wide three">
			<NumberField
				label={t('sheets.tiling.margin')}
				value={String(sheet.tiling?.margin_mm ?? 10)}
				step={1}
				min={0}
				max={100}
				onchange={(v) => sheets.update(sheet.id, { tiling: { margin_mm: Number(v) } })}
			/>
			<NumberField
				label={t('sheets.tiling.overlap')}
				value={String(sheet.tiling?.overlap_mm ?? 25)}
				step={1}
				min={0}
				onchange={(v) => sheets.update(sheet.id, { tiling: { overlap_mm: Number(v) } })}
			/>
			<NumberField
				label={t('sheets.tiling.marker')}
				value={String(sheet.tiling?.marker_size_mm ?? 8)}
				step={1}
				min={1}
				onchange={(v) => sheets.update(sheet.id, { tiling: { marker_size_mm: Number(v) } })}
			/>
		</div>

		<!-- Material is not filled in a second time here. It is in the top bar, because
		     everything downstream reads it there; two places to choose the same thing
		     only raises the question which is the real one. -->
		<label class="field-label wide">
			<span>{t('library.material')}</span>
			<button class="btn mini material" onclick={() => onEditMaterial?.()}>
				{materialName(sheet.material_id) ?? t('sheets.materialNotFilled')}{sheet.thickness_mm ===
				null
					? ''
					: ` · ${i18n.number(sheet.thickness_mm)} mm`}
			</button>
		</label>
		<button
			class="btn mini danger drop"
			disabled={sheets.sheets.length < 2 || sheets.busy}
			title={sheets.sheets.length < 2 ? t('sheets.needsOne') : undefined}
			onclick={() => askOrGo(sheet.id)}
		>{t('sheets.removeSheet')}</button>
		<button class="btn mini close" onclick={() => (editing = null)}>{t('common.done')}</button>
	</div>

	{#if bevestigen === sheet.id}
		<!-- The question stands where the button stands, with the count in it: "7
		     elements" is the difference between a formality and a warning. -->
		<div class="confirm" role="alertdialog" aria-label={t('sheets.removeSheet')}>
			<p>{t('sheets.removeAsk', { sheet: sheet.name, what: telling(toRemove) })}</p>
			<div class="ask-actions">
				<button class="btn mini" onclick={() => (bevestigen = null)}>{t('common.cancel')}</button>
				<button class="btn mini danger" disabled={sheets.busy} title={sheets.busy ? t('reason.busy') : undefined} onclick={() => verwijder(sheet.id)}>
					{sheets.busy
						? t('common.busy')
						: t('sheets.removeConfirm', { what: telling(toRemove) })}
				</button>
			</div>
		</div>
	{/if}
{/if}

<style>
	.sheets {
		flex: none;
		display: flex;
		align-items: center;
		gap: var(--space-1);
		padding: var(--space-1) var(--space-3);
		background: var(--surface-1);
		border-bottom: 1px solid var(--line);
		overflow-x: auto;
	}
	/* A sheet is the shared chip: pressed is the current sheet, in the accent tint and
	   its edge, never the accent as text (accent on its tint only reaches 4.24:1 and
	   these are small letters). The weight is the third sign beside tint and
	   aria-pressed. */
	.sheet {
		flex: none;
		align-items: baseline;
		gap: var(--space-2);
	}
	.sheet[aria-pressed='true'] {
		font-weight: 600;
	}
	/* No opacity on text: that lowers the contrast unpredictably. The size is
	   secondary, but it has to stay readable. */
	.sheet .size { color: var(--text-2); }
	/* Reachable with a finger, gloved as well. */
	.sheet.add { align-items: center; min-width: max(32px, var(--target-min)); justify-content: center; }
	.refusal { margin: 0; }
	.editor {
		flex: none;
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		gap: var(--space-2);
		padding: var(--space-2) var(--space-3);
		background: var(--surface-2);
		border-bottom: 1px solid var(--line);
	}
	/* The wells sit on the editor's grey, so they take the panel white to stay wells. */
	.editor input { background: var(--surface-1); }
	/* Between two input fields a button in ordinary text colour looks like a field
	   that is not taking part; this one is a door to the material window. */
	.editor .material { justify-content: flex-start; }
	/* The tiling row: a heading, a sentence and the three fields in a line. `wide`
	   breaks the flex row, so each of the three parts starts on its own. */
	.editor .wide { flex-basis: 100%; }
	.editor .label-section { margin-top: var(--space-2); }
	.editor .three { display: flex; gap: var(--space-2); }
	.editor input[type='text'] { width: 9em; }
	.editor input[type='number'] { width: 5em; }
	/* The question belongs below the button that asks it, not in a dialog in the
	   middle of the screen: you keep looking at the same strip. Tinted as the danger
	   it asks about, not striped. */
	.confirm {
		flex: none;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-2) var(--space-3);
		background: var(--danger-tint);
		border-bottom: 1px solid var(--danger-edge);
	}
	.confirm p { margin: 0; font-size: var(--text-xs); color: var(--text-1); }
	/* The row itself is the shared ask row in tokens.css, which also keeps the two
	   outcomes 24 px apart — they exclude each other and one of them is irreversible.
	   All this says is that it hangs at the end of the line the question is on. */
	.ask-actions { margin-left: auto; }
	.close { margin-left: auto; }
</style>
