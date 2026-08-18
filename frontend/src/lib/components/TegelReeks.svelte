<!-- frontend/src/lib/components/TegelReeks.svelte -->
<script lang="ts">
	/**
	 * Eén stap tegelijk, want dit is een procedure waarbij je met je handen aan
	 * de machine staat. Alles wat niet nu aan de beurt is, staat er niet.
	 *
	 * De twee merken van een niet-eerste tegel vragen twee keer "Hier", maar de
	 * server accepteert alleen een aanroep met precies één punt (de hoek) of
	 * precies twee (beide merken) — `TileRun.align` (`api/openkerf_api/tilerun.py`)
	 * gooit een fout bij één merk. De eerste tik wordt daarom alleen lokaal
	 * onthouden (de huidige kopstand uit de status), en pas de tweede tik gaat
	 * naar de server, die er zijn eigen kopstand aan toevoegt.
	 */
	import type { TilingStore } from '$lib/tiling.svelte';

	// Geen `device`-prop meer: de kopstand komt sinds de twee-bronnen-fout via
	// `tiling.liveHead()` bij de server vandaan, niet uit de statussnapshot.
	let { tiling }: { tiling: TilingStore } = $props();

	let getikt = $state<{ x_mm: number; y_mm: number }[]>([]);
	/** Fout bij het lokaal vastleggen van een tik; los van `tiling.error`, dat
	 *  alleen over een serveraanroep gaat. */
	let lokaleFout = $state<string | null>(null);

	const run = $derived(tiling.run);
	const eerste = $derived(run?.current === 0);
	const nodig = $derived(eerste ? 1 : 2);
	// Deze ene weigering vraagt om een bevestiging die het scherm anders nergens
	// aanbiedt: zonder deze knop is "Bevestig om door te gaan" een doodlopende
	// weg, en de enige uitweg zou de reeks stoppen zijn — en daarmee de
	// uitlijning weggooien voor niets.
	/**
	 * Hoe ver de plaat moet opschuiven, en welke kant op.
	 *
	 * De afstand komt van de server (`shift_mm`): zelf uitrekenen ging mis, want
	 * het verschil tussen twee brandgebieden is een halve overlap groter dan dat
	 * tussen twee vensters, en met dat grotere getal schuif je de merken van het
	 * bed af.
	 *
	 * De richting is **vast per as**, en dat is geen versimpeling: de vensters
	 * lopen op, dus de verschuiving is altijd positief. Hier stond een keuze
	 * tussen "boven" en "beneden" alsof beide konden voorkomen — nagerekend over
	 * platen van 500 tot 1200 mm is de stap in élk geval positief, dus die tweede
	 * tak was onbereikbaar en suggereerde een zorgvuldigheid die er niet was.
	 *
	 * Overschrijdt de plaat het bed in de hoogte, dan gaat hij **naar boven** —
	 * dat is de richting die Jelles 5030 nodig heeft, en de enige die een machine
	 * zonder zij-invoer kan. Voor een te brede plaat staat er "naar links"; dat is
	 * niet op een machine bevestigd en geldt zolang niemand het tegendeel meet.
	 */
	const verschuiving = $derived.by(() => {
		const stap = tiling.layout?.tiles?.[run?.current ?? 0]?.shift_mm;
		if (!stap) return null;
		if (Math.abs(stap.y) >= Math.abs(stap.x)) {
			return { mm: Math.abs(stap.y), richting: 'naar boven' };
		}
		return { mm: Math.abs(stap.x), richting: 'naar links' };
	});

	/**
	 * Welk merk nu aan de beurt is — bij nummer, niet bij plaats.
	 *
	 * Hier stond "het linker" of "het bovenste merk", afgeleid uit de onderlinge
	 * ligging. Dat woord hing af van `flip_x`, `swap_xy` en de thuishoek van de
	 * machine, en kon dus omgekeerd zijn zonder dat iemand het merkte. Een nummer
	 * hangt van niets af, en het staat gebrand naast het rondje — daarom is het
	 * ook op de plaat te vinden, wat een nummer zonder die gravure niet zou zijn.
	 */
	const welkMerk = $derived(`merk ${getikt.length + 1}`);

	const magOpnieuw = $derived(
		typeof tiling.error === 'string' && tiling.error.includes('al gebrand')
	);

	async function opnieuwBranden() {
		await tiling.burn(true);
	}

	async function hier() {
		lokaleFout = null;
		// Bij een niet-eerste tegel is de eerste tik nooit een serveraanroep:
		// die zou met één punt meteen mislukken. Onthoud hem lokaal en wacht op
		// de tweede tik.
		if (!eerste && getikt.length < nodig - 1) {
			// De live stand bij de server opvragen, niet de statussnapshot: die is
			// tot twee seconden oud, en de tweede tik gebruikt wél de live stand.
			// Twee bronnen voor één meting leverden 230 mm verschil op (gemeten).
			const punt = await tiling.liveHead();
			if (!punt) {
				lokaleFout =
					'Deze machine meldt geen positie, dus Hier weet niet waar hij staat.';
				return;
			}
			getikt = [...getikt, punt];
			return;
		}
		const ok = await tiling.alignHere(eerste ? 'plate_corner' : 'markers', getikt);
		if (!ok) return;
		getikt = [];
	}

	async function volgende() {
		await tiling.advance();
		getikt = [];
	}
</script>

