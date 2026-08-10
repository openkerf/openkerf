<script lang="ts">
	import { formatDuration, type Device, type Job } from '$lib/api';
	import type { Controller } from '$lib/control.svelte';

	let {
		control,
		device,
		job,
		preflight = $bindable(),
		onJog,
		onHome,
		onUnlock
	}: {
		control: Controller;
		device: Device | null;
		job: Job | null;
		preflight: boolean;
		onJog?: (dxMm: number, dyMm: number) => void;
		onHome?: () => void;
		onUnlock?: () => void;
	} = $props();

	let actions = $derived(control.capabilities?.actions ?? null);
	let running = $derived(Boolean(job?.running));
	let queued = $derived(device?.spooler.queue_length ?? 0);
	let tokenDraft = $state('');
	let step = $state(10);
	let estimate = $state<{ seconds: number; parts: number } | null>(null);
	let estimating = $state(false);

	// De schatting van de engine vóór het starten: de pre-flight toonde tot nu
	// toe alleen de tijd van een al lopende job, wat precies te laat is.
	async function loadEstimate() {
		estimating = true;
		try {
			const response = await fetch('/api/job/estimate');
			estimate = response.ok ? await response.json() : null;
		} catch {
			estimate = null;
		} finally {
			estimating = false;
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
					{#if estimating}…{:else}{formatDuration(estimate?.seconds ?? job?.estimate_seconds)}{/if}
				</span>
			</div>
			<div class="pf-row">In wachtrij: <span class="mono">{queued}</span></div>
			<p class="pf-warn">
				Controleer deksel, koeling en air assist. Start pas als het werkstuk vastligt.
			</p>
			<div class="pf-actions">
				<button class="btn" onclick={() => (preflight = false)}>Annuleren</button>
				<button class="btn primary" onclick={confirmStart} disabled={control.busy !== null}>
					{control.busy === 'start' ? 'Bezig…' : 'Nu starten'}
				</button>
			</div>
		</div>
	{:else}
		<div class="controls">
			<button
				class="btn primary"
				disabled={!actions?.start || blocked}
				title={blockedReason}
				onclick={() => (preflight = true)}
			>
				Job starten
			</button>
			<button
				class="btn"
				disabled={!actions?.pause || !running || blocked}
				title={blockedReason}
				onclick={() => control.pause()}
			>
				Pauze
			</button>
			<button
				class="btn"
				disabled={!actions?.resume || blocked}
				title={blockedReason}
				onclick={() => control.resume()}
			>
				Hervatten
			</button>
			<!-- Stoppen kan altijd, in één tik — zolang we mogen schrijven. -->
			<button
				class="btn danger"
				disabled={!actions?.stop || control.needsToken}
				title={blockedReason}
				onclick={() => control.stop()}
			>
				Stop
			</button>
			<button
				class="btn subtle"
				disabled={!actions?.clear_queue || queued === 0 || blocked}
				title={blockedReason}
				onclick={() => control.clearQueue()}
			>
				Wachtrij legen ({queued})
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
			<div class="pad">
				<button class="jog up" aria-label="Naar boven" disabled={running} title={movingBlocked} onclick={() => onJog?.(0, -step)}>↑</button>
				<button class="jog left" aria-label="Naar links" disabled={running} title={movingBlocked} onclick={() => onJog?.(-step, 0)}>←</button>
				<button class="jog down" aria-label="Naar beneden" disabled={running} title={movingBlocked} onclick={() => onJog?.(0, step)}>↓</button>
				<button class="jog right" aria-label="Naar rechts" disabled={running} title={movingBlocked} onclick={() => onJog?.(step, 0)}>→</button>
				<button class="jog home" disabled={running} title={movingBlocked} onclick={() => onHome?.()}>Home</button>
			</div>
			<div class="steps">
				{#each [0.1, 1, 10, 50] as size (size)}
					<button class="rot mono" class:on={step === size} onclick={() => (step = size)}>
						{size} mm
					</button>
				{/each}
				<button class="rot" onclick={() => onUnlock?.()}>Ontgrendelen</button>
			</div>
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
		background: var(--danger);
		border-color: var(--danger);
		color: #fff;
	}
	.btn.subtle {
		grid-column: 1 / -1;
	}
	.preflight {
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		padding: var(--space-3);
	}
	.pf-time {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		padding-bottom: var(--space-2);
		margin-bottom: 6px;
		border-bottom: 1px solid var(--line);
	}
	.pf-time .v {
		font-size: 16px;
	}
	.pf-row {
		color: var(--text-2);
		font-size: 12px;
		padding: var(--space-1) 0;
	}
	.pf-warn {
		margin: var(--space-2) 0;
		padding: var(--space-2);
		border-radius: var(--radius-field);
		background: color-mix(in srgb, var(--warn) 14%, transparent);
		font-size: var(--text-xs);
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
		padding: 6px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.motion { margin-top: var(--space-4); }
	.rot-label {
		font-size: 10px;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-2);
	}
	.pad {
		display: grid;
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
	.jog {
		padding: 8px 0;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		font-weight: 500;
	}
	.jog:hover { background: var(--surface-2); }
	.jog.home { font-size: var(--text-xs); }
	.steps { display: flex; flex-wrap: wrap; gap: 4px; }
	.rot {
		font-size: var(--text-xs);
		padding: 3px 7px;
		border: 1px solid var(--line);
		border-radius: 4px;
		background: var(--surface-1);
	}
	.rot.on { border-color: var(--accent); color: var(--accent); }
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
