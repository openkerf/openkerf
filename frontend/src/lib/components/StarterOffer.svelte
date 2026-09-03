<script lang="ts">
	/**
	 * The one moment this whole feature exists for: a machine with no settings.
	 *
	 * Somebody has just defined a laser. The app notices there is not one setting for
	 * it, and offers to fetch some that match the kind of laser and its tube power.
	 * Everything else about the shared catalogue is subordinate to this — including the
	 * catalogue itself, which is why it no longer has a rail button, an overflow row or
	 * a 720 × 720 window of its own. What is left is this card, in two places: the top
	 * of the material library and the end of setup. Both render this component, fed by
	 * `offerState` in `$lib/library.svelte`, in the pattern `actions.ts` and `jobPhase`
	 * set — where more than one surface has to know the same thing, it is written once.
	 *
	 * Four rules hold the card together, and each one answers something measured:
	 *
	 * 1. **It fetches per material, never in one press.** One bulk tick-list produced
	 *    fourteen of the author's twenty materials, all bound to a machine he does not
	 *    run. So there is a button per material and none for "all of it".
	 * 2. **Every import it makes can be taken back in one press.** That is what makes a
	 *    one-press fetch honest at all: an import you can undo is not a dump.
	 * 3. **It says where the rows come from.** The shared catalogue or the starting
	 *    points the app ships with, how old the copy is, and — because the catalogue is
	 *    CC BY — who gets the credit. A row copied without its attribution cannot
	 *    lawfully be passed on, so the credit is on screen at the moment of copying.
	 * 4. **It can be waved away, and then it stays away.** A card that comes back is a
	 *    nag, and this one would come back on every open of the library.
	 *
	 * Nothing is fetched when the card appears: naming the machine costs six COUNT(*)s
	 * over a 204 KB file, while the rows come from a cache that may go to the network
	 * with a ten-second timeout. Hanging the opening of the material library on that is
	 * how a feature gets switched off.
	 */
	import NumberField from './NumberField.svelte';
	import { i18n, t } from '$lib/i18n/index.svelte';
	import { StarterStore, operationName, type StarterRow } from '$lib/library.svelte';
	import { LASER_KINDS, laserKindLabel, type LaserKind } from '$lib/machines.svelte';

	let {
		/**
		 * What to do when the answer is a test grid rather than another fetch. Absent on
		 * a surface that cannot open that window — the last step of setup — and then the
		 * sentence stands on its own rather than a button that goes nowhere.
		 */
		onTestGrid = undefined,
		/** The library around this card has changed and should read itself again. */
		onChanged = undefined,
		/**
		 * Whether to keep one quiet line here when there is nothing to offer.
		 *
		 * True in the material library, false at the end of setup. Without it the shared
		 * catalogue has no door on a machine that has settings of its own — which is
		 * every machine that has been used — and with it on the wizard's last step the
		 * catalogue would be furniture on a page about a first cut.
		 */
		door = false
	}: { onTestGrid?: () => void; onChanged?: () => void; door?: boolean } = $props();

	const starter = new StarterStore(() =>
		typeof localStorage === 'undefined' ? '' : (localStorage.getItem('openkerf.token') ?? '')
	);

	let view = $derived(starter.view);
	let machine = $derived(starter.offer?.machine ?? null);
	let coverage = $derived(starter.offer?.coverage ?? null);

	// The two fields the match needs, as the reader is filling them in. They start from
	// what the profile says, so a kind the app derived is a prefill and not a question.
	let kind = $state<LaserKind | ''>('');
	let watt = $state('');
	$effect(() => {
		const known = machine?.laser_type;
		if (kind === '' && known && known !== 'unknown') kind = known as LaserKind;
	});

	$effect(() => {
		starter.load();
	});

	/**
	 * Whether the rows are on screen.
	 *
	 * Its own flag rather than `rows !== null`, because the offer's state moves under
	 * the list: taking over one material's rows turns `nothing` into `unburned`
	 * (measured — the machine now has settings, and none of them burned), and reading
	 * the list out of the state would close it after the first press. The state decides
	 * whether to *offer*; this decides whether a list the reader opened stays open.
	 */
	let looking = $state(false);

	/**
	 * Whether the way back out is on screen — and therefore whether the fetch button is.
	 *
	 * One flag rather than the same three terms written twice, because the button and the
	 * row it lives on are now decided in two places: with the list open the fold moves up
	 * on to the line above, and the row it left would otherwise stay behind empty (see the
	 * markup, where it was measured).
	 */
	let canFold = $derived(view.canFetch && looking && !starter.busy);

	async function look(refresh = false) {
		looking = true;
		await starter.look(refresh);
	}

	async function describeMachine() {
		const fields: { laser_type?: string; power_watt?: number | null } = {};
		if (kind) fields.laser_type = kind;
		if (watt.trim() !== '') fields.power_watt = Number(watt);
		if (!Object.keys(fields).length) return;
		if (await starter.describeMachine(fields)) await look();
	}

	async function notSure() {
		// The honest third answer to "how powerful is your tube": match on the kind
		// alone, and label every row as unmatched on power. A dead end here is a dead
		// end on the whole feature, because the registry carries no wattage to default
		// from — there is nothing to guess with.
		if (kind && kind !== machine?.laser_type) await starter.describeMachine({ laser_type: kind });
		if (await starter.say('power_unknown')) await look();
	}

	async function take(material: string) {
		if (await starter.take(material)) onChanged?.();
	}

	async function undo(batch: string) {
		if (await starter.undo(batch)) onChanged?.();
	}

	/** `3 mm · Cut` — the row's own data, in the order the library writes it. */
	function what(row: StarterRow): string {
		const thickness = row.thickness_mm === null ? null : `${i18n.number(row.thickness_mm)} mm`;
		return [thickness, operationName(row.operation)].filter(Boolean).join(' · ');
	}

	/**
	 * Who gets the credit for what is on screen.
	 *
	 * The handles of the rows themselves first: those are the people who measured or
	 * typed these numbers, and CC BY is about them. The catalogue's own line is the
	 * fallback for a copy that carries no handles — a cache written by an older client.
	 */
	let credited = $derived.by(() => {
		const handles = [...new Set((starter.rows ?? []).map((row) => row.by).filter(Boolean))];
		if (handles.length) return i18n.list(handles as string[]);
		return starter.catalogue?.attribution ?? null;
	});

	/** Whether every row on offer is somebody's guess rather than somebody's board. */
	let allStartingPoints = $derived(
		(starter.rows ?? []).length > 0 && (starter.rows ?? []).every((row) => row.tier !== 'measured')
	);

	let copied = $derived(
		starter.catalogue?.fetched_at ? i18n.dateTime(starter.catalogue.fetched_at * 1000) : null
	);
