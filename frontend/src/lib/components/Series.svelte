<script lang="ts">
	/**
	 * The Series window: the list, the burns it makes, and what each one engraves.
	 *
	 * One design burned once per row of a list. That is a thing you *search and
	 * compare in* — is row twelve right, did the header land where I meant it to,
	 * which of these has already been burned — so by the placement rule it gets a
	 * window of its own rather than a corner of the right-hand panel.
	 *
	 * ## Two panes, and which fact lives in which
	 *
	 * The library treatment (DESIGN-SYSTEM, "a library is a diptych"): on the left
	 * what you have, on the right what belongs with it. Here the left is the
	 * *identity* column — the numbered burn list, what each burn puts on the
	 * material, which one is on the bed and which are done — and the right is the
	 * *detail*: where the rows come from, what this app decided about the file, and
	 * the button that takes them.
	 *
	 * The reason that split is not arbitrary: the left is the only place in the app
	 * where a reader can check the list against the design before there is material
	 * in the machine, and it must therefore be readable while the right-hand form is
	 * still being fiddled with. Putting the burn list under the form would mean
	 * scrolling away from the thing you are checking in order to change it.
	 *
	 * ## The rules copied from surfaces that paid for them
	 *
	 * **One function builds both requests.** `request()` is handed to `preview()`
	 * and to `attach()` unchanged — `Generators.svelte`'s `opdracht()`. Without that
	 * the screen can show a list read with a header row while the button attaches
	 * the same file read as data, and nobody notices until fifty plates carry the
	 * word "name".
	 *
	 * **A preview refusal is not a failure.** `series.previewError` and
	 * `series.error` are strictly apart (`TestGrid.svelte:82-93`): a half-typed
	 * range is refused all the time and that is an intermediate state, so the last
	 * good reading stays on screen with a notice above it instead of the block
	 * falling away and the form jumping three hundred pixels wide.
	 *
	 * **A column name and a cell are the reader's data.** They go bare into the
	 * markup with a `title`, never through `t()`. A spreadsheet header of forty
	 * characters is theirs to have; our job is to make it hoverable rather than to
	 * translate it.
	 *
	 * ## What this window deliberately does not do
	 *
	 * It never burns. `SeriesStore.burn()` belongs to the button in the Job panel
	 * that somebody standing at the machine presses; the only verbs here are
	 * reading the list, pointing the bed at a row, and marking one burn to be done
	 * again. That is why "Burn this one again" is `redo()` — which points and marks
	 * and sends nothing to the laser.
	 */
	import { i18n, t } from '$lib/i18n/index.svelte';
	import Dialog from './Dialog.svelte';
	import Menu from './Menu.svelte';
	import NumberField from './NumberField.svelte';
	import Segmented from './Segmented.svelte';
	import type { Menu as MenuList } from '$lib/actions';
	import { findColumn, columnsUsed, reservedColumn } from '$lib/series';
	import type { SeriesRequest, SeriesStore } from '$lib/series.svelte';
	import type { SheetStore } from '$lib/sheets.svelte';
	import type { LibraryStore } from '$lib/library.svelte';

	let {
		open = $bindable(),
		series,
		sheets,
		library,
		canEdit = false,
		onChanged,
		onDeleteShape,
		onEditMaterial
	}: {
		open: boolean;
		series: SeriesStore;
		/**
		 * The sheets, because the plate this window lays out *is* the active sheet: how
		 * many pieces fit is measured against its size, so its size has to be readable
		 * and changeable from here. The sheet stays the one source — this is a second
		 * door to it, exactly as the sheet editor's material button is a second door to
		 * the top bar's dialog.
		 */
		sheets: SheetStore;
		/** Only to put a name to the material the plate is made of. */
		library: LibraryStore;
		canEdit?: boolean;
		/** After anything that moves the pointer or changes the list: the bed shows
		 *  another name, so the canvas has to read the design again. */
		onChanged?: () => void;
		/**
		 * Throw a ghost away. There is deliberately no counterpart that *shows* one:
		 * measured, a text that is nothing but a placeholder for a missing column
		 * renders as the empty string, its bounds come back `(nan, nan, nan, nan)` and
		 * it is not in the snapshot at all — so selecting it selected nothing and the
		 * action bar still said "Pick a shape on the bed". A button that does nothing
		 * half the time is worse than the sentence above the list, which says why.
		 */
		onDeleteShape?: (id: string) => Promise<void> | void;
		/**
		 * Open the top bar's material dialog. The same door the sheet editor uses, and
		 * for the same reason (decision B1): the material of a sheet is chosen in one
		 * place, whatever surface sends you there.
		 */
		onEditMaterial?: () => void;
	} = $props();

	/** Which of the two doors the rows come through. */
	let source = $state<'file' | 'numbers'>('file');
	/**
	 * The name the file has *on the server*, from the upload's answer.
	 *
	 * Not the name on the reader's disk: the upload directory is where every later
	 * request finds the bytes again, and two people uploading `list.csv` are two
	 * different files there.
	 */
	let fileName = $state<string | null>(null);
	/** The name the reader knows it by, which is the one worth showing. */
	let onDisk = $state<string | null>(null);
	/** Whether the first row holds the column names. Pre-filled with the server's guess. */
	let header = $state(true);
	let skipBlank = $state(true);
	/** Counted from one, because that is how the burn list is numbered on screen. */
	let startAt = $state('1');
	let range = $state({ first: '1', last: '50', step: '1', padding: '3', column: 'number' });
	let query = $state('');
	let rowMenu = $state<{ list: MenuList; x: number; y: number } | null>(null);
	/** How tall the pinned banner strip is, so the search head can pin below it. */
	let bannerHeight = $state(0);
	/**
	 * Filling the plate: how much material stays free at the edge, and how much between
	 * two pieces. Numbers and not a tick, because both are decisions about the material
	 * — the margin is where the clamps live and the gap is two kerfs plus what burns
	 * away between them.
	 */
	let plate = $state({ margin_mm: '10', gap_mm: '5' });

	/**
	 * The server's own sum about the list and the design — `Series.check()` plus the
	 * list around it.
	 *
	 * Called `sum` and not `state` on purpose: a local named `state` shadows the
	 * `$state` rune, and `$state('')` in this file would then compile as an
	 * auto-subscription to a store nobody has.
	 */
	const sum = $derived(series.state);
	const attached = $derived(series.attached);
	/** A run is going: the list may not be changed under it. */
	const running = $derived(series.running);

	/**
	 * Every burn, in order, with what it engraves.
	 *
	 * Computed once per change rather than per row of markup: `engraves()` walks the
	 * placeholders for every burn, and a thousand rows in a `{#each}` that called it
	 * twice would walk them twice.
	 *
	 * A place whose row has run out keeps its `{…}` run standing, because that is
	 * what the engine would engrave — see `fillFor` in `$lib/series`. Those are
	 * counted and left out of the engraved text instead of being shown: the server's
	 * mutator takes those shapes off the last sheet, so the honest thing to say is
	 * that the place stays empty, not that it burns nine characters of syntax.
	 */
	const burns = $derived.by(() =>
		series.burns.map((rows, index) => {
			const engraved = series.engraves(rows[0]);
			const standing = engraved.filter((text) => /\{[^}]+\}/.test(text)).length;
			const parts = engraved.filter((text) => text.trim() && !/\{[^}]+\}/.test(text));
			return {
				number: index + 1,
				rows,
				standing,
				text: parts.length ? i18n.list(parts) : '',
				done: isDone(rows),
				now: rows.includes(sum?.current_row ?? -1)
			};
		})
	);

	/**
	 * Whether anything on the bed reads from the list at all.
	 *
	 * Said once above the list and not once per row: with nothing reading, every burn
	 * engraves the same nothing, and a column of fifty identical sentences is noise
	 * where one sentence is an instruction. The same fact refuses a start on the
	 * server, so this is the warning that arrives before the refusal.
	 *
	 * `known` is part of it, and that is the difference between two things that look
	 * alike: a text asking for a column the list has not got is a ghost, listed below
	 * with the reason, and it reads nothing either. Measured with a list swapped for a
	 * counted range: without `known` the head fell silent and twenty-five rows each
	 * said "nothing to put on the material" instead.
	 */
	const reads = $derived((sum?.uses ?? []).some((use) => !use.reserved && use.known));

	/** The search is over the reader's own data, so it is a plain case-fold match. */
	const shown = $derived.by(() => {
		const needle = query.trim().toLowerCase();
		if (!needle) return burns;
		return burns.filter((burn) => burn.text.toLowerCase().includes(needle));
	});

	/**
	 * Whether every row of this burn falls inside a range the run calls done.
	 *
	 * `done` holds row ranges and not burn numbers on purpose: nudging a rectangle
	 * can change how many rows one burn eats, and with burn numbers that would void
	 * nineteen done-marks. Rows survive the re-partition.
	 */
	function isDone(rows: number[]): boolean {
		const done = sum?.run?.done ?? [];
		if (!rows.length || !done.length) return false;
		return rows.every((row) => done.some((span) => row >= span[0] && row <= span[1]));
	}

	// ----------------------------------------------------------- the two doors

	/**
	 * What goes to the server — one object, whether it is being previewed or taken.
	 *
	 * `null` means "there is not enough here to ask yet", which is a different thing
	 * from a refusal: the preview leaves the last good reading standing for it.
	 */
	function request(): SeriesRequest | null {
		if (source === 'numbers') {
			const numbers = {
				first: Number(range.first),
				last: Number(range.last),
				step: Number(range.step),
				padding: Number(range.padding)
			};
			const column = range.column.trim();
			if (!column) return null;
			if (Object.values(numbers).some((value) => !Number.isFinite(value))) return null;
			if ([range.first, range.last, range.step, range.padding].some((v) => v.trim() === ''))
				return null;
			return { kind: 'numbers', ...numbers, column, skip_blank: skipBlank };
		}
		if (!fileName) return null;
		return { kind: 'file', file: fileName, has_header: header, skip_blank: skipBlank };
	}

	/** Whether the form is unfinished rather than wrong. Only the numbers can be. */
	const unfinished = $derived(source === 'numbers' && request() === null);

	/**
	 * Watching along while the reader sets things.
	 *
	 * The store debounces 200 ms and counts rounds, so a late answer to older input
	 * cannot overwrite a newer one. Two guards here rather than in the store,
	 * because they are about this screen: a closed window shows nothing, and a
	 * half-typed range must not clear what is already up.
	 */
	$effect(() => {
		const body = request();
		if (!open) {
			series.preview(null);
			return;
		}
		// No file chosen yet is genuinely nothing to show, so the block goes away
		// rather than standing empty.
		if (source === 'file' && !fileName) {
			series.preview(null);
			return;
		}
		if (!body) return;
		series.preview(body);
	});

	/**
	 * The pending round is dropped when this component goes, and what is on screen
	 * is left alone: the last valid reading is still the honest thing to have shown.
	 */
	$effect(() => () => series.cancelPreview());

	/**
	 * What filling the plate would do, asked again whenever a number or the list moves.
	 *
	 * Every answer is a read that draws nothing (`GET /api/series/plate`), so the
	 * sentence above the button and the button itself come out of one sum — the rule the
	 * generators window pays for in the same way.
	 */
	$effect(() => {
		const margin = Number(plate.margin_mm);
		const gap = Number(plate.gap_mm);
		// `sum` is read so that filling, attaching another list or moving a shape asks
		// again, and the plate's own size because that is what the pieces are counted
		// against: how many fit depends on all four.
		void sum?.row_count;
		void sum?.step;
		void sheets.active?.width_mm;
		void sheets.active?.height_mm;
		if (!open || !Number.isFinite(margin) || !Number.isFinite(gap)) return;
		series.plan([], margin, gap);
	});

	/**
	 * Is this plate already laid out?
	 *
	 * Read off the *design* and not off the last answer: how many rows a burn eats is
	 * what a laid-out plate means, and that is the same number the burn list and the run
	 * work from. A plate laid out before the window was opened, or one that came with a
	 * project, says so here too.
	 */
	const laidOut = $derived((sum?.step ?? 1) > 1);
	/** How many places the last plate uses. The others use all of them. */
	const lastPlaces = $derived.by(() => {
		const step = sum?.step ?? 1;
		const rows = sum?.row_count ?? 0;
		if (step < 2 || !rows) return step;
		const rest = rows % step;
		return rest === 0 ? step : rest;
	});

	/** What the plate is made of, in the reader's own words. Null when nothing is set. */
	const materialName = $derived.by(() => {
		const sheet = sheets.active;
		if (!sheet || sheet.material_id === null) return null;
		const material = library.materials.find((one) => one.id === sheet.material_id);
		if (!material) return null;
		return sheet.thickness_mm === null
			? material.name
			: t('series.plate.materialThick', {
					name: material.name,
					thickness: i18n.number(sheet.thickness_mm)
				});
	});

	/** Change the plate itself. The sheet is the one source; this is a door to it. */
	async function resize(fields: Record<string, number>) {
		const sheet = sheets.active;
		if (!sheet) return;
		const value = Object.values(fields)[0];
		if (!Number.isFinite(value) || value < 5) return;
		await sheets.update(sheet.id, fields);
	}

	/** Lay the piece out over the plate, then let the canvas read the design again. */
	async function fillPlate() {
		const margin = Number(plate.margin_mm);
		const gap = Number(plate.gap_mm);
		if (!Number.isFinite(margin) || !Number.isFinite(gap)) return;
		if (!(await series.fill([], margin, gap))) return;
		onChanged?.();
	}

	/**
	 * Opening the window is what brings the rows themselves — and asks again when they
	 * turn out not to be the rows of the list that is attached.
	 *
	 * The rows deliberately never ride in the status payload: a thousand of them down
	 * every open socket a few times a minute is a lot of traffic for a number that fits
	 * in a word. The cost of that is this: a list attached by something *other* than
	 * this window — another tab, a project being opened — arrives here as a state with
	 * `row_count` and no rows, and then the burn list is empty while the head above it
	 * counts five. Measured: attaching from outside with the window open left "No burn
	 * engraves ." standing for good. One comparison, and one extra request in the only
	 * case where the two disagree.
	 */
	let asked = false;
	$effect(() => {
		if (!open) {
			asked = false;
			return;
		}
		// Both facts are read every time so the effect follows them; `asked` is a plain
		// field, because a rune that this effect both reads and writes makes it chase
		// its own tail — the same trap `SeriesStore.adopt` documents.
		const short = series.attached && series.rows.length !== (sum?.row_count ?? 0);
		if (asked && !short) return;
		asked = true;
		void series.load();
	});

	async function pick(file: File) {
		onDisk = file.name;
		const answer = await series.upload(file);
		if (!answer) {
			onDisk = null;
			return;
		}
		fileName = answer.file ?? null;
		// The server's own answer to the header question, so the control shows a
		// decision that was taken rather than an empty choice. A decision taken
		// silently is one the reader cannot overrule.
		header = answer.has_header ?? answer.header_guess ?? true;
		source = 'file';
	}

	async function attach() {
		const body = request();
		if (!body || !canEdit) return;
		if (!(await series.attach(body))) return;
		// `attach` puts the pointer on the first row; a reader who typed another one
		// meant it. Counted from one on screen, from nought in the API.
		const row = Math.round(Number(startAt));
		if (Number.isFinite(row) && row > 1) await series.setRow(row - 1);
		onChanged?.();
	}

	async function detach() {
		if (!canEdit) return;
		if (await series.detach()) onChanged?.();
	}

	/**
	 * Take a ghost off the bed, and read the sum again.
	 *
	 * The reload is not belt and braces: the ghost list comes out of `check()`, and
	 * deleting a shape is a design edit that this store hears nothing about.
	 * Measured without it — three ghosts before, three after, while the server was
	 * down to two.
	 */
	async function remove(id: string) {
		if (!canEdit || !id) return;
		await onDeleteShape?.(id);
		await series.load();
	}

	/** Point the bed at a burn. Reading, not burning — hence a plain row click. */
	async function show(rows: number[]) {
		if (!canEdit) return;
		if (await series.setRow(rows[0])) onChanged?.();
	}

	async function again(rows: number[]) {
		if (!canEdit) return;
		if (await series.redo(rows[0])) onChanged?.();
	}

	/**
	 * The menu on one burn.
	 *
	 * Deliberately not in `actions.ts`: that file covers the canvas selection, the
	 * canvas, nodes and layers — surfaces that have to stay in step with the
	 * keyboard and the action bar. A verb scoped to one row of this window's own
	 * data has no second surface to keep in step with, and `MaterialLibrary` does
	 * exactly this for the menu on a setting.
	 */
	function burnMenu(burn: { rows: number[]; number: number }): MenuList {
		return [
			{
				items: [
					{
						id: 'show',
						label: t('series.menu.show'),
						off: canEdit ? undefined : t('reason.needsToken'),
						run: () => void show(burn.rows)
					},
					{
						id: 'again',
						label: t('series.menu.again'),
						off: !canEdit
							? t('reason.needsToken')
							: running
								? undefined
								: t('series.menu.again.needsRun'),
						run: () => void again(burn.rows)
					}
				]
			}
		];
	}

	// ------------------------------------------------------- what the file said

	/**
	 * What the reader is looking at: the file just read, or the list already taken.
	 *
	 * The sample wins when there is one, because that is what the button would
	 * attach. Without it the attached list is the subject, and then this window is a
	 * report on what is going to burn rather than a form.
	 */
	const sample = $derived(series.sample);
	const columns = $derived(sample?.columns ?? sum?.columns ?? []);
	const blanks = $derived(sample?.blanks ?? sum?.blanks ?? {});
	/**
	 * Which columns the design reads, in the list's own spelling.
	 *
	 * Off `uses` rather than off `used_columns`, because a file that is only being
	 * previewed has no `used_columns` for it yet — the server spells those against
	 * the list that is attached, and here the question is about the one that is not.
	 */
	const used = $derived(columnsUsed((sum?.uses ?? []).map((use) => use.placeholder)));

	/** The four characters the reader's file can be split on, each with its name. */
	function delimiterName(delimiter: string | null | undefined): string | null {
		if (delimiter === ',') return t('series.delimiter.comma');
		if (delimiter === ';') return t('series.delimiter.semicolon');
		if (delimiter === '\t') return t('series.delimiter.tab');
		if (delimiter === '|') return t('series.delimiter.bar');
		return null;
	}

	/** The example placeholder, which is data and not a message: `{name}`. */
	function example(column: string): string {
		return `{${column}}`;
	}
