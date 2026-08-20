<script lang="ts">
	/**
	 * Offset — een pad naar buiten of naar binnen zetten.
	 *
	 * Dit liep via `window.prompt('Offset in mm (negatief = naar binnen)', '2')`.
	 * Dat is de enige plek in de app waar een browservenster de vraag stelde, en
	 * daar is alles aan mis: het staat buiten het thema, het valideert niets (een
	 * letter komt er als NaN uit en levert stille onzin op), de tekst is niet te
	 * vertalen, en op sommige browsers is hij door de gebruiker uit te zetten —
	 * dan doet de knop niets, zonder één woord.
	 *
	 * Hetzelfde venster als bij Hoeken: klein, met de betekenis erbij, en een
	 * primaire knop die zegt wat er gaat gebeuren.
	 */
	import Dialog from './Dialog.svelte';
	import NumberField from './NumberField.svelte';

	let {
		open = $bindable(false),
		aantal = 0,
		bezig = false,
		onToepassen
	}: {
		open?: boolean;
		aantal?: number;
		bezig?: boolean;
		onToepassen: (afstandMm: number) => void;
	} = $props();

	let afstand = $state('2');
	let waarde = $derived(Number(afstand));
	let geldig = $derived(Number.isFinite(waarde) && waarde !== 0);
	let richting = $derived(waarde > 0 ? 'naar buiten' : 'naar binnen');
</script>

<Dialog title="Offset" bind:open width="400px">
	<div class="offset">
		<div class="paar">
			<NumberField label="Afstand" unit="mm" step={0.5} bind:value={afstand} />
			<!-- De richting in woorden naast het getal. Een minteken is de invoer,
			     "naar binnen" is de betekenis — en die twee zijn niet hetzelfde
			     zolang je nog moet bedenken welke kant negatief is. -->
			<p class="richting">
				{#if geldig}
					{Math.abs(waarde)} mm <strong>{richting}</strong>
				{:else}
					Vul een afstand in; negatief is naar binnen.
				{/if}
			</p>
		</div>
		<p class="regel">
			Er komt een nieuw pad naast het bestaande. De oorspronkelijke vorm blijft
			staan.
		</p>
	</div>

	<div class="ask-actions">
		<button class="btn" onclick={() => (open = false)}>Annuleren</button>
		<button
			class="btn primary"
			disabled={bezig || !geldig || !aantal}
			onclick={() => onToepassen(waarde)}
		>
			{#if !aantal}
				Offset maken
			{:else}
				{aantal === 1 ? '1 vorm' : `${aantal} vormen`} — {Math.abs(waarde) || '?'} mm
				{richting}
			{/if}
		</button>
	</div>
</Dialog>

<style>
	.offset {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		margin-bottom: var(--space-4);
	}
	.paar {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-3);
		align-items: end;
	}
	.richting {
		margin: 0 0 6px;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.regel {
		margin: 0;
		font-size: var(--text-xs);
		line-height: 1.5;
		color: var(--text-2);
	}
</style>
