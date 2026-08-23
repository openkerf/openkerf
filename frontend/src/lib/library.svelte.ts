/**
 * The local material library.
 *
 * Everything sits in SQLite beside the engine's own settings — no service, no
 * account. A preset knows which machine it came from and where it came from
 * (by hand, extrapolated, test grid), because that determines how far you may
 * trust it.
 */

import { apiError, t } from './i18n/core.ts';

export type Material = { id: number; name: string; synonyms: string[] };

export type Preset = {
	id: number;
	material_id: number;
	material_name: string;
	machine_name: string | null;
	thickness_mm: number | null;
	operation: string;
	speed_mm_s: number;
	power_percent: number;
	passes: number;
	/** Line spacing when rastering; empty for cutting and vector engraving (B12). */
	interval_mm?: number | null;
	air_assist: boolean;
	focus_offset_mm: number;
	source: 'handmatig' | 'geextrapoleerd' | 'testraster' | 'geimporteerd';
	note: string;
	/** The grid this preset came from, if there is a photo of it. */
	grid_id: number | null;
	grid_photo: string | null;
	/** When that grid was burned — the date of the evidence. */
	grid_date?: string | null;
	/** Which square of that grid it became; pointable on the photo. */
	grid_cell?: { row: number; column: number } | null;
	/**
	 * Whether the photo of that grid is aligned. If not, the marker falls back on
	 * four default corners and the outline is only approximate.
	 */
	grid_aligned?: boolean;
	/** The last time this setting was put on a layer. */
	last_used_at?: string | null;
	/**
	 * The import this row came in on, or `''` for everything measured or typed here.
	 *
	 * It is the handle on a whole batch: one press takes the batch back, and that is
	 * what makes a one-press fetch honest. Twenty-six of the author's thirty-five
	 * settings arrived in one such batch and until now not one of them could be
	 * removed again.
	 */
	import_batch?: string;
	/** The laser the values were *measured* on, which is not the laser they are filed under. */
	origin_laser_type?: string | null;
	origin_power_watt?: number | null;
	/**
	 * Who offered the row to the shared catalogue.
	 *
	 * The catalogue is CC BY, so the credit is a condition of the copy: a setting
	 * whose attribution was dropped cannot lawfully be passed on, and nobody can see
	 * that it was dropped. A handle is the contributor's own data and goes on screen
	 * as it stands.
	 */
	origin_by?: string | null;
};

/**
 * The four operations, named for the reader.
 *
 * A function and not a constant, for the same reason as `sourceLabel` below: an array
 * built at import time carries the language of the first import for the rest of the
 * session, and a language switch then leaves half a window behind. The values are ours
 * and stay Dutch — they are data in the database, not text for the screen.
 */
export function operations(): { value: string; label: string }[] {
	return [
		{ value: 'snijden', label: t('operation.cut') },
		{ value: 'graveren-vector', label: t('operation.engraveVector') },
		{ value: 'graveren-raster', label: t('operation.engraveRaster') },
		{ value: 'markeren', label: t('operation.mark') }
	];
}

/**
 * The same operation, without the middle dot.
 *
 * In a dropdown "Engrave · vector" reads fine, but on a card where the middle dot
 * is already the separator between thickness and operation you get
 * "3 mm · Engrave · vector" and no longer know what belongs to what.
 */
export function operationName(value: string): string {
	const label = operations().find((o) => o.value === value)?.label ?? value;
	const [main, kind] = label.split(' · ');
	return kind ? `${main} (${kind})` : main;
}

/**
 * Which layer type belongs to which operation.
 *
 * Putting a cut preset on an engrave layer is not a typo but burned material:
 * 12 mm/s at 65% does something very different from 250 mm/s at 20%. We do not
 * block it — sometimes the user knows better — but we do say it.
 */
export const OPERATION_LAYER: Record<string, string[]> = {
	snijden: ['op cut'],
	'graveren-vector': ['op engrave'],
	'graveren-raster': ['op raster', 'op image'],
	markeren: ['op engrave', 'op dots']
};

/**
 * How certain is this preset?
 *
 * A badge alone is too easy to read past: two pills of the same size that differ
 * only in colour and word read as the same thing while scrolling. So every source
 * also carries a shape (the icon), a line saying what it means, and — where it
 * involves risk — a line saying what to do about it. Colour is then the third
 * signal, not the only one.
 */
export type SourceLabel = {
	text: string;
	tone: string;
	icon: 'check' | 'alert' | 'pen' | 'down';
	means: string;
	advice: string;
};

