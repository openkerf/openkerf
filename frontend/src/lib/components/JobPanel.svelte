<script lang="ts">
	// Standaard dicht: dit is gereedschap voor storingen, geen dagelijkse kost.
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
	import { verbinding } from '$lib/verbinding.svelte';
	import JobControls from './JobControls.svelte';

	let {
		device,
		events,
		control,
		activeJob,
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
		events: SignalEvent[];
		control: Controller;
		activeJob: Job | null;
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
</script>

<JobControls {control} {device} job={activeJob} bind:preflight {onJog} {onHome} {onUnlock} {onFocus} {onFrame} {colorFor} {profile} />

<div class="section">
	<h2 class="section-title">Spooler</h2>
	<!-- Drie soorten leegte, en ze betekenen niet hetzelfde: we weten het niet
	     (geen verbinding), de machine heeft geen wachtrij (protocolprobleem), of
	     er staat gewoon niets klaar. Eén regel "Wachtrij is leeg" voor alle drie
	     stelde de gebruiker gerust op momenten dat dat niet mocht. -->
	{#if !verbinding.online}
		<p class="empty">
			Onbekend — zonder verbinding weten we niet wat er in de wachtrij staat.
			Wat je hier las, is van vlak vóór de stilte.
		</p>
	{:else if !spooler?.present}
		<p class="empty">
			Deze machine meldt geen wachtrij. Starten kan wel; je ziet alleen de
			voortgang niet.
		</p>
	{:else if jobs.length === 0}
		<p class="empty">
			Niets in de wachtrij. Wat je start komt hier te staan, met voortgang en
			resterende tijd.
		</p>
	{:else}
		{#each jobs as job, i (i)}
			<!-- Alleen de job waar de bediening over gaat kan stilstaan; de rest
			     staat gewoon in de rij te wachten. Zonder dat onderscheid kreeg
			     elke wachtende job het pauze-uiterlijk. -->
			{@const stil = job === activeJob && isStalled(job)}
			<article class="job" class:running={job.running || stil} class:paused={stil}>
				<header>
					<!-- "Spooler:3 items" is de interne opsomming van de engine, geen
					     naam (gat P4). De vertaling staat in api.ts, zodat het
					     Job-paneel, de statusbalk en de telefoon niet ieder hun eigen
					     omweg houden. -->
					<span class="name" title={job.label}>{jobLabel(job)}</span>
					<!-- De engine zegt "running"/"queued"; deze app spreekt Nederlands. -->
					<span class="status" class:nu={job.running && !stil} class:pauze={stil}
						>{stil ? 'Gepauzeerd' : jobStatusLabel(job)}</span
					>
				</header>

				{#if job.running || stil}
					<!-- "Hoe lang nog" is het enige getal dat iemand naast de machine
					     wil weten; verstreken en totaal staan eronder om het na te
					     kunnen rekenen. -->
					<p class="resterend">
						<span class="mono groot">{formatDuration(remainingSeconds(job))}</span>
						<span class="rest-label">resterend</span>
					</p>
				{/if}

				{#if job.progress !== null}
					<!-- Kerflijn als voortgang: de omtrek "snijdt" zich af. Op 2px was
					     hij niet als voortgang te lezen; nu draagt hij de kaart. -->
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
						<span>{job.steps_done ?? '—'} / {job.steps_total ?? '—'} stappen</span>
					</div>
				{/if}

				<dl class="meta mono">
					<div><dt>Verstreken</dt><dd>{formatDuration(job.elapsed_seconds)}</dd></div>
					<!-- Uit dezelfde bron als "resterend" hierboven; zie gat B1. Twee
					     bronnen naast elkaar gaven "nog 0:00" onder "Totaal 13:45:04". -->
					<div><dt>Totaal</dt><dd>{formatDuration(totalSeconds(job))}</dd></div>
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
	/* De lopende job hoort er niet uit te zien als de drie eronder in de rij:
	   een randje in accentkleur viel op een schermvullend paneel weg. */
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