{#if tiling.error}
	<!-- Buiten `{#if run}`: een mislukte start (bijvoorbeeld het aanbod op het
	     canvas, vóórdat er een reeks loopt) moet je ook zien als er nog geen
	     tegel is. Anders lijkt een knop die 409't niets te doen. -->
	<p class="melding" role="alert">{tiling.error}</p>
{/if}

{#if run}
	<section class="tegels" aria-label="Tegelreeks">
		<header>
			<div>
				<strong>Tegel {run.current + 1} van {run.tiles}</strong>
				<!-- De aanname die je als gebruiker niet kunt zien: tijdens een
				     tegelreeks bepalen de merken waar er gebrand wordt, niet het
				     ingestelde nulpunt van het vel. -->
				<p class="nulpunt">
					Het ingestelde nulpunt geldt nu niet: de merken bepalen waar er
					gebrand wordt.
				</p>
			</div>
			<button class="btn subtle" type="button" onclick={() => tiling.cancel()}>
				Reeks stoppen
			</button>
		</header>

			<!-- Waar je bent in de reeks, in één regel. Het canvas vinkt de gedane
			     tegels af, maar wie in het paneel staat te werken hoort het daar ook
			     te kunnen lezen. -->
			<ol class="voortgang" aria-label="Voortgang">
				{#each Array(run.tiles) as _, i (i)}
					<li class:klaar={run.done.includes(i)} class:nu={i === run.current}>
						{i + 1}{#if run.done.includes(i)}&nbsp;✓{/if}
					</li>
				{/each}
			</ol>

		{#if run.stale}
			<p class="melding stale" role="alert">{run.message}</p>
		{:else if !run.aligned}
			<p>
				{#if eerste}
					Leg de plaat zo dat de linkerbovenhoek onder de kop kan. Jog
					ernaartoe en druk op Hier.
				{:else}
					{#if verschuiving}
						Schuif de plaat {verschuiving.mm.toFixed(0)} mm
						{verschuiving.richting}, tot de twee merken onder de kop kunnen.
					{:else}
						Schuif de plaat op tot de twee merken onder de kop kunnen.
					{/if}
					Jog naar {welkMerk} en druk op Hier.
				{/if}
			</p>
			<!-- Ook deze knop zegt wát hij vastlegt: met twee rondjes voor je neus is
			     "Hier" alleen niet genoeg om te weten welk van de twee je nu bevestigt. -->
			<button class="btn primary" type="button" onclick={hier} disabled={tiling.busy}>
				{#if eerste}
					Hier · hoek van de plaat
				{:else}
					Hier · {welkMerk} van {nodig}
				{/if}
			</button>
			{#if !eerste && getikt.length > 0}
				<!-- De aangetikte merken staan alleen in het geheugen van deze
				     pagina; een refresh kent ze niet meer. De geometrie zelf loopt
				     geen gevaar, maar iemand die net een tik zette hoort niet
				     stilzwijgend terug op 0 te komen. -->
				<p class="nulpunt">
					Ververs je de pagina, dan begin je met aantikken opnieuw. De
					merken zelf blijven gewoon staan.
				</p>
			{/if}
		{:else}
			<p class="uitgelijnd">
				Uitgelijnd
				{#if run.angle_deg != null}· {run.angle_deg.toFixed(2)}° scheef{/if}
				{#if run.distance_error_mm != null}
					· {run.distance_error_mm.toFixed(1)} mm afwijking
				{/if}
			</p>
			<div class="acties">
				<button class="btn primary" type="button" onclick={() => tiling.burn()} disabled={tiling.busy}>
					Deze tegel branden
				</button>
				<button class="btn" type="button" onclick={volgende} disabled={tiling.busy}>
					Tegel klaar, volgende
				</button>
				{#if magOpnieuw}
					<!-- De uitzondering, niet de gewone weg: alleen zichtbaar ná de
					     weigering, en met opzet niet de primaire knop. -->
					<button class="btn warn" type="button" onclick={opnieuwBranden} disabled={tiling.busy}>
						Toch opnieuw branden
					</button>
				{/if}
			</div>
		{/if}

		{#if lokaleFout}
			<p class="melding" role="alert">{lokaleFout}</p>
		{/if}
	</section>
{/if}

<style>
	.tegels {
		display: grid;
		gap: var(--space-2);
		padding: var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		margin-bottom: var(--space-4);
	}
	header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: var(--space-2);
	}
	.nulpunt {
		margin: 2px 0 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.voortgang {
		display: flex;
		gap: var(--space-2);
		list-style: none;
		margin: 0;
		padding: 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.voortgang .klaar {
		color: var(--text-1);
	}
	.voortgang .nu {
		color: var(--accent);
		font-weight: 600;
	}
	.uitgelijnd {
		color: var(--text-1);
	}
	.acties {
		display: flex;
		gap: var(--space-2);
		flex-wrap: wrap;
	}
	.melding {
		color: var(--danger);
		margin: 0;
	}
	.melding.stale {
		color: var(--warn);
	}
	.btn {
		padding: 8px 12px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		font-weight: 500;
		transition: background var(--transition);
	}
	.btn:hover:not(:disabled) {
		background: var(--surface-2);
	}
	.btn:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}
	.btn.primary {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
	}
	.btn.warn {
		border-color: var(--warn);
		color: var(--warn);
	}
	.btn.subtle {
		flex: none;
		font-size: var(--text-xs);
		color: var(--text-2);
		background: none;
		border: none;
		padding: 4px 8px;
	}
	.btn.subtle:hover:not(:disabled) {
		background: var(--surface-2);
		color: var(--text-1);
	}
</style>
