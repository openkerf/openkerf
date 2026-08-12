/// <reference types="@sveltejs/kit" />
/**
 * Service worker: de app-schil offline beschikbaar houden.
 *
 * Bewust géén caching van /api — dat is de machine, en verouderde status of
 * een uit de cache geserveerde jobopdracht is precies wat je niet wilt bij
 * iets dat brandt. Alleen de gebouwde bestanden gaan in de cache.
 */
import { build, files, prerendered, version } from '$service-worker';

const CACHE = `openkerf-${version}`;
// `prerendered` hoorde hier ook bij: dat zijn de pagina's zelf. Zonder die
// stond de schil nooit in de cache, en viel de offline-terugval altijd terug op
// een foutmelding — een PWA die alleen offline werkt als je online bent.
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
 * Een melding aantikken hoort de app te openen, niet een tweede tabblad.
 *
 * De meldingen zelf worden vanuit de pagina verstuurd (zie meldingen.svelte.ts);
 * ze lopen via de service worker omdat Android `new Notification()` vanuit een
 * pagina weigert. Dan hoort de klik hier ook opgevangen te worden — anders
 * gebeurt er niets als je hem aantikt terwijl de telefoon in je zak zat.
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

	// De machine nooit uit de cache: status moet vers zijn en een opdracht mag
	// niet stilletjes uit een cache komen.
	if (request.method !== 'GET' || url.pathname.startsWith('/api')) return;
	if (url.origin !== location.origin) return;

	// Pagina's eerst van het netwerk. Cache-first leek zuiniger, maar dan houd
	// je na een nieuwe versie een oude pagina vast die naar bestanden verwijst
	// die niet meer bestaan — en dan is de app stuk tot je de cache leegt.
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

	// De rest draagt een hash in zijn naam en verandert dus nooit van inhoud;
	// die mag uit de cache.
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
