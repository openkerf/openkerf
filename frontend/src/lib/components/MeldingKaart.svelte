<script lang="ts">
	/**
	 * Meldingen aan- en uitzetten, en zien wat de browser ervan vindt.
	 *
	 * Twee gedaanten, één component, omdat het over hetzelfde ding gaat:
	 *
	 * - `aanleiding` — de vraag zelf, en die stellen we alleen op het moment dat
	 *   er iets te melden valt (een job die net begon). Een toestemmingsvraag
	 *   zonder aanleiding wordt weggeklikt, en die weigering krijg je niet meer
	 *   terug: de browser onthoudt hem voorgoed. Daarom vragen wij het eerst zelf,
	 *   met de reden erbij, en pas na "ja" de browser.
	 * - `instellingen` — de vaste plek. Toestemming geweigerd is een toestand die
	 *   je moet kunnen zien én herstellen, dus staat er niet alleen dát het
	 *   geblokkeerd is maar ook waar je dat terugdraait.
	 */
	import { TOESTEMMING_TEKST, type Meldingen } from '$lib/meldingen.svelte';

	let {
		meldingen,
		variant = 'instellingen',
		onKlaar
	}: {
		meldingen: Meldingen;
		variant?: 'aanleiding' | 'instellingen';
		onKlaar?: () => void;
	} = $props();

	let bezig = $state(false);

	async function aanzetten() {
		bezig = true;
		try {
			await meldingen.vraag();
		} finally {
			bezig = false;
		}
		if (meldingen.toestemming === 'granted') onKlaar?.();
	}

	function tijdstip(ms: number) {
		return new Date(ms).toLocaleTimeString('nl-NL', { hour: '2-digit', minute: '2-digit' });
	}
</script>

