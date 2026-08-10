/// <reference types="@sveltejs/kit" />
/**
 * Service worker: de app-schil offline beschikbaar houden.
 *
 * Bewust géén caching van /api — dat is de machine, en verouderde status of
 * een uit de cache geserveerde jobopdracht is precies wat je niet wilt bij
 * iets dat brandt. Alleen de gebouwde bestanden gaan in de cache.
 */
import { build, files, version } from '$service-worker';

const CACHE = `openkerf-${version}`;
const SHELL = [...build, ...files];

self.addEventListener('install', (event) => {
	const worker = self as unknown as ServiceWorkerGlobalScope;
	event.waitUntil(
		caches
			.open(CACHE)
			.then((cache) => cache.addAll(SHELL))
			.then(() => worker.skipWaiting())
	);
});

self.addEventListener('activate', (event) => {
	const worker = self as unknown as ServiceWorkerGlobalScope;
	event.waitUntil(
		caches
			.keys()
			.then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
			.then(() => worker.clients.claim())
	);
});

self.addEventListener('fetch', (event) => {
	const request = event.request;
	const url = new URL(request.url);

	// De machine nooit uit de cache: status moet vers zijn en een opdracht mag
	// niet stilletjes uit een cache komen.
	if (request.method !== 'GET' || url.pathname.startsWith('/api')) return;
	if (url.origin !== location.origin) return;

	event.respondWith(
		caches.match(request).then(
			(hit) =>
				hit ??
				fetch(request).catch(() =>
					// Offline en niet in de cache: geef de app-schil, dan blijft
					// client-routing werken.
					caches.match('/').then((shell) => shell ?? Response.error())
				)
		)
	);
});
