<script lang="ts">
	/**
	 * Step 4: the work area.
	 *
	 * This was a bare pass-through from the engine: "Width — Width of the laser
	 * bed.", "Force Declared Home — Override native home location", "Flip X",
	 * and two fields both called "Swap XY". Developer language, and the bed size —
	 * the only thing on this page that can really go wrong — carried exactly the same
	 * weight as "Flip Y".
	 *
	 * Now: bed size and origin are a block of their own with words of their own and a
	 * drawing that moves along. The rest of the engine's fields still exist, but sit
	 * under "More about this machine" and behind "All settings".
	 */
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import SettingFieldInput from '$components/SettingField.svelte';
	import NumberField from '$components/NumberField.svelte';
	import { t, type MessageKey } from '$lib/i18n/index.svelte';
	import { createStore } from '$lib/setup.svelte';
	import {
		LASER_KINDS,
		laserKindLabel,
		laserKindOfMachine,
		type LaserKind,
		type SettingField
	} from '$lib/machines.svelte';

	const store = createStore();

	let machinePath = $derived($page.url.searchParams.get('machine') ?? '');
	let values = $state<Record<string, unknown>>({});
	let essentialOnly = $state(true);

	/** What we put on screen ourselves; the engine must not show it a second time. */
	const OURS = ['bedwidth', 'bedheight', 'home_corner'];

	/**
	 * What the search button in step 1 found (decision B6).
	 *
	 * The port or the IP address comes along as a parameter and is filled in here —
	 * visibly, and only recorded when you press save. None of this makes a
	 * connection; that happens on the first job.
	 */
	let connection = $derived.by(() => {
		const raw = $page.url.searchParams.get('connection');
		if (!raw) return null;
		try {
			const parsed = JSON.parse(raw);
			return parsed && typeof parsed === 'object' ? (parsed as Record<string, string>) : null;
		} catch {
			return null;
		}
	});

	const CONNECTION_WORD: Record<string, MessageKey> = {
		interface: 'setup.connection.word.interface',
		address: 'setup.connection.word.address',
		serial_port: 'setup.connection.word.port'
	};
	/** "udp" is the engine's key, not a word for the screen. */
	const CONNECTION_VALUE: Record<string, MessageKey> = {
		udp: 'setup.connection.value.udp',
		usb: 'setup.connection.value.usb'
	};

	/** The engine's key in words, or the key itself when we have no word for it. */
	function inWords(map: Record<string, MessageKey>, key: string): string {
		return key in map ? t(map[key]) : key;
	}

	async function reload() {
		if (!machinePath) return;
		const sheets = await store.loadSettings(machinePath, essentialOnly);
		values = Object.fromEntries(
			sheets.flatMap((sheet) => sheet.fields.map((field) => [field.attr, field.value]))
		);
		// Only fill in what this machine really knows: a `serial_port` on a device
		// that has none is refused by the API.
		if (connection) {
			for (const [attr, value] of Object.entries(connection)) {
				if (attr in values) values[attr] = value;
			}
		}
	}

	onMount(reload);

	/**
	 * The engine registers bedwidth as a Length and hands back a string with a unit.
	 * The stepper works in millimetres, so the unit has to be taken into account —
	 * not thrown away.
	 *
	 * Ruida defaults to "24.0in". Taking only the digits turned that into a bed of 24
	 * by 16 millimetres: a canvas the size of a postage stamp, and nobody able to see
	 * why.
	 */
	const TO_MM: Record<string, number> = { mm: 1, cm: 10, in: 25.4, mil: 0.0254 };

	function asNumber(value: unknown): string {
		const text = String(value ?? '').trim();
		const found = text.match(/^\s*(-?\d+(?:\.\d+)?)\s*([a-zA-Z]*)/);
		if (!found) return '0';
		const factor = TO_MM[found[2].toLowerCase()] ?? 1;
		const mm = Number(found[1]) * factor;
		// No trail of floating-point digits behind a measure in millimetres.
		return String(Math.round(mm * 100) / 100);
	}

	let width = $state('0');
	let height = $state('0');
	let loaded = $state(false);

	$effect(() => {
		if (loaded || !('bedwidth' in values)) return;
		width = asNumber(values.bedwidth);
		height = asNumber(values.bedheight);
		loaded = true;
	});

	// Where the head goes when you say "home". The engine calls this "Force Declared
	// Home"; in the workshop it is simply the corner the head creeps to when you
	// switch it on.
	const CORNERS = [
		{ id: 'auto', label: t('setup.corner.auto') },
		{ id: 'top-left', label: t('setup.corner.topLeft') },
		{ id: 'top-right', label: t('setup.corner.topRight') },
		{ id: 'bottom-left', label: t('setup.corner.bottomLeft') },
		{ id: 'bottom-right', label: t('setup.corner.bottomRight') },
		{ id: 'center', label: t('setup.corner.centre') }
	];
	let hasCorner = $derived('home_corner' in values);
	let corner = $derived(String(values.home_corner ?? 'auto'));

	/** Position of the origin dot in the drawing, in per cent. */
	let originDot = $derived(
		{
			'top-left': { x: 0, y: 0 },
			'top-right': { x: 100, y: 0 },
			'bottom-left': { x: 0, y: 100 },
			'bottom-right': { x: 100, y: 100 },
			center: { x: 50, y: 50 }
		}[corner] ?? null
	);

	// The drawing is an ordinary SVG in pixels, not in millimetres: the trap from
	// DESIGN-SYSTEM ("every CSS length is then a millimetre") is never stepped into.
	// Only the *shape* of the bed follows the ratio.
	const DRAWING = { w: 200, h: 130 };
	/** Margin around it, so the bed reads as a surface *inside* a workspace. */
	const ROOM = { w: 176, h: 108 };
	let ratio = $derived(
		Math.max(0.2, Math.min(4, (Number(width) || 1) / (Number(height) || 1)))
	);
	let bedBox = $derived(
		ratio >= ROOM.w / ROOM.h
			? { w: ROOM.w, h: ROOM.w / ratio }
			: { w: ROOM.h * ratio, h: ROOM.h }
	);

	/**
	 * Everything the engine knows except what we show ourselves above.
	 *
	 * Deduplicated on the attribute: on Newly `swap_xy` sits in two sheets, with two
	 * different descriptions of the same checkbox. That produced not only two
	 * identical "Swap XY" rows but, in one list, a duplicate key as well — at which
	 * Svelte dropped the whole block and there was nothing left to see.
	 */
	let otherFields = $derived.by(() => {
		const seen = new Set(OURS);
		const fields: SettingField[] = [];
		for (const sheet of store.settings) {
			for (const field of sheet.fields) {
				if (seen.has(field.attr)) continue;
				seen.add(field.attr);
				fields.push(field);
			}
		}
		return fields;
	});
	let restOpen = $state(false);

	async function save() {
		if ('bedwidth' in values) {
			values.bedwidth = `${Number(width) || 0}mm`;
			values.bedheight = `${Number(height) || 0}mm`;
		}
		if (Object.keys(values).length) {
			if (!(await store.updateSettings(machinePath, values))) return;
		}
		await saveProfile();
		// `/setup/ready` never existed. The layout registers `/setup/done` as the fifth
		// step, so finishing the wizard landed on SvelteKit's 404 — and with it on
		// nothing: no first-cut route, no sheet question, and no offer of settings for
		// the machine that had just been created.
		await goto(`/setup/done?machine=${encodeURIComponent(machinePath)}`);
	}

	// The library profile belongs to this device; the fields below live there, not in
	// the engine. Two of them decide whether this machine can ever be offered a setting
	// that suits it: MeerK40t's own registry carries no wattage anywhere — grepped, in
	// all 46 catalogue entries — so the tube power is the one thing that has to be
	// asked, and here is where machine-wide facts belong (CLAUDE.md's placement rule).
	let hasZ = $state(false);
	let hasAutofocus = $state(false);
	let profileId = $state<number | null>(null);
	/** The kind of laser: derived from the catalogue entry, and changeable. */
	let laserKind = $state<LaserKind>('unknown');
	let watt = $state('');
	let lens = $state('');
	/**
	 * "I am not sure what my tube is" — a legitimate answer, and the one the whole
	 * feature needs to survive.
	 *
	 * There is nothing to default a wattage from, so refusing without one would leave
	 * every reader who does not know their tube with a dead end. Ticked, it records
	 * `starter_state = 'power_unknown'`: the catalogue then matches on the kind of laser
	 * alone and says so on every row it shows.
	 */
	let wattUnknown = $state(false);
	let profileRead = $state(false);
	/** What the profile already said about the offer, so saving does not undo it. */
	let starterState = $state('');

	$effect(() => {
		if (!machinePath || profileRead) return;
		(async () => {
			const response = await fetch('/api/library/active-machine');
			if (!response.ok) return;
			const profile = await response.json();
			if (profile.device_path !== machinePath) return;
			profileRead = true;
			profileId = profile.id;
			hasZ = Boolean(profile.has_z);
			hasAutofocus = Boolean(profile.has_autofocus);
			if (profile.power_watt) watt = String(profile.power_watt);
			if (profile.lens_mm) lens = String(profile.lens_mm);
			starterState = String(profile.starter_state ?? '');
			wattUnknown = starterState === 'power_unknown';
			// What the library already says wins over the derivation: a reader who has
			// corrected a glass tube to an RF one must not have it corrected back on the
			// next visit. `co2-glass` is the column's default for a profile nobody has
			// described, so it counts as unsaid and the catalogue decides.
			const said = String(profile.laser_type ?? '');
			if (said && said !== 'unknown' && said !== 'co2-glass') laserKind = said as LaserKind;
			else await deriveKind();
		})();
	});

	/**
	 * Which kind of laser this is, from the catalogue line the machine was made from.
	 *
	 * Derived and never asked as free text: the entry says it, and a reader standing in
	 * their workshop should not have to translate "co2-glass" out of a driver name. It
	 * is prefilled and changeable, because a glass tube and an RF metal tube cannot be
	 * told apart from this data at all.
	 */
	async function deriveKind() {
		if (!store.catalog.length) await store.loadCatalog();
		if (!store.machines.length) await store.loadMachines();
		const info = await store.infoKey(machinePath);
		const device = store.machines.find((m) => m.path === machinePath) ?? null;
		laserKind = laserKindOfMachine(store.catalog, { info, provider: device?.provider ?? null });
	}

	async function saveProfile() {
		if (profileId === null) return;
		const token = localStorage.getItem('openkerf.token') ?? '';
		const fields: Record<string, unknown> = {
			has_z: hasZ,
			has_autofocus: hasAutofocus,
			laser_type: laserKind,
			// Empty on purpose when the reader does not know: a wattage nobody typed must
			// not be invented, and the state below is what says so out loud.
			power_watt: wattUnknown || watt.trim() === '' ? null : Number(watt),
			lens_mm: lens.trim() === '' ? null : Number(lens)
		};
		// Only ever touched when this page has something to say about it. Writing an
		// empty state unasked would bring a card back that the reader had waved away on
		// another screen, and that is the one thing an offer must not do.
		if (wattUnknown) fields.starter_state = 'power_unknown';
		else if (starterState === 'power_unknown') fields.starter_state = '';
		await fetch(`/api/library/machines/${profileId}`, {
			method: 'PATCH',
			headers: {
				'Content-Type': 'application/json',
				...(token ? { Authorization: `Bearer ${token}` } : {})
			},
			body: JSON.stringify(fields)
		});
	}