/**
 * A function and not a table, because a table resolves its `t()` calls once.
 *
 * Measured: with the library window open, switching to Dutch turned every sentence in
 * it Dutch and left the badges reading "Manual" and "Verified" — the object was built
 * when the module was imported, in whichever language happened to be first. The same
 * trap the catalogue's own confidence table fell into. Called per render, so the
 * language it answers in is the language on screen.
 */
export function sourceLabel(source: Preset['source']): SourceLabel {
	const table: Record<Preset['source'], SourceLabel> = {
		testraster: {
			text: t('source.verified'),
			tone: 'ok',
			icon: 'check',
			means: t('source.verified.means'),
			advice: ''
		},
		handmatig: {
			text: t('source.manual'),
			tone: 'neutral',
			icon: 'pen',
			means: t('source.manual.means'),
			advice: ''
		},
		geextrapoleerd: {
			text: t('source.extrapolated'),
			tone: 'warn',
			icon: 'alert',
			means: t('source.extrapolated.means'),
			advice: t('source.extrapolated.advice')
		},
		geimporteerd: {
			text: t('source.imported'),
			tone: 'warn',
			icon: 'down',
			means: t('source.imported.means'),
			advice: t('source.imported.advice')
		}
	};
	return table[source];
}

/** Two settings about the same thing that carry different numbers. */
export type PresetConflict = {
	material: string;
	thickness_mm: number | null;
	operation: string;
	machine: string | null;
	mine: { speed_mm_s: number; power_percent: number; passes: number; source: string };
	theirs: { speed_mm_s: number; power_percent: number; passes: number; source: string };
};

export type Tally = {
	materials: number;
	presets: number;
	machines: number;
	test_grids: number;
};

/**
 * What is going to happen if you take this file in.
 *
 * Both choices are worked out in full, because the difference between merging and
 * replacing has to be on screen at the moment you choose — not afterwards.
 */
export type ImportPreview = {
	bundle: string;
	exported_at: string | null;
	contains: Tally & { photos: number };
	current: Tally;
	merge: {
		materials: {
			new: string[];
			existing: { name: string; as: string; material_id: number }[];
			/** A different name, probably the same board — the M5 pitfall. */
			similar: { name: string; match: string; material_id: number; why: string }[];
		};
		machines: { new: string[]; existing: string[] };
		presets: { new: number; identical: number; conflicts: PresetConflict[] };
		test_grids: { new: number; existing: number };
	};
	replace: { removes: Tally };
};

export type ImportResult = {
	mode: string;
	removed: Tally | null;
	materials: number;
	machines: number;
	test_grids: number;
	presets: { added: number; updated: number; skipped: number };
};

export type MachineProfile = {
	id: number;
	name: string;
	/** `co2-glass`, `diode`, … — the axis along which a setting may travel at all. */
	laser_type: string;
	power_watt: number | null;
	lens_mm: number | null;
	device_path: string | null;
	/**
	 * The device this profile belongs to no longer exists in the engine.
	 *
	 * The library sits beside the engine and does not follow along when you throw a
	 * machine away or wipe the settings. Without this distinction the list fills up
	 * with names that have nothing behind them any more — and then "for this
	 * machine" says nothing.
	 */
	orphaned: boolean;
	/**
	 * Which of the two it is: `device-gone` or `no-device`.
	 *
	 * They are told apart because the answer differs. A profile whose device is not
	 * here may get it back — plug the laser in, or the engine's settings were wiped —
	 * while one that points at no device at all is a row somebody typed or one this
	 * library let go of when its slot went to another laser, and its way out is a
	 * merge into the machine it belongs to.
	 */
	orphaned_because: string | null;
	/** How much evidence hangs off it; decides whether it may go. */
	presets: number;
	test_grids: number;
};

/**
 * What hangs off a material, counted before anybody presses Remove.
 *
 * Read before the question is asked, so the question can name the number. Removing
 * `Berkentriplex` from a copy of the author's library took six settings with it — two
 * of them measured, with photographs — orphaned two boards and answered
 * `{"removed": 6}`; a confirmation saying "remove?" and nothing else is what made
 * that possible.
 */
export type MaterialUsage = {
	material_id: number;
	name: string;
	presets: number;
	test_grids: number;
	grid_recipes: number;
	photos: number;
	/** Sheets on the table that name this material; the link is cleared, not the sheet. */
	sheets: number;
};

/** What taking one import back actually took. */
export type ImportUndone = {
	batch: string;
	presets: number;
	/** The materials the batch created that nothing else uses any more. */
	materials: number[];
	/** The ones it created that something else does use, and that therefore stay. */
	kept_materials: number[];
	sheets: number;
};

