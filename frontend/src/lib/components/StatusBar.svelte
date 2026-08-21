<script lang="ts">
	import {
		formatDuration,
		formatMm,
		isStalled,
		remainingSeconds,
		totalSeconds,
		type Device,
		type Job,
		type MachineState
	} from '$lib/api';

	import type { Controller } from '$lib/control.svelte';
	import { connection } from '$lib/connection.svelte';
	import { t } from '$lib/i18n/index.svelte';
	import ConnectionCard from './ConnectionCard.svelte';
	import Melding from './Message.svelte';

	let {
		device,
		machineState,
		job,
		connected,
		control,
		pointerMm = null,
		actions = true
	}: {
		device: Device | null;
		machineState: MachineState;
		job: Job | null;
		connected: boolean;
		control: Controller;
		/** Pointer position on the bed; sits beside the machine position. */
		pointerMm?: { x: number; y: number } | null;
		/** Does this bar carry the pause and stop buttons? Not on a tablet: there
		 *  the machine controls are in the top bar, and two places for the same stop
		 *  makes it unclear at the deciding moment which one is the real one. At 768
		 *  the bar also overflowed and the stop button fell off the screen. */
		actions?: boolean;
	} = $props();

	// Stopping used to live only in the Job tab. Anybody designing while the
	// machine was burning had no stop on screen — and that is exactly the moment
	// you need it. Hence here, always visible as soon as something is running or in
	// the queue.
	// A paused job counts too: on Lihuiyu that has `running === false` and so
	// disappeared from this bar — precisely when you are looking for resume.
	let busy = $derived(Boolean(job) || (device?.spooler.queue_length ?? 0) > 0);

	let mm = $derived(device?.position.mm ?? null);

	// Pausing had to work from *every* tab. Living only in the Job panel it cost a
	// tab switch plus a click — exactly when you do not want a second action. So
	// here, beside the stop.
	let paused = $derived(isStalled(job));
	let canPause = $derived(control.capabilities?.actions.pause ?? false);
	let canResume = $derived(control.capabilities?.actions.resume ?? false);
	let remaining = $derived(remainingSeconds(job));
	// From the same source as `remaining` — that is the whole fix for gap B1. With
	// `job.estimate_seconds` here the bar read "0:00 left of 13:45:04": a remainder
	// from the clock beside a total from the burn model.
	let total = $derived(totalSeconds(job));
	let percent = $derived(job?.progress !== null && job?.progress !== undefined
		? Math.round(job.progress * 100)
		: null);

	// Without a connection every number below is a memory, not a measurement. They
	// stay — they still say where the head was — but they must not present
	// themselves as current.
	let fresh = $derived(connected);

	/**
	 * What the bar says about the connection, in the right order of bad news.
	 *
	 * There used to be one sentence: "Connected to the laser", or not. It was
	 * untrue three ways over. It said "connected" while no cable was plugged in, on
	 * a dropped server it pointed at the laser while the problem was the server —
	 * and then you state there checking a USB cable that is perfectly fine — and it
	 * said it even when nobody *could* know.
	 *
	 * That last one was gap E3. For grbl, newly and the dummy device the engine
	 * reports `connection.state === "unknown"`: there is simply no source. Our bar
	 * turned that into "Connected to the laser", with a green dot beside it, even
	 * straight after the wizard — while the wizard itself says the connection is
	 * only made on the first job. Two screens contradicting each other, in the
	 * place you trust most.
	 *
	 * Now the bar says "connected" only when the driver reports it itself. If
	 * nobody knows, that is what it says: "Connection unknown". That is not a fault
	 * and not a promise, and it is the only thing that is true.
	 *
	 * Tempting but wrong: taking a running job as proof. Measured on this very
	 * server — the Job panel showed a job at 80% while the engine underneath
	 * reported "USB connection did not exist". The spooler runs happily on without
	 * a machine; it is therefore not a handshake.
	 */
	let unknown = $derived(
		connected && machineState !== 'unplugged' && device?.connection?.state !== 'connected'
	);
	/**
	 * Twee indicatoren, twee onderwerpen.
	 *
	 * The bar said it twice: here it read "Machine not connected" and at the far
	 * right "Not connected" — the same message, twice, 700 px apart. And the one
	 * thing it did *not* say was whether the page itself is still attached to the
	 * server; you only saw that because this text went red.
	 *
	 * So: the machine here (with the button beside it, because that is where you
	 * can do something), and the line to OpenKerf on the right. Two things that can
	 * break separately get two places that can say so separately.
	 */
	let verbindingstekst = $derived(
		!connected
			? t('status.machine.unknown')
			: machineState === 'unplugged'
				? t('status.machine.notConnected')
				: unknown
					? t('status.machine.connectionUnknown')
					: t('status.machine.connected')
	);
	/**
	 * The button beside the state.
	 *
	 * The bar could read that no machine was on the line and do nothing about it —
	 * "not connected" without a button. Only visible when the driver knows it: grbl
	 * opens by itself as soon as work goes to it, and then there should be no button
	 * that means nothing.
	 *
	 * Disconnecting asks for confirmation, connecting does not. Measured on the real
	 * KH-5030, reconnecting after a disconnect sometimes works and sometimes does
	 * not: on a server with only curl talking to it, it failed three out of three;
	 * with the app attached the connection was open again by itself within ~6 s.
	 * What reopens it has not been found. As long as that is so, disconnecting must
	 * not be a one-click button — and the text must not promise more than we know.
	 */
	let hangt = $derived(device?.connection?.state === 'connected');
	let kanVerbinden = $derived(
		connected &&
			Boolean(
				hangt
					? control.capabilities?.connection?.disconnect
					: control.capabilities?.connection?.connect
			)
	);
	let zekerVerbreken = $state(false);

	let verbindingsuitleg = $derived(
		unknown
			? t('status.machine.connectionUnknown.hint')
			: undefined
	);
