<script lang="ts">
	/**
	 * Een getal met − en +.
	 *
	 * De eigen spinner van de browser is twee pixels hoog en met handschoenen aan
	 * onbruikbaar; naast een draaiende laser typ je liever niet. Zie
	 * DESIGN-SYSTEM, "Getalinvoer is overal een stepper".
	 */
	let {
		label,
		value = $bindable(),
		step = 1,
		min = null,
		max = null,
		unit = null,
		disabled = false
	}: {
		label: string;
		/** Als string, zodat een half getypt getal ("1.") niet wegspringt. */
		value: string;
		step?: number;
		min?: number | null;
		max?: number | null;
		unit?: string | null;
		disabled?: boolean;
	} = $props();

	function zet(richting: number) {
		const nu = Number(value);
		const basis = Number.isFinite(nu) ? nu : 0;
		let nieuw = basis + richting * step;
		if (min !== null) nieuw = Math.max(min, nieuw);
		if (max !== null) nieuw = Math.min(max, nieuw);
		// Drijvende komma laat 0.1 + 0.2 als 0.30000000000000004 achter.
		value = String(Math.round(nieuw * 1000) / 1000);
	}
</script>

<label class="veld">
	<span class="naam">{label}{#if unit}{' '}<span class="eenheid">({unit})</span>{/if}</span>
	<span class="teller">
		<button type="button" {disabled} aria-label="{label} verlagen" onclick={() => zet(-1)}>−</button>
		<input class="mono" type="text" inputmode="decimal" bind:value {disabled} />
		<button type="button" {disabled} aria-label="{label} verhogen" onclick={() => zet(1)}>+</button>
	</span>
</label>

<style>
	.veld { display: grid; gap: 4px; }
	.naam { font-size: var(--text-xs); color: var(--text-2); }
	.eenheid { color: var(--text-2); }
	.teller { display: flex; }
	.teller input {
		flex: 1;
		min-width: 0;
		text-align: center;
		font: inherit;
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		padding: 8px 4px;
		border: 1px solid var(--line);
		border-left: 0;
		border-right: 0;
		background: var(--surface-2);
		color: var(--text-1);
	}
	.teller button {
		flex: none;
		width: 38px;
		font: inherit;
		font-size: var(--text-lg);
		line-height: 1;
		border: 1px solid var(--line);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.teller button:first-child { border-radius: var(--radius-field) 0 0 var(--radius-field); }
	.teller button:last-child { border-radius: 0 var(--radius-field) var(--radius-field) 0; }
	.teller button:hover:not(:disabled) { background: var(--surface-1); }
	.teller button:disabled, .teller input:disabled { opacity: 0.5; }
</style>