<div class="kaart" class:vraag={variant === 'aanleiding'}>
	{#if variant === 'aanleiding'}
		<h3>Zal ik het melden als deze job klaar is?</h3>
		<p>
			Dan hoef je er niet bij te blijven kijken. Je krijgt ook bericht bij een storing
			of als de teller stil komt te staan. Ingrijpen doet OpenKerf nooit zelf.
		</p>
		<div class="acties">
			<button class="btn" onclick={() => { meldingen.nietNu(); onKlaar?.(); }}>Niet nu</button>
			<button class="btn primary" disabled={bezig} onclick={aanzetten}>
				{bezig ? 'Bezig…' : 'Meldingen aanzetten'}
			</button>
		</div>
		<p class="klein">
			De browser vraagt hierna zelf om toestemming. Je kunt het later altijd nog
			aanzetten bij Meldingen.
		</p>
	{:else}
		<!--
			De schakelaar staat uit zolang de browser niet meewerkt, ook als de
			voorkeur "aan" is. Anders belooft een petrolkleurige schakelaar iets wat
			niet gebeurt: op een geblokkeerde site stond hij aan terwijl er nooit
			een melding zou komen. De voorkeur blijft wel bewaard — hij springt
			terug zodra de toestemming er is.
		-->
		<label class="schakel" class:machteloos={meldingen.toestemming !== 'granted'}>
			<input
				type="checkbox"
				checked={meldingen.aan && meldingen.toestemming === 'granted'}
				disabled={meldingen.toestemming !== 'granted'}
				onchange={(e) => meldingen.zet(e.currentTarget.checked)}
			/>
			<span class="spoor" aria-hidden="true"><span class="knikker"></span></span>
			<span class="tekst">
				<span class="titel">Melden als een job klaar is of vastloopt</span>
				<span class="klein">Ook als dit tabblad op de achtergrond staat.</span>
			</span>
		</label>

		<p
			class="stand"
			class:mis={meldingen.toestemming === 'denied'}
			class:goed={meldingen.toestemming === 'granted'}
		>
			<span class="stip" aria-hidden="true"></span>
			{TOESTEMMING_TEKST[meldingen.toestemming]}
		</p>

		{#if meldingen.toestemming === 'default'}
			<button class="btn primary" disabled={bezig} onclick={aanzetten}>
				{bezig ? 'Bezig…' : 'Toestemming vragen'}
			</button>
		{:else if meldingen.toestemming === 'denied'}
			<p class="herstel">
				Klik links in de adresbalk op het slotje of het ⓘ-teken, zet <em>Meldingen</em>
				op <em>Toestaan</em> en ververs deze pagina. Op een telefoon staat het onder
				de site-instellingen van de browser.
			</p>
		{:else if meldingen.toestemming === 'granted'}
			<button class="btn" onclick={() => meldingen.test()}>Testmelding sturen</button>
		{/if}

		{#if meldingen.fout}
			<p class="fout" role="alert">{meldingen.fout}</p>
		{/if}

		{#if meldingen.laatste}
			<p class="laatste">
				Laatste melding {tijdstip(meldingen.laatste.tijd)} — “{meldingen.laatste.titel}”
				{#if !meldingen.laatste.getoond}
					<span class="klein">(niet als pop-up getoond: het scherm stond aan, of meldingen staan uit)</span>
				{/if}
			</p>
		{/if}

		<p class="klein grens">
			OpenKerf meldt, maar grijpt niet in: er is geen vlam- of rookdetectie. De camera
			hangt aan de computer en niet aan de machine, dus wij kunnen niet zien of er iets
			misgaat in het bed. Blijf in de buurt van een lopende job.
		</p>
	{/if}
</div>

<style>
	.kaart {
		display: grid;
		gap: var(--space-3);
	}
	.kaart.vraag {
		padding: var(--space-4);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-1);
		box-shadow: var(--lift-1);
	}
	h3 {
		margin: 0;
		font-size: var(--text-md);
		font-weight: 600;
		letter-spacing: -0.01em;
	}
	p {
		margin: 0;
		color: var(--text-1);
	}
	.klein {
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.grens {
		padding-top: var(--space-3);
		border-top: 1px solid var(--line);
	}
	.acties {
		display: flex;
		gap: var(--space-2);
		justify-content: flex-end;
		flex-wrap: wrap;
	}
	.btn {
		min-height: 36px;
		padding: 0 var(--space-4);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		font-weight: 500;
		justify-self: start;
	}
	.btn:hover:not(:disabled) {
		background: var(--surface-2);
	}
	.btn.primary {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
	}
	.btn:disabled {
		opacity: 0.5;
		cursor: default;
	}

	/* Schakelaar: aan/uit per stuk, conform de patroonkeuzewijzer. */
	.schakel {
		display: flex;
		align-items: flex-start;
		gap: var(--space-3);
		cursor: pointer;
	}
	.schakel input {
		position: absolute;
		width: 1px;
		height: 1px;
		opacity: 0;
	}
	.spoor {
		flex: none;
		position: relative;
		width: 40px;
		height: 24px;
		margin-top: 1px;
		border: 1px solid var(--line);
		border-radius: var(--radius-dot);
		background: var(--surface-2);
		transition: background var(--transition), border-color var(--transition);
	}
	.knikker {
		position: absolute;
		top: 2px;
		left: 2px;
		width: 18px;
		height: 18px;
		border-radius: var(--radius-dot);
		background: var(--surface-1);
		box-shadow: var(--lift-1);
		transition: transform var(--transition);
	}
	.schakel input:checked + .spoor {
		background: var(--accent);
		border-color: var(--accent);
	}
	.schakel input:checked + .spoor .knikker {
		transform: translateX(16px);
	}
	.schakel input:focus-visible + .spoor {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
	.schakel.machteloos {
		cursor: default;
	}
	.schakel.machteloos .spoor,
	.schakel.machteloos .knikker {
		opacity: 0.55;
	}
	.tekst {
		display: grid;
		gap: 2px;
	}
	.titel {
		font-weight: 500;
	}

	.stand {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.stip {
		flex: none;
		width: 8px;
		height: 8px;
		border-radius: var(--radius-dot);
		background: var(--text-2);
	}
	/* Kleur naast het woord, nooit in plaats ervan: de zin zegt het al, de stip
	   maakt het scanbaar. */
	.stand.goed .stip {
		background: var(--ok);
	}
	.stand.mis {
		color: var(--warn);
	}
	.stand.mis .stip {
		background: var(--warn-solid);
	}
	.herstel {
		font-size: var(--text-xs);
		line-height: 1.5;
		padding: var(--space-3);
		border-left: 3px solid var(--warn-solid);
		border-radius: var(--radius-sharp);
		background: var(--surface-2);
	}
	.fout {
		font-size: var(--text-xs);
		color: var(--danger);
	}
	.laatste {
		font-size: var(--text-xs);
		color: var(--text-2);
	}
</style>
