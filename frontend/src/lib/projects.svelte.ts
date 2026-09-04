/**
 * Projects kept on the server, and which one is open.
 *
 * One store for four surfaces: the project button in the top bar (name and the unsaved
 * dot), the menu behind it, the keyboard, and the Projects window. Each of them reads
 * this and none of them keeps a copy of the rule.
 */
import { apiError } from './i18n/core.ts';

export type ProjectEntry = { name: string; saved_at: string; bytes: number; current: boolean };
export type CurrentProject = { name: string; saved_at: string };

export const MAX_NAME = 60;

/** The same rule as `openkerf_api/projects.py:clean_name`, held to it by a test. */
export function cleanName(raw: string): string {
	const kept = (raw ?? '').replace(/[^A-Za-z0-9 ._-]/g, '').replace(/^\.+/, '').trim();
	return kept.slice(0, MAX_NAME).trim();
}

function token(): string {
	return typeof localStorage === 'undefined' ? '' : (localStorage.getItem('openkerf.token') ?? '');
}
function headers(json = false): Record<string, string> {
	const h: Record<string, string> = {};
	if (json) h['Content-Type'] = 'application/json';
	const t = token();
	if (t) h['X-OpenKerf-Token'] = t;
	return h;
}

async function describe(response: Response): Promise<string> {
	try {
		const body = await response.json();
		if (typeof body.detail === 'string') return apiError(response, body.detail);
		return apiError(response, null);
	} catch {
		return apiError(response, null);
	}
}

export class ProjectsStore {
	list = $state<ProjectEntry[]>([]);
	current = $state<CurrentProject | null>(null);
	dirty = $state(false);
	busy = $state(false);
	error = $state<string | null>(null);

	/** Called with every design snapshot, which carries `project` and `dirty`. */
	follow(snapshot: { project?: CurrentProject | null; dirty?: boolean } | null) {
		if (snapshot && 'project' in snapshot) this.current = snapshot.project ?? null;
		if (typeof snapshot?.dirty === 'boolean') this.dirty = snapshot.dirty;
	}

	async load() {
		const response = await fetch('/api/projects');
		if (response.ok) this.list = await response.json();
	}

	private async run(path: string, init: RequestInit): Promise<Response | null> {
		this.busy = true;
		this.error = null;
		try {
			const response = await fetch(path, init);
			if (!response.ok) {
				this.error = await describe(response);
				return null;
			}
			await this.load();
			return response;
		} finally {
			this.busy = false;
		}
	}

	async save(name?: string, overwrite = false): Promise<ProjectEntry | null> {
		const target = name ?? this.current?.name;
		if (!target) return null;
		const response = await this.run(
			`/api/projects/${encodeURIComponent(target)}${overwrite ? '?overwrite=1' : ''}`,
			{ method: 'POST', headers: headers() }
		);
		if (!response) return null;
		const entry = (await response.json()) as ProjectEntry;
		this.current = { name: entry.name, saved_at: entry.saved_at };
		return entry;
	}

	async open(name: string): Promise<boolean> {
		return (await this.run(`/api/projects/${encodeURIComponent(name)}/open`, { method: 'POST', headers: headers() })) !== null;
	}

	async rename(from: string, to: string): Promise<boolean> {
		return (
			(await this.run(`/api/projects/${encodeURIComponent(from)}/rename`, {
				method: 'POST',
				headers: headers(true),
				body: JSON.stringify({ name: to })
			})) !== null
		);
	}

	async remove(name: string): Promise<boolean> {
		return (await this.run(`/api/projects/${encodeURIComponent(name)}`, { method: 'DELETE', headers: headers() })) !== null;
	}

	/** Whether saving under this name would replace another project. */
	taken(name: string): boolean {
		return this.list.some((e) => e.name === name && e.name !== this.current?.name);
	}
}

// No singleton is constructed here — the same reason `LibraryStore` in
// `library.svelte.ts` is not either: a `$state` field only compiles inside Svelte's own
// pipeline, so a module-scope `new ProjectsStore()` would run at plain import time and
// crash the moment a test (or anything else run through plain Node) imports this file
// for `cleanName` alone. `+page.svelte` builds the one instance, the way it builds
// `LibraryStore`, and hands it down.
