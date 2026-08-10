<script lang="ts">
	import { STATE_LABEL, type Device, type MachineState } from '$lib/api';
	import Logo from './Logo.svelte';

	let {
		device,
		state,
		canStart,
		canStop,
		onStart,
		onStop,
		onToggleTheme
	}: {
		device: Device | null;
		state: MachineState;
		canStart: boolean;
		canStop: boolean;
		onStart: () => void;
		onStop: () => void;
		onToggleTheme: () => void;
	} = $props();
</script>

<header class="topbar">
	<div class="brand" title="OpenKerf"><Logo />OpenKerf</div>

	<!-- Machine-eerst: de gebruiker weet altijd of de laser "er is". -->
	<div class="machine">
		<span class="dot {state}" aria-hidden="true"></span>
		<span>{device?.label ?? 'Geen machine'}</span>
		<span class="muted">{STATE_LABEL[state]}</span>
	</div>

	<div class="spacer"></div>

	<!-- Kader tonen beweegt de kop: dat is fase 3, niet fase 2. -->
	<button class="btn" disabled title="Beschikbaar in fase 3">
		<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="1" stroke-dasharray="4 3"/></svg>
		Kader tonen
	</button>
	<!-- Stoppen kan altijd, overal, in één tik. -->
	<button class="btn danger" disabled={!canStop} onclick={onStop} title="Job direct afbreken">
		<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="1.5"/></svg>
		Stop
	</button>
	<!-- Opent geen dialoog maar de pre-flight in het rechterpaneel. -->
	<button class="btn primary" disabled={!canStart} onclick={onStart}>
		<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5.5v13l11-6.5z"/></svg>
		Start job
	</button>
	<button class="iconbtn" onclick={onToggleTheme} title="Thema wisselen" aria-label="Thema wisselen">
		<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
	</button>
</header>

<style>
	.topbar {
		height: var(--topbar-height);
		flex: none;
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: 0 var(--space-3);
		background: var(--surface-1);
		border-bottom: 1px solid var(--line);
	}
	.brand {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-weight: 600;
		font-size: var(--text-md);
		letter-spacing: -0.01em;
	}
	.machine {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: 6px 10px;
		border-radius: var(--radius-field);
		background: var(--surface-2);
	}
	.muted {
		color: var(--text-2);
	}
	.dot {
		width: 8px;
		height: 8px;
		border-radius: var(--radius-dot);
		flex: none;
		background: var(--text-2);
	}
	.dot.ready { background: var(--ok); }
	.dot.busy { background: var(--accent); }
	.dot.paused { background: var(--warn); }
	.dot.alarm { background: var(--danger); }
	.spacer { flex: 1; }
	.btn {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 7px 14px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		font-weight: 500;
		transition: background var(--transition);
	}
	.btn:hover:not(:disabled) { background: var(--surface-2); }
	.btn.primary {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
	}
	.btn.primary:hover:not(:disabled) { filter: brightness(1.06); }
	.btn.danger {
		background: var(--danger);
		border-color: var(--danger);
		color: #fff;
	}
	.btn.danger:hover:not(:disabled) { filter: brightness(1.06); }
	.btn:disabled { opacity: 0.45; cursor: not-allowed; }
	.iconbtn {
		display: grid;
		place-items: center;
		width: 32px;
		height: 32px;
		border-radius: var(--radius-field);
		color: var(--text-2);
		transition: background var(--transition);
	}
	.iconbtn:hover { background: var(--surface-2); color: var(--text-1); }
</style>
