<script lang="ts">
	/**
	 * De kleurenstrook onder het canvas — besluit B2.
	 *
	 * Twee dingen op één rij vakjes, precies zoals LightBurn het doet:
	 * mét selectie verplaatst een klik die naar de laag van die kleur (die zo
	 * nodig wordt aangemaakt), zonder selectie zet hij de kleur voor nieuw werk.
	 * Dat is één handeling waar het via het lagenpaneel er drie waren.
	 *
	 * Rechts staat wat die kleur onthoudt. Een geheugen dat je niet ziet is geen
	 * geheugen — en het moet er ook staan omdat het níet hetzelfde is als een
	 * preset: het palet weet wat jij het laatst deed, een preset weet wat er
	 * gebrand is. Daarom staat er "onthouden", nooit "geverifieerd".
	 */
	import { inktOp, LAYER_COLORS, type DesignStore } from '$lib/design.svelte';
	import { t } from '$lib/i18n/index.svelte';
	import type { EditController } from '$lib/edits.svelte';

	let {
		design,
		edits,
		canEdit = false,
		onChanged
	}: {
		design: DesignStore;
		edits: EditController;
		canEdit?: boolean;
		onChanged?: () => void;
	} = $props();

	/** Waar de aanwijzer of het toetsenbord nu staat; anders de actieve kleur. */
	let aangewezen = $state<string | null>(null);

	let kleuren = $derived(
		(design.palette?.colors.map((c) => c.color) ?? LAYER_COLORS).map((c) => c.toLowerCase())
	);
	let actief = $derived((design.palette?.default_color ?? '').toLowerCase());
	let getoond = $derived(aangewezen ?? actief ?? null);
	let selectie = $derived(design.selectedIds.length);

	/** De laag die deze kleur nu draagt, plus zijn plek in de brandvolgorde. */
	function laag(kleur: string) {
		const op = design.layerWithColor(kleur);
		if (!op) return null;
		const nummer = design.operations.filter((o) => !o.grid).findIndex((o) => o.id === op.id);
		return { op, nummer: nummer < 0 ? null : nummer + 1 };
	}

	function waarden(kleur: string): string | null {
		const gevonden = laag(kleur);
		if (gevonden?.op.speed != null) {
			const vermogen = gevonden.op.power == null ? null : Math.round(gevonden.op.power / 10);
			return `${gevonden.op.speed} mm/s${vermogen == null ? '' : ` · ${vermogen}%`}`;
		}
		const onthouden = design.memoryFor(kleur);
		if (!onthouden?.speed_mm_s) return null;
		return `${onthouden.speed_mm_s} mm/s${
			onthouden.power_percent == null ? '' : ` · ${Math.round(onthouden.power_percent)}%`
		}`;
	}

	/** Eén zin die zegt wat er gebeurt als je hier klikt. */
	function omschrijving(kleur: string): string {
		const gevonden = laag(kleur);
		const cijfers = waarden(kleur);
		const where = gevonden
			? t('palette.layerNamed', { n: gevonden.nummer, label: gevonden.op.label })
			: cijfers
				? t('palette.noLayerYetRemembered')
				: t('palette.noLayerYetBlank');
		const what = selectie
			? t('palette.putInColour', { n: selectie })
			: t('palette.setForNewWork');
		return `${what} ${where}${cijfers ? ` · ${cijfers}` : ''}`;
	}

	// De hoogte van de onderrand (deze strook plus een eventuele waarschuwing)
	// wordt gemeten in Canvas.svelte en daar in `--palet-hoogte` gezet — de
	// camerapil rekent ermee. Eén meter voor het hele blok, want er kan meer dan
	// één strook onder het bed staan.

	async function kies(kleur: string) {
		if (!canEdit || edits.busy) return;
		const ok = await edits.paletteColor(kleur, design.selectedIds);
		if (!ok) return;
		await design.load();
		onChanged?.();
	}
</script>

