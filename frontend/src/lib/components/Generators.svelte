<script lang="ts">
	import { untrack } from 'svelte';
	import { i18n, t } from '$lib/i18n/index.svelte';
	import Dialog from './Dialog.svelte';
	import FontPicker from './FontPicker.svelte';
	import GeneratorPreview from './GeneratorPreview.svelte';
	import NumberField from './NumberField.svelte';
	import Segmented from './Segmented.svelte';

	import type { Voorbeeld } from './GeneratorPreview.svelte';

	let {
		open = $bindable(),
		hasSelection = false,
		selectedIds = [],
		busy = false,
		hasZAxis = false,
		listAttached = false,
		onGenerate
	}: {
		open: boolean;
		hasSelection?: boolean;
		/** Can the software move this machine's Z? The focus test is the one tab that
		 *  cannot do anything without it — it would burn every mark at the same height —
		 *  so on other machines the tab is not there. Same flag as the drop per pass. */
		hasZAxis?: boolean;
		/** What has to be repeated. Without this list, repeat and circle cannot show
		 *  a real preview; the image then falls back on the sketch that only explains
		 *  the fields. */
		selectedIds?: string[];
		busy?: boolean;
		/**
		 * Is there a list to take the next name from? (`SeriesStore.attached`.)
		 *
		 * Only the Repeat tab asks: without a list "each copy takes the next name" has
		 * no next name, and the API refuses it (`gen.noList`). Grey with the reason
		 * beside it rather than absent — a control that is not there teaches nobody
		 * that the feature exists.
		 */
		listAttached?: boolean;
		onGenerate: (
			what: string,
			body: Record<string, unknown>
		) => Promise<{ error?: string | null; notice?: string | null }>;
	} = $props();

	type Tab =
		| 'grid'
		| 'radial'
		| 'polygon'
		| 'box'
		| 'qrcode'
		| 'barcode'
		| 'arctext'
		| 'hinge'
		| 'focus';
	type HingePattern = 'straight' | 'staggered' | 'wavy';
	let tab = $state<Tab>('grid');
	let error = $state<string | null>(null);

	let grid = $state({
		columns: '4',
		rows: '3',
		gap_x_mm: '5',
		gap_y_mm: '5',
		// The gap this closes: `grid` copies with a plain `copy(node)` and knows nothing
		// about a list, so three copies of a tag reading `{name}` came out as three
		// Annas while chain-duplicating walked the list. Two ways of copying that
		// disagree is worse than either.
		follow_list: false
	});
	let radial = $state({ repeats: '8', radius_mm: '40', rotate: true });
	let polygon = $state({ corners: '6', radius_mm: '20', inner: '', cx_mm: '50', cy_mm: '50' });
	let box = $state({
		width_mm: '100',
		depth_mm: '80',
		height_mm: '50',
		thickness_mm: '3',
		finger_mm: '10',
		kerf_mm: '0.15',
		lid: true,
		spread: true
	});
	let qr = $state({ text: '', size_mm: '30' });
	let bar = $state({ text: '', kind: 'code128', width_mm: '60', height_mm: '20' });
	let arc = $state({
		text: '',
		cx_mm: '100',
		cy_mm: '100',
		radius_mm: '40',
		font_size_mm: '10',
		inside: false,
		// The API already knew `font`; only this dialog never asked for it, so every
		// arc text came out in the default typeface. The same picker as the text
		// dialog — with a preview in the typeface itself.
		font: '',
		fontName: ''
	});

	let hinge = $state({
		pattern: 'staggered' as HingePattern,
		slit_mm: '8',
		gap_mm: '3',
		row_mm: '2',
		x_mm: '0',
		y_mm: '0',
		width_mm: '60',
		height_mm: '40',
		from_selection: false
	});

	let focus = $state({
		z_from_mm: '-2',
		z_to_mm: '2',
		marks: '9',
		mark_mm: '15',
		gap_mm: '8',
		x_mm: '10',
		y_mm: '10',
		text: true
	});

	// The types python-barcode can handle that make sense on a laser.
	const BARCODES = ['code128', 'code39', 'ean13', 'ean8', 'upca', 'itf', 'issn'];

	// "Grid" was called the same as the test grid, and that is something else
	// entirely. "Repeat" says what it does.
	const TABS: { id: Tab; label: string; needsSelection: boolean; icon: string }[] = [
		{
			id: 'grid',
			label: t('gen.tab.grid'),
			needsSelection: true,
			icon: 'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z'
		},
		{
			id: 'radial',
			label: t('gen.tab.radial'),
			needsSelection: true,
			icon: 'M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16zM12 4v3M20 12h-3M12 20v-3M4 12h3'
		},
		{ id: 'polygon', label: t('gen.tab.polygon'), needsSelection: false, icon: 'M12 3l8 6-3 10H7L4 9z' },
		{
			id: 'box',
			label: t('gen.tab.box'),
			needsSelection: false,
			icon: 'M3 8l9-5 9 5-9 5zM3 8v8l9 5 9-5V8'
		},
		{
			id: 'qrcode',
			label: t('gen.tab.qrcode'),
			needsSelection: false,
			icon: 'M3.5 3.5h6v6h-6zM14.5 3.5h6v6h-6zM3.5 14.5h6v6h-6zM14.5 15h2v2h-2zM19 19h1.5v1.5H19'
		},
		{
			id: 'barcode',
			label: t('gen.tab.barcode'),
			needsSelection: false,
			icon: 'M4 5v14M7.5 5v14M10 5v14M14 5v14M17 5v14M20 5v14'
		},
		{
			id: 'arctext',
			label: t('gen.tab.arctext'),
			needsSelection: false,
			icon: 'M4 16a8 8 0 0 1 16 0M8 12l.8-2.4M12 10.6V8M16 12l-.8-2.4'
		},
		{
			id: 'hinge',
			// The icon is the pattern itself: two rows of slits, the second one shifted.
			// That is the one thing about a hinge you can see without reading.
			label: t('gen.tab.hinge'),
			needsSelection: false,
			icon: 'M4 8h5M12 8h5M20 8h1M3 12h2M8 12h5M16 12h5M4 16h5M12 16h5M20 16h1'
		},
		{
			id: 'focus',
			// The icon is the board: lines of the same length at different heights, the
			// middle one the sharpest.
			label: t('gen.tab.focus'),
			needsSelection: false,
			icon: 'M4 6v12M8 8v8M12 4v16M16 8v8M20 6v12'
		}
	];

	// A tab that can do nothing on this machine is not shown greyed out but left out:
	// the whole point of the board is that the head moves between the marks.
	let tabs = $derived(TABS.filter((item) => item.id !== 'focus' || hasZAxis));
	// Switching machine can take the visible tab away under your feet.
	$effect(() => {
		if (!tabs.some((item) => item.id === tab)) tab = 'grid';
	});

	let current = $derived(TABS.find((t) => t.id === tab)!);
	/** The fields of the visible tab, for the sketch beside it. */
	let currentValues = $derived(
		(
			{
				grid, radial, polygon, box, qrcode: qr, barcode: bar, arctext: arc, hinge, focus
			} as Record<string, Record<string, unknown>>
		)[tab] ?? {}
	);
	let blocked = $derived(current.needsSelection && !hasSelection);

	let notice = $state<string | null>(null);
	/** The arc text's typeface drawer; closed until you open it. */
	let fontOpen = $state(false);

	async function run(body: Record<string, unknown>) {
		notice = null;
		const outcome = await onGenerate(tab, body);
		error = outcome.error ?? null;
		notice = outcome.notice ?? null;
		// Stays open when there was something to report — a sheet that appears
		// silently is exactly the kind of surprise you do not want.
		if (!error && !notice) open = false;
	}

	const n = (value: string) => Number(value);

	/**
	 * What goes to the server — one place, so that the button and the preview are
	 * guaranteed to ask the same thing. Kept apart, the preview could show something
	 * other than what the button makes, and that is exactly the kind of difference
	 * nobody notices until there is wood in the machine.
	 */
	function opdracht(): Record<string, unknown> {
		if (tab === 'grid')
			return {
				columns: n(grid.columns), rows: n(grid.rows),
				gap_x_mm: n(grid.gap_x_mm), gap_y_mm: n(grid.gap_y_mm),
				// `listAttached` as well as the box: the list can be taken away in the
				// Series window while this dialog stands open, and a tick left over from
				// then would send a request that can only be refused.
				follow_list: listAttached && grid.follow_list
			};
		if (tab === 'radial')
			return {
				repeats: n(radial.repeats), radius_mm: n(radial.radius_mm), rotate: radial.rotate
			};
		if (tab === 'polygon')
			return {
				corners: n(polygon.corners), radius_mm: n(polygon.radius_mm),
				cx_mm: n(polygon.cx_mm), cy_mm: n(polygon.cy_mm),
				inner_radius_mm: polygon.inner.trim() === '' ? null : n(polygon.inner)
			};
		if (tab === 'box')
			return {
				width_mm: n(box.width_mm), depth_mm: n(box.depth_mm), height_mm: n(box.height_mm),
				thickness_mm: n(box.thickness_mm), finger_mm: n(box.finger_mm),
				kerf_mm: n(box.kerf_mm), lid: box.lid, spread: box.spread
			};
		if (tab === 'qrcode') return { text: qr.text.trim(), size_mm: n(qr.size_mm) };
		if (tab === 'barcode')
			return {
				text: bar.text.trim(), kind: bar.kind,
				width_mm: n(bar.width_mm), height_mm: n(bar.height_mm)
			};
		if (tab === 'arctext')
			return {
				text: arc.text.trim(), cx_mm: n(arc.cx_mm), cy_mm: n(arc.cy_mm),
				radius_mm: n(arc.radius_mm), font_size_mm: n(arc.font_size_mm),
				inside: arc.inside, font: arc.font || null
			};
		if (tab === 'focus')
			return {
				z_from_mm: n(focus.z_from_mm), z_to_mm: n(focus.z_to_mm),
				marks: n(focus.marks), mark_mm: n(focus.mark_mm), gap_mm: n(focus.gap_mm),
				x_mm: n(focus.x_mm), y_mm: n(focus.y_mm), text: focus.text
			};
		return {
			pattern: hinge.pattern,
			slit_mm: n(hinge.slit_mm), gap_mm: n(hinge.gap_mm), row_mm: n(hinge.row_mm),
			x_mm: n(hinge.x_mm), y_mm: n(hinge.y_mm),
			width_mm: n(hinge.width_mm), height_mm: n(hinge.height_mm),
			from_selection: hinge.from_selection
		};
	}

	/**
	 * What the two numbers beside each other mean in wood.
	 *
	 * The gap between two slits in a row *is* the bridge that carries the whole twist, and
	 * it is the piece that snaps. Nothing is invented on top of that — no threshold, no
	 * advice. The one thing that is beyond argument, a bridge thinner than the cut itself,
	 * the API says, and that lands under the preview with the other warnings.
	 */
	let bridges = $derived.by(() => {
		const gap = Number(hinge.gap_mm);
		const row = Number(hinge.row_mm);
		if (!Number.isFinite(gap) || !Number.isFinite(row) || gap <= 0 || row <= 0) return '';
		return t('gen.hinge.material', { gap: i18n.mm(gap), row: i18n.mm(row) });
	});

	/**
	 * What the sweep comes down to per mark.
	 *
	 * The step is the thing you are really setting and it is nowhere in the form: you
	 * type two ends and a count. A tenth of a millimetre apart is a board you cannot
	 * read, and finding that out after burning it is the whole problem.
	 */
	let sweep = $derived.by(() => {
		const low = Number(focus.z_from_mm);
		const high = Number(focus.z_to_mm);
		const count = Number(focus.marks);
		if (![low, high, count].every(Number.isFinite) || count < 2 || low === high) return '';
		return t('gen.focus.step', {
			step: i18n.mm(Math.abs(high - low) / (count - 1)),
			span: i18n.mm(Math.abs(high - low))
		});
	});

	// ----------------------------------------------------------- the preview

	let preview = $state<Voorbeeld | null>(null);
	let previewError = $state<string | null>(null);
	/**
	 * Is there anything to show?
	 *
	 * Two reasons not to. Repeat and circle need the chosen elements; without them
	 * they fall back on the sketch rather than on something invented. And a QR code
	 * without content does not exist — there we wait for your first character
	 * instead of fetching a refusal on every opening of the dialog that you could
	 * see coming yourself.
	 */
	let voorbeeldbaar = $derived(
		(!current.needsSelection || selectedIds.length > 0) &&
			(tab !== 'qrcode' || qr.text.trim() !== '') &&
			(tab !== 'barcode' || bar.text.trim() !== '') &&
			(tab !== 'arctext' || arc.text.trim() !== '') &&
			(tab !== 'hinge' || !hinge.from_selection || selectedIds.length > 0)
	);

	/**
	 * Which fields have to hold a number before there is anything to draw.
	 *
	 * A field you have just cleared the number out of is not wrong but unfinished.
	 * Sending it anyway, `Number('')` reads as zero and back comes "finger_mm must be
	 * greater than zero" — the name of a variable, not of a field that says "Finger
	 * (mm)" on screen. Seeing it coming ourselves is shorter than translating the
	 * answer.
	 *
	 * The polygon's inner radius is not among them: empty means "no star" there, and
	 * that is a valid choice.
	 */
	const NUMBER_FIELDS: Record<Tab, string[]> = {
		grid: ['columns', 'rows', 'gap_x_mm', 'gap_y_mm'],
		radial: ['repeats', 'radius_mm'],
		polygon: ['corners', 'radius_mm', 'cx_mm', 'cy_mm'],
		box: ['width_mm', 'depth_mm', 'height_mm', 'thickness_mm', 'finger_mm', 'kerf_mm'],
		qrcode: ['size_mm'],
		barcode: ['width_mm', 'height_mm'],
		arctext: ['cx_mm', 'cy_mm', 'radius_mm', 'font_size_mm'],
		hinge: ['slit_mm', 'gap_mm', 'row_mm', 'x_mm', 'y_mm', 'width_mm', 'height_mm'],
		focus: ['z_from_mm', 'z_to_mm', 'marks', 'mark_mm', 'gap_mm', 'x_mm', 'y_mm']
	};
	/**
	 * The area fields are not on screen when the selection supplies the area, so they must
	 * not be able to hold the preview back either: "fill in the empty fields" pointing at a
	 * field you cannot see is worse than the refusal it was meant to prevent.
	 */
	let required = $derived(
		tab === 'hinge' && hinge.from_selection
			? ['slit_mm', 'gap_mm', 'row_mm']
			: NUMBER_FIELDS[tab]
	);
	let unfinished = $derived(
		required.some((field) => {
			const value = currentValues[field];
			return (
				typeof value !== 'string' ||
				value.trim() === '' ||
				!Number.isFinite(Number(value))
			);
		})
	);

	// Answers can overtake each other: you keep typing while the previous round is
	// still in flight. Only the last request may still set the image.
	let round = 0;

	async function haalVoorbeeld(mijn: number, what: string, body: Record<string, unknown>) {
		try {
			const token =
				typeof localStorage === 'undefined' ? '' : (localStorage.getItem('openkerf.token') ?? '');
			const response = await fetch('/api/design/generate/preview', {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					...(token ? { Authorization: `Bearer ${token}` } : {})
				},
				body: JSON.stringify({ ...body, what, ids: selectedIds })
			});
			const data = await response.json().catch(() => null);
			if (mijn !== round) return;
			if (!response.ok) {
				previewError =
					typeof data?.detail === 'string' ? data.detail : t('gen.cannotDraw');
				return;
			}
			previewError = null;
			// Only replace it when something valid came out; leaving the last valid
			// image is calmer than dropping a hole, and also more honest: that is still
			// what you would get if you stopped typing now.
			preview = data;
		} catch (e) {
			if (mijn === round)
				previewError = t('error.network', { message: e instanceof Error ? e.message : e });
		}
	}

	let timer: ReturnType<typeof setTimeout> | null = null;
	// Only to see *whether* the tab changed. With `untrack` because this must not
	// become a subscription: it sits outside the effect.
	let vorigTabblad: Tab = untrack(() => tab);
	/**
	 * Watching along while you type.
	 *
	 * A preview behind a button is not a preview: you only see what you are setting
	 * after you have decided you want to see it. So on every change, with 200 ms of
	 * rest in between so it is not calculated per keystroke. This does not touch
	 * `error`: that block at the bottom of the form belongs to a failed operation,
	 * not to a half-typed number.
	 */
	$effect(() => {
		const what = tab;
		const body = opdracht();
		// Whatever is still in flight no longer counts: it belongs to a question this
		// round has overtaken. Without this an answer to the previous, still valid
		// input can wipe the message below away again.
		if (timer) clearTimeout(timer);
		const mijn = ++round;

		// Switching tabs leaves no shape from the previous tab behind: that would be a
		// preview of something other than the form beside it.
		if (what !== vorigTabblad) {
			vorigTabblad = what;
			preview = null;
			previewError = null;
		}
		if (!open || !voorbeeldbaar) {
			preview = null;
			previewError = null;
			return;
		}
		if (unfinished) {
			previewError = t('gen.incomplete');
			return;
		}
		timer = setTimeout(() => haalVoorbeeld(mijn, what, body), 200);
		return () => {
			if (timer) clearTimeout(timer);
		};
	});

	/**
	 * "Make panels — 6 pieces, fits on this sheet": the button says what is coming.
	 *
	 * The dash is punctuation and lives here; both halves are whole messages, so a
	 * translation can put the words in its own order within each of them.
	 */
	let buttonTail = $derived.by(() => {
		if (!preview || previewError) return '';
		if (preview.what === 'box')
			return ` — ${
				preview.sheets > 1
					? t('gen.tail.sheets', { parts: preview.parts.length, sheets: preview.sheets })
					: t('gen.tail.fits', { parts: preview.parts.length })
			}`;
		const b = preview.bounds;
		const size = (v: number) => (v >= 100 ? v.toFixed(0) : v.toFixed(1));
		return ` — ${t('gen.tail.size', { width: size(b[2] - b[0]), height: size(b[3] - b[1]) })}`;
	});