/**
 * The things that would go with this material, each one a whole message.
 *
 * Only what is really there: "0 test boards" beside a material that does carry one is
 * a half truth, and the same list is the refusal's own wording on the engine side. The
 * caller joins them with `i18n.list`, so the separator is the reader's own and can
 * never be the decimal mark.
 */
export function wouldGoWith(usage: MaterialUsage): string[] {
	const parts: string[] = [];
	if (usage.presets) parts.push(t('count.presets', { n: usage.presets }));
	if (usage.test_grids) parts.push(t('count.testGrids', { n: usage.test_grids }));
	if (usage.grid_recipes) parts.push(t('count.recipes', { n: usage.grid_recipes }));
	// The photographs are the evidence, and they are files beside the database: the
	// cascade cannot reach them and only this route ever unlinks one.
	if (usage.photos) parts.push(t('count.photos', { n: usage.photos }));
	return parts;
}

export type ActiveMachine = {
	id: number;
	name: string;
	device_path: string | null;
	has_z: number;
	has_autofocus: number;
};

export class LibraryStore {
	materials = $state<Material[]>([]);
	presets = $state<Preset[]>([]);
	machines = $state<MachineProfile[]>([]);
	/** The profile of the machine that is active now; decides what you see here. */
	activeMachine = $state<ActiveMachine | null>(null);
	/** Off: show presets from other machines as well. */
	onlyThisMachine = $state(true);
	/**
	 * The six counts of this machine, read on every load.
	 *
	 * Six `COUNT(*)`s over a 204 KB file, and no network — the same answer the offer
	 * card reads, and the only place that knows how many settings belong to no machine
	 * at all. Four presets and eleven boards in the author's library are in that state,
	 * and `presets()` shows them on every machine because its WHERE says
	 * `machine_id = ? OR machine_id IS NULL`.
	 */
	coverage = $state<StarterCoverage | null>(null);
	busy = $state(false);
	error = $state<string | null>(null);

	#token: () => string;

	constructor(token: () => string) {
		this.#token = token;
	}