</script>

<Dialog title={t('series.title')} bind:open width="960px">
	<div class="werkbank" style="--banners: {bannerHeight}px">
		{#if series.error || running}
			<!-- Pinned rather than scrolled away, and measured rather than calculated: a
			     refusal above a fifty-row burn list would otherwise sit above the fold
			     the moment somebody scrolls to the row it is about. The height goes into
			     a variable because the search head below has to pin underneath it —
			     without that the head covered the left third of this sentence and left
			     the tail of it hanging in the other column (measured). -->
			<div class="banners" bind:clientHeight={bannerHeight}>
				{#if series.error}
					<p class="error" role="alert">{series.error}</p>
				{/if}
				{#if running}
					<p class="notice">{t('series.running')}</p>
				{/if}
			</div>
		{/if}

		<div class="tweeluik">
		<!-- LEFT: the identity column. What this list makes, burn by burn. -->
		<section class="lijst" aria-label={t('series.burns.aria')}>
			{#if attached}
				<div class="kopblok">
					<input
						class="zoek"
						type="search"
						bind:value={query}
						placeholder={t('series.search')}
						aria-label={t('series.searchAria')}
					/>
					<p class="fine">
						{t('series.summary', {
							burns: t('count.burns', { n: burns.length }),
							rows: t('count.rows', { n: sum?.row_count ?? 0 })
						})}
					</p>
					{#if sum && sum.step > 1}
						<!-- A sheetful eats several rows per burn, and that is the one number
						     that explains why five rows make two burns. -->
						<p class="fine">{t('series.step', { n: i18n.number(sum.step) })}</p>
					{/if}
					{#if !reads}
						<p class="notice">{t('series.nothingReads')}</p>
					{/if}
					{#if sum?.source?.kind === 'numbers'}
						<p class="fine">
							{t('series.from.numbers', {
								first: i18n.number(sum.source.first ?? 0),
								last: i18n.number(sum.source.last ?? 0)
							})}
						</p>
					{:else if sum?.source?.name}
						<!-- The file name goes in the body and not in the window's title: a
						     title built out of somebody's file name is a window the docs
						     cannot name. -->
						<p class="fine">{t('series.from.file', { file: sum.source.name })}</p>
					{/if}
				</div>

				{#if shown.length === 0}
					<div class="leeg">
						<p>{t('series.nothingFound', { query })}</p>
						<button class="mini" onclick={() => (query = '')}>{t('series.clearSearch')}</button>
					</div>
				{:else}
					<ul>
						{#each shown as burn (burn.number)}
							<li
								class:now={burn.now}
								oncontextmenu={(e) => {
									e.preventDefault();
									rowMenu = { x: e.clientX, y: e.clientY, list: burnMenu(burn) };
								}}
							>
								<button
									class="brandrij"
									disabled={!canEdit}
									title={canEdit ? t('series.menu.show') : t('reason.needsToken')}
									onclick={() => void show(burn.rows)}
								>
									<!-- The number is the mark, not the colour: a chip you can read
									     from a metre away and still read in a screenshot. -->
									<span class="nummer" class:chip={burn.now}>{i18n.number(burn.number)}</span>
									<span class="wat">
										{#if burn.text}
											<!-- The reader's own data: bare, with the whole string in the
											     title for the ones that do not fit. -->
											<span class="cell" title={burn.text}>{burn.text}</span>
										{:else if reads}
											<span class="fine">{t('series.burn.blank')}</span>
										{/if}
										{#if burn.standing}
											<span class="fine">{t('series.burn.short', { n: burn.standing })}</span>
										{/if}
									</span>
									{#if burn.now}
										<span class="mark bed" title={t('series.onBed.title')}>{t('series.onBed')}</span>
									{/if}
									{#if burn.done}
										<span class="mark klaar" title={t('series.done.title')}>{t('series.done')}</span>
									{/if}
								</button>
								<button
									class="dots"
									aria-label={t('series.rowMenu')}
									onclick={(e) => {
										const box = (e.currentTarget as HTMLElement).getBoundingClientRect();
										rowMenu = { x: box.left, y: box.bottom + 4, list: burnMenu(burn) };
									}}>⋯</button
								>
							</li>
						{/each}
					</ul>
				{/if}
			{:else}
				<!-- No greyed second control for what is absent: prose says it instead.
				     An empty state may take the room, because here it *is* the screen. -->
				<div class="welkom">
					<h3>{t('series.empty')}</h3>
					<p>{t('series.empty.how', { example: example('name') })}</p>
				</div>
			{/if}
		</section>

		<!-- RIGHT: the detail. Where the rows come from and what was decided. -->
		<section class="detail">
			<Segmented
				label={t('series.source')}
				bind:value={source}
				options={[
					{ value: 'file' as const, label: t('series.source.file') },
					{ value: 'numbers' as const, label: t('series.source.numbers') }
				]}
			/>

			{#if source === 'file'}
				<!-- A file input and no drag-and-drop: there is none anywhere in this app,
				     and a tablet has no drag. The value is cleared so that choosing the
				     same file twice still fires. -->
				<div class="rij">
					<label class="btn file" class:off={!canEdit}>
						{fileName ? t('series.pick.again') : t('series.pick')}
						<input
							type="file"
							accept=".csv,.txt,.tsv"
							disabled={!canEdit}
							onchange={(e) => {
								const input = e.currentTarget as HTMLInputElement;
								const file = input.files?.[0];
								input.value = '';
								if (file) void pick(file);
							}}
						/>
					</label>
					{#if onDisk}
						<span class="fine">{t('series.chosen', { file: onDisk })}</span>
					{/if}
				</div>
				{#if !fileName}
					<p class="fine">{t('series.pick.hint')}</p>
				{/if}
			{:else}
				<!-- The second way in. Numbers are not a second kind of series — the rows
				     are ours either way — so this fills the same rows in and goes through
				     the same attach. -->
				<div class="velden">
					<div class="paar">
						<NumberField label={t('series.numbers.first')} step={1} bind:value={range.first} />
						<NumberField label={t('series.numbers.last')} step={1} bind:value={range.last} />
					</div>
					<div class="paar">
						<NumberField label={t('series.numbers.step')} step={1} min={1} bind:value={range.step} />
						<NumberField
							label={t('series.numbers.padding')}
							step={1}
							min={0}
							max={12}
							bind:value={range.padding}
						/>
					</div>
					<label class="veld">
						<span>{t('series.numbers.column')}</span>
						<input type="text" bind:value={range.column} />
					</label>
				</div>
				<p class="fine">
					{t('series.numbers.hint', { example: example(range.column.trim() || 'number') })}
				</p>
			{/if}

			{#if unfinished}
				<p class="notice">{t('series.unfinished')}</p>
			{/if}
			{#if series.previewError}
				<!-- Kept apart from `error` on purpose: this is an intermediate state, and
				     the last good reading below stays up. -->
				<p class="notice" role="status">{series.previewError}</p>
			{/if}

			{#if sample}
				<div class="blok">
					<h3>{t('series.firstRows')}</h3>

					{#if sample.has_header !== null}
						<div class="veld">
							<span class="grouplabel">{t('series.header')}</span>
							<Segmented
								label={t('series.header')}
								bind:value={header}
								options={[
									{ value: true, label: t('series.header.names') },
									{ value: false, label: t('series.header.data') }
								]}
							/>
						</div>
						{#if header === sample.header_guess}
							<!-- Only while the guess still stands. Once the reader has overruled
							     it, this sentence contradicts the control right above it:
							     measured, "read the first row as the column names" sat under a
							     switch set to Data. -->
							<p class="fine">
								{sample.header_guess
									? t('series.header.guess.names')
									: t('series.header.guess.data')}
							</p>
						{/if}
					{/if}

					<dl class="feiten">
						{#if delimiterName(sample.delimiter)}
							<dt>{t('series.delimiter')}</dt>
							<dd>{delimiterName(sample.delimiter)}</dd>
						{/if}
						{#if sample.encoding}
							<dt>{t('series.encoding')}</dt>
							<!-- A character set is a machine fact, so it stands as it is. -->
							<dd class="mono">{sample.encoding}</dd>
						{/if}
					</dl>

					{#each sample.warnings ?? [] as warning (warning.code)}
						<!-- The server's own sentence: it names numbers this side cannot know,
						     and it reaches curl and the logs in the same words. -->
						<p class="notice">{warning.text}</p>
					{/each}

					<div class="tabelrol">
						<table class="rijen">
							<thead>
								<tr>
									{#each sample.columns as column (column)}
										<th class="colname" title={column}>{column}</th>
									{/each}
								</tr>
							</thead>
							<tbody>
								{#each sample.rows as row, index (index)}
									<tr>
										{#each sample.columns as column (column)}
											<td class="cell" title={row[column] ?? ''}>{row[column] ?? ''}</td>
										{/each}
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
					{#if sample.row_count > sample.rows.length}
						<p class="fine">
							{t('series.moreRows', { n: sample.row_count - sample.rows.length })}
						</p>
					{/if}
				</div>
			{/if}

			{#if columns.length}
				<div class="blok">
					<h3>{t('series.columns')}</h3>
					<div class="tabelrol">
						<table class="kolommen">
							<thead>
								<tr>
									<th>{t('series.column')}</th>
									<th>{t('series.column.placeholder')}</th>
									<th class="getal">{t('series.column.blanks')}</th>
									<th></th>
								</tr>
							</thead>
							<tbody>
								{#each columns as column (column)}
									<tr>
										<td class="colname" title={column}>{column}</td>
										<!-- Readable and typable, and the reader's own word inside it: this
										     is what goes into a text on the bed. -->
										<td class="mono">{example(column)}</td>
										<td class="getal">{i18n.number(blanks[column] ?? 0)}</td>
										<td>
											{#if reservedColumn(column)}
												<span class="mark waarschuwing" title={t('series.column.reserved')}>
													{t('series.column.reserved.short')}
												</span>
											{:else if findColumn(used, column)}
												<span class="mark inuse" title={t('series.column.used.title')}>
													{t('series.column.used')}
												</span>
											{/if}
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</div>
			{/if}

			{#if sum?.ghosts?.length}
				<div class="blok">
					<h3>{t('series.ghosts')}</h3>
					<p class="fine">{t('series.ghosts.why')}</p>
					<ul class="geesten">
						{#each sum.ghosts as ghost (ghost.id ?? ghost.text)}
							<li>
								<!-- The text is the reader's own, placeholders and all. -->
								<span class="cell mono" title={ghost.text}>{ghost.text}</span>
								<span class="fine">
									{t('series.ghost.missing', {
										columns: i18n.list(ghost.missing.map((name) => example(name)))
									})}
								</span>
								{#if ghost.id}
									<button
										class="mini danger"
										disabled={!canEdit}
										title={canEdit ? undefined : t('reason.needsToken')}
										onclick={() => void remove(ghost.id ?? '')}
									>
										{t('series.ghost.delete')}
									</button>
								{/if}
							</li>
						{/each}
					</ul>
				</div>
			{/if}

			<!-- On one plate. A verb with two numbers of its own, so it is a block and not
			     a row: the margin is where the clamps live and the gap is two kerfs plus
			     what burns away between them, and both are decisions about the material
			     rather than about the list. It sits above the closing block because it
			     changes the drawing, which is the thing the rest of this window reads. -->
			{#if attached}
				<div class="blok plaat">
					<h3>{t('series.plate')}</h3>
					<!-- Which plate this is, and what it is made of. The sum below is measured
					     against these three numbers, and a number you cannot check is a number
					     you cannot trust — that is why they are here and not only under the
					     sheet tab. -->
					<p class="fine">
						{#if laidOut}
							<!-- The fields are gone once the plate is laid out, so the size comes
							     back into the sentence: this is then the only place it is said. -->
							{t('series.plate.sheet', {
								name: sheets.active?.name ?? '',
								size: t('series.plate.size', {
									w: i18n.number(sheets.active?.width_mm ?? 0),
									h: i18n.number(sheets.active?.height_mm ?? 0)
								})
							})}
						{:else}
							{sheets.active?.name ?? ''}
						{/if}
						· {materialName ?? t('sheets.materialNotFilled')}
					</p>
					{#if !laidOut}
						<div class="paar">
							<NumberField
								label={t('series.plate.width')}
								unit="mm"
								step={10}
								min={5}
								value={String(sheets.active?.width_mm ?? '')}
								onchange={(value) => void resize({ width_mm: Number(value) })}
							/>
							<NumberField
								label={t('series.plate.height')}
								unit="mm"
								step={10}
								min={5}
								value={String(sheets.active?.height_mm ?? '')}
								onchange={(value) => void resize({ height_mm: Number(value) })}
							/>
						</div>
						<button class="btn subtle" type="button" onclick={() => onEditMaterial?.()}>
							{materialName ? t('series.plate.material.change') : t('series.plate.material')}
						</button>
					{/if}
					{#if series.plateError}
						<p class="fine">{series.plateError}</p>
					{:else if laidOut}
						<!-- Already laid out. The plan beside it would measure the whole plate
						     as the piece and answer "one place, seven plates" about a plate that
						     has just been filled, so what is said here is what the plate now
						     holds — and the number of plates comes from the run's own sum. -->
						<p class="fine">
							{t('series.plate.done', { n: i18n.number(sum?.step ?? 1) })}
						</p>
						{#if (sum?.burns ?? 1) > 1}
							<p class="fine">
								{t('series.plate.more', {
									burns: i18n.number(sum?.burns ?? 1),
									last: i18n.number(lastPlaces)
								})}
							</p>
						{/if}
					{:else if series.plate}
						<p class="fine">
							{t('series.plate.fits', {
								// `number` and not `mm` for the two halves: the sentence carries
								// the unit once, and "80.0 mm × 40.0 mm mm" is what happens when
								// both do.
								piece: t('series.plate.size', {
									w: i18n.number(series.plate.piece_mm[0]),
									h: i18n.number(series.plate.piece_mm[1])
								}),
								places: i18n.number(series.plate.places),
								across: i18n.number(series.plate.columns),
								down: i18n.number(series.plate.rows)
							})}
						</p>
						{#if series.plate.burns > 1}
							<!-- The question this feature raises the moment it answers the first
							     one: and the other thirty names? They are plates of this same
							     sheet, which is what the run counts. -->
							<p class="fine">
								{t('series.plate.more', {
									burns: i18n.number(series.plate.burns),
									last: i18n.number(series.plate.last_places)
								})}
							</p>
						{/if}
					{/if}
					{#if !laidOut}
					<div class="paar">
						<NumberField
							label={t('series.plate.gap')}
							unit="mm"
							step={0.5}
							min={0}
							bind:value={plate.gap_mm}
						/>
						<NumberField
							label={t('series.plate.margin')}
							unit="mm"
							step={1}
							min={0}
							bind:value={plate.margin_mm}
						/>
					</div>
					<button
						class="btn"
						disabled={!canEdit ||
							running ||
							series.busy ||
							!series.plate ||
							series.plate.places < 2 ||
							series.plate.already > 1}
						title={running
							? t('series.running')
							: series.plate && series.plate.already > 1
								? t('series.plate.already')
								: undefined}
						onclick={() => void fillPlate()}
					>
						{series.plate && series.plate.places > 1
							? t('series.plate.fill', { n: i18n.number(series.plate.places) })
							: t('series.plate.fillPlain')}
					</button>
					{/if}
				</div>
			{/if}

			<div class="afsluiting">
				<label class="vink">
					<input
						type="checkbox"
						bind:checked={skipBlank}
						disabled={(sum?.step ?? 1) > 1}
					/>
					<span>
						{t('series.skipBlank')}
						{#if (sum?.step ?? 1) > 1}
							<span class="fine"
								>{t('series.skipBlank.cannot', { n: i18n.number(sum?.step ?? 1) })}</span
							>
						{/if}
					</span>
				</label>

				<div class="paar">
					<NumberField label={t('series.startAt')} step={1} min={1} bind:value={startAt} />
				</div>
				<p class="fine">{t('series.startAt.hint')}</p>

				<!-- Buttons at the bottom, primary on the right, helper on the same line
				     to the left of it — and never across the full width. -->
				<div class="knoppen">
					{#if attached}
						<button
							class="btn"
							disabled={!canEdit || running || series.busy}
							title={running ? t('series.running') : undefined}
							onclick={() => void detach()}>{t('series.detach')}</button
						>
					{/if}
					<button
						class="btn primary"
						disabled={!canEdit || running || series.busy || request() === null}
						title={running ? t('series.running') : undefined}
						onclick={() => void attach()}
					>
						{attached ? t('series.attach.instead') : t('series.attach')}
					</button>
				</div>
			</div>
		</section>
		</div>
	</div>
</Dialog>

{#if rowMenu}
	<Menu menu={rowMenu.list} x={rowMenu.x} y={rowMenu.y} onClose={() => (rowMenu = null)} />
{/if}

<style>
	/* ── The diptych ───────────────────────────────────────────────────────────
	   Left the burn list, right the detail. The left column is fixed: it must not
	   move as soon as somebody's name is long, because then the list slides out
	   from under the pointer. Below 720px it stacks, like the generators. */
	.tweeluik {
		display: grid;
		grid-template-columns: 300px minmax(0, 1fr);
		gap: var(--space-4);
		align-items: start;
	}
	@media (max-width: 720px) {
		.tweeluik {
			grid-template-columns: 1fr;
		}
	}

	/* A refusal, and the fact that a run is going, stay in sight while the list
	   scrolls. Full width and above the search head, or a pinned head covers the
	   left third of the sentence. */
	.banners {
		position: sticky;
		top: calc(-1 * var(--space-4));
		z-index: 3;
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		margin: calc(-1 * var(--space-4)) calc(-1 * var(--space-4)) 0;
		padding: var(--space-4) var(--space-4) var(--space-2);
		background: var(--surface-1);
	}
	/* Search has to stay reachable while scrolling a list of fifty burns; the
	   window's own body is the scroll container, so this sticks to its top — below
	   the banner strip when there is one, which is what `--banners` carries. */
	.kopblok {
		position: sticky;
		top: calc(var(--banners, 0px) - var(--space-4));
		z-index: 2;
		margin: calc(-1 * var(--space-4)) 0 0;
		padding: var(--space-4) 0 var(--space-2);
		background: var(--surface-1);
		border-bottom: 1px solid var(--line);
	}
	.zoek {
		width: 100%;
	}
	.lijst ul {
		margin: var(--space-2) 0 0;
		padding: 0;
		list-style: none;
		display: flex;
		flex-direction: column;
		gap: 1px;
	}
	.lijst li {
		display: flex;
		align-items: center;
		gap: 2px;
		border-radius: var(--radius-field);
	}
	.lijst li:hover {
		background: var(--surface-2);
	}
	/* The row the bed is showing, tinted as well as chipped: the tint finds it while
	   scrolling, the chip and the word say what it is once you are there. */
	.lijst li.now {
		background: color-mix(in srgb, var(--accent) 8%, transparent);
	}
	.brandrij {
		flex: 1;
		min-width: 0;
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: 6px var(--space-2);
		border: 0;
		border-radius: var(--radius-field);
		background: none;
		color: var(--text-1);
		font: inherit;
		font-size: var(--text-sm);
		text-align: left;
	}
	.brandrij:disabled {
		cursor: default;
	}
	/* The number of the burn, in a column of its own so the numbers line up under
	   each other while the names beside them vary in length. */
	.nummer {
		flex: none;
		min-width: 2.2em;
		font-variant-numeric: tabular-nums;
		font-size: var(--text-xs);
		color: var(--text-2);
		text-align: right;
	}
	/* The one on the bed carries a chip *with its number in it*: a colour alone is
	   read by nobody in a screenshot and by nobody who does not see the difference. */
	.nummer.chip {
		padding: 2px 7px;
		border-radius: 999px;
		background: var(--accent);
		color: var(--accent-ink);
		font-weight: 600;
		text-align: center;
	}
	.wat {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 1px;
	}
	span.cell {
		display: block;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.mark {
		flex: none;
		font-size: 10px;
		letter-spacing: 0.03em;
		padding: 1px 5px;
		border-radius: var(--radius-dot);
		white-space: nowrap;
	}
	.mark.bed {
		border: 1px solid color-mix(in srgb, var(--accent) 40%, var(--line));
		color: var(--accent);
	}
	.mark.klaar {
		border: 1px solid color-mix(in srgb, var(--ok) 45%, var(--line));
		color: var(--ok);
	}
	.mark.inuse {
		border: 1px solid color-mix(in srgb, var(--accent) 40%, var(--line));
		color: var(--accent);
	}
	.mark.waarschuwing {
		border: 1px solid color-mix(in srgb, var(--warn-solid) 45%, var(--line));
		color: var(--warn);
	}
	.dots {
		flex: none;
		width: 28px;
		height: 28px;
		border-radius: var(--radius-field);
		color: var(--text-2);
		background: none;
		border: 0;
	}
	.dots:hover {
		background: var(--surface-2);
		color: var(--text-1);
	}
	/* An empty state may take the room: with nothing attached it *is* this pane. */
	.welkom {
		padding: var(--space-6) 0;
		max-width: 40ch;
	}
	.welkom h3 {
		margin: 0 0 var(--space-2);
		font-size: var(--text-md);
		font-weight: 600;
	}
	.welkom p {
		margin: 0;
		color: var(--text-2);
		line-height: 1.5;
	}
	.leeg {
		padding: var(--space-4) 0;
	}
	.leeg p {
		margin: 0 0 var(--space-2);
		color: var(--text-2);
	}

	/* ── The detail column ──────────────────────────────────────────────────── */
	.detail {
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.blok {
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		padding: var(--space-3);
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.blok h3 {
		margin: 0;
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-2);
	}
	/* Form rule v4: a stack of rows, and what belongs together sits in a pair. */
	.velden {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.paar {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-3);
		align-items: end;
	}
	.veld {
		display: grid;
		gap: 2px;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.grouplabel {
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.feiten {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr);
		gap: 2px var(--space-3);
		margin: 0;
		font-size: var(--text-xs);
	}
	.feiten dt {
		color: var(--text-2);
	}
	.feiten dd {
		margin: 0;
		color: var(--text-1);
	}
	.rij {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		flex-wrap: wrap;
	}
	.vink {
		display: flex;
		align-items: flex-start;
		gap: var(--space-1h);
		font-size: var(--text-xs);
		color: var(--text-2);
		line-height: 1.5;
	}
	.vink input {
		width: auto;
		margin-top: 2px;
	}
	/* The reason a box cannot be ticked goes on a line of its own. Inline it butted
	   straight up against the label and the two read as one broken sentence:
	   "Skip a row with an empty cell This design takes 2 rows per burn, and…" —
	   measured, both on one line box at x=595. Each half is a whole sentence in the
	   catalogue; it is the layout that was gluing them. */
	.vink .fine {
		display: block;
	}
	.afsluiting {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	/* The buttons stay on screen while the right-hand pane scrolls.
	
	   Measured before this: the pane is 749 px of tables, ticks and fields inside a
	   body of 705, and the dialog is capped at min(80vh, 760px) — so at *every* window
	   height the primary button sat below the fold and the one thing this window is for
	   was reached by scrolling past two tables. A sticky foot costs 44 px of the pane
	   and takes the scroll away from the action. */
	.knoppen {
		position: sticky;
		bottom: calc(-1 * var(--space-4));
		z-index: 2;
		display: flex;
		justify-content: flex-end;
		gap: var(--space-2);
		margin: var(--space-2) calc(-1 * var(--space-4)) calc(-1 * var(--space-4));
		padding: var(--space-2) var(--space-4) var(--space-4);
		background: var(--surface-1);
		border-top: 1px solid var(--line);
	}

	/* A wide table scrolls inside its own box; the window itself never scrolls
	   sideways, because then the burn list beside it would leave the screen. */
	.tabelrol {
		overflow-x: auto;
	}
	table {
		border-collapse: collapse;
		font-size: var(--text-xs);
		width: 100%;
	}
	th {
		text-align: left;
		font-weight: 600;
		color: var(--text-2);
		border-bottom: 1px solid var(--line);
		padding: 4px var(--space-2) 4px 0;
	}
	td {
		padding: 3px var(--space-2) 3px 0;
		border-bottom: 1px solid var(--line);
		color: var(--text-1);
	}
	/* Four narrow columns about one column of the reader's file: they hug their
	   content instead of stretching, or "Empty" and the mark beside it end up half a
	   window apart from the name they belong to. */
	.kolommen {
		width: auto;
	}
	.getal {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	/* A spreadsheet header can be forty characters wide; the whole string is in the
	   title attribute so nothing is lost, and the column keeps its width. */
	.colname,
	td.cell {
		max-width: 18ch;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.mono {
		font-family: var(--font-mono);
	}
	.geesten {
		margin: 0;
		padding: 0;
		list-style: none;
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.geesten li {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-2);
	}
	.geesten .cell {
		max-width: 22ch;
	}

	.fine {
		margin: 0;
		font-size: var(--text-xs);
		color: var(--text-2);
		line-height: 1.5;
	}
	.error {
		margin: 0 0 var(--space-2);
		font-size: var(--text-xs);
		color: var(--danger);
	}
	.notice {
		margin: 0;
		font-size: var(--text-xs);
		color: var(--accent);
		line-height: 1.5;
	}
	.mini {
		font-size: var(--text-xs);
		color: var(--accent);
		padding: 4px var(--space-1h);
		border-radius: var(--radius-field);
	}
	.mini:hover {
		background: var(--surface-2);
	}
	.mini.danger {
		color: var(--danger);
		font-weight: 600;
	}
	input[type='text'],
	input[type='search'] {
		font: inherit;
		padding: 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.btn {
		padding: 8px 12px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		font-weight: 500;
		white-space: nowrap;
	}
	.btn:hover:not(:disabled) {
		background: var(--surface-2);
	}
	.btn:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}
	.btn.primary {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
	}
	/* A file input is invisible and its label is the button.
	   `MaterialLibrary`'s own way of hiding it, and the difference matters: with
	   `display: none` the input is out of the tab order altogether, so measured, Tab
	   went from the two source buttons straight to the checkbox and there was no
	   keyboard route to choosing a file at all — the one step of this window that
	   cannot be done any other way. Laid over the label at nought opacity it keeps its
	   place in the order, and the ring goes on the label, which is the part that can be
	   seen. */
	.btn.file {
		position: relative;
		overflow: hidden;
		display: inline-flex;
		align-items: center;
		cursor: pointer;
	}
	.btn.file input {
		position: absolute;
		inset: 0;
		opacity: 0;
		cursor: pointer;
	}
	.btn.file:has(input:focus-visible) {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
	.btn.file.off {
		opacity: 0.45;
		cursor: not-allowed;
	}
</style>
