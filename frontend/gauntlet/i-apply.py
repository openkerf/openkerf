#!/usr/bin/env python3
"""
Move a batch of strings out of a component and into the catalogues.

The interface conversion is a thousand small edits, and doing them by hand is a
thousand chances to put the Dutch in `en.ts`, forget a key, or leave a stale
literal behind. This does the same three steps every time:

  1. replace the literal in the component with a `t('key')` call,
  2. append the English to `en.ts`,
  3. append the Dutch to `nl.ts`,

and it refuses to do any of them if the literal is not found — so a typo is a
loud failure instead of a silently unconverted string.

Usage: a plan file with one entry per string:

    PLAN = [
        ('src/lib/components/Foo.svelte', 'Foo', [
            # (what is in the file, key, English, Dutch)
            ('"Opslaan"', 'foo.save', 'Save', 'Opslaan'),
        ]),
    ]

The first element is matched literally, so it carries its own quotes and any
surrounding markup. What replaces it is derived from where it sits: an attribute
value becomes `{t('key')}`, a text node becomes `{t('key')}` as well, and a
string literal in the script becomes `t('key')`.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def add_to_catalogue(language: str, section: str, entries: list[tuple[str, str]]) -> None:
    """Append keys under a section heading, creating the heading if needed."""
    path = ROOT / 'src' / 'lib' / 'i18n' / f'{language}.ts'
    text = path.read_text()
    heading = f'\t// ── {section} ─'
    lines = ''.join(
        f'\t{key!r}: {value!r},\n'.replace("'", "'", 1) for key, value in entries
    )
    # Python's repr uses single quotes unless the value contains one; normalise to
    # the project's style (single quotes, escaped where needed).
    lines = ''
    for key, value in entries:
        # A partly failed run has already written some keys; adding them again
        # would produce a duplicate entry rather than an error.
        if f"'{key}':" in text:
            continue
        if isinstance(value, dict):
            lines += (
                f"\t'{key}': {{\n"
                f"\t\tone: {quote(value['one'])},\n"
                f"\t\tother: {quote(value['other'])}\n"
                f"\t}},\n"
            )
        else:
            lines += f"\t'{key}': {quote(value)},\n"

    if heading in text:
        # Insert after the existing heading line.
        start = text.index(heading)
        eol = text.index('\n', start) + 1
        text = text[:eol] + lines + text[eol:]
    else:
        dashes = '─' * max(4, 74 - len(section))
        block = f'\n\t// ── {section} {dashes}\n{lines}'
        marker = '\n} as const;' if language == 'en' else '\n};'
        assert marker in text, f'{language}: end of catalogue not found'
        # The last entry of an object literal has no trailing comma; appending
        # after it would produce `'a': 'b'\n\t'c': 'd'`, which is a syntax error
        # rather than a missing key — and therefore harder to place.
        head, tail = text.rsplit(marker, 1)
        if not head.rstrip().endswith(','):
            head = head.rstrip() + ','
        text = head + block + marker + tail
    path.write_text(text)


def quote(value: str) -> str:
    """Single-quoted TypeScript string, escaping what needs it."""
    escaped = value.replace('\\', '\\\\').replace("'", "\\'")
    return f"'{escaped}'"


def apply(plan) -> None:
    total = 0
    for relative, section, entries in plan:
        path = ROOT / relative
        text = path.read_text()
        english: list[tuple[str, str]] = []
        dutch: list[tuple[str, str]] = []
        # Longest literal first. Otherwise replacing "Nulpunt" everywhere eats the
        # word out of "Nulpunt van het werk", and the longer entry is then not
        # found — a failure whose cause is three lines further up in the plan.
        for found, key, en, nl in sorted(
            entries, key=lambda e: -len(e[0] or '')
        ):
            if found is not None:
                # `ALL:` says the same message really does appear more than once —
                # a label that exists in both the compact and the wide variant, for
                # instance. Without it, a repeat is an error: two occurrences are
                # usually two different messages that happen to read alike, and
                # replacing only the first leaves a silent leftover.
                every = found.startswith('ALL:')
                needle = found[4:] if every else found
                # `ALL:` on a bare short word is how a comment, a CSS class and a
                # variable name all end up containing `{t('…')}`. Measured the hard
                # way on "werk" and "Nulpunt". A repeated literal must carry its
                # markup delimiters so it can only match a text node.
                if every and len(needle) < 14 and not (
                    needle.startswith('>') or needle.startswith('\n') or needle.startswith('"')
                ):
                    sys.exit(
                        f'{relative}: ALL:{needle!r} is too short to match safely — '
                        'give it its delimiters (>…<) or list each occurrence'
                    )
                if needle not in text:
                    sys.exit(f'{relative}: not found → {needle[:70]!r}')
                count = text.count(needle)
                if count > 1 and not every:
                    sys.exit(f'{relative}: {needle[:50]!r} occurs {count}× — use ALL: if that is right')
                text = text.replace(needle, replacement(needle, key), -1 if every else 1)
            english.append((key, en))
            dutch.append((key, nl))
            total += 1
        path.write_text(text)
        add_to_catalogue('en', section, english)
        add_to_catalogue('nl', section, dutch)
    print(f'{total} strings moved to the catalogue')


def replacement(found: str, key: str) -> str:
    """What takes the place of the literal, judged by its shape."""
    call = f"t('{key}')"
    stripped = found.strip()
    # An attribute with a quoted value: title="…" → title={t('…')}
    attribute = re.match(r'^([a-zA-Z-]+)="([^"]*)"$', stripped)
    if attribute:
        return f'{attribute.group(1)}={{{call}}}'
    # A quoted string in the script: 'Save' → t('foo.save')
    if (stripped.startswith("'") and stripped.endswith("'")) or (
        stripped.startswith('"') and stripped.endswith('"')
    ):
        return call
    # A text node given with its delimiters, e.g. `>Save<`: keep them, or the
    # element loses its bracket and the markup breaks in a way that is hard to
    # trace back to this script.
    lead = '>' if found.startswith('>') else ''
    tail = '<' if found.endswith('<') else ''
    if lead or tail:
        return f'{lead}{{{call}}}{tail}'
    # Anything else is a text node, whitespace and all.
    keep_before = found[: len(found) - len(found.lstrip())]
    keep_after = found[len(found.rstrip()) :]
    return f'{keep_before}{{{call}}}{keep_after}'


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit('usage: i-apply.py <plan.py>')
    namespace: dict = {}
    exec(pathlib.Path(sys.argv[1]).read_text(), namespace)
    apply(namespace['PLAN'])