	#headers(json = false): Record<string, string> {
		const headers: Record<string, string> = {};
		const token = this.#token();
		if (token) headers.Authorization = `Bearer ${token}`;
		if (json) headers['Content-Type'] = 'application/json';
		return headers;
	}

	async #request(path: string, init?: RequestInit) {
		this.busy = true;
		this.error = null;
		try {
			const response = await fetch(path, init);
			if (!response.ok) {
				this.error = await describe(response);
				return null;
			}
			return await response.json();
		} catch (e) {
			this.error = t('error.network', { message: e instanceof Error ? e.message : String(e) });
			return null;
		} finally {
			this.busy = false;
		}
	}

	async load() {
		const all = this.onlyThisMachine ? '' : '?all_machines=true';
		const [materials, presets, machines, active, starter] = await Promise.all([
			this.#request('/api/library/materials'),
			this.#request(`/api/library/presets${all}`),
			this.#request('/api/library/machines'),
			// 409 when no machine is active; then the field stays empty and the
			// library shows itself without a machine header.
			this.#request('/api/library/active-machine'),
			// Counts, not rows, and no network: this is what decides whether the
			// window says anything about settings that hang off no machine.
			this.#request('/api/library/starter')
		]);
		if (materials) this.materials = materials;
		if (presets) this.presets = presets;
		if (machines) this.machines = machines;
		this.coverage = starter?.coverage ?? null;
		this.activeMachine = active ?? null;
		// A failed 409 must not stay behind as an error message.
		if (!active) this.error = null;
		// Nor must the counts: they are an extra on top of this window, and the four
		// reads above are the window itself. An engine that does not answer this route
		// should cost the reader one strip, not a red banner over a library that loaded.
		if (!starter && materials && presets && machines) this.error = null;
	}

	async toggleScope() {
		this.onlyThisMachine = !this.onlyThisMachine;
		await this.load();
	}

	async addMaterial(name: string) {
		const created = await this.#request('/api/library/materials', {
			method: 'POST',
			headers: this.#headers(true),
			body: JSON.stringify({ name })
		});
		if (created) await this.load();
		return created;
	}

	async addPreset(preset: Record<string, unknown>) {
		const created = await this.#request('/api/library/presets', {
			method: 'POST',
			headers: this.#headers(true),
			body: JSON.stringify(preset)
		});
		if (created) await this.load();
		return created;
	}

	async updatePreset(id: number, fields: Record<string, unknown>) {
		const updated = await this.#request(`/api/library/presets/${id}`, {
			method: 'PATCH',
			headers: this.#headers(true),
			body: JSON.stringify(fields)
		});
		if (updated) await this.load();
		return updated;
	}

	/**
	 * What hangs off a material, before the question about removing it is asked.
	 *
	 * Deliberately not cached: the number is read at the moment it is going to be said,
	 * because a count from before the last import is a sentence the reader can catch
	 * out.
	 */
	materialUsage(id: number): Promise<MaterialUsage | null> {
		return this.#request(`/api/library/materials/${id}/usage`);
	}

	/**
	 * Renaming a material, or giving it another word people call it by.
	 *
	 * There was no way to do this at all, which is why this library holds both
	 * `Multiplex berken` and `Berkentriplex` for one board: the only way to fix a typo
	 * was to add a second material beside the first. A name that is taken is refused
	 * rather than merged — merging is a different verb with its own question.
	 */
	async renameMaterial(id: number, fields: { name?: string; synonyms?: string[] }) {
		const saved = await this.#request(`/api/library/materials/${id}`, {
			method: 'PATCH',
			headers: this.#headers(true),
			body: JSON.stringify(fields)
		});
		if (saved) await this.load();
		return saved;
	}

	/**
	 * Two names for one board, joined into one — losing neither side's work.
	 *
	 * Nothing is thrown away but the row itself: the settings, the boards, the
	 * photographs and the recipes move over, and the old name joins the target's
	 * synonyms so the next import of a bundle that still calls it by the old name lands
	 * on the right board.
	 */
	async mergeMaterial(id: number, targetId: number) {
		const done = await this.#request(
			`/api/library/materials/${id}/merge-into/${targetId}`,
			{ method: 'POST', headers: this.#headers() }
		);
		if (done) await this.load();
		return done;
	}

	/**
	 * Removing a material, with everything on it or not at all.
	 *
	 * `withEverything` is a second word and never a default: behind it sit
	 * `preset` CASCADE, `grid_recipe` CASCADE and `test_grid.material_id` SET NULL, so
	 * the bare call this used to be was a data-loss button with a one-word label. The
	 * engine refuses without the word and names what it would take; the interface reads
	 * the same counts first and says them, so nothing here is silent.
	 */
	async removeMaterial(id: number, withEverything = false) {
		const done = await this.#request(
			`/api/library/materials/${id}?with_everything=${withEverything ? 'true' : 'false'}`,
			{ method: 'DELETE', headers: this.#headers() }
		);
		if (done) await this.load();
		return done;
	}

	/**
	 * Taking one import back: its settings, and the materials it brought with them.
	 *
	 * The strongest defence there is against a library turning into a junk drawer, and
	 * the reason is arithmetic: one bulk tick-list produced fourteen of the author's
	 * twenty materials and twenty-six of his thirty-five settings, all for a machine he
	 * does not run. Materials the batch created that something else now uses stay.
	 */
	async removeImport(batch: string): Promise<ImportUndone | null> {
		const done = await this.#request(`/api/library/imports/${encodeURIComponent(batch)}`, {
			method: 'DELETE',
			headers: this.#headers()
		});
		if (done) await this.load();
		return done;
	}

	/**
	 * What the machine is, written where the machine lives.
	 *
	 * Every profile in the author's library carries `power_watt: null`, so somebody who
	 * is already set up needs a door: without the kind and the wattage nothing can
	 * match, and an 80 W catalogue showed all twenty-six of its rows to a machine nobody
	 * had described. The wizard asks it once; this is the same field for the machine you
	 * already have, and it writes through the same route.
	 */
	async updateMachineProfile(id: number, fields: Record<string, unknown>) {
		const saved = await this.#request(`/api/library/machines/${id}`, {
			method: 'PATCH',
			headers: this.#headers(true),
			body: JSON.stringify(fields)
		});
		if (saved) await this.load();
		return saved;
	}

	/**
	 * The settings and boards that belong to no machine, onto the active one.
	 *
	 * Never by itself: adopting them says they were measured here, which may be false,
	 * and leaving them says they hold everywhere, which is false too. Only the reader
	 * knows, so this is a button and the strip beside it states the count.
	 */
	async adoptStrays() {
		const done = await this.#request('/api/library/presets/adopt', {
			method: 'POST',
			headers: this.#headers(true),
			body: JSON.stringify({})
		});
		if (done) await this.load();
		return done;
	}

	/**
	 * Two profiles for one laser, joined into the one you are working on.
	 *
	 * The case is measured rather than imagined: this library holds a device-less
	 * `5030 CO2` with 60 W and twenty-seven settings beside the device-bound `KH-5030`
	 * with three settings and no wattage, and they are one machine. `_dedupe_machines`
	 * cannot reach it — it only merges rows that share a device path, and the unique
	 * index it creates keeps that case from ever arising.
	 */
	async mergeMachineProfile(id: number, targetId: number) {
		const done = await this.#request(`/api/library/machines/${id}/merge-into/${targetId}`, {
			method: 'POST',
			headers: this.#headers()
		});
		if (done) await this.load();
		return done;
	}

	async removeMachineProfile(id: number) {
		const done = await this.#request(`/api/library/machines/${id}`, {
			method: 'DELETE',
			headers: this.#headers()
		});
		if (done) await this.load();
		return done;
	}

	suggest(materialId: number | null, operation: string, thicknessMm: number | null) {
		const params = new URLSearchParams({ operation });
		if (materialId !== null) params.set('material_id', String(materialId));
		if (thicknessMm !== null) params.set('thickness_mm', String(thicknessMm));
		return this.#request(`/api/library/suggest?${params}`);
	}

	/**
	 * What offering this setting would say, before anything is written.
	 *
	 * A read, and the first thing the share panel does: the tier, the reason for it and
	 * the missing handle are all knowable without touching the catalogue, and telling
	 * the reader beforehand is better than a refusal from somebody else's CI afterwards.
	 */
	async contribution(id: number): Promise<Contribution | null> {
		return (await this.#request(`/api/presetariat/contribution/${id}`)) as Contribution | null;
	}

	/**
	 * The answers the panel collected, and then the contribution.
	 *
	 * Both answers are writes on this computer — the handle beside the library so it is
	 * asked once, the outcome onto the row so a second offer does not ask again — which
	 * is why this is a POST and the reading above is not.
	 */
	async offerContribution(
		id: number,
		answers: { by?: string; result?: { charring: string; cut_through?: boolean | null; kerf_mm?: number | null } }
	): Promise<Contribution | null> {
		const done = await this.#request(`/api/presetariat/contribution/${id}`, {
			method: 'POST',
			headers: this.#headers(true),
			body: JSON.stringify(answers)
		});
		// The outcome now sits on the row, so the list is a version behind.
		if (done) await this.load();
		return done as Contribution | null;
	}

	async removePreset(id: number) {
		const done = await this.#request(`/api/library/presets/${id}`, {
			method: 'DELETE',
			headers: this.#headers()
		});
		if (done) await this.load();
		return done;
	}

	applyTo(presetId: number, operationId: string) {
		return this.#request(`/api/library/presets/${presetId}/apply`, {
			method: 'POST',
			headers: this.#headers(true),
			body: JSON.stringify({ operation_id: operationId })
		});
	}

	// -------------------------------------------------- exchange (decision B7)

	/**
	 * Fetch the whole library as one file.
	 *
	 * Through an anchor and not through fetch: that way the browser does what it is
	 * good at — a download with a name, without pulling the file into the page's
	 * memory first.
	 */
	exportBundle() {
		const anchor = document.createElement('a');
		anchor.href = '/api/library/export.openkerf-lib';
		anchor.download = 'library.openkerf-lib';
		anchor.click();
	}

	async uploadBundle(file: File): Promise<ImportPreview | null> {
		this.busy = true;
		this.error = null;
		try {
			const form = new FormData();
			form.append('file', file);
			const response = await fetch('/api/library/import/upload', {
				method: 'POST',
				headers: this.#headers(),
				body: form
			});
			if (!response.ok) {
				this.error = await describe(response);
				return null;
			}
			return await response.json();
		} catch (e) {
			this.error = t('error.network', { message: e instanceof Error ? e.message : String(e) });
			return null;
		} finally {
			this.busy = false;
		}
	}

	/** The same preview, recomputed after you have pointed at a material. */
	previewBundle(bundle: string, mergeMaterials: Record<string, number>) {
		return this.#request('/api/library/import/preview', {
			method: 'POST',
			headers: this.#headers(true),
			body: JSON.stringify({ bundle, merge_materials: mergeMaterials })
		}) as Promise<ImportPreview | null>;
	}

	async importBundle(
		bundle: string,
		mode: 'merge' | 'replace',
		mergeMaterials: Record<string, number>,
		onConflict: 'mine' | 'file'
	): Promise<ImportResult | null> {
		const done = await this.#request('/api/library/import', {
			method: 'POST',
			headers: this.#headers(true),
			body: JSON.stringify({
				bundle,
				mode,
				merge_materials: mergeMaterials,
				on_conflict: onConflict
			})
		});
		if (done) await this.load();
		return done;
	}

	presetsFor(materialId: number | null) {
		return materialId === null
			? this.presets
			: this.presets.filter((p) => p.material_id === materialId);
	}
}

