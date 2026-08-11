<script lang="ts">
	// Standaard dicht: dit is gereedschap voor storingen, geen dagelijkse kost.
	let showEvents = $state(false);
	import { formatDuration, type Device, type Job, type SignalEvent } from '$lib/api';
	import type { Controller } from '$lib/control.svelte';
	import JobControls from './JobControls.svelte';

	let {
		device,
		events,
		control,
		activeJob,
		preflight = $bindable(),
		onJog,
		onHome,
		onUnlock
	}: {
		device: Device | null;
		events: SignalEvent[];
		control: Controller;
		activeJob: Job | null;
		preflight: boolean;
		onJog?: (dxMm: number, dyMm: number) => void;
		onHome?: () => void;
		onUnlock?: () => void;
	} = $props();

	let spooler = $derived(device?.spooler ?? null);
	let jobs = $derived(spooler?.jobs ?? []);
</script>

<JobControls {control} {device} job={activeJob} bind:preflight {onJog} {onHome} {onUnlock} />

<div class="section">
	<h2 class="section-title">Spooler</h2>
	{#if !spooler?.present}
		<p class="empty">Geen spooler beschikbaar.</p>
	{:else if jobs.length === 0}
		<p class="empty">Wachtrij is leeg.</p>
	{:else}
		{#each jobs as job, i (i)}
			<article class="job" class:running={job.running}>
				<header>
					<span class="name">{job.label}</span>
					<span class="status mono">{job.status ?? '—'}</span>
				</header>

				{#if job.progress !== null}
					<!-- Kerflijn als voortgang: de omtrek "snijdt" zich af. -->
					<svg class="progress" viewBox="0 0 100 4" preserveAspectRatio="none" aria-hidden="true">
						<line x1="0" y1="2" x2="100" y2="2" class="track" />
						<line
							x1="0"
							y1="2"
							x2={Math.max(0.01, job.progress * 100)}
							y2="2"
							class="fill job-progress"
							class:kerf-anim={job.running}
						/>
					</svg>
					<div class="figures mono">
						<span>{Math.round(job.progress * 100)}%</span>
						<span>{job.steps_done ?? '—'} / {job.steps_total ?? '—'} stappen</span>
					</div>
				{/if}

				<dl class="meta mono">
					<div><dt>Verstreken</dt><dd>{formatDuration(job.elapsed_seconds)}</dd></div>
					<div><dt>Schatting</dt><dd>{formatDuration(job.estimate_seconds)}</dd></div>
					<div>
						<dt>Passes</dt>
						<dd>{job.loops_executed ?? 0} / {job.loops ?? '∞'}</dd>
					</div>
				</dl>
			</article>
		{/each}
	{/if}
</div>

<div class="section">
	<!-- Dit was "Engine-signalen" met ruwe codes: ontwikkelaarstaal op de plek
	     waar een nieuwe gebruiker als eerste kijkt. Nu ingeklapt en met een
	     naam die zegt waar het over gaat. -->
	<button class="section-title collapse" aria-expanded={showEvents} onclick={() => (showEvents = !showEvents)}>
		Meldingen van de machine
		<span class="mono">{events.length ? events.length : ''}</span>
	</button>
	{#if !showEvents}
		<p class="empty">
			Technische meldingen van de engine. Handig bij het zoeken naar een
			storing; verder heb je ze niet nodig.
		</p>
	{:else if events.length === 0}
		<p class="empty">Nog niets gemeld.</p>
	{:else}
		<ul class="events mono">
			{#each events.slice(0, 12) as event (event.time + event.code)}
				<li><span class="code">{event.code}</span><span class="args">{JSON.stringify(event.args)}</span></li>
			{/each}
		</ul>
	{/if}
</div>

<style>
	.section + .section {
		margin-top: var(--space-6);
	}
	.section-title {
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-2);
		margin: 0 0 var(--space-2);
	}
	.collapse {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		text-align: left;
	}
	.collapse::after {
		content: '';
		margin-left: auto;
		width: 6px;
		height: 6px;
		border-right: 1px solid var(--text-2);
		border-bottom: 1px solid var(--text-2);
		transform: rotate(45deg);
	}
	.collapse[aria-expanded='true']::after { transform: rotate(-135deg); }
	.empty {
		color: var(--text-2);
		margin: 0;
	}
	.job {
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		padding: var(--space-3);
	}
	.job + .job {
		margin-top: var(--space-2);
	}
	.job.running {
		border-color: var(--accent);
	}
	.job header {
		display: flex;
		justify-content: space-between;
		gap: var(--space-2);
		align-items: baseline;
	}
	.name {
		font-weight: 600;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.status {
		font-size: var(--text-xs);
		color: var(--text-2);
		flex: none;
	}
	.progress {
		width: 100%;
		height: 4px;
		margin: var(--space-3) 0 var(--space-1);
		overflow: visible;
	}
	.track {
		stroke: var(--line);
		stroke-width: 2;
	}
	.fill {
		stroke: var(--accent);
		stroke-width: 2;
		stroke-dasharray: 6 4;
		vector-effect: non-scaling-stroke;
	}
	.figures {
		display: flex;
		justify-content: space-between;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.meta {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: var(--space-2);
		margin: var(--space-3) 0 0;
	}
	.meta dt {
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-2);
		font-family: var(--font-ui);
	}
	.meta dd {
		margin: 2px 0 0;
		font-size: var(--text-sm);
	}
	.events {
		list-style: none;
		margin: 0;
		padding: 0;
		font-size: var(--text-xs);
	}
	.events li {
		display: flex;
		gap: var(--space-2);
		padding: 4px 0;
		border-bottom: 1px solid var(--line);
	}
	.code {
		color: var(--accent);
		flex: none;
	}
	.args {
		color: var(--text-2);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
</style>