</script>

<svelte:head><title>{t('setup.head.workarea')}</title></svelte:head>

<section class="setup">
	{#if store.error}<p class="error" role="alert">{store.error}</p>{/if}

	{#if !machinePath}
		<h1>{t('setup.noMachine')}</h1>
		<p class="muted">{t('setup.noMachine.body')}</p>
		<div class="actions"><a class="btn primary" href="/setup">{t('setup.toOverview')}</a></div>
	{:else}
		{#if connection}
			{@const filled = Object.entries(connection).filter(([attr]) => attr in values)}
			<p class="connection">
				<strong>{t('setup.connection.filled')}</strong>
				{#if filled.length}
					<span class="mono">
						{filled
							.map(
								([attr, value]) =>
									`${inWords(CONNECTION_WORD, attr)}: ${inWords(CONNECTION_VALUE, value)}`
							)
							.join(' · ')}
					</span>
				{:else}
					<span class="muted">{t('setup.connection.unknown')}</span>
				{/if}
				<span class="muted">{t('setup.connection.notYet')}</span>
			</p>
		{/if}

		<h1>{t('setup.bedSize')}</h1>
		<p class="muted">{t('setup.bedSize.body')}</p>

		<div class="workarea">
			<div class="fields">
				{#if 'bedwidth' in values}
					<NumberField label={t('gen.width')} unit="mm" bind:value={width} step={10} min={1} />
					<NumberField label={t('gen.height')} unit="mm" bind:value={height} step={10} min={1} />
				{:else}
					<p class="muted">{t('setup.noBedSize')}</p>
				{/if}

				{#if hasCorner}
					<label class="choice">
						<span>{t('setup.whereIsZero')}</span>
						<select
							value={corner}
							onchange={(e) => (values.home_corner = e.currentTarget.value)}
						>
							{#each CORNERS as option (option.id)}
								<option value={option.id}>{option.label}</option>
							{/each}
						</select>
						<span class="hint">{t('setup.corner.hint')}</span>
					</label>
				{/if}
			</div>

			<figure class="drawing">
				<svg viewBox="0 0 {DRAWING.w} {DRAWING.h}" role="img"
					aria-label={t('setup.bedAria', { width: width, height: height })}>
					<defs>
						<pattern id="bedgrid" width="10" height="10" patternUnits="userSpaceOnUse">
							<path d="M10 0 L0 0 0 10" fill="none" stroke="var(--line)" stroke-width="0.5" />
						</pattern>
					</defs>
					<rect width={DRAWING.w} height={DRAWING.h} class="plate" />
					<g transform="translate({(DRAWING.w - bedBox.w) / 2} {(DRAWING.h - bedBox.h) / 2})">
							<rect width={bedBox.w} height={bedBox.h} class="bed" />
							<rect width={bedBox.w} height={bedBox.h} fill="url(#bedgrid)" />
							<rect width={bedBox.w} height={bedBox.h} class="edge" />
							{#if originDot}
								<circle
									cx={(bedBox.w * originDot.x) / 100}
									cy={(bedBox.h * originDot.y) / 100}
									r="3.5"
									class="originMark"
								/>
							{/if}
					</g>
				</svg>
				<figcaption>
					<span class="size mono">{width} × {height} mm</span>
					{#if originDot}{t('setup.zeroOnDot')}{:else}{t('setup.zeroByMachine')}{/if}
				</figcaption>
			</figure>
		</div>

		<!-- What kind of light this machine makes, and how much of it. Neither is in the
		     engine's registry, and without them the shared catalogue cannot tell which
		     settings would suit this laser: measured before this, an 80 W catalogue
		     showed all 26 of its rows to a machine nobody had described. Asked once,
		     here, because machine-wide facts belong to the setup flow. -->
		<fieldset class="laser">
			<legend>{t('setup.laser')}</legend>
			<p class="muted hint">{t('setup.laser.body')}</p>
			<div class="fields">
				<label class="choice">
					<span>{t('setup.laser.kind')}</span>
					<select bind:value={laserKind}>
						<option value="unknown">{t('laser.kind.unknown')}</option>
						{#each LASER_KINDS as kind (kind)}
							<option value={kind}>{laserKindLabel(kind)}</option>
						{/each}
					</select>
					<span class="hint">{t('setup.laser.kind.hint')}</span>
				</label>
				<NumberField
					label={t('setup.laser.watt')}
					unit="W"
					bind:value={watt}
					step={10}
					min={1}
					max={1000}
					disabled={wattUnknown}
					why={t('setup.laser.wattUnknown')}
				/>
				<label class="toggle">
					<input type="checkbox" bind:checked={wattUnknown} />
					<span>{t('setup.laser.wattUnknown')}</span>
				</label>
				<p class="muted hint">
					{wattUnknown ? t('setup.laser.wattUnknown.then') : t('setup.laser.watt.why')}
				</p>
				<NumberField
					label={t('setup.laser.lens')}
					unit="mm"
					bind:value={lens}
					step={5}
					min={1}
				/>
			</div>
		</fieldset>

		<!-- What the machine *can* do. This is not in the engine — it is a statement by
		     the user about their own device, and it decides what appears in the jog
		     controls. -->
		<fieldset class="capabilities">
			<legend>{t('setup.capabilities')}</legend>
			<label class="toggle">
				<input type="checkbox" bind:checked={hasZ} />
				<span>{t('setup.hasZ')}</span>
			</label>
			<label class="toggle">
				<input type="checkbox" bind:checked={hasAutofocus} />
				<span>{t('setup.hasAutofocus')}</span>
			</label>
		</fieldset>

		{#if otherFields.length}
			<details class="rest" bind:open={restOpen}>
				<summary>
					{t('setup.more')}
					<span class="muted">{t('setup.more.what')}</span>
				</summary>
				<p class="muted warning">{t('setup.more.warning')}</p>
				<label class="toggle">
					<input
						type="checkbox"
						checked={!essentialOnly}
						onchange={(e) => {
							essentialOnly = !e.currentTarget.checked;
							loaded = false;
							reload();
						}}
					/>
					<span>{t('setup.showHidden')}</span>
				</label>
				{#each otherFields as field (field.attr)}
					<SettingFieldInput {field} bind:value={values[field.attr]} />
				{/each}
			</details>
		{/if}

		<div class="actions">
			<a class="btn" href="/setup">{t('setup.skip')}</a>
			<button class="btn primary" onclick={save} disabled={store.busy} title={store.busy ? t('reason.busy') : undefined}>
				{store.busy ? t('setup.saving') : t('setup.saveAndFinish')}
			</button>
		</div>
	{/if}
</section>

<style>
	.connection {
		display: grid;
		gap: 4px;
		margin: 0 0 var(--space-4);
		padding: var(--space-2) var(--space-3);
		font-size: var(--text-xs);
		border-left: 3px solid var(--ok);
		background: var(--surface-2);
		border-radius: var(--radius-field);
	}
	.connection .muted {
		color: var(--text-2);
	}
	.workarea {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: var(--space-6);
		align-items: start;
		margin: var(--space-4) 0;
	}
	.fields {
		display: grid;
		gap: var(--space-3);
		min-width: 0;
		/* A 520px stepper for a three-digit number puts − and + so far apart that you
		   no longer read them as one control. */
		max-width: 320px;
	}
	.choice {
		display: grid;
		gap: 4px;
	}
	.choice > span:first-child {
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.choice select {
		font: inherit;
		padding: 8px;
		min-height: 40px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.hint {
		font-size: var(--text-xs);
		color: var(--text-2);
	}

	.drawing {
		margin: 0;
		width: 240px;
	}
	.drawing svg {
		width: 100%;
		height: auto;
		display: block;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
	}
	/* The bed lay as a white surface on a white card and read as an empty box. Now it
	   sits on the same ground as on the canvas, *with* the mm grid: then you recognise
	   what you are looking at without a caption. */
	.drawing .plate {
		fill: var(--canvas-bg);
	}
	.drawing .bed {
		fill: var(--bed);
	}
	.drawing .edge {
		fill: none;
		stroke: var(--text-2);
		stroke-width: 1;
	}
	.drawing .originMark {
		fill: var(--accent);
	}
	.drawing figcaption {
		display: grid;
		gap: 2px;
		font-size: var(--text-xs);
		color: var(--text-2);
		text-align: center;
		margin-top: var(--space-2);
	}
	.drawing .size {
		color: var(--text-1);
	}

	/* The same block as the capabilities below it: a set of related fields with a
	   heading, which is what DESIGN-SYSTEM v4's form rule 7 asks for as soon as there
	   are more than two of them. */
	.laser {
		margin: var(--space-4) 0;
		padding: var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		display: grid;
		gap: var(--space-3);
	}
	.laser legend {
		font-size: var(--text-xs);
		color: var(--text-2);
		padding: 0 4px;
	}
	.laser .fields {
		max-width: 320px;
	}
	.laser .hint {
		margin: 0;
	}

	.capabilities {
		margin: var(--space-4) 0;
		padding: var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		display: grid;
		gap: var(--space-2);
	}
	.capabilities legend { font-size: var(--text-xs); color: var(--text-2); padding: 0 4px; }

	.rest {
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		padding: var(--space-3);
	}
	.rest summary {
		cursor: pointer;
		font-weight: 500;
		/* A collapse row is a touch target, gloved as well. */
		min-height: 32px;
		display: flex;
		align-items: center;
		gap: var(--space-1h);
		flex-wrap: wrap;
	}
	.rest .warning {
		font-size: var(--text-xs);
		margin: var(--space-3) 0 0;
	}

	.toggle {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin: var(--space-3) 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.toggle input { width: 16px; height: 16px; accent-color: var(--accent); }

	/* On a tablet and a phone the drawing sits *below* the fields: side by side the
	   stepper gets so narrow there that the buttons touch each other. */
	/* Touch targets hold on tablet *and* phone; this was at 767px and so left the
	   tablet at 40px (measured: select 40, expander row 32). */
	@media (max-width: 1199px) {
		.rest summary,
		.choice select {
			min-height: 44px;
		}
		.toggle input { width: 22px; height: 22px; }
	}
	@media (max-width: 767px) {
		.workarea {
			grid-template-columns: minmax(0, 1fr);
		}
		.drawing {
			width: 100%;
			max-width: 260px;
		}
	}
</style>