// ------------------------------------------------ the offer, and the one moment for it
//
// Somebody has just defined a machine and the app notices it has no settings. That is
// the moment this whole part of the app exists for, and it is the reason the catalogue
// itself is no longer a window with a rail button: a workspace you consult once per
// machine does not earn a permanent seat beside Rectangle and Pen.
//
// Two surfaces make the offer — the top of the material library and the end of setup —
// and they read one function, `offerState`, in the pattern `actions.ts` and `jobPhase`
// set: where more than one place has to know the same thing, it is written once.

/** How much of this library belongs to this machine. Six counts, one instant. */
export type StarterCoverage = {
	mine: number;
	mine_measured: number;
	materials_covered: number;
	materials_known: number;
	unattached: number;
	unattached_grids: number;
};

/** What the machine is, as far as the library knows. */
export type StarterMachine = {
	id: number;
	name: string | null;
	laser_type: string;
	power_watt: number | null;
	/** `''`, `'dismissed'` or `'power_unknown'` — what the user has already said. */
	starter_state: string;
};

/** The answer of `GET /api/library/starter`. */
export type StarterOffer = {
	machine: StarterMachine | null;
	state: string;
	needed: boolean;
	coverage: StarterCoverage | null;
};

export type OfferState = 'askMachine' | 'nothing' | 'unburned' | 'none';

