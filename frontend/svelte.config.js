import adapter from '@sveltejs/adapter-static';

/** @type {import('@sveltejs/kit').Config} */
export default {
	kit: {
		// Static build: the API layer serves these files, so the user installs one thing.
		adapter: adapter({ fallback: 'index.html' }),
		alias: { $components: 'src/lib/components' }
	}
};
