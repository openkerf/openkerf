/**
 * Shared building blocks for the setup routes.
 *
 * The steps are separate pages, so there is no component state that survives them.
 * What a next step needs is in the URL — which is why the back button, a bookmark
 * and a refresh all simply work.
 */

import { MachineStore } from './machines.svelte';

const TOKEN_KEY = 'openkerf.token';

export function createStore() {
	return new MachineStore(() =>
		typeof localStorage === 'undefined' ? '' : (localStorage.getItem(TOKEN_KEY) ?? '')
	);
}