</script>

<ConnectionCard burns={Boolean(job?.running)} />

<!-- Gap E2. The socket is back, the bar is green again, but it is a different
     engine from the one this page knows: the element tree on the other side is
     empty. Do not reload by ourselves — that throws work away without anybody
     asking — but do not keep quiet about it either, because everything you do
     after this is about a document that no longer exists over there. -->
{#if connection.restarted}
	<div class="restarted" role="alert">
		<div class="text">
			<strong>{t('status.restart.title')}</strong>
			<p>
				{t('status.restart.body')}
			</p>
		</div>
		<button onclick={() => location.reload()}>{t('status.restart.reload')}</button>
	</div>
{/if}
<!-- Errors from write actions are not really at home here, but this is the only
     component that runs along on every tab. Without it a failed import landed in
     a panel you did not have open at that moment. -->
<Melding {control} />

<footer class="statusbar mono">
	<!-- Two positions side by side: where the head is, and where your pointer is.
	     Without the distinction one reads as the other. -->
	<span class="what">{t('status.head')}</span>
	<span class:stale={!fresh}>X <b>{formatMm(mm?.[0])}</b></span>
	<span class:stale={!fresh}>Y <b>{formatMm(mm?.[1])}</b> mm</span>
	{#if !fresh}
		<!-- One word, but it is the difference between "the head is there" and "the
		     head was there when we last saw it". -->
		<span class="what">{t('status.lastSeen')}</span>
	{/if}
	<span class="sep pointerpart" aria-hidden="true"></span>
	<span class="what pointerpart">{t('status.mouse')}</span>
	<span class="pointer pointerpart">
		{#if pointerMm}
			<b>{pointerMm.x.toFixed(1)}</b>, <b>{pointerMm.y.toFixed(1)}</b> mm
		{:else}
			—
		{/if}
	</span>
	<span class="sep" aria-hidden="true"></span>
	<!-- During a job "how much longer" is the only number that counts; the total
	     estimate was there, but you had to subtract it from the clock yourself. -->
	<span class="time">
		{#if job && remaining !== null}
			{#if percent !== null}<b class="pct">{percent}%</b>{/if}
			<!-- Two whole messages instead of one sentence with a styled tail: the
			     emphasis survives (how long is left is the number that counts) and
			     neither half is a fragment a translator cannot place. -->
			{t('status.remaining', { remaining: formatDuration(remaining) })}
			<span class="of">{t('status.total', { total: formatDuration(total) })}</span>
		{:else if job}
			{t('status.estimated', { total: formatDuration(total) })}
		{:else}
			{t('status.noJob')}
		{/if}
	</span>
	<span class="sep" aria-hidden="true"></span>
	<!-- The user's language, not the protocol's: whoever reads this wants to know
	     whether the laser is listening, not whether a socket is open. -->
	<span
		class:offline={!connected}
		class:onthecht={connected && machineState === 'unplugged'}
		class:afwachtend={Boolean(verbindingsuitleg)}
		title={verbindingsuitleg}
	>
		{verbindingstekst}
	</span>
	{#if kanVerbinden}
		{#if zekerVerbreken}
			<span class="verbreek-ask">
				{t('status.disconnect.ask')}
				<button
					class="verbind"
					disabled={control.busy === 'disconnect'}
					onclick={() => {
						zekerVerbreken = false;
						control.disconnect();
					}}
				>{t('status.disconnect')}</button>
				<button class="verbind" onclick={() => (zekerVerbreken = false)}>{t('status.disconnect.keep')}</button>
			</span>
		{:else}
			<button
				class="verbind"
				disabled={control.needsToken || control.busy === 'connect' || control.busy === 'disconnect'}
				title={control.needsToken
					? t('status.needsToken')
					: hangt
						? t('status.disconnect.title')
						: t('status.connect.title')}
				onclick={() => (hangt ? (zekerVerbreken = true) : control.connect())}
			>
				{control.busy === 'connect'
					? t('status.connect.busy')
					: control.busy === 'disconnect'
						? t('status.disconnect.busy')
						: hangt
							? t('status.disconnect')
							: t('status.connect')}
			</button>
		{/if}
	{/if}
	<!--
		Pause and stop used to be here. They have gone to the top bar, where start
		and stop already were: the transport belongs together, and three bars each
		holding a part of it is exactly the scattering the complaint was about. What
		the status bar keeps is the progress, and that belongs here — it holds for the
		whole app, on every tab.
	-->
	<!-- The line to OpenKerf itself. The machine state used to be here, and that is
	     already on the left of this bar *and* in the top bar. -->
	<span
		class="right"
		class:offline={!connected}
		title={connected ? t('status.openkerf.live.title') : t('status.openkerf.away.title')}
	>
		<span class="dot {connected ? 'ready' : 'offline'}" aria-hidden="true"></span>
		{connected ? t('status.openkerf.live') : t('status.openkerf.away')}
	</span>
</footer>

<style>
	/* Above the status bar, across the full width: this is about the whole page and
	   not about one panel. Not centred at the top — the connection card is already
	   there, and two cards on top of each other is not a message. */
	.restarted {
		position: fixed;
		left: 0;
		right: 0;
		bottom: var(--statusbar-height);
		z-index: 70;
		display: flex;
		align-items: center;
		gap: var(--space-4);
		padding: var(--space-2) var(--space-4);
		border-top: 1px solid var(--warn-solid);
		background: var(--surface-1);
		box-shadow: var(--lift-2);
		font-size: var(--text-xs);
		color: var(--text-1);
	}
	.restarted .text { min-width: 0; }
	.restarted strong { display: block; font-size: var(--text-sm); }
	.restarted p { margin: 0; color: var(--text-2); }
	.restarted button {
		flex: none;
		margin-left: auto;
		/* 44px: this gets touched on a tablet beside the machine too. */
		min-height: 44px;
		padding: 0 var(--space-4);
		font: inherit;
		font-weight: 600;
		border: 1px solid var(--accent);
		border-radius: var(--radius-field);
		background: var(--accent);
		color: var(--accent-ink);
	}
	.what {
		font-family: var(--font-ui);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	/* Fixed width: otherwise the whole bar jumps along with every pointer move. */
	.pointer { display: inline-block; min-width: 13ch; }
	/* On a tablet you do not draw, so the pointer position is not information — and
	   the control buttons do need the room: without this the bar broke over two
	   lines as soon as a job was running. */
	@media (max-width: 1199px) {
		.pointerpart { display: none; }
	}
	.statusbar > span { white-space: nowrap; }

	.statusbar {
		/* Fixed height on the desktop; on touch the buttons grow to 44px and then the
		   bar has to give way instead of letting them stick out. */
		min-height: var(--statusbar-height);
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
	.offline { color: var(--danger); }
	/* Not red: the server is fine, there is simply no machine attached. Red would
	   equate this with a fault, and then nobody believes the red that does
	   matter. */
	.onthecht { color: var(--warn); }
	.verbind {
		margin-left: var(--space-1);
		padding: 1px var(--space-1);
		font: inherit;
		color: var(--text-1);
		background: var(--surface-2);
		border: 1px solid var(--line);
		border-radius: var(--radius-1);
		cursor: pointer;
	}
	.verbind:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
	.verbind:disabled { opacity: 0.5; cursor: default; }
	.verbreek-ask {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		margin-left: var(--space-1);
		color: var(--text-1);
	}

	/* Not yet connected is neither a fault nor a promise. The same muted tone as
	   the rest of the bar, with an underline saying there is an explanation behind
	   it. Yellow would raise an alarm here about something entirely normal just
	   after the wizard. */
	.afwachtend {
		color: var(--text-2);
		text-decoration: underline dotted;
		text-underline-offset: 3px;
	}
	/* Positions from before the silence: readable, but no longer as fact. */
	.stale { opacity: 0.55; }
	b {
		color: var(--text-1);
		font-weight: 400;
	}
	.sep {
		width: 1px;
		height: 14px;
		background: var(--line);
	}
	/* The progress in figures: percentage bold, remaining bold, total muted —
	   three numbers side by side otherwise read as one mush. */
	.time { white-space: nowrap; }
	.pct { margin-right: var(--space-2); }
	.of { color: var(--text-2); }

	.right {
		margin-left: auto;
		display: flex;
		align-items: center;
		gap: 8px;
		color: var(--text-1);
	}
	.dot {
		width: 8px;
		height: 8px;
		border-radius: var(--radius-dot);
		background: var(--text-2);
	}
	.dot.ready { background: var(--ok); }
</style>