/** What the card shows, and why. */
export type OfferView = {
	state: OfferState;
	/** Anything to say at all. False means the card is not there. */
	needed: boolean;
	/** The kind is not known, so the field is shown and the fetch cannot match. */
	needsKind: boolean;
	/** The tube power is not known and the reader has not said they do not know. */
	needsWatt: boolean;
	/** Enough is known about the machine to go and look. */
	canFetch: boolean;
	/** Matching on the kind alone: every row has to say so on its own line. */
	powerUnknown: boolean;
	/** Settings, but not one of them burned here. Another fetch is not the answer. */
	suggestTestGrid: boolean;
};

/**
 * Whether to offer this machine a set of starting points, and what to put on screen.
 *
 * The same order of tests as `Starter._state` in the engine layer, on the same fields,
 * because the two answer one question at two moments: this one when the card is drawn,
 * that one when the fetch is written. Dismissal wins over everything — a card that
 * comes back after you waved it away is a nag, and this one would come back on every
 * open of the library.
 *
 * The trigger is `mine == 0` and not a ratio of covered materials. Measured on the
 * author's library, one of twenty materials has a setting for the active machine, and
 * a ratio would therefore fire on it forever. The *sentence* still carries that one of
 * twenty, because it is the fact the reader recognises; the ratio just never decides.
 *
 * A caller that has the profile but no `machine` block — `/api/library/active-machine`
 * hands the two apart — may pass the state it was given, and then that is used as it
 * came. Anything else is derived here, so a surface cannot invent a fifth state.
 */
export function offerState(offer: StarterOffer | null | undefined): OfferView {
	const quiet: OfferView = {
		state: 'none',
		needed: false,
		needsKind: false,
		needsWatt: false,
		canFetch: false,
		powerUnknown: false,
		suggestTestGrid: false
	};
	if (!offer) return quiet;
	const machine = offer.machine;
	if (!machine) {
		// No machine to describe. Trust the state the server sent, if it sent a known
		// one; without a machine there is nothing here to derive it from.
		const said = offer.state;
		if (said === 'askMachine' || said === 'nothing' || said === 'unburned')
			return { ...quiet, state: said, needed: true };
		return quiet;
	}

	const said = machine.starter_state ?? '';
	if (said === 'dismissed') return quiet;
	const kind = machine.laser_type || 'unknown';
	const powerUnknown = said === 'power_unknown';
	const needsKind = kind === 'unknown';
	const needsWatt = !machine.power_watt && !powerUnknown;
	const coverage = offer.coverage;

	if (needsKind || needsWatt)
		return {
			state: 'askMachine',
			needed: true,
			needsKind,
			needsWatt,
			// Filling the two fields in is the way out; going to look before they are
			// filled in would match nothing and say nothing about why.
			canFetch: false,
			powerUnknown,
			suggestTestGrid: false
		};

	const mine = coverage?.mine ?? 0;
	const measured = coverage?.mine_measured ?? 0;
	if (!mine)
		return { ...quiet, state: 'nothing', needed: true, canFetch: true, powerUnknown };
	if (!measured)
		return {
			...quiet,
			state: 'unburned',
			needed: true,
			canFetch: true,
			powerUnknown,
			suggestTestGrid: true
		};
	return { ...quiet, canFetch: true, powerUnknown };
}