<div class="palet" class:leeg={!canEdit}>
	<!-- De kop zegt wat een klik doet, niet wat de vakjes zijn.
	     Hiervóór stond hier "Laagkleur" en helemaal rechts, in kleine grijze
	     letters, wat een klik zou doen — en dát verandert met de selectie. Eén
	     strook met twee betekenissen, en het verschil stond op de plek waar je
	     het laatst kijkt. Nu staat het vooraan, waar het label hoort. -->
	<span class="kop">{selectie ? t('palette.selectionToLayer') : t('palette.forNewWork')}</span>
	<div class="strook" role="group" aria-label={t('palette.aria')}>
		{#each kleuren as kleur, index (kleur)}
			{@const gevonden = laag(kleur)}
			<button
				class="vak"
				class:gebruikt={!!gevonden}
				class:nu={kleur === actief}
				style="background: {kleur}; color: {inktOp(kleur)}"
				disabled={!canEdit || edits.busy}
				aria-pressed={kleur === actief}
				aria-label={t('palette.colourAria', { n: index + 1, description: omschrijving(kleur) })}
				title={omschrijving(kleur)}
				onpointerenter={() => (aangewezen = kleur)}
				onpointerleave={() => (aangewezen = null)}
				onfocus={() => (aangewezen = kleur)}
				onblur={() => (aangewezen = null)}
				onclick={() => kies(kleur)}
			>
				<!-- Nooit alleen kleur: het laagnummer staat in het vakje, zoals bij de
				     chips in het lagenpaneel. Een kleur zonder laag krijgt een punt —
				     dan is het vakje leeg maar niet dood. -->
				{#if gevonden?.nummer}
					<span class="mono">{gevonden.nummer}</span>
				{:else}
					<span class="punt" aria-hidden="true"></span>
				{/if}
			</button>
		{/each}
	</div>

	<!-- Het geheugen, uitgeschreven. Dit is de helft van B2 die je anders nooit
	     te zien krijgt, en de plek waar het onderscheid met een preset valt. -->
	<div class="geheugen" aria-live="polite">
		{#if getoond}
			{@const gevonden = laag(getoond)}
			{@const cijfers = waarden(getoond)}
			<span class="stip" style="background: {getoond}"></span>
			<span class="wie">
				{#if gevonden}
					{t('palette.layerNamed', { n: gevonden.nummer, label: gevonden.op.label })}
				{:else if getoond === actief}
					{t('palette.newWork')}
				{:else}
					{t('palette.noLayerYet')}
				{/if}
			</span>
			{#if cijfers}
				<span class="cijfers mono">{cijfers}</span>
				<span
					class="bron"
					title={gevonden ? t('palette.layerValues') : t('palette.memory')}
				>{gevonden ? t('palette.inUse') : t('palette.remembered')}</span>
			{:else}
				<span class="niets">{t('palette.nothingRemembered')}</span>
			{/if}
		{/if}
	</div>

	<span class="uitleg">
		{selectie
			? selectie === 1
				? t('palette.clickHintOne')
				: t('palette.clickHintMany', { n: selectie })
			: t('palette.clickHintNew')}
	</span>
</div>

<style>
	.palet {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-2) var(--space-3);
		border-top: 1px solid var(--line);
		background: var(--surface-1);
		min-height: 40px;
		flex-wrap: wrap;
		/* Op 768px liep deze strook 91px buiten beeld, en met `visible` betekent
		   dat afgekapt in plaats van scrollbaar. De swatches zijn sinds besluit
		   B2 een besturingselement: een vakje dat je niet kunt raken is een
		   verdwenen functie, geen verdwenen versiering. */
		min-width: 0;
	}
	.kop {
		font-size: var(--text-xs);
		color: var(--text-2);
		text-transform: none;
		white-space: nowrap;
		flex: 0 0 auto;
	}
	/* Onder 800px is er geen ruimte voor het woord naast tien vakjes van 44px.
	   De vakjes winnen: die zijn de bediening, dit is het bijschrift. */
	@media (max-width: 800px) {
		.kop { display: none; }
	}
	/* De swatches blijven altijd heel — ze zijn het enige hier dat je aanraakt —
	   maar op tablet zijn ze 44px, en tien daarvan is 476px. Naast de kop en de
	   stand past dat niet in 768. Dus wrappen: liever twee rijen vakjes dan één
	   rij waarvan de laatste drie buiten beeld vallen. */
	.strook {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		min-width: 0;
		/* `auto` als basis houdt de tien vakjes op één rij zolang ze passen; pas
		   als dat niet meer kan, breekt hij. Met basis 0 wrapte hij ook op 1024
		   naar vier rijen, en dat is erger dan het probleem. */
		flex: 0 1 auto;
	}
	.vak {
		width: 26px;
		height: 26px;
		border: 1px solid rgb(0 0 0 / 0.18);
		border-radius: var(--radius-field);
		display: grid;
		place-items: center;
		cursor: pointer;
		padding: 0;
		font-size: var(--text-xs);
		line-height: 1;
		/* Een vakje zonder laag is lichter aanwezig: de strook laat zo in één
		   blik zien welke kleuren dit ontwerp gebruikt. */
		opacity: 0.55;
		transition: opacity 150ms ease-out, border-color 150ms ease-out;
	}
	.vak.gebruikt {
		opacity: 1;
	}
	/* Geen optilling bij hover: een doel van 26px dat een pixel omhoog springt,
	   verschuift onder je cursor terwijl je mikt. Het design system verbiedt
	   layout-verschuiving bij hover en focus; de nadruk komt uit de dekking en
	   een iets zwaardere rand. */
	.vak:hover:not(:disabled) {
		opacity: 1;
		border-color: rgb(0 0 0 / 0.45);
	}
	.vak:disabled {
		cursor: default;
	}
	.vak:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
	/* De kleur voor nieuw werk: een ring in de tekstkleur van de app, niet in
	   het accent — het accent betekent hier "actie", en dit is een stand. */
	.vak.nu {
		box-shadow: 0 0 0 2px var(--surface-1), 0 0 0 3px var(--text-1);
	}
	.punt {
		width: 4px;
		height: 4px;
		border-radius: var(--radius-dot);
		background: currentColor;
		opacity: 0.5;
	}
	.geheugen {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-xs);
		color: var(--text-2);
		min-width: 0;
		flex: 1;
	}
	.stip {
		width: 8px;
		height: 8px;
		border-radius: var(--radius-dot);
		flex: none;
		border: 1px solid rgb(0 0 0 / 0.2);
	}
	.wie {
		color: var(--text-1);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.cijfers {
		font-variant-numeric: tabular-nums;
		color: var(--text-1);
		white-space: nowrap;
	}
	.bron,
	.niets {
		border: 1px solid var(--line);
		border-radius: var(--radius-dot);
		padding: 1px var(--space-2);
		white-space: nowrap;
		/* Bewust geen accent- of statuskleur: dit is gewoonte, geen bewijs.
		   Groen of amber zijn hier verboden — die betekenen "geverifieerd" en
		   "geëxtrapoleerd" bij presets, en dat is iets heel anders. */
		background: var(--surface-2);
	}
	/* De sluitende tekst geeft als eerste mee — die is uitleg, geen bediening. */
	.uitleg {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	/* De stand en de uitleg zijn bijschrift bij de vakjes; als er te weinig
	   ruimte is, geven zíj mee. De vakjes zijn de bediening en blijven heel. */
	.geheugen { min-width: 0; flex: 0 1 auto; overflow: hidden; }
	@media (max-width: 820px) {
		.geheugen,
		.uitleg { display: none; }
	}
	.uitleg {
		font-size: var(--text-xs);
		color: var(--text-2);
		white-space: nowrap;
		margin-left: auto;
	}
	@media (max-width: 1199px) {
		/* De sluitende tekst geeft als eerste mee — die is uitleg, geen bediening. */
	.uitleg {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	/* De stand en de uitleg zijn bijschrift bij de vakjes; als er te weinig
	   ruimte is, geven zíj mee. De vakjes zijn de bediening en blijven heel. */
	.geheugen { min-width: 0; flex: 0 1 auto; overflow: hidden; }
	@media (max-width: 820px) {
		.geheugen,
		.uitleg { display: none; }
	}
	.uitleg {
			display: none;
		}
	}
	@media (max-width: 720px) {
		.geheugen {
			/* Op de telefoon staat de strook op één regel en het geheugen eronder;
			   afkappen zou juist het stuk weghalen waar het om gaat. */
			flex-basis: 100%;
		}
	}
</style>
