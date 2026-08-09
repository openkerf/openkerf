import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

const API = process.env.OPENKERF_API ?? 'http://127.0.0.1:8080';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		// In dev the frontend runs on 5173 and the engine on 8080; proxying keeps
		// the app's own URLs identical to how it is served in production.
		proxy: {
			'/api': { target: API, changeOrigin: true, ws: true }
		}
	}
});
