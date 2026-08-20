<script lang="ts">
	/**
	 * Het rechterklikmenu — één component voor alle drie de plekken waar er een
	 * hangt: op een vorm, op het canvas, en op een rij in een lijst.
	 *
	 * Waarom één component en niet drie: de inhoud verschilt per plek, het
	 * gedrág mag dat niet. Een menu dat op de ene plek met Escape sluit en op de
	 * andere niet, of dat hier wel en daar niet met de pijltjes te bedienen is,
	 * kost meer dan het oplevert. Wat hier één keer klopt, klopt overal.
	 *
	 * Wat het doet, en waarom:
	 * - **Opent bij de cursor**, en klapt om zodra hij tegen een rand komt. Een
	 *   menu dat half buiten het venster valt is een menu waarvan je de onderste
	 *   helft niet kunt kiezen.
	 * - **Toetsenbord volledig**: pijltjes lopen langs de kiesbare regels (en
	 *   slaan de uitgeschakelde over — een tabstop op iets dat niet kan is een
	 *   omweg), Enter kiest, Escape sluit, Home/End springen. Submenu's openen
	 *   met → en sluiten met ←.
	 * - **Uitgeschakelde regels blijven staan** met de reden in de tooltip. Ze
	 *   weghalen zou betekenen dat het menu van vorm verandert per selectie, en
	 *   dan is er geen plek meer om te leren waar iets staat.
	 * - **Sneltoets rechts uitgelijnd** in dezelfde kolom, want dat is waar je
	 *   hem leert: niet uit een handleiding maar uit het menu.
	 */
	import ArrangeIcon from './ArrangeIcon.svelte';
	import type { Menu, MenuItem } from '$lib/acties';

	let {
		menu,
		x,
		y,
		omhoog = false,
		onSluit
	}: {
		menu: Menu;
		/** Positie in schermcoördinaten; het menu zoekt zelf een passende hoek. */
		x: number;
		y: number;
		/** Voor een menu dat aan een knop hangt die onderin staat: `y` is dan de
		 *  ónderkant van het menu in plaats van de bovenkant. Een uitklap die over
		 *  zijn eigen knop heen valt, dekt af wat je net aanwees. */
		omhoog?: boolean;
		onSluit: () => void;
	} = $props();

	let doos = $state<HTMLElement | null>(null);
	let breedte = $state(240);
	let hoogte = $state(320);
	let venster = $state({ w: 1440, h: 900 });

	// Omklappen in plaats van afkappen. Gemeten met het canvasmenu rechtsonder:
	// zonder dit viel er 180px buiten beeld en waren de onderste vier regels
	// onbereikbaar.
	let plek = $derived({
		left: x + breedte + 8 > venster.w ? Math.max(4, x - breedte) : x,
		top: omhoog
			? Math.max(4, y - hoogte)
			: y + hoogte + 8 > venster.h
				? Math.max(4, venster.h - hoogte - 8)
				: y
	});

	/** Alleen de regels waar je op kunt landen. */
	let kiesbaar = $derived(
		menu.flatMap((groep) =>
			groep.items.filter((item): item is MenuItem => item !== 'scheiding' && !item.uit)
		)
	);
	let cursor = $state(-1);
	let openSub = $state<string | null>(null);

	function kies(item: MenuItem) {
		if (item.uit) return;
		if ('items' in item) {
			openSub = openSub === item.id ? null : item.id;
			return;
		}
		onSluit();
		item.doen();
	}

	function stap(richting: number) {
		if (!kiesbaar.length) return;
		cursor = (cursor + richting + kiesbaar.length) % kiesbaar.length;
		openSub = null;
	}

	function toets(event: KeyboardEvent) {
		const sleutels = ['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter', ' ', 'Escape', 'ArrowRight', 'ArrowLeft'];
		if (!sleutels.includes(event.key)) return;
		event.preventDefault();
		event.stopPropagation();
		if (event.key === 'Escape') return onSluit();
		if (event.key === 'ArrowDown') return stap(1);
		if (event.key === 'ArrowUp') return stap(-1);
		if (event.key === 'Home') return (cursor = 0);
		if (event.key === 'End') return (cursor = kiesbaar.length - 1);
		const huidig = kiesbaar[cursor];
		if (!huidig) return;
		if (event.key === 'ArrowRight') {
			if ('items' in huidig) openSub = huidig.id;
			return;
		}
		if (event.key === 'ArrowLeft') {
			openSub = null;
			return;
		}
		kies(huidig);
	}

	$effect(() => {
		doos?.focus();
	});
</script>

<svelte:window bind:innerWidth={venster.w} bind:innerHeight={venster.h} />

<!-- Buiten het menu klikken sluit het. Een eigen laag eronder, want een
     document-listener vangt óók de klik die het menu net opende. -->
<div class="afdek" role="presentation" oncontextmenu={(e) => { e.preventDefault(); onSluit(); }} onpointerdown={onSluit}></div>

<div
	class="menu"
	role="menu"
	tabindex="-1"
	bind:this={doos}
	bind:clientWidth={breedte}
	bind:clientHeight={hoogte}
	style="left: {plek.left}px; top: {plek.top}px"
	onkeydown={toets}
	oncontextmenu={(e) => e.preventDefault()}
