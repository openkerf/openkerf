<script lang="ts">
	import { formatDuration, formatMm, STATE_LABEL, type Device, type Job, type MachineState } from '$lib/api';

	let {
		device,
		state,
		job,
		connected
	}: { device: Device | null; state: MachineState; job: Job | null; connected: boolean } = $props();

	let mm = $derived(device?.position.mm ?? null);
</script>

<footer class="statusbar mono">
	<span>X <b>{formatMm(mm?.[0])}</b></span>
	<span>Y <b>{formatMm(mm?.[1])}</b> mm</span>
	<span class="sep" aria-hidden="true"></span>
	<span>
		{#if job}
			~ {formatDuration(job.estimate_seconds)} geschat
		{:else}
			geen job
		{/if}
	</span>
	<span class="sep" aria-hidden="true"></span>
	<span>{connected ? 'API verbonden' : 'API onbereikbaar'}</span>
	<span class="right">
		<span class="dot {state}" aria-hidden="true"></span>{STATE_LABEL[state]}
	</span>
</footer>

<style>
	.statusbar {
		height: var(--statusbar-height);
		flex: none;
		display: flex;
		align-items: center;
		gap: var(--space-4);
		padding: 0 var(--space-3);
		background: var(--surface-1);
		border-top: 1px solid var(--line);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	b {
		color: var(--text-1);
		font-weight: 400;
	}
	.sep {
		width: 1px;
		height: 14px;
		background: var(--line);
	}
	.right {
		margin-left: auto;
		display: flex;
		align-items: center;
		gap: 6px;
		color: var(--text-1);
	}
	.dot {
		width: 8px;
		height: 8px;
		border-radius: var(--radius-dot);
		background: var(--text-2);
	}
	.dot.ready { background: var(--ok); }
	.dot.busy { background: var(--accent); }
	.dot.paused { background: var(--warn); }
	.dot.alarm { background: var(--danger); }
</style>
