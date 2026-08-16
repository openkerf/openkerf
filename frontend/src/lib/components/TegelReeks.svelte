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
	import type { Device } from '$lib/api';
	import type { TilingStore } from '$lib/tiling.svelte';

	let { tiling, device }: { tiling: TilingStore; device: Device | null } = $props();

	let getikt = $state<{ x_mm: number; y_mm: number }[]>([]);
	/** Fout bij het lokaal vastleggen van een tik; los van `tiling.error`, dat
	 *  alleen over een serveraanroep gaat. */
	let lokaleFout = $state<string | null>(null);

	const run = $derived(tiling.run);
	const eerste = $derived(run?.current === 0);
	const nodig = $derived(eerste ? 1 : 2);

	async function hier() {
		lokaleFout = null;
		// Bij een niet-eerste tegel is de eerste tik nooit een serveraanroep:
		// die zou met één punt meteen mislukken. Onthoud hem lokaal en wacht op
		// de tweede tik.
		if (!eerste && getikt.length < nodig - 1) {
			const punt = device?.position?.mm;
			if (!punt) {
				lokaleFout =
					'Deze machine meldt geen positie, dus Hier weet niet waar hij staat.';
				return;
			}
			getikt = [...getikt, { x_mm: punt[0], y_mm: punt[1] }];
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

		{#if run.stale}
			<p class="melding stale" role="alert">{run.message}</p>
		{:else if !run.aligned}
			<p>
				{#if eerste}
					Leg de plaat zo dat de linkerbovenhoek onder de kop kan. Jog
					ernaartoe en druk op Hier.
				{:else}
					Schuif de plaat op tot de twee merken onder de kop kunnen. Jog
					naar het {getikt.length === 0 ? 'eerste' : 'tweede'} merk en druk op
					Hier.
				{/if}
			</p>
			<button class="btn primary" type="button" onclick={hier} disabled={tiling.busy}>
				Hier ({getikt.length}/{nodig})
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
