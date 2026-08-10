<script lang="ts">
	import { formatDuration, type Device, type Job } from '$lib/api';
	import type { Controller } from '$lib/control.svelte';

	let {
		control,
		device,
		job,
		preflight = $bindable()
	}: {
		control: Controller;
		device: Device | null;
		job: Job | null;
		preflight: boolean;
	} = $props();

	let actions = $derived(control.capabilities?.actions ?? null);
	let running = $derived(Boolean(job?.running));
	let queued = $derived(device?.spooler.queue_length ?? 0);
	let tokenDraft = $state('');

	// Zonder token levert elke schrijfactie een 401 op. Een knop aanbieden die
	// gegarandeerd faalt is een lege belofte, dus die blokkeren we hier al.
	let blocked = $derived(control.needsToken || control.busy !== null);
	let blockedReason = $derived(
		control.needsToken ? 'Eerst een token invullen' : undefined
	);

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
				<span class="v mono">{formatDuration(job?.estimate_seconds)}</span>
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
