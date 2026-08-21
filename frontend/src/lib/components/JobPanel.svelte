<script lang="ts">
	// Closed by default: this is fault-finding gear, not daily fare.
	let showEvents = $state(false);
	import {
		formatDuration,
		isStalled,
		jobLabel,
		jobStatusLabel,
		remainingSeconds,
		totalSeconds,
		type Device,
		type Job,
		type SignalEvent
	} from '$lib/api';
	import type { Controller } from '$lib/control.svelte';
	import type { TilingStore } from '$lib/tiling.svelte';
	import { t } from '$lib/i18n/index.svelte';
	import { connection } from '$lib/connection.svelte';
	import JobControls from './JobControls.svelte';
	import TileRun from './TileRun.svelte';

	let {
		device,
		tiling,
		events,
		control,
		activeJob,
		revisie = 0,
		preflight = $bindable(),
		onJog,
		onHome,
		onUnlock,
		onFocus,
		onFrame,
		colorFor,
		profile = null
	}: {
		device: Device | null;
		tiling: TilingStore;
		events: SignalEvent[];
		control: Controller;
		activeJob: Job | null;
		/** Revision of the drawing; the time estimate in the preflight follows it. */
		revisie?: number;
		preflight: boolean;
		onJog?: (dxMm: number, dyMm: number) => void;
		onHome?: () => void;
		onUnlock?: () => void;
		onFocus?: (distanceMm: number) => void;
		onFrame?: () => void;
		colorFor?: (operationId: string | null) => string;
		profile?: { has_z: number; has_autofocus: number } | null;
	} = $props();

	let spooler = $derived(device?.spooler ?? null);
	let jobs = $derived(spooler?.jobs ?? []);
	/**
	 * The queue minus the job the controls are about.
	 *
	 * Since v5 that one sits at the top of the progress block, with the same bar,
	 * the same percentage and the same time remaining. Showing it here as well is
	 * the same number twice on one screen — and then the question is which of the
	 * two to believe as soon as they drift a poll apart.
	 */
	let wachtenden = $derived(jobs.filter((job) => job !== activeJob));
</script>

<TileRun {tiling} />
<JobControls {control} {device} job={activeJob} {revisie} bind:preflight {onJog} {onHome} {onUnlock} {onFocus} {onFrame} {colorFor} {profile} />

