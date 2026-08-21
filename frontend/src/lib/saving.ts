/**
 * Een bestand ophalen en aanbieden als download — en pas terugkomen als het er is.
 *
 * Opslaan was een gewone `<a href download>`. Dat werkt (het bestand komt),
 * maar de app leert er niets van: de server set bij die route
 * `document.clean()`, terwijl de client zijn eigen `dirty` alleen bijwerkt als
 * `/api/design` opnieuw langskomt — en dat gebeurt bij een download niet, want
 * er verandert niets in de elementenboom en er komt dus geen signaal.
 *
 * Gemeten: iets tekenen, project saving, "Nieuw project" → *"Dit ontwerp is
 * gewijzigd since de last keer saving"*, terwijl `/api/design` op dat
 * moment `dirty: false` gaf. Een waarschuwing die ook komt als er niets aan de
 * hand is, leer je wegklikken; dat is de schade, niet de zin zelf.
 *
 * Daarom halen we het bestand zelf op. Dan weten we wanneer het klaar is en
 * kunnen we daarna de toestand verversen. De bestandsnaam komt uit
 * `Content-Disposition`, zodat de server hem blijft bepalen.
 */

export async function bewaarBestand(url: string, standaardnaam: string): Promise<boolean> {
	try {
		const response = await fetch(url);
		if (!response.ok) return false;
		const blob = await response.blob();
		const naam = naamUit(response.headers.get('content-disposition')) ?? standaardnaam;
		const adres = URL.createObjectURL(blob);
		const anker = document.createElement('a');
		anker.href = adres;
		anker.download = naam;
		document.body.appendChild(anker);
		anker.click();
		anker.remove();
		// Niet meteen intrekken: Safari begint de download pas ná de klik.
		setTimeout(() => URL.revokeObjectURL(adres), 60_000);
		return true;
	} catch {
		return false;
	}
}

function naamUit(header: string | null): string | null {
	if (!header) return null;
	const ster = /filename\*=UTF-8''([^;]+)/i.exec(header);
	if (ster) return decodeURIComponent(ster[1].trim());
	const gewoon = /filename="?([^";]+)"?/i.exec(header);
	return gewoon ? gewoon[1].trim() : null;
}
