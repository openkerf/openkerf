<script lang="ts">
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

	async function vraagOfWeg(id: string) {
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
		const voor = sheets.active?.id ?? null;
		if (await sheets.add()) {
			if ((sheets.active?.id ?? null) !== voor) onSwitched?.();
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
			class="sheet"
			aria-pressed={sheet.active}
			disabled={sheets.busy}
			title="{sheet.name} — {sheet.width_mm} × {sheet.height_mm} mm{materialName(
				sheet.material_id
			)
				? ` · ${materialName(sheet.material_id)}`
				: ''}"
			onclick={() => go(sheet.id)}
		>
			<span class="name">{sheet.name}</span>
			<span class="size mono">{sheet.width_mm}×{sheet.height_mm}</span>
		</button>
	{/each}

	{#if canEdit}
		<button
			class="sheet add"
			disabled={sheets.busy}
			title={t('sheets.addSheet')}
			onclick={voegToe}
		>+</button>
	{/if}

	{#if sheets.error}
		<span class="error">{sheets.error}</span>
	{/if}
</div>

{#if editing && sheets.active && canEdit}
	{@const sheet = sheets.active}
	<div class="editor">
		<label>
			<span>{t('panel.name')}</span>
			<input
				type="text"
				value={sheet.name}
				onchange={(e) => sheets.update(sheet.id, { name: e.currentTarget.value })}
			/>
		</label>
		<label>
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
		<label>
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
		<!-- Material is not filled in a second time here. It is in the top bar, because
		     everything downstream reads it there; two places to choose the same thing
		     only raises the question which is the real one. -->
		<label class="wide">
			<span>{t('library.material')}</span>
			<button class="materiaal" onclick={() => onEditMaterial?.()}>
				{materialName(sheet.material_id) ?? t('sheets.materialNotFilled')}{sheet.thickness_mm ===
				null
					? ''
					: ` · ${i18n.number(sheet.thickness_mm)} mm`}
			</button>
		</label>
		<button
			class="drop"
			disabled={sheets.sheets.length < 2 || sheets.busy}
			title={sheets.sheets.length < 2 ? t('sheets.needsOne') : undefined}
			onclick={() => vraagOfWeg(sheet.id)}
		>{t('sheets.removeSheet')}</button>
		<button class="close" onclick={() => (editing = null)}>{t('common.done')}</button>
	</div>

	{#if bevestigen === sheet.id}
		<!-- The question stands where the button stands, with the count in it: "7
		     elements" is the difference between a formality and a warning. -->
		<div class="confirm" role="alertdialog" aria-label={t('sheets.removeSheet')}>
			<p>{t('sheets.removeAsk', { sheet: sheet.name, what: telling(toRemove) })}</p>
			<div class="knoppen">
				<button class="annuleer" onclick={() => (bevestigen = null)}>{t('common.cancel')}</button>
				<button class="weg" disabled={sheets.busy} onclick={() => verwijder(sheet.id)}>
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
		gap: 4px;
		padding: 4px var(--space-3);
		background: var(--surface-1);
		border-bottom: 1px solid var(--line);
		overflow-x: auto;
	}
	.sheet {
		flex: none;
		display: flex;
		align-items: baseline;
		gap: 8px;
		padding: 4px 8px;
		border-radius: 999px;
		border: 1px solid var(--line);
		background: var(--surface-1);
		color: var(--text-1);
		font-size: var(--text-xs);
	}
	.sheet:hover:not(:disabled) { background: var(--surface-2); color: var(--text-1); }
	.sheet[aria-pressed='true'] {
		/* The accent sits in the border and the tint, not in the text: accent colour
		   on an accent tint only reaches 4.24:1 and these are the smallest letters on
		   screen. The active state is still doubly encoded (border + tint +
		   aria-pressed). */
		border-color: var(--accent);
		color: var(--text-1);
		font-weight: 600;
		background: color-mix(in srgb, var(--accent) 10%, transparent);
	}
	/* No opacity on text: that lowers the contrast unpredictably. The size is
	   secondary, but it has to stay readable. */
	.sheet .size { font-size: var(--text-xs); color: var(--text-2); }
	/* Reachable with a finger, gloved as well. */
	.sheet.add { padding: 4px 12px; font-weight: 600; min-width: 44px; }
	.error { font-size: var(--text-xs); color: var(--danger); }
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
	.editor label { display: grid; gap: 2px; font-size: var(--text-xs); color: var(--text-2); }
	.editor input {
		font: inherit;
		font-size: var(--text-xs);
		padding: 4px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		color: var(--text-1);
	}
	.editor .materiaal {
		font-size: var(--text-xs);
		padding: 4px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		/* Between two input fields a button in ordinary text colour looks like a field
		   that is not taking part. The accent colour says something happens when you
		   press it. */
		color: var(--accent-text);
		text-align: left;
	}
	.editor .materiaal:hover { background: var(--surface-2); }
	.editor input[type='text'] { width: 9em; }
	.editor input[type='number'] { width: 5em; }
	.drop,
	.close {
		font-size: var(--text-xs);
		padding: 4px 8px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
	}
	.drop { color: var(--danger); }
	/* The question belongs below the button that asks it, not in a dialog in the
	   middle of the screen: you keep looking at the same strip. */
	.confirm {
		flex: none;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-2) var(--space-3);
		background: var(--surface-2);
		border-bottom: 1px solid var(--line);
		border-left: 3px solid var(--danger-solid);
	}
	.confirm p { margin: 0; font-size: var(--text-xs); color: var(--text-1); }
	.knoppen {
		display: flex;
		/* Two outcomes that exclude each other, and one of them is irreversible: far
		   enough apart not to mis-aim. */
		gap: var(--space-6);
		margin-left: auto;
	}
	.annuleer,
	.weg {
		font-size: var(--text-xs);
		min-height: 32px;
		padding: 4px 12px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
	}
	.annuleer:hover { background: var(--hover); }
	.weg {
		background: var(--danger-solid);
		border-color: var(--danger-solid);
		color: var(--on-color);
		font-weight: 600;
	}
	.weg:hover:not(:disabled) { filter: brightness(1.06); }
	.weg:disabled { opacity: 0.45; cursor: not-allowed; }
	@media (pointer: coarse) {
		.annuleer,
		.weg { min-height: 44px; }
	}
	.drop:disabled { opacity: 0.45; cursor: not-allowed; }
	.close { margin-left: auto; }
</style>
