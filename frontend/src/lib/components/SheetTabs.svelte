<script lang="ts">
	import { i18n, t } from '$lib/i18n/index.svelte';
	import type { SheetStore } from '$lib/sheets.svelte';
	import type { LibraryStore } from '$lib/library.svelte';

	let {
		sheets,
		library,
		canEdit = false,
		elementen = 0,
		onSwitched,
		onEditMaterial
	}: {
		sheets: SheetStore;
		library: LibraryStore;
		canEdit?: boolean;
		/** Hoeveel er op het actieve vel staat — het ontwerp in beeld. Alleen dat
		 *  vel is te verwijderen (de editor opent nergens anders). Dient hier als
		 *  terugval: op het moment van verwijderen telt `tellen()` bij de server,
		 *  want deze waarde loopt na een velwissel even achter. */
		elementen?: number;
		onSwitched?: () => void;
		/** Opent het materiaalvenster van de bovenbalk — dezelfde plek, want daar
		 *  hoort deze keuze thuis (besluit B1). */
		onEditMaterial?: () => void;
	} = $props();

	let editing = $state<string | null>(null);
	/**
	 * Bevestiging vóór het weggooien van werk.
	 *
	 * Een vel verwijderen nam het ontwerp erop mee zonder één ask — precies het
	 * soort verlies waar je pas achter komt als het al gebeurd is. Op een leeg vel
	 * blijft het één klik: dan valt er niets te verliezen, en een ask stellen
	 * over niets leert je alleen ze weg te klikken.
	 */
	let bevestigen = $state<string | null>(null);
	$effect(() => {
		// Sluit de editor of wissel van vel, dan is de ask van de baan.
		void editing;
		bevestigen = null;
	});

	/** Hoeveel er weggaat, vastgelegd op het moment van shouldAsk. */
	let teVerwijderen = $state(0);

	function telling(n: number) {
		return t('sheets.elements', { n });
	}

	/**
	 * Counting at the source, not in the shop window.
	 *
	 * `elementen` komt uit het ontwerp in beeld en loopt een paar honderd ms
	 * achter op een velwissel. Dat is precies lang genoeg om een vel mét werk
	 * voor leeg aan te zien en het zonder ask weg te gooien — de failure die deze
	 * reparatie moet voorkomen. Valt de server weg, dan is de prop het beste wat
	 * er is.
	 */
	async function tellen() {
		try {
			const response = await fetch('/api/design');
			if (!response.ok) return elementen;
			const data = await response.json();
			return Array.isArray(data.elements) ? data.elements.length : elementen;
		} catch {
			return elementen;
		}
	}

	async function vraagOfWeg(id: string) {
		const aantal = await tellen();
		// Leeg vel: geen ask. Er is niets te verliezen, en een ask over niets
		// leert je alleen ze weg te klikken.
		if (aantal === 0) {
			await verwijder(id);
			return;
		}
		teVerwijderen = aantal;
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
	 * Een vel toevoegen laat je op het huidige vel staan — vandaag.
	 *
	 * Daarom stond hier geen `onSwitched`. Maar dat is een aanname over de API,
	 * niet iets wat deze component ziet: gaat `/api/sheets` het nieuwe vel ooit
	 * wél activeren, dan toont het canvas de inhoud van het vórige vel terwijl
	 * de tab het nieuwe aanwijst — een scherm dat met zichzelf klopt en niet met
	 * de engine. Dus kijken we gewoon of het actieve vel veranderd is.
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
	<!-- Eén rij vellen, zoals de platen van een slicer. Elk vel is een eigen
	     document: wat je ziet is precies wat er gebrand wordt. -->
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
		<div class="bevestig" role="alertdialog" aria-label={t('sheets.removeSheet')}>
			<p>{t('sheets.removeAsk', { sheet: sheet.name, what: telling(teVerwijderen) })}</p>
			<div class="knoppen">
				<button class="annuleer" onclick={() => (bevestigen = null)}>{t('common.cancel')}</button>
				<button class="weg" disabled={sheets.busy} onclick={() => verwijder(sheet.id)}>
					{sheets.busy
						? t('common.busy')
						: t('sheets.removeConfirm', { what: telling(teVerwijderen) })}
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
		/* Het accent zit in de rand en de tint, niet in de tekst: accentkleur op
		   een accenttint haalt maar 4,24:1 en dit zijn de kleinste letters in
		   beeld. De actieve staat is nog steeds dubbel gecodeerd (rand + tint +
		   aria-pressed). */
		border-color: var(--accent);
		color: var(--text-1);
		font-weight: 600;
		background: color-mix(in srgb, var(--accent) 10%, transparent);
	}
	/* Geen opacity op tekst: dat verlaagt het contrast onvoorspelbaar. De maat
	   is secundair, maar moet leesbaar blijven. */
	.sheet .size { font-size: var(--text-xs); color: var(--text-2); }
	/* Met een vinger te raken, ook met een handschoen aan. */
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
		/* Tussen twee invoervelden ziet een knop met gewone tekstkleur eruit als
		   een veld dat niet meedoet. De accentkleur zegt dat er iets gebeurt als
		   je erop drukt. */
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
	/* De ask hoort onder de knop die hem stelt, niet in een venster midden op
	   het scherm: je blijft in dezelfde strook kijken. */
	.bevestig {
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
	.bevestig p { margin: 0; font-size: var(--text-xs); color: var(--text-1); }
	.knoppen {
		display: flex;
		/* Twee uitkomsten die elkaar uitsluiten, en één ervan is onomkeerbaar:
		   ver genoeg uit elkaar om er niet naast te mikken. */
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