/**
 * What a setting of your own would look like in the shared catalogue, and what it still
 * needs before it can go.
 *
 * `preset` is the body that would be offered, and it is `null` until the offer would
 * pass the repository's own schema — the app had never asked for a GitHub handle, so
 * every contribution file it wrote was refused by that repository's CI on
 * `missing required: [by, tier]`. Everything about the *state* of the offer is out here
 * beside the body and never inside it: the schema is `additionalProperties: false`, so
 * one extra key of ours is refused as hard as one field of theirs that is missing.
 */
export type Contribution = {
	ready: boolean;
	/** What is missing, as tokens to branch on: `handle` is the only one today. */
	needs: string[];
	by: string | null;
	/** `measured` needs a board, this machine, and an outcome; anything else is a guess. */
	tier: 'measured' | 'starting_point';
	/** Why it is not measured, in one word — `null` when it is. */
	tier_reason: string | null;
	/** The board it was read off, `OK1` and eight characters, or null. */
	board: string | null;
	measured_at: string | null;
	/** The catalogue entry these numbers were adjusted from, if they came out of it. */
	derived_from: string | null;
	preset: Record<string, unknown> | null;
	filename: string;
	issue_url: string | null;
	repo_url: string;
};

/** One row of the shared catalogue, as `GET /api/presetariat` hands it back. */
export type StarterRow = {
	id: string;
	material: string;
	synonyms?: string[];
	thickness_mm: number | null;
	operation: string;
	speed_mm_s: number;
	power_percent: number;
	passes?: number | null;
	machine?: { laser_type?: string | null; power_watt?: number | null } | null;
	/** `measured` (somebody burned it) or `starting_point` (somebody believed it). */
	tier?: string | null;
	/** Who gets the credit. CC BY means this travels with the row or the copy is
	 *  not licensed, so it is the reader's data and goes on screen as it came. */
	by?: string | null;
	note?: string | null;
	imported?: boolean;
	/** Matched on the kind alone, because one of the two wattages is not known. */
	power_unmatched?: boolean;
};

/** Where the rows came from, and under what terms. */
export type StarterCatalogue = {
	count: number;
	total: number;
	/** The starting points that ship inside the app, rather than the shared set. */
	from_seed: boolean;
	license: string | null;
	attribution: string | null;
	/** Seconds since the epoch, or null for the seed — it was never fetched. */
	fetched_at: number | null;
	very_stale: boolean;
	stale: boolean;
	error: string | null;
	matched_on: string;
	skipped: number;
};

/** One press of Add, and what it did — the thing a second press takes back. */
export type StarterImport = {
	batch: string;
	material: string;
	presets: number;
	materials: number;
};

/**
 * The offer, and the fetching that follows from it.
 *
 * Its own store rather than a corner of `LibraryStore`, because the card exists on a
 * page that has no library — the last step of the wizard — and because everything it
 * writes goes through routes the library store never touches.
 *
 * The rows are **not** loaded when the card appears. `GET /api/presetariat` reads a
 * cache that may be six hours old, and then it goes to the network with a ten-second
 * timeout; hanging the opening of the material library on that is how a feature gets
 * switched off. So the card names the machine straight away and looks only when asked.
 */
export class StarterStore {
	offer = $state<StarterOffer | null>(null);
	rows = $state<StarterRow[] | null>(null);
	catalogue = $state<StarterCatalogue | null>(null);
	/** Every import this card made, newest first, each one still undoable. */
	imports = $state<StarterImport[]>([]);
	busy = $state(false);
	error = $state<string | null>(null);
	/** Waved away here and now, before the server has been told. */
	away = $state(false);

	#token: () => string;

	constructor(token: () => string) {
		this.#token = token;
	}

