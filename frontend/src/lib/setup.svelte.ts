/**
 * Gedeelde bouwstenen voor de setup-routes.
 *
 * De stappen zijn losse pagina's, dus er is geen component-state die ze
 * overleeft. Wat een volgende stap nodig heeft staat in de URL — daardoor
 * werken de terugknop, een bladwijzer en een verversing allemaal gewoon.
 */

import { MachineStore } from './machines.svelte';

const TOKEN_KEY = 'openkerf.token';

export function createStore() {
	return new MachineStore(() =>
		typeof localStorage === 'undefined' ? '' : (localStorage.getItem(TOKEN_KEY) ?? '')
	);
}
