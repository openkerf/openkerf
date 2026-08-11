<script lang="ts">
	import { formatDuration, isStalled, type Device, type Job } from '$lib/api';
	import type { Controller } from '$lib/control.svelte';
	import Segmented from './Segmented.svelte';

	let {
		control,
		device,
		job,
		preflight = $bindable(),
		onJog,
		onHome,
		onUnlock,
		onFocus,
		onFrame,
		colorFor,
		profile = null
	}: {
		control: Controller;
		device: Device | null;
		job: Job | null;
		preflight: boolean;
		onJog?: (dxMm: number, dyMm: number) => void;
		onHome?: () => void;
		onUnlock?: () => void;
		onFocus?: (distanceMm: number) => void;
		/** De kop langs de omtrek sturen, zonder te branden. */
		onFrame?: () => void;
		/** Dezelfde laagkleur als het canvas en de lagenlijst tonen. */
		colorFor?: (operationId: string | null) => string;
		/** Wat dit machineprofiel zegt te kunnen; bepaalt wat er verschijnt. */
		profile?: { has_z: number; has_autofocus: number } | null;
	} = $props();

	let actions = $derived(control.capabilities?.actions ?? null);
	let running = $derived(Boolean(job?.running));
	// Stilstaand, niet alleen "gepauzeerd volgens het statusveld": pauzeren zet
	// bij Lihuiyu `running` op false en meldt verder niets. Zonder dit stond hier
	// "Pauze" (uitgeschakeld) op een job die juist hervat moest worden.
	let paused = $derived(isStalled(job));
	let queued = $derived(device?.spooler.queue_length ?? 0);
	// Een lopende job is de reden dat starten niet mag; dat moet in de tooltip
	// staan, want een grijze knop zonder reden is een raadsel.
	let bezet = $derived(running || paused);
	let tokenDraft = $state('');
	let step = $state(10);
	type Layer = {
		id: string | null;
		label: string;
		speed_mm_s: number | null;
		power_percent: number | null;
		passes: number;
		elements: number;
		source: string | null;
	};
	let estimate = $state<{ seconds: number; parts: number; layers?: Layer[] } | null>(null);

	// Instellingen die niet gemeten zijn, verdienen een waarschuwing vóór het
	// materiaal in de machine ligt — niet erna.
	const ONZEKER: Record<string, string> = {
		geextrapoleerd: 'geëxtrapoleerd — niet gemeten',
		handmatig: 'handmatig ingesteld',
		geimporteerd: 'van iemand anders'
	};
	let risky = $derived(
		(estimate?.layers ?? []).filter((l) => l.source !== 'testraster')
	);
	let estimating = $state(false);
	let estimateTraag = $state(false);

	// De engine bouwt voor deze schatting het hele snijplan op. Op een zwaar
	// ontwerp duurde dat hier meer dan drie minuten, en de pre-flight bleef
	// intussen op een puntje staan. Een schatting mag nooit de reden zijn dat
	// je niet kunt starten, dus na tien seconden zeggen we het gewoon.
	const ESTIMATE_GEDULD = 10_000;

	// De schatting van de engine vóór het starten: de pre-flight toonde tot nu
	// toe alleen de tijd van een al lopende job, wat precies te laat is.
	async function loadEstimate() {
		estimating = true;
		estimateTraag = false;
		const traag = setTimeout(() => (estimateTraag = true), ESTIMATE_GEDULD);
		try {
			const response = await fetch('/api/job/estimate');
			estimate = response.ok ? await response.json() : null;
		} catch {
			estimate = null;
		} finally {
			clearTimeout(traag);
			estimating = false;
			estimateTraag = false;
		}
	}

	$effect(() => {
		if (preflight) loadEstimate();
		else estimate = null;
	});

	// Zonder token levert elke schrijfactie een 401 op. Een knop aanbieden die
	// gegarandeerd faalt is een lege belofte, dus die blokkeren we hier al.
	let blocked = $derived(control.needsToken || control.busy !== null);
	let blockedReason = $derived(
		control.needsToken ? 'Eerst een token invullen' : undefined
	);

	// De kop verzetten terwijl er gebrand wordt, verpest op zijn best de job.
	let movingBlocked = $derived(running ? 'Kan niet tijdens een lopende job' : undefined);

	async function confirmStart() {
		if (await control.start()) preflight = false;
	}
</script>