	#headers(json = false): Record<string, string> {
		const headers: Record<string, string> = {};
		const token = this.#token();
		if (token) headers.Authorization = `Bearer ${token}`;
		if (json) headers['Content-Type'] = 'application/json';
		return headers;
	}

	async #request(path: string, init?: RequestInit) {
		this.busy = true;
		this.error = null;
		try {
			const response = await fetch(path, init);
			if (!response.ok) {
				this.error = await describe(response);
				return null;
			}
			return await response.json();
		} catch (e) {
			this.error = t('error.network', { message: e instanceof Error ? e.message : String(e) });
			return null;
		} finally {
			this.busy = false;
		}
	}

	/** What the machine has, and whether that is worth a word. No network. */
	async load() {
		const offer = await this.#request('/api/library/starter');
		if (offer) this.offer = offer;
		// A machine that is not set up yet answers `needed: false` rather than
		// refusing, so an error here is a real one and stays on screen.
		return this.offer;
	}

	/** What the card shows, from the one function both surfaces read. */
	get view(): OfferView {
		return this.away ? offerState(null) : offerState(this.offer);
	}

	/** The two things the match needs, written where the machine lives. */
	async describeMachine(fields: { laser_type?: string; power_watt?: number | null }) {
		const id = this.offer?.machine?.id;
		if (id === undefined) return null;
		const saved = await this.#request(`/api/library/machines/${id}`, {
			method: 'PATCH',
			headers: this.#headers(true),
			body: JSON.stringify(fields)
		});
		if (saved) await this.load();
		return saved;
	}

	/**
	 * "Not now", or "I don't know what my tube is".
	 *
	 * One route for both, because both are the same column: what the user has already
	 * told us about starting points for this machine. `power_unknown` is not a
	 * dismissal — it keeps the offer and drops the wattage half of the match.
	 */
	async say(state: 'dismissed' | 'power_unknown') {
		if (state === 'dismissed') this.away = true;
		const offer = await this.#request('/api/library/starter/dismiss', {
			method: 'POST',
			headers: this.#headers(true),
			body: JSON.stringify({ state })
		});
		if (offer) this.offer = offer;
		else if (state === 'dismissed') this.away = false;
		return offer;
	}

	/**
	 * Go and look: what the shared catalogue has for this machine.
	 *
	 * `refresh` goes past the cache to the network, and is only ever a button the
	 * reader presses — a copy a month old says so and offers this, rather than the app
	 * deciding to wait ten seconds on somebody's behalf.
	 */
	async look(refresh = false) {
		const id = this.offer?.machine?.id;
		const params = new URLSearchParams();
		if (id !== undefined) params.set('machine_id', String(id));
		if (refresh) params.set('refresh', 'true');
		const found = await this.#request(`/api/presetariat?${params}`);
		if (!found) return null;
		this.rows = (found.presets ?? []) as StarterRow[];
		this.catalogue = found as StarterCatalogue;
		return this.rows;
	}

	/** The rows this machine could still take over, per material, in one order. */
	get perMaterial(): { material: string; rows: StarterRow[] }[] {
		const groups = new Map<string, StarterRow[]>();
		for (const row of this.rows ?? []) {
			if (row.imported) continue;
			const group = groups.get(row.material);
			if (group) group.push(row);
			else groups.set(row.material, [row]);
		}
		return [...groups].map(([material, rows]) => ({ material, rows }));
	}

	/**
	 * Take over the rows of one material — one press, one material, never the lot.
	 *
	 * A bulk tick-list is what put fourteen unwanted materials in the author's
	 * library, all bound to a machine he does not run. And nothing is written by this
	 * module: `stage` builds a real library file and the import route that already
	 * exists does the writing, in one transaction, with the batch stamp that makes the
	 * next method possible.
	 */
	async take(material: string) {
		const rows = this.perMaterial.find((group) => group.material === material)?.rows ?? [];
		if (!rows.length) return null;
		const staged = await this.#request('/api/presetariat/stage', {
			method: 'POST',
			headers: this.#headers(true),
			body: JSON.stringify({ ids: rows.map((row) => row.id) })
		});
		if (!staged) return null;
		const done = await this.#request('/api/library/import', {
			method: 'POST',
			headers: this.#headers(true),
			body: JSON.stringify({
				bundle: staged.bundle,
				mode: 'merge',
				// Your own numbers win over a starting point, always. This is the same
				// answer the import screen defaults to.
				on_conflict: 'mine',
				import_batch: staged.import_batch
			})
		});
		if (!done) return null;
		this.imports = [
			{
				batch: staged.import_batch,
				material,
				presets: done.presets?.added ?? 0,
				materials: done.materials ?? 0
			},
			...this.imports
		];
		await Promise.all([this.load(), this.look()]);
		return done;
	}

	/**
	 * Take one import back, in one press.
	 *
	 * This is the real answer to a junk drawer, and the reason the fetch is allowed to
	 * be one press in the first place: an import you can undo is not a dump. It removes
	 * the settings and the materials that import created which nothing else uses.
	 */
	async undo(batch: string) {
		const done = await this.#request(`/api/library/imports/${encodeURIComponent(batch)}`, {
			method: 'DELETE',
			headers: this.#headers()
		});
		if (!done) return null;
		this.imports = this.imports.filter((entry) => entry.batch !== batch);
		await Promise.all([this.load(), this.look()]);
		return done;
	}
}

async function describe(response: Response): Promise<string> {
	if (response.status === 401) return t('error.noToken');
	try {
		const body = await response.json();
		if (typeof body.detail === 'string') return apiError(response, body.detail);
		if (body.detail?.output?.length) return body.detail.output.join(' · ');
	} catch {
		/* generic text below */
	}
	return t('error.libraryRefused', { status: response.status });
}
