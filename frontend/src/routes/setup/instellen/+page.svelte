<script lang="ts">
	/**
	 * Stap 4: het werkgebied.
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
	import type { SettingField } from '$lib/machines.svelte';

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
		const rauw = $page.url.searchParams.get('connection');
		if (!rauw) return null;
		try {
			const uit = JSON.parse(rauw);
			return uit && typeof uit === 'object' ? (uit as Record<string, string>) : null;
		} catch {
			return null;
		}
	});

	const VERBINDINGSWOORD: Record<string, MessageKey> = {
		interface: 'setup.connection.word.interface',
		address: 'setup.connection.word.address',
		serial_port: 'setup.connection.word.port'
	};
	/** "udp" is the engine's key, not a word for the screen. */
	const VERBINDINGSWAARDE: Record<string, MessageKey> = {
		udp: 'setup.connection.value.udp',
		usb: 'setup.connection.value.usb'
	};

	/** The engine's key in words, or the key itself when we have no word for it. */
	function woord(map: Record<string, MessageKey>, key: string): string {
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
			for (const [attr, waarde] of Object.entries(connection)) {
				if (attr in values) values[attr] = waarde;
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
	const NAAR_MM: Record<string, number> = { mm: 1, cm: 10, in: 25.4, mil: 0.0254 };

	function alsGetal(waarde: unknown): string {
		const tekst = String(waarde ?? '').trim();
		const gevonden = tekst.match(/^\s*(-?\d+(?:\.\d+)?)\s*([a-zA-Z]*)/);
		if (!gevonden) return '0';
		const factor = NAAR_MM[gevonden[2].toLowerCase()] ?? 1;
		const mm = Number(gevonden[1]) * factor;
		// No trail of floating-point digits behind a measure in millimetres.
		return String(Math.round(mm * 100) / 100);
	}

	let breedte = $state('0');
	let hoogte = $state('0');
	let geladen = $state(false);

	$effect(() => {
		if (geladen || !('bedwidth' in values)) return;
		breedte = alsGetal(values.bedwidth);
		hoogte = alsGetal(values.bedheight);
		geladen = true;
	});

	// Where the head goes when you say "home". The engine calls this "Force Declared
	// Home"; in the workshop it is simply the corner the head creeps to when you
	// switch it on.
	const HOEKEN = [
		{ id: 'auto', label: t('setup.corner.auto') },
		{ id: 'top-left', label: t('setup.corner.topLeft') },
		{ id: 'top-right', label: t('setup.corner.topRight') },
		{ id: 'bottom-left', label: t('setup.corner.bottomLeft') },
		{ id: 'bottom-right', label: t('setup.corner.bottomRight') },
		{ id: 'center', label: t('setup.corner.centre') }
	];
	let heeftHoek = $derived('home_corner' in values);
	let hoek = $derived(String(values.home_corner ?? 'auto'));

	/** Position of the origin dot in the drawing, in per cent. */
	let stip = $derived(
		{
			'top-left': { x: 0, y: 0 },
			'top-right': { x: 100, y: 0 },
			'bottom-left': { x: 0, y: 100 },
			'bottom-right': { x: 100, y: 100 },
			center: { x: 50, y: 50 }
		}[hoek] ?? null
	);

	// The drawing is an ordinary SVG in pixels, not in millimetres: the trap from
	// DESIGN-SYSTEM ("every CSS length is then a millimetre") is never stepped into.
	// Only the *shape* of the bed follows the ratio.
	const DRAWING = { w: 200, h: 130 };
	/** Margin around it, so the bed reads as a surface *inside* a workspace. */
	const ROOM = { w: 176, h: 108 };
	let verhouding = $derived(
		Math.max(0.2, Math.min(4, (Number(breedte) || 1) / (Number(hoogte) || 1)))
	);
	let bedDoos = $derived(
		verhouding >= ROOM.w / ROOM.h
			? { w: ROOM.w, h: ROOM.w / verhouding }
			: { w: ROOM.h * verhouding, h: ROOM.h }
	);

	/**
	 * Everything the engine knows except what we show ourselves above.
	 *
	 * Deduplicated on the attribute: on Newly `swap_xy` sits in two sheets, with two
	 * different descriptions of the same checkbox. That produced not only two
	 * identical "Swap XY" rows but, in one list, a duplicate key as well — at which
	 * Svelte dropped the whole block and there was nothing left to see.
	 */
	let restVelden = $derived.by(() => {
		const gezien = new Set(OURS);
		const velden: SettingField[] = [];
		for (const sheet of store.settings) {
			for (const field of sheet.fields) {
				if (gezien.has(field.attr)) continue;
				gezien.add(field.attr);
				velden.push(field);
			}
		}
		return velden;
	});
	let restOpen = $state(false);

	async function save() {
		if ('bedwidth' in values) {
			values.bedwidth = `${Number(breedte) || 0}mm`;
			values.bedheight = `${Number(hoogte) || 0}mm`;
		}
		if (Object.keys(values).length) {
			if (!(await store.updateSettings(machinePath, values))) return;
		}
		await bewaarProfiel();
		await goto(`/setup/klaar?machine=${encodeURIComponent(machinePath)}`);
	}

	// The library profile belongs to this device; the checkboxes below live there,
	// not in the engine.
	let heeftZ = $state(false);
	let heeftAutofocus = $state(false);
	let profielId = $state<number | null>(null);

	$effect(() => {
		if (!machinePath) return;
		(async () => {
			const response = await fetch('/api/library/active-machine');
			if (!response.ok) return;
			const profiel = await response.json();
			if (profiel.device_path !== machinePath) return;
			profielId = profiel.id;
			heeftZ = Boolean(profiel.has_z);
			heeftAutofocus = Boolean(profiel.has_autofocus);
		})();
	});

	async function bewaarProfiel() {
		if (profielId === null) return;
		const token = localStorage.getItem('openkerf.token') ?? '';
		await fetch(`/api/library/machines/${profielId}`, {
			method: 'PATCH',
			headers: {
				'Content-Type': 'application/json',
				...(token ? { Authorization: `Bearer ${token}` } : {})
			},
			body: JSON.stringify({ has_z: heeftZ, has_autofocus: heeftAutofocus })
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
			{@const ingevuld = Object.entries(connection).filter(([attr]) => attr in values)}
			<p class="connection">
				<strong>{t('setup.connection.filled')}</strong>
				{#if ingevuld.length}
					<span class="mono">
						{ingevuld
							.map(
								([attr, waarde]) =>
									`${woord(VERBINDINGSWOORD, attr)}: ${woord(VERBINDINGSWAARDE, waarde)}`
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

		<div class="werkgebied">
			<div class="velden">
				{#if 'bedwidth' in values}
					<NumberField label={t('gen.width')} unit="mm" bind:value={breedte} step={10} min={1} />
					<NumberField label={t('gen.height')} unit="mm" bind:value={hoogte} step={10} min={1} />
				{:else}
					<p class="muted">{t('setup.noBedSize')}</p>
				{/if}

				{#if heeftHoek}
					<label class="keuze">
						<span>{t('setup.whereIsZero')}</span>
						<select
							value={hoek}
							onchange={(e) => (values.home_corner = e.currentTarget.value)}
						>
							{#each HOEKEN as optie (optie.id)}
								<option value={optie.id}>{optie.label}</option>
							{/each}
						</select>
						<span class="hint">{t('setup.corner.hint')}</span>
					</label>
				{/if}
			</div>

			<figure class="drawing">
				<svg viewBox="0 0 {DRAWING.w} {DRAWING.h}" role="img"
					aria-label={t('setup.bedAria', { width: breedte, height: hoogte })}>
					<defs>
						<pattern id="bedgrid" width="10" height="10" patternUnits="userSpaceOnUse">
							<path d="M10 0 L0 0 0 10" fill="none" stroke="var(--line)" stroke-width="0.5" />
						</pattern>
					</defs>
					<rect width={DRAWING.w} height={DRAWING.h} class="plate" />
					<g transform="translate({(DRAWING.w - bedDoos.w) / 2} {(DRAWING.h - bedDoos.h) / 2})">
							<rect width={bedDoos.w} height={bedDoos.h} class="bed" />
							<rect width={bedDoos.w} height={bedDoos.h} fill="url(#bedgrid)" />
							<rect width={bedDoos.w} height={bedDoos.h} class="rand" />
							{#if stip}
								<circle
									cx={(bedDoos.w * stip.x) / 100}
									cy={(bedDoos.h * stip.y) / 100}
									r="3.5"
									class="oorsprong"
								/>
							{/if}
					</g>
				</svg>
				<figcaption>
					<span class="maat mono">{breedte} × {hoogte} mm</span>
					{#if stip}{t('setup.zeroOnDot')}{:else}{t('setup.zeroByMachine')}{/if}
				</figcaption>
			</figure>
		</div>

		<!-- What the machine *can* do. This is not in the engine — it is a statement by
		     the user about their own device, and it decides what appears in the jog
		     controls. -->
		<fieldset class="kunnen">
			<legend>{t('setup.capabilities')}</legend>
			<label class="toggle">
				<input type="checkbox" bind:checked={heeftZ} />
				<span>{t('setup.hasZ')}</span>
			</label>
			<label class="toggle">
				<input type="checkbox" bind:checked={heeftAutofocus} />
				<span>{t('setup.hasAutofocus')}</span>
			</label>
		</fieldset>

		{#if restVelden.length}
			<details class="rest" bind:open={restOpen}>
				<summary>
					{t('setup.more')}
					<span class="muted">{t('setup.more.what')}</span>
				</summary>
				<p class="muted waarschuwing">{t('setup.more.warning')}</p>
				<label class="toggle">
					<input
						type="checkbox"
						checked={!essentialOnly}
						onchange={(e) => {
							essentialOnly = !e.currentTarget.checked;
							geladen = false;
							reload();
						}}
					/>
					<span>{t('setup.showHidden')}</span>
				</label>
				{#each restVelden as field (field.attr)}
					<SettingFieldInput {field} bind:value={values[field.attr]} />
				{/each}
			</details>
		{/if}

		<div class="actions">
			<a class="btn" href="/setup">{t('setup.skip')}</a>
			<button class="btn primary" onclick={save} disabled={store.busy}>
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
	.werkgebied {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: var(--space-6);
		align-items: start;
		margin: var(--space-4) 0;
	}
	.velden {
		display: grid;
		gap: var(--space-3);
		min-width: 0;
		/* A 520px stepper for a three-digit number puts − and + so far apart that you
		   no longer read them as one control. */
		max-width: 320px;
	}
	.keuze {
		display: grid;
		gap: 4px;
	}
	.keuze > span:first-child {
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.keuze select {
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
	.drawing .rand {
		fill: none;
		stroke: var(--text-2);
		stroke-width: 1;
	}
	.drawing .oorsprong {
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
	.drawing .maat {
		color: var(--text-1);
	}

	.kunnen {
		margin: var(--space-4) 0;
		padding: var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		display: grid;
		gap: var(--space-2);
	}
	.kunnen legend { font-size: var(--text-xs); color: var(--text-2); padding: 0 4px; }

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
	.rest .waarschuwing {
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
		.keuze select {
			min-height: 44px;
		}
		.toggle input { width: 22px; height: 22px; }
	}
	@media (max-width: 767px) {
		.werkgebied {
			grid-template-columns: minmax(0, 1fr);
		}
		.drawing {
			width: 100%;
			max-width: 260px;
		}
	}
</style>
