/**
 * Fetch a file and offer it as a download — and only come back when it is there.
 *
 * Saving used to be an ordinary `<a href download>`. That works (the file arrives),
 * but the app learns nothing from it: the server calls `document.clean()` on that
 * route, while the client only updates its own `dirty` when `/api/design` comes past
 * again — and that does not happen on a download, because nothing changes in the
 * element tree and so no signal arrives.
 *
 * Measured: draw something, save the project, "New project" → *"This design has
 * changed since it was last saved"*, while `/api/design` said `dirty: false` at that
 * very moment. A warning that also appears when nothing is wrong is one you learn to
 * click away; that is the damage, not the sentence itself.
 *
 * So we fetch the file ourselves. Then we know when it is done and can refresh the
 * state afterwards. The file name comes from `Content-Disposition`, so the server
 * keeps deciding it.
 */

export async function saveFile(url: string, defaultName: string): Promise<boolean> {
	try {
		const response = await fetch(url);
		if (!response.ok) return false;
		const blob = await response.blob();
		const name = nameFrom(response.headers.get('content-disposition')) ?? defaultName;
		const address = URL.createObjectURL(blob);
		const anchor = document.createElement('a');
		anchor.href = address;
		anchor.download = name;
		document.body.appendChild(anchor);
		anchor.click();
		anchor.remove();
		// Do not revoke it at once: Safari only starts the download *after* the click.
		setTimeout(() => URL.revokeObjectURL(address), 60_000);
		return true;
	} catch {
		return false;
	}
}

function nameFrom(header: string | null): string | null {
	if (!header) return null;
	const star = /filename\*=UTF-8''([^;]+)/i.exec(header);
	if (star) return decodeURIComponent(star[1].trim());
	const plain = /filename="?([^";]+)"?/i.exec(header);
	return plain ? plain[1].trim() : null;
}