<div class="section">
	<h2 class="section-title">Bediening</h2>

	{#if control.needsToken}
		<!-- De API is vanaf het netwerk bereikbaar; zonder token blijft alles read-only. -->
		<div class="token">
			<label for="token">Token voor schrijfacties</label>
			<div class="token-row">
				<input id="token" type="password" bind:value={tokenDraft} placeholder="plak de token" />
				<button class="btn" onclick={() => control.saveToken(tokenDraft)}>Opslaan</button>
			</div>
			<p class="hint">De engine logt de token bij het starten van de API.</p>
		</div>
	{/if}

	{#if preflight}
		<!-- Pre-flight in het paneel, geen modaal venster. -->
		<div class="preflight">
			<div class="pf-time">
				<span class="muted">Geschatte tijd</span>
				<span class="v mono">
					{#if estimating}
						<span class="rekent">rekent…</span>
					{:else}{formatDuration(estimate?.seconds ?? job?.estimate_seconds)}{/if}
				</span>
			</div>
			{#if estimateTraag}
				<p class="pf-row">
					De engine bouwt het hele snijplan om dit te schatten; op een zwaar
					ontwerp duurt dat even. Starten kan gewoon — de machine wacht er
					niet op.
				</p>
			{/if}
			<!-- Alleen tonen als er iets in staat: "In wachtrij: 0" vlak vóór het
			     starten is de normale situatie, en dus geen mededeling. -->
			{#if queued > 0}
				<div class="pf-row">
					Er staat al <span class="mono">{queued}</span>
					{queued === 1 ? 'job' : 'jobs'} in de wachtrij; deze komt erachteraan.
				</div>
			{/if}

			<!-- Wat de machine gaat dóén. Tijd en aantal alleen is theater: een
			     laseraar controleert snelheid, vermogen en passes voordat hij
			     iets in de machine legt. -->
			{#if estimate?.layers?.length}
				<table class="pf-layers">
					<thead>
						<tr><th>Laag</th><th>mm/s</th><th>%</th><th>×</th><th>Bron</th></tr>
					</thead>
					<tbody>
						<!-- Op de index, niet op het label: twee operaties van hetzelfde
						     type heten allebei "Graveren", en een dubbele sleutel laat
						     Svelte de tabel verkeerd bijwerken. -->
						{#each estimate.layers as layer, i (i)}
							<tr>
								<td class="pf-name" title={layer.label}>
										<!-- Twee snijlagen heten allebei "Snijden"; de chip is het
										     enige wat ze uit elkaar houdt, en het is dezelfde kleur
										     als op het canvas en in de lagenlijst. -->
										{#if colorFor}
											<span class="chip" style:background={colorFor(layer.id)} aria-hidden="true"></span>
										{/if}{layer.label}
									</td>
								<td class="mono">{layer.speed_mm_s ?? '—'}</td>
								<td class="mono">{layer.power_percent ?? '—'}</td>
								<td class="mono">{layer.passes}</td>
								<td class:unsure={layer.source !== 'testraster'}>
									{layer.source === 'testraster'
										? 'gemeten'
										: (ONZEKER[layer.source ?? ''] ?? 'niet gemeten')}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
				{#if risky.length}
					<p class="pf-warn strong">
						{risky.length === 1 ? 'Eén laag gebruikt' : `${risky.length} lagen gebruiken`}
						instellingen die niet met een testraster gemeten zijn. Op onbekend
						materiaal: eerst een proefje op een restje.
					</p>
				{/if}
			{/if}

			<!-- Dit stond als tweede geel blok onder de risicomelding. Twee
			     waarschuwingen op rij van dezelfde kleur devalueren elkaar: de
			     routinecontrole maakte de échte melding onzichtbaar. Nu neutraal
			     en als lijst, want je loopt hem af. -->
			<div class="pf-check">
				<span class="pf-kop">Loop dit even na</span>
				<ul>
					<li>Deksel dicht</li>
					<li>Afzuiging en air assist aan</li>
					<li>Werkstuk ligt vast en vlak</li>
				</ul>
			</div>

			<!-- De kop langs de omtrek, zonder te branden: de laatste controle die
			     je écht kunt uitvoeren in plaats van alleen aanvinken. Stond alleen
			     in de bovenbalk; hier is het moment waarop je hem nodig hebt. -->
			{#if onFrame}
				<button
					class="btn kader"
					disabled={control.busy !== null || running}
					title="De kop langs de omtrek van je werk sturen — de laser blijft uit"
					onclick={() => onFrame?.()}
				>
					Eerst het kader tonen
				</button>
			{/if}

			<div class="pf-actions">
				<button class="btn" onclick={() => (preflight = false)}>Annuleren</button>
				<button class="btn primary" onclick={confirmStart} disabled={control.busy !== null}>
					{control.busy === 'start' ? 'Bezig…' : 'Nu starten'}
				</button>
			</div>
		</div>
	{:else}
		<div class="controls">
			<!-- Eén primaire knop per toestand. Stond "Job starten" ook tijdens een
			     lopende job in het accent, dan is de opvallendste knop op het scherm
			     degene die je niet moet hebben — en spoolt een tik er een tweede
			     job achteraan. -->
			<button
				class="btn"
				class:primary={!bezet}
				disabled={!actions?.start || blocked || bezet}
				title={bezet ? 'Er loopt al een job — eerst stoppen of afwachten' : blockedReason}
				onclick={() => (preflight = true)}
			>
				Job starten
			</button>
			{#if paused}
				<button
					class="btn primary"
					disabled={!actions?.resume || blocked}
					title={blockedReason}
					onclick={() => control.resume()}
				>
					Hervatten
				</button>
			{:else}
				<button
					class="btn"
					disabled={!actions?.pause || !running || blocked}
					title={running
						? blockedReason
						: 'Er loopt niets om te pauzeren'}
					onclick={() => control.pause()}
				>
					Pauze
				</button>
			{/if}
			<button
				class="btn subtle"
				disabled={!actions?.clear_queue || queued === 0 || blocked}
				title={queued === 0 ? 'De wachtrij is al leeg' : blockedReason}
				onclick={() => control.clearQueue()}
			>
				Wachtrij legen ({queued})
			</button>
			<!-- Stoppen kan altijd, in één tik — maar niet vlak naast pauze:
			     24px eronder, eigen breedte, zodat een mistik niet je werkstuk
			     kost. Zie DESIGN-SYSTEM v2, "Touch als eersteklas input". -->
			<button
				class="btn danger stop"
				disabled={!actions?.stop || control.needsToken}
				title={blockedReason ?? 'Job direct afbreken'}
				onclick={() => control.stop()}
			>
				Stop
			</button>
		</div>

	{/if}

	{#if !control.needsToken}
		<!-- Beweging: nodig om uit te lijnen en het nulpunt te zetten. Deze
		     knoppen zetten de kop echt in beweging. -->
		<div class="motion">
			<span class="rot-label">Bewegen</span>
			<!-- Omgekeerde T, zoals de pijltjes op een toetsenbord: ↑ boven ↓,
			     met ← en → ernaast. Home staat ernaast en niet in het midden,
			     want dat is geen richting. -->
			<div class="pad" class:metz={control.capabilities?.motion?.focus}>
				<button class="jog up" aria-label="Naar boven" disabled={running} title={movingBlocked} onclick={() => onJog?.(0, -step)}>↑</button>
				<button class="jog left" aria-label="Naar links" disabled={running} title={movingBlocked} onclick={() => onJog?.(-step, 0)}>←</button>
				<button class="jog down" aria-label="Naar beneden" disabled={running} title={movingBlocked} onclick={() => onJog?.(0, step)}>↓</button>
				<button class="jog right" aria-label="Naar rechts" disabled={running} title={movingBlocked} onclick={() => onJog?.(step, 0)}>→</button>
				<button class="jog home" disabled={running} title={movingBlocked} onclick={() => onHome?.()}>Home</button>
				{#if control.capabilities?.motion?.focus}
					<!-- De Z-as staat in dezelfde pad als X en Y: het is dezelfde
					     handeling met een derde richting, en hij volgt dezelfde
					     stapgrootte. -->
					<button
						class="jog zup"
						disabled={running}
						title={movingBlocked ?? `Kop ${step} mm omhoog`}
						onclick={() => onFocus?.(-step)}
					>Z&nbsp;↑</button>
					<button
						class="jog zdown"
						disabled={running}
						title={movingBlocked ?? `Kop ${step} mm omlaag`}
						onclick={() => onFocus?.(step)}
					>Z&nbsp;↓</button>
				{/if}
			</div>
			<div class="steps">
				<Segmented
					label="Stapgrootte"
					mono
					bind:value={step}
					options={[0.1, 1, 10, 50].map((size) => ({ value: size, label: `${size} mm` }))}
				/>
				<button class="rot" onclick={() => onUnlock?.()}>Ontgrendelen</button>
			</div>
			{#if !control.capabilities?.motion?.focus && profile?.has_z}
				<!-- Het profiel zegt dat deze machine een Z-as heeft, maar de
				     driver van de engine kent er geen commando voor. Dat is geen
				     ontbrekende knop maar ontbrekende ondersteuning; zeg dat. -->
				<p class="hint">
					Dit profiel meldt een Z-as, maar de driver van deze machine kent
					geen commando om de kop te verzetten. Scherpstellen doe je met de
					hand.
				</p>
			{/if}
			{#if profile?.has_autofocus}
				<!-- MeerK40t kent geen commando om een autofocus te starten. Een
				     knop die in plaats daarvan iets ánders doet, is erger dan geen
				     knop — dus zeggen we waar hij wél zit, in één zin. -->
				<p class="hint">Autofocus start je op de machine zelf.</p>
			{/if}
		</div>
	{/if}

	{#if actions && !actions.pause}
		<p class="hint">
			Dit apparaat kent geen pauze/hervatten — die commando's komen van de device-service.
		</p>
	{/if}

	{#if control.error}
		<p class="error" role="alert">{control.error}</p>
	{/if}
</div>

<style>
	.section-title {
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-2);
		margin: 0 0 var(--space-2);
	}
	.controls {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-2);
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
	.btn.danger {
		background: var(--danger-solid);
		border-color: var(--danger-solid);
		color: var(--on-color);
	}
	.btn.subtle {
		grid-column: 1 / -1;
	}
	.btn.stop {
		grid-column: 1 / -1;
		margin-top: var(--space-6);
	}
	.preflight {
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		padding: var(--space-3);
	}
	.pf-layers {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--text-xs);
		margin: 8px 0;
	}
	.pf-layers th {
		text-align: left;
		font-weight: 500;
		color: var(--text-2);
		border-bottom: 1px solid var(--line);
		padding-bottom: 2px;
	}
	.pf-layers td { padding: 2px 0; }
	.pf-layers td.mono { text-align: right; padding-right: 8px; font-variant-numeric: tabular-nums; }
	.chip {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 2px;
		margin-right: 6px;
		vertical-align: baseline;
	}
	.pf-name {
		max-width: 9em;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.unsure { color: var(--warn); }
	.pf-warn.strong { color: var(--warn); font-weight: 500; }
	.pf-time {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		padding-bottom: var(--space-2);
		margin-bottom: 8px;
		border-bottom: 1px solid var(--line);
	}
	.pf-time .v {
		font-size: var(--text-md);
	}
	.rekent {
		font-family: var(--font-ui);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.pf-row {
		color: var(--text-2);
		font-size: var(--text-xs);
		padding: var(--space-1) 0;
	}
	.pf-warn {
		margin: var(--space-2) 0;
		padding: var(--space-2);
		border-radius: var(--radius-field);
		background: color-mix(in srgb, var(--warn) 14%, transparent);
		font-size: var(--text-xs);
	}
	.pf-check {
		margin: var(--space-3) 0;
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		font-size: var(--text-xs);
	}
	.pf-kop {
		display: block;
		font-weight: 600;
		color: var(--text-2);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		margin-bottom: var(--space-1);
	}
	.pf-check ul {
		margin: 0;
		padding-left: 1.1em;
		color: var(--text-1);
	}
	.pf-check li { padding: 1px 0; }
	.kader {
		width: 100%;
		margin-bottom: var(--space-3);
	}
	.pf-actions {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-2);
	}
	.muted {
		color: var(--text-2);
	}
	.token {
		border: 1px solid var(--warn);
		border-radius: var(--radius-card);
		padding: var(--space-3);
		margin-bottom: var(--space-3);
	}
	.token label {
		display: block;
		font-weight: 500;
		margin-bottom: var(--space-2);
	}
	.token-row {
		display: flex;
		gap: var(--space-2);
	}
	.token input {
		flex: 1;
		min-width: 0;
		font: inherit;
		padding: 8px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.motion { margin-top: var(--space-4); }
	.rot-label {
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-2);
	}
	.pad {
		display: grid;
		/* Vier kolommen; de vijfde bestaat alleen als er een Z-as is, anders
		   staat er een lege kolom ruimte in te nemen. */
		grid-template-columns: repeat(4, 40px);
		grid-template-rows: repeat(2, 34px);
		gap: 4px;
		margin: var(--space-2) 0;
	}
	/* Expliciet plaatsen: met impliciete plaatsing schoof ↓ naar de eerste
	   kolom in plaats van onder ↑. */
	.pad .up { grid-area: 1 / 2; }
	.pad .left { grid-area: 2 / 1; }
	.pad .down { grid-area: 2 / 2; }
	.pad .right { grid-area: 2 / 3; }
	.pad .home { grid-area: 1 / 4 / 3 / 5; }
	.pad.metz { grid-template-columns: repeat(5, 40px); }
	.pad .zup { grid-area: 1 / 5; }
	.pad .zdown { grid-area: 2 / 5; }
	/* De Z-knoppen dragen een letter én een pijl; dat past niet op 15px. */
	.pad .zup, .pad .zdown { font-size: var(--text-xs); }
	.jog {
		padding: 8px 0;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		font-weight: 500;
	}
	.jog:hover { background: var(--surface-2); }
	.jog.home { font-size: var(--text-xs); }
	.steps { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); }
	.rot {
		font-size: var(--text-xs);
		padding: 4px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
	}
	.hint {
		margin: var(--space-2) 0 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.error {
		margin: var(--space-3) 0 0;
		padding: var(--space-2);
		border-radius: var(--radius-field);
		background: color-mix(in srgb, var(--danger) 14%, transparent);
		color: var(--text-1);
		font-size: var(--text-xs);
	}
</style>
