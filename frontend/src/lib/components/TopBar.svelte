<script lang="ts">
	import { machineStateLabel, STOP_KEY, type Device, type MachineState } from '$lib/api';
	import { i18n, t } from '$lib/i18n/index.svelte';
	import LanguagePicker from './LanguagePicker.svelte';
	import { screen } from '$lib/screen.svelte';
	import { connection } from '$lib/connection.svelte';
	import Logo from './Logo.svelte';
	import Menu from './Menu.svelte';
	import Icon from './Icon.svelte';
	import type { Menu as MenuList } from '$lib/actions';

	let {
		device,
		state: machineState,
		canStop,
		stopArmed = false,
		mayLeave = true,
		canEdit = false,
		narrow = false,
		canPause = false,
		canResume = false,
		paused = false,
		onPause,
		onResume,
		onStop,
		onFrame,
		canFrame = false,
		designLoaded = true,
		material = null,
		thicknessMm = null,
		onOpenMaterial,
		projectName = null,
		dirty = false,
		projectMenu
	}: {
		device: Device | null;
		state: MachineState;
		canStop: boolean;
		/** There is something to stop. The button always stays usable — if our state
		 *  detection is wrong you must not lose the emergency stop — but it only shouts
		 *  when it matters. */
		stopArmed?: boolean;
		/** May the app take you off the work area right now? `mayLeaveWorkArea` in
		 *  `api.ts` decides it, from the same phase `jobBusy` reads. */
		mayLeave?: boolean;
		canEdit?: boolean;
		/**
		 * @deprecated Ignored; the agreement lives in `$lib/screen.svelte`.
		 *
		 * Gap J9: this prop and the `@media (max-width: 1199px)` in JobControls were
		 * two sources for one rule. Both components now read
		 * `screen.controlsInBar`. The prop is still accepted so that the page does not
		 * have to change in the same step; it may go there.
		 */
		tablet?: boolean;
		/** Tablet width: the material chip says "Material" instead of "Choose
		 *  material" and keeps its name short. */
		narrow?: boolean;
		canPause?: boolean;
		canResume?: boolean;
		paused?: boolean;
		onPause?: () => void;
		onResume?: () => void;
		onStop: () => void;
		onFrame?: () => void;
		/** There is something on the bed *and* this machine can move. */
		canFrame?: boolean;
		/** Has the design been read? Until it has, the frame button stays off but
		 *  gives no reason: "Nothing is on the bed" was said over a full one. */
		designLoaded?: boolean;
		/** The current sheet's material — what is being burned *into*. Belongs beside
		 *  the machine: together those two decide every setting downstream. Empty is a
		 *  valid state and says so. */
		material?: string | null;
		thicknessMm?: number | null;
		onOpenMaterial?: () => void;
		/** The open project's name, or `null` for one that has never been saved. */
		projectName?: string | null;
		/** Unsaved changes — the dot beside the name. */
		dirty?: boolean;
		/** The project menu's rows, built by `projectActions` on the page: New, Open…,
		 *  Save, Save as…, Download, Upload…, and then Import… and Export for the sheet
		 *  in hand, with the reasons and shortcuts that belong to them. */
		projectMenu: MenuList;
	} = $props();

	/**
	 * Het projectmenu.
	 *
	 * Fixed positioning, following the button's position: the bar scrolls internally
	 * (`overflow-x: auto`), so an absolutely placed menu is clipped at the bar's height
	 * and is then unusable.
	 */
	let projectOpen = $state(false);
	let projectPos = $state({ x: 0, y: 0 });

	function openProjectMenu(button: HTMLElement) {
		if (projectOpen) {
			projectOpen = false;
			return;
		}
		const box = button.getBoundingClientRect();
		// Aligned to the button's right edge, but never off screen.
		const width = 250;
		projectPos = {
			x: Math.max(8, Math.min(box.right - width, window.innerWidth - width - 8)),
			y: box.bottom + 6
		};
		projectOpen = true;
	}

	// The top bar is always there; the listening to the screen width hangs here, so
	// the rest of the app does not have to do it again.
	$effect(() => screen.follow());

	/**
	 * Without a server this is no longer a control, and you have to see that.
	 *
	 * This was gap E1, and it was the most dangerous thing the round found. The Stop in
	 * this bar stayed clickable after the server had dropped out (measured at 1440 *and*
	 * 1024: `disabled` stayed `false`), while the Stop *in* the Job panel did go dead.
	 * On a tablet this bar is the only one carrying the controls — so there this was the
	 * *only* stop button, and it did nothing. You press, nothing visible happens, and
	 * you believe the machine is stopping.
	 *
	 * A button that does not arrive should not pretend. It goes dead, and the tooltip
	 * says what is going on *and* what to do instead: the button on the machine. That
	 * last part is half the answer; without that sentence you only have a dead
	 * button.
	 */
	let gone = $derived(!connection.online);
	let machineTitle = $derived(
		`${device?.label ?? t('topbar.machine.setup')} — ${machineStateLabel(machineState)}` +
			(device?.bed?.width_mm && device?.bed?.height_mm
				? ` · bed ${Math.round(device.bed.width_mm)} × ${Math.round(device.bed.height_mm)} mm`
				: '')
	);
	let stopTitle = $derived(
		gone
			? `${t('transport.noServer')} ${t('transport.noServer.stop')}`
			: stopArmed
				? t('transport.stop.now', { key: STOP_KEY })
				: t('transport.stop.armed', { key: STOP_KEY })
	);
	let pauseTitle = $derived(
		gone
			? `${t('transport.noServer')} ${t('transport.noServer.pause')}`
			: canPause
				? t('transport.pause.title')
				: t('transport.pause.unsupported')
	);
	let resumeTitle = $derived(
		gone
			? `${t('transport.noServer')} ${t('transport.noServer.resume')}`
			: t('transport.resume.title')
	);

	/**
	 * Shortcuts for pausing and stopping (gap J4).
	 *
	 * LightBurn has Pause and Ctrl+Break, and there they work even when the window is
	 * not in front. That last part we cannot do: a web page gets no key strokes when it
	 * does not have focus, and there is no browser that makes an exception for it. What
	 * we *can* do is this — anywhere in the app, on any tab, without having to find a
	 * panel first. Anybody who wants to stop the machine *without* looking at the screen
	 * uses the button on the machine; that is also where the tooltip points as soon as
	 * the server is gone.
	 *
	 * Pause is not on every keyboard (Apple has not shipped it for years), which is why
	 * there is a second route that exists everywhere.
	 */
	function sneltoets(e: KeyboardEvent) {
		// An open menu closes with Escape, even in the middle of typing a name.
		if (e.key === 'Escape' && projectOpen) {
			projectOpen = false;
			return;
		}
		// Do not intervene while somebody is typing a measure or a name: there Ctrl+.
		// is a character and not an emergency stop.
		const target = e.target as HTMLElement | null;
		if (
			target?.isContentEditable ||
			['INPUT', 'TEXTAREA', 'SELECT'].includes(target?.tagName ?? '')
		) {
			return;
		}
		const meta = e.ctrlKey || e.metaKey;
		// Stop: Ctrl/⌘ + full stop. One hand, no mode, and free in every browser.
		if (meta && (e.key === '.' || e.code === 'Period')) {
			e.preventDefault();
			if (canStop && !gone) onStop();
			return;
		}
		// Pause/resume: the Pause key, with or without Ctrl (Ctrl+Break sends the same
		// `key`). A toggle, because you press it twice.
		if (e.key === 'Pause') {
			e.preventDefault();
			if (gone) return;
			if (paused && canResume) onResume?.();
			else if (!paused && canPause && stopArmed) onPause?.();
		}
	}

	// While dragging, `box` reads the preview, so the fields follow along. They cannot
	// be edited then: you are already dragging.

	// "3mm" run together: in the bar every pixel counts, and it reads as one measure.
	// "3 mm", not "3.0 mm" — and in the reader's notation: 3,5 in Dutch, 3.5 in
	// English. Glued to the unit, because every pixel counts in the bar and it
	// reads as one measurement.
	let thickness = $derived(
		thicknessMm === null || thicknessMm === undefined
			? null
			: `${i18n.number(thicknessMm)}mm`
	);
	let materialTitle = $derived(
		material
			? thickness
				? t('topbar.material.isThickness', { material, thickness: thickness })
				: t('topbar.material.noThickness', { material })
			: t('topbar.material.none')
	);
