"""
Bijhouden of het ontwerp onopgeslagen wijzigingen heeft.

MeerK40t kent zelf geen "gewijzigd sinds opslaan"-vlag, en zonder die vlag kun
je bij het openen van een bestand niet zien of je iets weggooit. We markeren
daarom op één plek: elke console-opdracht die niet aantoonbaar alleen leest,
plus elke directe boomwijziging.
"""

# Opdrachten die het ontwerp niet veranderen.
# `plan` bouwt een snijplan op uit de bestaande operaties; het raakt de
# elementenboom niet, dus een tijdschatting maakt je ontwerp niet vuil.
READ_ONLY = {"version", "save", "flush", "channel", "help", "plan"}


class Document:
    def __init__(self):
        self.dirty = False

    def touch(self, command: str | None = None) -> None:
        if command is not None:
            first = command.strip().split(" ", 1)[0]
            if first in READ_ONLY:
                return
        self.dirty = True

    def clean(self) -> None:
        """Na opslaan, openen of leegmaken staat het bestand gelijk aan het ontwerp."""
        self.dirty = False