<!-- Only when there is something to report. "Spooler — nothing in the queue"
     under a block that already says nothing is running says it twice. -->
{#if !connection.online || !spooler?.present || wachtenden.length}
<div class="section">
	<!-- "Spooler" is what the engine calls it. What it is to the user is the
	     queue. -->
	<h2 class="section-title">{t('queue.title')}</h2>
	<!-- Three kinds of emptiness, and they do not mean the same thing: we do not
	     know (no connection), the machine has no queue (protocol problem), or
	     nothing is lined up. One line "the queue is empty" for all three
	     reassured the user at moments when it should not have. -->
	{#if !connection.online}
		<p class="empty">{t('queue.unknown')}</p>
	{:else if !spooler?.present}
		<p class="empty">{t('queue.noQueue')}</p>
	{:else}
		<p class="empty klein">{t('queue.after', { n: wachtenden.length })}</p>
		{#each wachtenden as job, i (i)}
			<!-- Only the job the controls are about can stall; the rest are simply
			     waiting their turn. Without that distinction every waiting job got
			     the paused look. -->
			{@const stil = job === activeJob && isStalled(job)}
			<article class="job" class:running={job.running || stil} class:paused={stil}>
				<header>
					<!-- "Spooler:3 items" is the engine's internal tally, not a name
					     (gap P4). The wording lives in api.ts, so the Job panel, the
					     status bar and the phone view do not each keep their own
					     detour. -->
					<span class="name" title={job.label}>{jobLabel(job)}</span>
					<!-- The engine says "running"/"queued"; this app speaks the user's
					     language. -->
					<span class="status" class:nu={job.running && !stil} class:pauze={stil}
						>{stil ? t('job.status.paused') : jobStatusLabel(job)}</span
					>
				</header>

				{#if job.running || stil}
					<!-- "How much longer" is the only number someone standing next to
					     the machine wants; elapsed and total sit below it so the sum can
					     be checked. -->
					<p class="resterend">
						<span class="mono groot">{formatDuration(remainingSeconds(job))}</span>
						<span class="rest-label">{t('queue.remaining')}</span>
					</p>
				{/if}

				{#if job.progress !== null}
					<!-- Kerf line as progress: the outline "cuts" itself away. At 2px it
					     did not read as progress; now it carries the card. -->
					<svg class="progress" viewBox="0 0 100 6" preserveAspectRatio="none" aria-hidden="true">
						<line x1="0" y1="3" x2="100" y2="3" class="track" />
						<line
							x1="0"
							y1="3"
							x2={Math.max(0.01, job.progress * 100)}
							y2="3"
							class="fill job-progress"
							class:kerf-anim={job.running}
						/>
					</svg>
					<div class="figures mono">
						<span class="pct">{Math.round(job.progress * 100)}%</span>
						<span>{t('job.steps', { done: job.steps_done ?? '—', total: job.steps_total ?? '—' })}</span>
					</div>
				{/if}

				<dl class="meta mono">
					<div><dt>{t('queue.elapsed')}</dt><dd>{formatDuration(job.elapsed_seconds)}</dd></div>
					<!-- From the same source as "remaining" above; see gap B1. Two
					     sources side by side gave "0:00 left" under "Total 13:45:04". -->
					<div><dt>{t('queue.total')}</dt><dd>{formatDuration(totalSeconds(job))}</dd></div>
					<div>
						<dt>{t('queue.passes')}</dt>
						<dd>{job.loops_executed ?? 0} / {job.loops ?? '∞'}</dd>
					</div>
				</dl>
			</article>
		{/each}
	{/if}
</div>
{/if}

<div class="section">
	<!-- This was "Engine signals" with raw codes: developer language in the place
	     a new user looks first. Now collapsed, and named after what it is
	     about. -->
	<button class="section-title collapse" aria-expanded={showEvents} onclick={() => (showEvents = !showEvents)}>
		{t('queue.messages')}
		<span class="mono">{events.length ? events.length : ''}</span>
	</button>
	{#if !showEvents}
		<p class="empty">{t('queue.messages.hint')}</p>
	{:else if events.length === 0}
		<p class="empty">{t('queue.messages.none')}</p>
	{:else}
		<ul class="events mono">
			{#each events.slice(0, 12) as event (event.time + event.code)}
				<li><span class="code">{event.code}</span><span class="args">{JSON.stringify(event.args)}</span></li>
			{/each}
		</ul>
	{/if}
</div>

<style>
	.section {
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
	/* The running job should not look like the three below it in the queue: a border in
	   the accent colour was lost on a full-screen panel. */
	.job.running {
		border-color: var(--accent);
		box-shadow: inset 3px 0 0 var(--accent);
	}
	.job.paused {
		border-color: var(--warn-solid);
		box-shadow: inset 3px 0 0 var(--warn-solid);
	}
	.resterend {
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
		margin: var(--space-2) 0 0;
	}
	.groot {
		font-size: var(--text-xl);
		line-height: 1.1;
		color: var(--text-1);
	}
	.rest-label {
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.figures .pct { color: var(--text-1); }
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
	.status.nu { color: var(--accent); font-weight: 600; }
	.status.pauze { color: var(--warn); font-weight: 600; }
	.progress {
		width: 100%;
		height: 6px;
		margin: var(--space-2) 0 var(--space-1);
		overflow: visible;
	}
	.track {
		stroke: var(--line);
		stroke-width: 6;
		stroke-linecap: round;
		vector-effect: non-scaling-stroke;
	}
	.fill {
		stroke: var(--accent);
		stroke-width: 6;
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