</script>

<Dialog title={t('gen.title')} bind:open width="800px">
	<div class="tabs">
		{#each tabs as item (item.id)}
			<button class="tab" aria-pressed={tab === item.id} onclick={() => { tab = item.id; error = null; }}>
				<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
					<path d={item.icon} />
				</svg>
				{item.label}
			</button>
		{/each}
	</div>

	{#if blocked}
		<p class="hint">{t('gen.needsSelection')}</p>
	{/if}
	{#if error}
		<p class="error" role="alert">{error}</p>
	{/if}
	{#if notice}
		<p class="notice">{notice}</p>
	{/if}

	<div class="werkbank">
	<div class="formulier">
	{#if tab === 'grid'}
		<p class="lead">{t('gen.grid.lead')}</p>
		<div class="fields">
			<div class="pair">
				<NumberField label={t('gen.columns')} step={1} min={1} bind:value={grid.columns} />
				<NumberField label={t('gen.rows')} step={1} min={1} bind:value={grid.rows} />
			</div>
			<div class="pair">
				<NumberField label={t('gen.gapX')} unit="mm" step={0.5} bind:value={grid.gap_x_mm} />
				<NumberField label={t('gen.gapY')} unit="mm" step={0.5} bind:value={grid.gap_y_mm} />
			</div>
			<!-- The one thing in this dialog that reads from outside the drawing. It goes
			     through `opdracht()` with everything else, so the preview and the button
			     cannot ask different things. -->
			<label class="check listfollow" title={listAttached ? undefined : t('api.gen.noList')}>
				<input type="checkbox" bind:checked={grid.follow_list} disabled={!listAttached} />
				<span>{t('gen.followList')}</span>
			</label>
			{#if !listAttached}
				<!-- The same sentence the server answers with, so the reason before the
				     press and the answer after it are one wording. -->
				<p class="hint">{t('api.gen.noList')}</p>
			{/if}
		</div>
		<button class="go" disabled={blocked || busy} onclick={() => run(opdracht())}>
			{t('gen.grid.go', { n: n(grid.columns) * n(grid.rows), tail: buttonTail })}
		</button>
	{:else if tab === 'radial'}
		<p class="lead">{t('gen.radial.lead')}</p>
		<div class="fields">
			<div class="pair">
				<NumberField label={t('gen.count')} step={1} min={2} bind:value={radial.repeats} />
				<NumberField label={t('gen.radius')} unit="mm" step={1} bind:value={radial.radius_mm} />
			</div>
			<label class="check"
				><input type="checkbox" bind:checked={radial.rotate} /><span>{t('gen.rotateAlong')}</span
				></label
			>
		</div>
		<button class="go" disabled={blocked || busy} onclick={() => run(opdracht())}
			>{t('gen.radial.go', { tail: buttonTail })}</button
		>
	{:else if tab === 'polygon'}
		<p class="lead">{t('gen.polygon.lead')}</p>
		<div class="fields">
			<div class="pair">
				<NumberField label={t('gen.corners')} step={1} min={3} bind:value={polygon.corners} />
				<NumberField label={t('gen.radius')} unit="mm" step={1} bind:value={polygon.radius_mm} />
			</div>
			<div class="pair">
				<NumberField label={t('gen.innerRadius')} unit="mm" step={1} bind:value={polygon.inner} />
			</div>
			<div class="pair">
				<NumberField label={t('gen.centreX')} unit="mm" step={1} bind:value={polygon.cx_mm} />
				<NumberField label={t('gen.centreY')} unit="mm" step={1} bind:value={polygon.cy_mm} />
			</div>
		</div>
		<button class="go" disabled={busy} onclick={() => run(opdracht())}
			>{t('gen.draw', { tail: buttonTail })}</button
		>
	{:else if tab === 'box'}
		<p class="lead">{t('gen.box.lead')}</p>
		<div class="fields">
			<!-- Width, depth and height are one measurement in three and so sit on one
			     line; the thickness of the material is something else and sits below. -->
			<div class="three">
				<NumberField label={t('gen.width')} unit="mm" step={1} bind:value={box.width_mm} />
				<NumberField label={t('gen.depth')} unit="mm" step={1} bind:value={box.depth_mm} />
				<NumberField label={t('gen.height')} unit="mm" step={1} bind:value={box.height_mm} />
			</div>
			<div class="pair">
				<NumberField
					label={t('gen.materialThickness')}
					unit="mm"
					step={0.1}
					bind:value={box.thickness_mm}
				/>
			</div>
			<div class="pair">
				<NumberField label={t('gen.finger')} unit="mm" step={1} bind:value={box.finger_mm} />
				<NumberField label={t('gen.kerf')} unit="mm" step={0.05} bind:value={box.kerf_mm} />
			</div>
			<label class="check"
				><input type="checkbox" bind:checked={box.lid} /><span>{t('gen.withLid')}</span></label
			>
			<label class="check">
				<input type="checkbox" bind:checked={box.spread} />
				<span>{t('gen.spreadSheets')}</span>
			</label>
		</div>
		<button class="go" disabled={busy} onclick={() => run(opdracht())}
			>{t('gen.makePanels', { tail: buttonTail })}</button
		>
	{:else if tab === 'qrcode'}
		<p class="lead">{t('gen.qr.lead')}</p>
		<div class="fields">
			<label
				><span>{t('gen.content')}</span><input
					type="text"
					placeholder="https://…"
					bind:value={qr.text}
				/></label
			>
			<div class="pair">
				<NumberField label={t('gen.size')} unit="mm" step={1} bind:value={qr.size_mm} />
			</div>
		</div>
		<button class="go" disabled={busy || !qr.text.trim()} onclick={() => run(opdracht())}
			>{t('gen.place', { tail: buttonTail })}</button
		>
	{:else if tab === 'barcode'}
		<p class="lead">{t('gen.barcode.lead')}</p>
		<div class="fields">
			<label
				><span>{t('gen.content')}</span><input
					type="text"
					placeholder="OPENKERF-1"
					bind:value={bar.text}
				/></label
			>
			<label>
				<span>{t('gen.barcode.type')}</span>
				<select bind:value={bar.kind}>
					{#each BARCODES as item (item)}
						<option value={item}>{item}</option>
					{/each}
				</select>
			</label>
			<div class="pair">
				<NumberField label={t('gen.width')} unit="mm" step={1} bind:value={bar.width_mm} />
				<NumberField label={t('gen.height')} unit="mm" step={1} bind:value={bar.height_mm} />
			</div>
		</div>
		<button class="go" disabled={busy || !bar.text.trim()} onclick={() => run(opdracht())}
			>{t('gen.place', { tail: buttonTail })}</button
		>
	{:else if tab === 'arctext'}
		<p class="lead">{t('gen.arc.lead')}</p>
		<div class="fields">
			<label
				><span>{t('gen.text')}</span><input
					type="text"
					placeholder="OPENKERF"
					bind:value={arc.text}
				/></label
			>
			<div class="pair">
				<NumberField label={t('gen.centreX')} unit="mm" step={1} bind:value={arc.cx_mm} />
				<NumberField label={t('gen.centreY')} unit="mm" step={1} bind:value={arc.cy_mm} />
			</div>
			<div class="pair">
				<NumberField label={t('gen.radius')} unit="mm" step={1} bind:value={arc.radius_mm} />
				<NumberField
					label={t('gen.letterHeight')}
					unit="mm"
					step={0.5}
					bind:value={arc.font_size_mm}
				/>
			</div>
			<label class="check"
				><input type="checkbox" bind:checked={arc.inside} /><span>{t('gen.underneath')}</span></label
			>
		</div>
		<!-- Collapsed until you open it: the list is 200 typefaces long and pushed the
		     "Place" button off screen (measured: from 725 to 865 px). The line does say
		     which typeface is chosen now, because otherwise a closed drawer is the same
		     as no choice. -->
		<div class="fontchoice">
			<button class="letterregel" aria-expanded={fontOpen} onclick={() => (fontOpen = !fontOpen)}>
				<span>{t('gen.font')}</span>
				<strong>{arc.font ? arc.fontName || arc.font : t('gen.font.default')}</strong>
				<span class="pijl" aria-hidden="true">{fontOpen ? '▴' : '▾'}</span>
			</button>
			{#if fontOpen}
				<FontPicker bind:font={arc.font} bind:fontName={arc.fontName} sample={arc.text} />
			{/if}
		</div>
		<button class="go" disabled={busy || !arc.text.trim()} onclick={() => run(opdracht())}
			>{t('gen.place', { tail: buttonTail })}</button
		>
	{:else if tab === 'focus'}
		<p class="lead">{t('gen.focus.lead')}</p>
		<div class="fields">
			<div class="three">
				<NumberField
					label={t('gen.focus.from')}
					unit="mm"
					step={0.5}
					bind:value={focus.z_from_mm}
				/>
				<NumberField label={t('gen.focus.to')} unit="mm" step={0.5} bind:value={focus.z_to_mm} />
				<NumberField label={t('gen.focus.marks')} step={1} min={2} bind:value={focus.marks} />
			</div>
			<!-- Which way is which. "+2" on the board says nothing by itself, and the sign
			     convention is the same one the drop per pass uses — one rule, not two. -->
			<p class="bridgeline">{t('gen.focus.direction')}</p>
			{#if sweep}
				<p class="bridgeline">{sweep}</p>
			{/if}
			<div class="pair">
				<NumberField label={t('gen.focus.mark')} unit="mm" step={1} bind:value={focus.mark_mm} />
				<NumberField label={t('gen.focus.gap')} unit="mm" step={1} bind:value={focus.gap_mm} />
			</div>
			<div class="pair">
				<NumberField label={t('gen.hinge.left')} unit="mm" step={1} bind:value={focus.x_mm} />
				<NumberField label={t('gen.hinge.top')} unit="mm" step={1} bind:value={focus.y_mm} />
			</div>
			<label class="check"
				><input type="checkbox" bind:checked={focus.text} /><span>{t('gen.focus.text')}</span></label
			>
		</div>
		<button class="go" disabled={busy} onclick={() => run(opdracht())}
			>{t('gen.focus.go', { tail: buttonTail })}</button
		>
	{:else}
		<p class="lead">{t('gen.hinge.lead')}</p>
		<div class="fields">
			<div class="wide">
				<span class="grouplabel">{t('gen.hinge.pattern')}</span>
				<Segmented
					label={t('gen.hinge.pattern')}
					bind:value={hinge.pattern}
					options={[
						{ value: 'straight', label: t('gen.hinge.straight') },
						{ value: 'staggered', label: t('gen.hinge.staggered') },
						{ value: 'wavy', label: t('gen.hinge.wavy') }
					]}
				/>
			</div>
			<div class="three">
				<NumberField label={t('gen.hinge.slit')} unit="mm" step={0.5} bind:value={hinge.slit_mm} />
				<NumberField label={t('gen.hinge.gap')} unit="mm" step={0.1} bind:value={hinge.gap_mm} />
				<NumberField label={t('gen.hinge.rows')} unit="mm" step={0.1} bind:value={hinge.row_mm} />
			</div>
			<!-- Beside the fields, not under the preview: this is what the two numbers you
			     just typed mean in wood, and it is the mistake that snaps the piece. It says
			     nothing about a limit — how thin a bridge may be depends on the material —
			     only what the bridge is and what it does. -->
			{#if bridges}
				<p class="bridgeline">{bridges}</p>
			{/if}
			<label class="check areatoggle">
				<input type="checkbox" bind:checked={hinge.from_selection} disabled={!hasSelection} />
				<span>{hasSelection ? t('gen.hinge.fromSelection') : t('gen.hinge.noSelection')}</span>
			</label>
			{#if !hinge.from_selection}
				<div class="pair">
					<NumberField label={t('gen.hinge.left')} unit="mm" step={1} bind:value={hinge.x_mm} />
					<NumberField label={t('gen.hinge.top')} unit="mm" step={1} bind:value={hinge.y_mm} />
				</div>
				<div class="pair">
					<NumberField label={t('gen.width')} unit="mm" step={1} bind:value={hinge.width_mm} />
					<NumberField label={t('gen.height')} unit="mm" step={1} bind:value={hinge.height_mm} />
				</div>
			{/if}
		</div>
		<button class="go" disabled={busy} onclick={() => run(opdracht())}
			>{t('gen.hinge.go', { tail: buttonTail })}</button
		>
	{/if}
	</div>

	<!-- The shape beside the form that makes it. -->
	<GeneratorPreview kind={tab} values={currentValues} {preview} failure={previewError}>
		{#if current.needsSelection}
			{t('gen.preview.sketch')}
		{:else if !voorbeeldbaar}
			{t('gen.preview.typeSomething')}
		{:else}
			{t('gen.preview.calculating')}
		{/if}
	</GeneratorPreview>
	</div>
</Dialog>

<style>
	/* Setting on the left, seeing what you set on the right. Below 720px it stacks. */
	.werkbank { display: grid; grid-template-columns: 1fr 210px; gap: var(--space-4); align-items: start; }
	/* A column, so the primary button can put itself at the bottom right. */
	.formulier {
		min-width: 0;
		display: flex;
		flex-direction: column;
	}
	@media (max-width: 720px) { .werkbank { grid-template-columns: 1fr; } }

	.tabs {
		display: flex;
		gap: 2px;
		margin-bottom: var(--space-3);
		flex-wrap: wrap;
		border-bottom: 1px solid var(--line);
	}
	/* Tabs, not pills: this is navigation between forms. With an icon above it you
	   recognise the box without reading. */
	.tab {
		display: grid;
		justify-items: center;
		gap: 2px;
		font-size: var(--text-xs);
		padding: var(--space-2) var(--space-3) var(--space-2);
		border: 0;
		border-bottom: 2px solid transparent;
		border-radius: 0;
		color: var(--text-2);
		background: none;
	}
	.tab:hover { color: var(--text-1); }
	.tab[aria-pressed='true'] {
		border-bottom-color: var(--accent);
		color: var(--accent);
		font-weight: 500;
	}
	.lead { margin: 0 0 var(--space-3); font-size: var(--text-xs); color: var(--text-2); line-height: 1.5; }
	.hint { margin: 0 0 var(--space-2); font-size: var(--text-xs); color: var(--warn); }
	.error { margin: 0 0 var(--space-2); font-size: var(--text-xs); color: var(--danger); }
	.notice { margin: 0 0 var(--space-2); font-size: var(--text-xs); color: var(--accent); }
	/* Form rule v4, the same model as in the test grid: a stack of rows, and what
	   belongs together sits in a `.pair` or a `.three`. In the continuous two-column
	   grid that used to be here, "Centre X" fell on one row and "Centre Y" on the
	   next, and the box's width-depth-height triad was broken up by the material
	   thickness. */
	.fields {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		margin-bottom: var(--space-4);
	}
	.fields label { display: grid; gap: 2px; font-size: var(--text-xs); color: var(--text-2); }
	.pair,
	.three {
		display: grid;
		gap: var(--space-3);
		align-items: end;
	}
	.pair { grid-template-columns: 1fr 1fr; }
	.three { grid-template-columns: 1fr 1fr 1fr; }
	.fields .check { display: flex; align-items: center; gap: 6px; align-self: end; }
	/* A row that is not an <input> and therefore cannot be a <label>: the Segmented has
	   its own aria-label, this is the one you read. */
	.fields .wide { display: grid; gap: 2px; }
	.grouplabel { font-size: var(--text-xs); color: var(--text-2); }
	/* This one governs the four fields below it, so it lines up with them on the left. The
	   `align-self: end` of `.check` is for a checkbox beside a field on the same row (the
	   box tab); here there is no row to line up with, and to the right it stood alone in the
	   middle of the form. */
	.fields .check.areatoggle { align-self: start; }
	/* The same reason as `.areatoggle` above: this one governs the whole repeat and
	   lines up with the fields on the left. Measured with the default `align-self: end`
	   it stood alone against the right edge of the form, a metre from the numbers it
	   is about. */
	.fields .check.listfollow { align-self: start; }
	.bridgeline { margin: 0; font-size: var(--text-xs); color: var(--text-2); line-height: 1.5; }
	.fontchoice { margin-bottom: var(--space-4); }
	.letterregel {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		width: 100%;
		min-height: 40px;
		padding: 8px var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-2);
		font-size: var(--text-xs);
		text-align: left;
	}
	.letterregel strong { flex: 1; color: var(--text-1); font-weight: 500; }
	.letterregel .pijl { color: var(--text-2); }
	.letterregel:hover { border-color: var(--accent); }
	input,
	select {
		font: inherit;
		width: 100%;
		padding: 8px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.check input { width: auto; }
	/* Form rule v4: the primary button sits bottom right, not across the full width.
	   A 500px button for one action reads as a banner, and it lined up with no other
	   form in the app. */
	.go {
		align-self: flex-end;
		padding: 8px 20px;
		border-radius: var(--radius-field);
		border: 1px solid var(--accent);
		background: var(--accent);
		color: var(--accent-ink);
		font-weight: 500;
	}
	.go:disabled { opacity: 0.45; cursor: not-allowed; }
</style>
