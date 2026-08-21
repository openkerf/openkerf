/// <reference types="@sveltejs/kit" />
/**
 * Service worker: de app-schil offline beschikbaar houden.
 *
 * Deliberately no caching of /api — that is the machine, and a stale status or a job
 * command served from the cache is exactly what you do not want around something that
 * burns. Only the built files go into the cache.
 */
import { build, files, prerendered, version } from '$service-worker';

const CACHE = `openkerf-${version}`;
// `prerendered` belonged here too: those are the pages themselves. Without them the
// shell was never in the cache, and the offline fallback always fell back on an error
// message — a PWA that only works offline while you are online.
const SHELL = [...build, ...files, ...prerendered];

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

/**
 * Tapping a notification should open the app, not a second tab.
 *
 * The notifications themselves are sent from the page (see notifications.svelte.ts); they
 * go through the service worker because Android refuses `new Notification()` from a page.
 * Then the click should be caught here as well — otherwise nothing happens when you tap
 * it while the phone was in your pocket.
 */
self.addEventListener('notificationclick', (event) => {
	const worker = self as unknown as ServiceWorkerGlobalScope;
	const melding = (event as NotificationEvent).notification;
	melding.close();
	event.waitUntil(
		worker.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((vensters) => {
			for (const venster of vensters) {
				if ('focus' in venster) return venster.focus();
			}
			return worker.clients.openWindow('/');
		})
	);
});

self.addEventListener('fetch', (event) => {
	const request = event.request;
	const url = new URL(request.url);

	// Never the machine from the cache: status has to be fresh and a command must not
	// come silently out of a cache.
	if (request.method !== 'GET' || url.pathname.startsWith('/api')) return;
	if (url.origin !== location.origin) return;

	// Pages from the network first. Cache-first seemed more frugal, but then after a new
	// version you hold on to an old page that refers to files that no longer exist — and
	// then the app is broken until you clear the cache.
	if (request.mode === 'navigate') {
		event.respondWith(
			fetch(request).catch(() =>
				caches
					.match(request)
					.then((hit) => hit ?? caches.match('/'))
					.then((shell) => shell ?? Response.error())
			)
		);
		return;
	}

	// The rest carries a hash in its name and therefore never changes content; that may
	// come from the cache.
	event.respondWith(
		caches.match(request).then(
			(hit) =>
				hit ??
				fetch(request).catch(() =>
					caches.match('/').then((shell) => shell ?? Response.error())
				)
		)
	);
});