</script>

<!-- Two parts of the card that both branches below need: what a press has already
     done and can undo, and what the catalogue holds. Written once as snippets so the
     quiet door cannot drift away from the offer. -->
{#snippet foldUp()}
	<!-- The way back out. Without it the list is a one-way door: measured on a 900 px
	     window, opening it put the card at 1086 x 558 and pushed the reader's own materials
	     off the bottom of the library, with no control anywhere to fold it up again.
	     One button written once, because it is rendered from two places: on the line above
	     the list while the list is open, and on a row of its own where there is no such
	     line. -->
	<button class="btn subtle" onclick={() => (looking = false)}>{t('starter.hide')}</button>
{/snippet}

{#snippet tookLines()}
	{#if starter.imports.length}
		<!-- What this card just did, and the way back out of it — above the list and
		     not below it, because after a press of Add the list is 320 px of scroll
		     long and the undo would be off screen at exactly the moment it is wanted.
		     One press per import, and it takes the settings and the materials that
		     import created with it. -->
		<!-- Announced: the press that puts settings in removes the button it was made
		     with, so the focus falls away and this line is the only answer. It also sits
		     *above* the list, which means Tab from where the reader now is walks away
		     from the undo rather than towards it — one more reason to say it out loud. -->
		<ul class="took" role="status">
			{#each starter.imports as done (done.batch)}
				<li>
					<span>{t('starter.took', { n: done.presets, material: done.material })}</span>
					<button class="btn subtle mini" onclick={() => undo(done.batch)} disabled={starter.busy} title={starter.busy ? t('reason.busy') : undefined}>
						{t('starter.undo')}
					</button>
				</li>
			{/each}
		</ul>
	{/if}
{/snippet}

{#snippet catalogueRows()}
	{#if looking && starter.catalogue}
		<!-- Where these rows come from, how old they are, and who gets the credit.
		     CC BY means the credit travels with the row or the copy is not licensed,
		     so it stands here — at the moment of copying, where a reader looking for
		     it will look. -->
		<p class="source muted">
			{#if starter.catalogue.from_seed}
				{starter.catalogue.error ? t('starter.from.seedOffline') : t('starter.from.seed')}
			{:else if copied}
				{t('starter.from.shared', { when: copied })}
			{:else}
				{t('starter.from.sharedUndated')}
			{/if}
			{#if starter.catalogue.license && credited}
				{t('starter.licence', { license: starter.catalogue.license, who: credited })}
			{/if}
		</p>
		{#if starter.catalogue.very_stale}
			<p class="muted why">
				{t('starter.from.old')}
				<button class="btn subtle mini" onclick={() => look(true)} disabled={starter.busy} title={starter.busy ? t('reason.busy') : undefined}>
					{t('starter.refresh')}
				</button>
			</p>
		{/if}
		{#if view.powerUnknown}
			<p class="muted why">{t('starter.powerUnknown.note')}</p>
		{/if}
		{#if starter.catalogue.skipped}
			<p class="muted why">{t('starter.skipped', { n: starter.catalogue.skipped })}</p>
		{/if}
		{#if allStartingPoints && !view.suggestTestGrid}
			<!-- Said once rather than badged on every row. Every entry that exists
			     today is a starting point, and a mark that is on all 26 rows is not a
			     mark: DESIGN-SYSTEM v4 measured that with ten orange rows out of
			     thirteen, which read as ten faults instead of one caveat. -->
			<p class="advice">{t('starter.allStartingPoints')}</p>
		{/if}

		{#if starter.perMaterial.length}
			<!-- Announced, because the button that was pressed removes itself and takes the
			     focus with it. This one sentence is the answer to the press, so it is what a
			     reader who cannot see the list arrive should hear. -->
			<p class="muted why" role="status">
				{t('starter.rows.count', { n: starter.perMaterial.length })}
			</p>
			<ul class="materials">
				{#each starter.perMaterial as group (group.material)}
					<li>
						<div class="material">
							<!-- A material name is the reader's own data, and goes on screen
							     as it stands. -->
							<strong>{group.material}</strong>
							<button
								class="btn primary mini"
								onclick={() => take(group.material)}
								disabled={starter.busy}
								title={t('starter.take.why', { material: group.material })}
							>
								{t('starter.take')}
							</button>
						</div>
						<ul class="rows">
							{#each group.rows as row (row.id)}
								<li>
									<span class="mono">{what(row)}</span>
									<span class="values">
										{t('starter.row.values', {
											speed: i18n.number(row.speed_mm_s),
											power: i18n.number(row.power_percent)
										})}
									</span>
									{#if row.tier === 'measured'}
										<span class="tier ok">{t('starter.tier.measured')}</span>
									{:else if !allStartingPoints}
										<!-- Only where it distinguishes: in a list that is all
										     starting points the sentence above says it once. -->
										<span class="tier">{t('starter.tier.startingPoint')}</span>
									{/if}
									{#if row.power_unmatched && !view.powerUnknown}
										<!-- Again only where it distinguishes. When this machine has said
										     it does not know its own tube power, every row is unmatched on
										     power and the note above says so once; 26 amber pills would
										     read as 26 faults rather than as one caveat. -->
										<span class="tier warn">{t('starter.row.unmatched')}</span>
									{/if}
								</li>
							{/each}
						</ul>
					</li>
				{/each}
			</ul>
		{:else}
			<!-- Announced for the same reason as the count above: this is the answer. -->
			<p class="advice" role="status">{t('starter.rows.none')}</p>
		{/if}
	{/if}
{/snippet}

{#if view.needed}
	<section class="offer" aria-label={t('starter.region')}>
		<div class="head">
			<!-- The heading is the question the card is actually asking. Two of them for
			     `askMachine`, because that state has two causes and asking the wrong one is
			     worse than asking nothing: measured on a machine made through the wizard,
			     the kind was filled in from the catalogue entry and only the wattage was
			     missing, and the card still headed itself "What kind of laser is this?"
			     with the kind read back two lines below it. The column's default gives
			     every machine a kind, so that is the common case, not the rare one. -->
			<h2>
				{#if view.state === 'askMachine'}
					{view.needsKind ? t('starter.title.askMachine') : t('starter.title.askWatt')}
				{:else if view.state === 'unburned'}{t('starter.title.unburned')}
				{:else}{t('starter.title.nothing')}{/if}
			</h2>
			<button
				class="btn subtle away"
				onclick={() => starter.say('dismissed')}
				title={t('starter.away.why')}
			>
				{t('starter.away')}
			</button>
		</div>

		<!-- What the machine is. Without these two facts nothing below can match: an
		     80 W catalogue used to show all 26 of its rows to a machine nobody had
		     described, and that is the complaint this card answers.
		     Two values read back rather than a sentence with the kind glued into it:
		     "a CO2 with a glass tube laser of 80 watt" is a sentence no language has,
		     and a value you read is what the design system asks for anyway. -->
		{#if !machine}
			<p class="what">{t('starter.machine.none')}</p>
		{:else}
			<p class="what">{machine.name}</p>
			<dl class="says">
				<dt>{t('setup.laser.kind')}</dt>
				<dd>
					{view.needsKind ? t('starter.unrecorded') : laserKindLabel(machine.laser_type)}
				</dd>
				<dt>{t('setup.laser.watt')}</dt>
				<dd>
					{machine.power_watt ? `${i18n.number(machine.power_watt)} W` : t('starter.unrecorded')}
				</dd>
			</dl>
		{/if}

		<!-- What this machine has, and — while the list is open — the way to fold it up
		     again, on that same line. The fold used to sit on a row of its own below this
		     one, which measured as an empty band across the card: the row is 1050 px wide
		     with a borderless 130 px control at its right end, 14 px under this line and
		     16 px above the list, and the sentence that fills that area when the list is
		     shut (`starter.look.hint`) is hidden while it is open. So 920 px of nothing with
		     a faint word at the end of it, in the picture the handbook prints. Here it reads
		     as what it is — a statement with its control at the end, the same shape as the
		     heading with "Not now" and a material with "Add these". -->
		{#if coverage}
			<div class="state">
				<p class="has muted">
					{#if view.state === 'unburned'}
						{t('starter.has.unburned', { n: coverage.mine })}
					{:else if !coverage.materials_known}
						{t('starter.has.emptyLibrary')}
					{:else if !coverage.materials_covered}
						{t('starter.has.none', { n: coverage.materials_known })}
					{:else}
						{t('starter.has.some', {
							n: coverage.materials_covered,
							known: i18n.number(coverage.materials_known)
						})}
					{/if}
				</p>
				{#if canFold}{@render foldUp()}{/if}
			</div>
		{/if}

		{#if view.state === 'askMachine'}
			<!-- Not a dead end: the two fields are here, beside the sentence that says
			     why they matter, and "I am not sure" is a real third answer. -->
			<fieldset class="laser">
				<legend>{t('setup.laser')}</legend>
				<p class="muted why">{t('starter.ask.body')}</p>
				<div class="pair">
					<label class="choice">
						<span>{t('setup.laser.kind')}</span>
						<select bind:value={kind}>
							<option value="">{t('laser.kind.unknown')}</option>
							{#each LASER_KINDS as one (one)}
								<option value={one}>{laserKindLabel(one)}</option>
							{/each}
						</select>
					</label>
					<NumberField
						label={t('setup.laser.watt')}
						unit="W"
						bind:value={watt}
						step={10}
						min={1}
						max={1000}
					/>
				</div>
				<div class="buttons">
					<button
						class="btn subtle"
						onclick={notSure}
						disabled={starter.busy || !kind}
						title={kind ? undefined : t('starter.ask.kindFirst')}
					>
						{t('starter.ask.notSure')}
					</button>
					<button
						class="btn primary"
						onclick={describeMachine}
						disabled={starter.busy || !kind}
						title={kind ? undefined : t('starter.ask.kindFirst')}
					>
						{t('starter.ask.record')}
					</button>
				</div>
				<!-- Both buttons need the kind, and only one of them needs the wattage.
				     Measured before this: pressing "I am not sure" on a machine of an
				     unknown kind wrote the escape hatch, matched nothing at all — an
				     unknown kind is a miss in `matching.fits` on purpose — and then said
				     the catalogue held nothing for this laser, which was not true. A
				     disabled button that says why beats a fetch that lies. -->
				<p class="muted why">
					{kind ? t('starter.ask.notSure.body') : t('starter.ask.kindFirst')}
				</p>
			</fieldset>
		{/if}

		{@render tookLines()}

		{#if view.suggestTestGrid}
			<!-- Settings, but every one of them out of a catalogue. The answer to that is
			     not another catalogue: it is a board burned on this laser, which is the
			     only thing that turns a starting point into a measurement. -->
			<p class="advice">{t('starter.unburned.body')}</p>
			{#if onTestGrid}
				<div class="buttons">
					<button class="btn primary" onclick={onTestGrid}>{t('starter.unburned.grid')}</button>
				</div>
			{/if}
		{/if}

		<!-- The button stays while the fetch is in flight, saying "Looking…", and goes
		     only once there is something to read. It used to disappear on the press,
		     which is measured: with the catalogue answering in 2.5 s — a cold cache
		     really does go to the network with a ten-second timeout — the card lost its
		     button and said nothing at all for those seconds, the only thing left on it
		     being "Not now". `starter.looking` existed for this and could never render,
		     and the focus of a reader who pressed with the keyboard fell to the body. -->
		{#if view.canFetch && !canFold}
			<div class="buttons">
				<button class="btn" onclick={() => look()} disabled={starter.busy} title={starter.busy ? t('reason.busy') : undefined}>
					{starter.busy ? t('starter.looking') : t('starter.look')}
				</button>
			</div>
			{#if !looking && !starter.busy}<p class="muted why">{t('starter.look.hint')}</p>{/if}
		{:else if canFold && !coverage}
			<!-- No coverage line to hang the fold on — a machine the server described
			     without one. Then it keeps its own row: an empty band is better than no way
			     back out. -->
			<div class="buttons">{@render foldUp()}</div>
		{/if}

		{@render catalogueRows()}

		{#if starter.error}<p class="failure" role="alert">{starter.error}</p>{/if}
	</section>
{:else if door && machine}
	<!-- The door, for when there is nothing to offer.
	     `offerState` answers `needed: false` as soon as this machine has a setting it
	     measured itself, or as soon as the offer was waved away — and with the 720 × 720
	     window gone there was then no way left to reach the shared catalogue at all.
	     Measured on a copy of the author's own library: the active KH-5030 carries three
	     settings, all three its own, so the card never appears and the catalogue had no
	     door on the one machine it was built for.
	     So: one line, in the material library only, and never on the last step of setup —
	     a workspace consulted once per machine does not earn furniture. It is a door and
	     not the offer coming back: nothing is fetched until it is pressed, and a reader
	     who waved the offer away is not asked anything again. -->
	<section class="offer quiet" aria-label={t('starter.region')}>
		<div class="door">
			<!-- Stays while the fetch is in flight, saying "Looking…", for the same measured
			     reason as the button in the offer above: the catalogue can take seconds, and
			     a button that vanishes on the press leaves nothing on screen and no focus. -->
			{#if looking && !starter.busy}
				<button class="btn subtle" onclick={() => (looking = false)}>{t('starter.hide')}</button>
			{:else}
				<button class="btn subtle" onclick={() => look()} disabled={starter.busy} title={starter.busy ? t('reason.busy') : undefined}>
					{starter.busy ? t('starter.looking') : t('starter.door')}
				</button>
			{/if}
			<span class="muted why">{t('starter.door.body', { machine: machine.name ?? '' })}</span>
		</div>
		{@render tookLines()}
		{@render catalogueRows()}
		{#if starter.error}<p class="failure" role="alert">{starter.error}</p>{/if}
	</section>
{/if}

<style>
	/* A card and not a banner: it says something about this machine, it has buttons of
	   its own, and it lives at the top of two different surfaces. The accent on the left
	   edge is the same mark the sheet question in setup uses — something to decide, not
	   something broken. */
	.offer {
		display: grid;
		gap: var(--space-2);
		margin: 0 0 var(--space-4);
		padding: var(--space-3) var(--space-4);
		border: 1px solid var(--line);
		border-left: 3px solid var(--accent);
		border-radius: var(--radius-card);
		background: var(--surface-2);
	}
	/* The door is not a card: no accent edge, no fill, no border. It is one line of
	   furniture at the top of a window, and the whole point of this round was that the
	   catalogue stops being furniture. It only grows into something once it is pressed,
	   and then it is the same list the offer shows. */
	.offer.quiet {
		margin: 0 0 var(--space-3);
		padding: 0;
		border: 0;
		border-radius: 0;
		background: none;
	}
	.door {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2) var(--space-3);
	}
	.head {
		display: flex;
		align-items: baseline;
		gap: var(--space-3);
	}
	h2 {
		flex: 1;
		margin: 0;
		font-size: var(--text-sm);
		font-weight: 600;
	}
	p {
		margin: 0;
		font-size: var(--text-xs);
	}
	.what {
		font-size: var(--text-sm);
		font-weight: 600;
	}
	/* Two values, read back. A grid so the labels line up and the numbers under each
	   other, which is the whole point of reading them off a screen. */
	.says {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr);
		gap: 2px var(--space-3);
		margin: 0;
		font-size: var(--text-xs);
	}
	.says dt {
		color: var(--text-2);
	}
	.says dd {
		margin: 0;
	}
	.muted {
		color: var(--text-2);
	}
	.advice {
		color: var(--text-1);
	}
	.failure {
		color: var(--danger);
	}

	.laser {
		margin: var(--space-2) 0 0;
		padding: var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		display: grid;
		gap: var(--space-2);
	}
	.laser legend {
		padding: 0 4px;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	/* A pair stays on one line: the kind and the power are one statement about one
	   machine (DESIGN-SYSTEM v4, form rule 2). */
	.pair {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: var(--space-3);
		align-items: end;
	}
	.choice {
		display: grid;
		gap: 4px;
		min-width: 0;
	}
	.choice > span {
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.choice select {
		font: inherit;
		min-height: 40px;
		padding: 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}

	/* The machine's state with its control at the end of the line, not on a line of its
	   own — the shape `.head` and `.material` already have. */
	.state {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--space-3);
	}
	.state .has {
		min-width: 0;
	}

	/* Buttons on their own line, the primary one on the right (v4, form rule 6). */
	.buttons {
		display: flex;
		flex-wrap: wrap;
		justify-content: flex-end;
		gap: var(--space-3);
		margin-top: var(--space-1h);
	}
	.btn.subtle {
		background: none;
		border-color: transparent;
		color: var(--text-2);
	}
	.away {
		flex: none;
	}

	.source {
		margin-top: var(--space-2);
	}
	.why {
		font-size: var(--text-xs);
	}

	/* A bounded list rather than a page that grows with the catalogue. Fifteen
	   materials at the end of the wizard pushed "From here to your first cut" a
	   screen and a half down, and the card stopped being a card. */
	.materials {
		max-height: 320px;
		overflow-y: auto;
	}
	.materials,
	.rows,
	.took {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: var(--space-2);
	}
	.materials > li {
		padding-top: var(--space-2);
		border-top: 1px solid var(--line);
	}
	.material {
		display: flex;
		align-items: center;
		gap: var(--space-3);
	}
	.material strong {
		flex: 1;
		min-width: 0;
		font-size: var(--text-sm);
	}
	.rows {
		gap: 2px;
		margin-top: 4px;
	}
	.rows > li {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: var(--space-2);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.values {
		color: var(--text-1);
	}
	/* The tier is a label and a sort order, never a filter: every entry that exists
	   today is a starting point, so a default that hid them would make this card empty
	   on the day it ships. */
	.tier {
		padding: 1px 6px;
		border: 1px solid var(--line);
		border-radius: var(--radius-dot);
		font-size: var(--text-xs);
	}
	.tier.ok {
		color: var(--ok);
		border-color: var(--ok);
	}
	.tier.warn {
		color: var(--warn);
		border-color: var(--warn);
	}
	.took > li {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		font-size: var(--text-xs);
	}
	.took > li span {
		flex: 1;
	}

	/* With a glove on, 32px is too little, and this card lives on a tablet too. */
	@media (max-width: 1199px), (pointer: coarse) {
		.choice select {
			min-height: 44px;
		}
		.pair {
			grid-template-columns: minmax(0, 1fr);
		}
	}
</style>