>
	{#each menu as groep, groepIndex (groep.titel ?? groepIndex)}
		{#if groepIndex > 0}<hr />{/if}
		{#if groep.titel}<p class="kop">{groep.titel}</p>{/if}
		{#each groep.items as item, i (item === 'scheiding' ? `s${i}` : item.id)}
			{#if item === 'scheiding'}
				<hr />
			{:else}
				{@const index = kiesbaar.indexOf(item)}
				<div class="regelwrap" class:sub={'items' in item}>
					<button
						class="regel"
						class:hier={index >= 0 && index === cursor}
						class:gevaar={item.gevaar}
						role={'items' in item ? 'menuitem' : item.aan === undefined ? 'menuitem' : 'menuitemcheckbox'}
						aria-haspopup={'items' in item ? 'menu' : undefined}
						aria-expanded={'items' in item ? openSub === item.id : undefined}
						aria-checked={item.aan === undefined ? undefined : item.aan}
						disabled={Boolean(item.uit)}
						title={item.uit || item.uitleg}
						onpointerenter={() => {
							if (index >= 0) cursor = index;
							openSub = 'items' in item ? item.id : null;
						}}
						onclick={() => kies(item)}
					>
						<span class="vink" aria-hidden="true">
							{#if item.aan}✓{/if}
						</span>
						<span class="tekst">{item.label}</span>
						{#if 'items' in item}
							<span class="pijl" aria-hidden="true">›</span>
						{:else if item.toets}
							<span class="toets mono">{item.toets}</span>
						{/if}
					</button>

					{#if 'items' in item && openSub === item.id}
						<!-- Het submenu opent naar rechts, of naar links als daar geen
						     ruimte is. `raster` is voor uitlijnen: acht pictogrammen in
						     twee rijen van vier, precies zoals ze in het paneel stonden,
						     zodat de spiergeheugen-volgorde overleeft. -->
						<div
							class="submenu"
							class:raster={item.raster}
							class:links={plek.left + breedte + 220 > venster.w}
							role="menu"
						>
							{#each item.items as kind (kind.id)}
								<button
									class="regel"
									class:tegel={item.raster}
									role="menuitem"
									disabled={Boolean(kind.uit)}
									title={kind.uit || kind.label}
									aria-label={kind.label}
									onclick={() => {
										onSluit();
										kind.doen();
									}}
								>
									{#if item.raster && kind.icoon}
										<ArrangeIcon name={kind.icoon} size={19} />
									{:else}
										<span class="vink" aria-hidden="true">{#if kind.aan}✓{/if}</span>
										<span class="tekst">{kind.label}</span>
										{#if kind.toets}<span class="toets mono">{kind.toets}</span>{/if}
									{/if}
								</button>
							{/each}
						</div>
					{/if}
				</div>
			{/if}
		{/each}
	{/each}
</div>

<style>
	.afdek {
		position: fixed;
		inset: 0;
		z-index: 90;
	}
	.menu {
		position: fixed;
		z-index: 91;
		min-width: 232px;
		max-width: 320px;
		padding: 4px;
		background: var(--surface-1);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		box-shadow: var(--shadow-float);
		font-size: var(--text-sm);
	}
	.menu:focus-visible {
		outline: none;
	}
	.kop {
		margin: 4px 8px 2px;
		font-size: var(--text-xs);
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--text-2);
	}
	hr {
		margin: 4px 6px;
		border: none;
		border-top: 1px solid var(--line);
	}
	.regelwrap {
		position: relative;
	}
	.regel {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		width: 100%;
		padding: 6px 8px;
		border-radius: var(--radius-field);
		text-align: left;
		color: var(--text-1);
		background: none;
		border: none;
	}
	/* Hover én toetsenbord krijgen dezelfde markering: er is één "hier ben je",
	   niet een muis-versie en een toetsenbord-versie. */
	.regel.hier:not(:disabled) {
		background: var(--surface-2);
	}
	.regel:disabled {
		color: var(--text-2);
		opacity: 0.5;
		cursor: default;
	}
	.regel.gevaar:not(:disabled) {
		color: var(--danger);
	}
	.regel.gevaar.hier:not(:disabled) {
		background: color-mix(in srgb, var(--danger) 10%, var(--surface-1));
	}
	.vink {
		flex: none;
		width: 12px;
		font-size: 12px;
		color: var(--accent);
	}
	.tekst {
		flex: 1;
		min-width: 0;
	}
	/* De sneltoets staat rechts in zijn eigen kolom en is grijs: hij is een
	   aanwijzing, niet de naam van de regel. */
	.toets {
		flex: none;
		font-size: var(--text-xs);
		color: var(--text-2);
		letter-spacing: 0.02em;
	}
	.pijl {
		flex: none;
		color: var(--text-2);
	}
	.submenu {
		position: absolute;
		left: 100%;
		top: -4px;
		min-width: 200px;
		padding: 4px;
		background: var(--surface-1);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		box-shadow: var(--shadow-float);
		z-index: 2;
	}
	.submenu.links {
		left: auto;
		right: 100%;
	}
	.submenu.raster {
		display: grid;
		grid-template-columns: repeat(4, 34px);
		gap: 2px;
		min-width: 0;
	}
	.regel.tegel {
		display: grid;
		place-items: center;
		width: 34px;
		height: 34px;
		padding: 0;
		color: var(--text-1);
	}
</style>