</script>

<svelte:window onkeydown={sneltoets} />

<!--
	The bar is state and machine verbs, in three weights.

	Quiet: the two state chips (what machine, what material) and the project menu —
	things you read, or open at the start and end of a session. Secondary: Show frame
	and Pause, bordered buttons you aim at deliberately. Strongest: Stop, red at every
	width and with its word at every width, full red while something is running.
	Import and Export are rows of the project menu, and preparing a job is the Job
	tab's: the bar no longer competes with the panel for the verb that starts a burn.
-->
<header class="topbar" class:narrow class:gone>
	<div class="brand" title={t('app.name')}><Logo /><span class="woord">OpenKerf</span></div>

	<!-- Machine first: the user always knows whether the laser "is there". Clicking
	     leads to the setup — which is also the route when there is no machine yet. -->
	<!-- Gap B3: on a tablet xTool shows the device as an object, with a picture of the
	     model. We do not, and deliberately — see the report for this round: we have no
	     artwork per board family and a wrong picture above a Ruida is a claim about
	     which machine you are touching. What the question underneath *does* deserve —
	     "which machine and how big" — is here in the tooltip and beside the bed on the
	     canvas, without making the bar wider (B6 measured that the room is gone). -->
	<!-- While something is burning this is not a link: the setup has no stop button and
	     no shortcut, so one click on your own machine name took both off the screen.
	     `mayLeaveWorkArea` decides that, beside `jobBusy`, so a second way out reads the
	     same rule. The chip keeps saying what it said; only the door is shut, with the
	     reason where the tooltip was. -->
	<svelte:element
		this={mayLeave ? 'a' : 'span'}
		class="machine identity"
		class:shut={!mayLeave}
		href={mayLeave ? '/setup' : undefined}
		title={mayLeave ? machineTitle : t('topbar.machine.busy')}
	>
		<span class="dot machinedot {machineState}" aria-hidden="true"></span>
		<span class="name">{device?.label ?? t('topbar.machine.setup')}</span>
		<span class="toestand">{machineStateLabel(machineState)}</span>
	</svelte:element>

	<!-- What with (machine) and what into (material) belong beside each other: together
	     they decide every setting that follows. Until now the material hung in a filter
	     in a dialog that you close again — see decision B1. -->
	<button
		class="machine material"
		class:empty={!material}
		disabled={!canEdit}
		title={materialTitle}
		onclick={onOpenMaterial}
	>
		<svg class="icon-svg" width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 8.5 12 4l9 4.5-9 4.5z"/><path d="M3 8.5V15l9 4.5 9-4.5V8.5"/></svg>
		<!-- On a narrow tablet "Choose material" is 49px that push the stop button off
		     the screen. One word beside a dashed border and a little plank invites just
		     as well, and the whole sentence is in the tooltip. -->
		<span class="name">{material ?? (narrow ? t('topbar.material.short') : t('topbar.material.choose'))}</span>
		{#if thickness}<span class="thickness mono">{thickness}</span>{/if}
	</button>

	<div class="spacer"></div>

	<!-- Opening and saving the project, and bringing a file into the sheet: one button,
	     at every width from 880 up.
	     Two separate buttons *with* their word cost 310px, and below 1600 they were not
	     there — they only lived in the tool rail's menu, and the user did not find them
	     there for two rounds ("all I see is export and import"). The decision "the
	     project leads" stands; only the execution was no good. Import and Export joined
	     the menu when the bar became the machine's: they are what you do with the sheet,
	     and the menu reads project first, then the sheet.
	     This button costs 106px with its word and 44px without, so it fits at 880 beside
	     the emergency stop as well (measured with c7-bar). The word "Project" is on
	     screen with it: *that* is what was missing — not the action, but the existence
	     of the concept in the bar. -->
	<button
		class="btn ghost project-button"
		aria-haspopup="menu"
		aria-expanded={projectOpen}
		aria-label={t(dirty ? 'topbar.project.aria.unsaved' : 'topbar.project.aria', {
			name: projectName ?? t('topbar.project.untitled')
		})}
		title={t('topbar.project.name', { name: projectName ?? t('topbar.project.untitled') })}
		onclick={(e) => openProjectMenu(e.currentTarget as HTMLElement)}
	>
		<svg class="icon-svg" width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7h6l2 2h10v10H3z"/></svg>
		<!-- Without `stays`: below 1200px the word drops away. Measured with c7-bar:
		     *with* the word the bar runs 44px over the edge at 768 and then the stop
		     button slides off the screen. A folder with a downward arrow is the menu
		     idiom at that width, and the tooltip and the aria-label carry the word. -->
		<span class="btn-label">{t('topbar.project.name', { name: projectName ?? t('topbar.project.untitled') })}</span>
		{#if dirty}<span class="unsaved-dot" title={t('topbar.project.unsaved')}></span>{/if}
		<span class="pijl"><Icon name="chevron-down" /></span>
	</button>

	{#if projectOpen}
		<Menu menu={projectMenu} x={projectPos.x} y={projectPos.y} onClose={() => (projectOpen = false)} />
	{/if}

	<span class="scheiding" aria-hidden="true"></span>

	<!-- The last check before you burn: does it fit, is it straight, is the clamp in
	     the way. The laser stays off. -->
	<button
		class="btn frame"
		disabled={!canFrame || gone}
		title={gone
			? `${t('transport.noServer')} ${t('topbar.frame.noServer')}`
			: canFrame
				? t('topbar.frame.title')
				: designLoaded
					? t('topbar.frame.off')
					: undefined}
		onclick={onFrame}
	>
		<svg class="icon-svg" width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="1" stroke-dasharray="4 3"/></svg>
		<!-- The word stays even on a tablet, because there this is a first-class
		     action and a thin dashed square says nothing. On a narrow bar only the
		     short form is left. Two whole labels rather than a word plus a
		     fragment: "show" on its own is not translatable, and in some languages
		     it does not even come second. -->
		<span class="btn-label stays lang">{t('topbar.frame')}</span>
		<span class="btn-label stays short">{t('topbar.frame.short')}</span>
	</button>
	<!-- Stopping is always possible, anywhere, in one tap. Full red only when something
	     is really running: a button raising an alarm for hours a day without a reason
	     teaches the user to ignore it, and then they miss it when it counts. -->
	<!-- Server dropped out: no red, no fill, and the word says where the stop is
	     *then*. A tooltip is no answer here — on a tablet, where this is the only stop
	     button, hover does not exist. -->
	<button
		class="btn danger stop"
		class:sluimer={!stopArmed && !gone}
		class:dood={gone}
		disabled={!canStop || gone}
		onclick={onStop}
		title={stopTitle}
	>
		<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="1.5"/></svg>
		<span class="btn-label stays"
			>{gone ? t('transport.stop.onMachine') : t('transport.stop')}</span
		>
	</button>
	<!--
		Pausing belongs beside stopping, at every width, and it keeps its place when
		nothing is running: a button that jumps as soon as the job starts is unfindable
		at exactly that moment. It comes after Stop, the way the running block in the
		right-hand panel reads (`JobControls`, `.now-actions`). Pause and Stop have
		opposing consequences — one saves your workpiece, the other throws it away — so
		24px stand between them.

		This sat behind `barCarries`, so on the desktop the top bar carried start and
		stop but *not* pause — that lived in the status bar, at the bottom of the screen.
		Two of the transport buttons together and the third somewhere else is the kind
		of inconsistency you only discover at the moment you need it.
	-->
	{#if paused}
		<button
			class="btn resume"
			disabled={!canResume || gone}
			title={resumeTitle}
			onclick={onResume}
		>
			<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5.5v13l11-6.5z"/></svg>
			<span class="btn-label stays">{t('transport.resume')}</span>
		</button>
	{:else}
		<button
			class="btn pause"
			disabled={!canPause || !stopArmed || gone}
			title={pauseTitle}
			onclick={onPause}
		>
			<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="7" y="5.5" width="3.5" height="13" rx="1"/><rect x="13.5" y="5.5" width="3.5" height="13" rx="1"/></svg>
			<span class="btn-label stays">{t('transport.pause')}</span>
		</button>
	{/if}
	<LanguagePicker />
</header>

<style>
	.topbar {
		height: var(--topbar-height);
		flex: none;
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: 0 var(--space-3);
		background: var(--surface-1);
		border-bottom: 1px solid var(--line);
		/* Without these two the row of buttons pushes the *whole* page wider than the
		   screen — on a tablet you then scroll horizontally past your own app. */
		min-width: 0;
		overflow-x: auto;
		scrollbar-width: none;
	}
	.topbar::-webkit-scrollbar { display: none; }
	/* A button you can scroll away is not a button. So the bar must not hand out
	   anything that does not fit in it: everything gets `flex: none`, and what cannot
	   come along at 768 moves to the rail's menu (the project, below 880). */
	.topbar > :global(*) { flex: none; }

	/* Narrow screen: buttons show only their icon. The title is in the tooltip and the
	   aria-label, so no meaning is lost. The bound is at 1200px, not at 900: on a 1024
	   tablet the labels otherwise break over two lines and the bar grows with them. */
	@media (max-width: 1199px) {
		/* `.topbar .frame .short`, three classes and not two: the `.btn-label.short
		   { display: none }` default further down this file has two, and at equal
		   specificity the later rule wins — so with two the frame lost its word on
		   every tablet (measured at 1024 and 800: both labels `none`, a 50 x 44 dashed
		   square) while the comment right below promised the opposite.
		   `tests/frame-word.test.ts` holds this. */
		.topbar .frame .short { display: inline; }
		/* The buttons that drive the machine keep their word: a little red square
		   without text is not an emergency stop. */
		.topbar :global(.btn-label:not(.stays)) { display: none; }
		/* The frame keeps its word — on a tablet this is a first-class action and a
		   thin dashed square says nothing — but only the short form: "Frame" next to
		   that square is unambiguous. */
		.topbar .frame .lang { display: none; }
		/* The whole brand goes, word *and* image.
		   The wordmark already cost 100px; the logo costs another 108 with its gap
		   (measured), and those are worth more here than a logo. On a tablet you know
		   which app you have open — you have just tapped it — and the tool rail on the
		   left already carries the identity. On a tablet this bar is the only one
		   carrying the emergency stop *and* the frame; that weighs more than a mark.
		   *This* is the room the frame comes back out of. */
		.topbar .brand { display: none; }
		/* A machine name can be arbitrarily long and at 768 pushed the stop button off
		   the screen. Only the machine link: `a.machine`, not `.machine` — the material
		   chip carries the same class and has a size of its own. */
		a.machine .name {
			max-width: 10ch;
			overflow: hidden;
			text-overflow: ellipsis;
			white-space: nowrap;
		}
		/* The thickness stays — 3 mm birch cuts differently from 6 mm — and the name
		   gets the room that is left. The icon gives up that room: the name of your
		   material says more than a 16px plank. */
		.material svg { display: none; }
		.topbar .identity .name { max-width: 10ch; }
	}
	/* Below 850px the frame loses its word after all.
	   Measured with the longest names this bar can get ("Thunder Nova 51 workshop" and
	   "Birch plywood transparent 18.5mm"): those 40px squeeze the material name down to
	   15px at 768 — one letter and an ellipsis. That is the wrong trade. What you burn
	   into decides, together with the machine, *every* setting that follows (decision
	   B1) and has no substitute; the frame has its dotted square, its fixed place beside
	   the controls and its tooltip. Without that word the name keeps 64px. */
	@media (max-width: 849px) {
		.topbar .frame .btn-label { display: none; }
		/* And without a server the material name drops away at 768 as well.
		   "Stop on the machine" is 60px wider than "Stop", and the material is the only
		   flexible thing in this bar, so it paid those 60px with its name: it read
		   "B  3mm" and that is not a chip but a remnant. Better gone explicitly. At the
		   moment the server is down the material is unchangeable and not what you are
		   looking at; the only question is where the stop is, and that answer may have
		   the whole width. Above 850px the chip stays — the room is there (measured). */
		.topbar.gone .material { display: none; }
	}
	/* That is where the project button stops.
	   The material is the only flexible thing beside it: measured, the material name
	   shrank from 63px to 40px at 850 and to 7px at 768 once this button was there too —
	   "M…", and that is no longer a chip. From 880 there is room for both (measured: 63px,
	   no shrink). What you burn into weighs more (decision B1) than something you do at
	   the start and end of a session. Below this width the project — Import and Export
	   included — lives in the tool rail's menu, *with* its word: see `projectInRail` in
	   +page.svelte. */
	@media (max-width: 879px) {
		.topbar .project-button,
		.topbar .scheiding { display: none; }
	}
	/* Was 8ch across the whole tablet width, back when the brand still cost 120px. That
	   brand is gone, and that room goes to the two chips that together decide every
	   setting (decision B1): behind "Multiple…" you cannot see whether you are burning
	   plywood or plywood with a film on it. At 768 the `flex: 0 1 auto` below catches
	   the difference — the chip shrinks and the name truncates, and the bar does not
	   overflow. */
	.topbar.narrow .material .name { max-width: 10ch; }
	/* Safety net for whatever else ends up in this bar: the machine controls are fixed
	   (`flex: none` above), but as a last resort the material may shrink instead of
	   pushing the stop button off the screen. */
	.material { flex: 0 1 auto; min-width: 0; }
	.material .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	/* A truncated material name is a shame but readable through the tooltip; a
	   truncated invitation ("Materia…") is incomprehensible. This selector has to beat
	   the rule above, so the whole chain is in it. */
	.topbar.narrow .material.empty .name { max-width: none; }
	.project-button .pijl { display: grid; color: var(--text-2); margin-left: -2px; }
	.project-button .btn-label { max-width: 20ch; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	/* Unsaved is a state, so the dot is ink and not the accent (the One Teal Rule); the
	   aria-label of the button says it in words. */
	.unsaved-dot {
		width: 8px;
		height: 8px;
		flex: none;
		border-radius: var(--radius-dot);
		background: var(--text-1);
	}
	/* Narrow bar: the short label, wide bar: the long one. Two whole labels, so a
	   translation is never half a sentence. */
	.btn-label.short { display: none; }
	/* The document's things and the machine's verbs are two kinds of action; a hairline
	   says so without words. */
	.scheiding {
		width: 1px;
		align-self: stretch;
		margin: var(--space-3) var(--space-1);
		background: var(--line);
	}
	.brand {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin-right: var(--space-2);
		font-weight: 600;
		font-size: var(--text-md);
		letter-spacing: -0.01em;
	}
	/*
	 * The state chips are quiet: no fill and no border at rest, so they read as what
	 * they are — the state of the machine and of the sheet — and not as two more
	 * buttons beside the ones that move the head. They are still doors (the setup, the
	 * material), so they answer the pointer with the shared veil.
	 */
	.machine {
		white-space: nowrap;
		display: flex;
		align-items: center;
		gap: var(--space-2);
		min-height: max(40px, var(--target-min));
		padding: var(--space-1) var(--space-2);
		border-radius: var(--radius-field);
		/* Invisible, but present: the empty material button gets a dashed border, and
		   without this rule the bar jumps 2px as soon as you put a material in it. */
		border: 1px solid transparent;
		background: transparent;
		color: inherit;
		text-decoration: none;
		transition: background var(--transition);
	}
	/* --hover is a translucent veil and works on every surface. Gap D9. */
	.machine:hover:not(:disabled) {
		background: var(--hover);
	}
	/* Shut: the chip says exactly what it said, it is only no longer a door. Not grey —
	   the machine's state is the one thing that must stay readable while it burns. */
	.machine.shut { cursor: default; }
	.machine.shut:hover { background: transparent; }
	/* Nothing chosen yet is not an error, so no red and no exclamation mark. A dashed
	   border says "something still belongs here" and nothing else; as soon as there is a
	   material it becomes an ordinary chip. */
	.material.empty {
		border: 1px dashed color-mix(in srgb, var(--text-2) 45%, transparent);
		color: var(--text-2);
	}
	/* "Choose material" is shorter than a material name and may stay whole: truncated
	   to "Material…" it is no longer an invitation. */
	.material.empty .name { max-width: none; }
	.material.empty:hover:not(:disabled) { color: var(--text-1); }
	.material:disabled { cursor: not-allowed; }
	.material svg { color: var(--text-2); }
	.material .name {
		max-width: 14ch;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	/* The thickness is half the answer and must not drop away, but it does not have to
	   weigh as much as the name. */
	.thickness { color: var(--text-2); font-size: var(--text-xs); }
	.toestand { display: block; font-size: var(--text-xs); color: var(--text-2); white-space: nowrap; }
	.identity { display: grid; grid-template-columns: auto minmax(0, 1fr); column-gap: var(--space-2); row-gap: 0; }
	.identity .dot { grid-row: span 2; }
	/* 28ch on a wide bar: at 1440 the name stood cut at 18ch with 385 px free beside it. */
	.identity .name { max-width: 28ch; overflow: hidden; text-overflow: ellipsis; font-weight: 500; }
	@media (min-width: 1200px) and (max-width: 1499px) {
		.topbar .material .name { max-width: 10ch; }
		/* The invitation stays whole here too: at 1440 it read "Materiaal k…". */
		.topbar .material.empty .name { max-width: none; }
		.topbar .brand .woord { display: none; }
	}
	/* Size only. The colour of a state is one rule for the whole app, in
	   `tokens.css` under `.machinedot`. */
	.dot {
		width: 8px;
		height: 8px;
	}
	.spacer { flex: 1; }
	/*
	 * Stopping and pausing lie over an open window.
	 *
	 * A dialog covers the whole screen, its backdrop included, and that backdrop used
	 * to take the middle of these two buttons: measured with `elementFromPoint` at
	 * (1147, 24) with the cut-path window open, the answer was `DIV.backdrop` and not
	 * the button. `Ctrl/⌘ .` came through, but the argument for this button two
	 * hundred lines up is the tablet, and a tablet has no Ctrl.
	 *
	 * They stay *below* the alarm: something wrong with the machine outranks the
	 * button you were about to press. The three numbers are in `tokens.css`, and
	 * `tests/stop-reach.test.ts` measures this one in the running app.
	 */
	.btn.danger,
	.btn.pause,
	.btn.resume {
		position: relative;
		z-index: var(--z-transport);
	}
	/* The strongest verb in the bar: full red with white ink, and the heaviest word. */
	.btn.danger {
		background: var(--danger-solid);
		border-color: var(--danger-solid);
		color: var(--on-color);
		font-weight: 600;
		/* Stop and Pause have opposing consequences — one saves your workpiece, the
		   other throws it away. The bar gap is 8, so this margin makes it 24: the
		   minimum from DESIGN-SYSTEM v2 for targets with opposing consequences. */
		margin-right: var(--space-4);
	}
	.btn.danger:hover:not(:disabled) { background: var(--danger-solid); filter: brightness(1.06); }
	.btn.resume {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
	}
	/* Dormant: recognisable as the stop button (red border, red square), but not as an
	   alarm. With a running job the filled variant above wins. */
	.btn.danger.sluimer {
		background: var(--surface-1);
		border-color: var(--danger-solid);
		/* The word in ordinary text colour, the icon in red: the word stays as readable
		   as every other label in the bar (--danger on --surface-1 measures 5.32:1). The
		   red border plus the little red square carry the meaning instead. */
		color: var(--text-1);
	}
	.btn.danger.sluimer svg { color: var(--danger); }
	.btn.danger.sluimer:hover:not(:disabled) {
		background: var(--danger-solid);
		color: var(--on-color);
		filter: none;
	}
	.btn.danger.sluimer:hover:not(:disabled) svg { color: inherit; }
	/* The button that does not arrive.
	   Not "red but faded": a faded emergency stop still reads as an emergency stop, and
	   that is precisely the promise that cannot be kept here. So no more red, a dashed
	   border — the same sign the empty material button carries for "nothing here yet" —
	   and the word that says where the stop *is*. Drained like every disabled button,
	   never see-through: the text is now the message, and it has to be readable. */
	.btn.danger.dood,
	.btn.danger.dood:disabled {
		background: transparent;
		border: 1px dashed color-mix(in srgb, var(--text-2) 55%, transparent);
		color: var(--text-2);
	}
	.btn.danger.dood svg { color: var(--text-2); }
</style>
