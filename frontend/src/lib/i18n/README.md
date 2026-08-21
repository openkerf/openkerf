# Languages

OpenKerf is written in English and translated from there. This directory holds
the machinery and the catalogues; this file says how to add a language, and what
the rules are that keep the catalogues honest.

## Adding a language

Four steps, and the type checker walks you through three of them.

1. **Copy the catalogue.** `cp en.ts de.ts`, then translate every value. Leave
   the keys exactly as they are — they are the addresses, not the text.
2. **Type it.** Change the first line to `import type { Catalogue } from
   './core';` and declare `export const de: Catalogue = { … }`. From that moment
   `svelte-check` tells you about every key you have not translated yet, and
   about every key that no longer exists.
3. **Register it** in `core.ts`: import the file, add it to `CATALOGUES`, and add
   a row to `LANGUAGES` with the language named **in its own language** —
   "Deutsch", not "German". Somebody looking for their language is not reading
   the one they cannot read.
4. **Run the tests**: `node --test frontend/tests/i18n.test.ts`. They check key
   parity, placeholders, plurals, and that the translation is not still the
   English.

That is all. There is no build step and no extraction tool: the catalogue is a
TypeScript object, and the compiler is the extraction tool.

## What a message looks like

```ts
'job.startNow': 'Start now',
'job.pass': 'pass {n} of {total}',
'panel.empties': {
    one: 'One layer is empty.',
    other: '{n} layers are empty.'
},
```

- `{name}` placeholders are filled by `t('key', { name: value })`. A name that is
  not supplied stays visible as `{name}` — loudly wrong rather than quietly
  missing.
- A message with `one` / `other` is chosen by `params.n`.

## The rules, and why

**A message is a whole sentence.** Never glue two of them together in the markup
to make one sentence. Word order is not a constant across languages, and the two
halves cannot be reordered once the markup owns the join. If a sentence changes
with a condition, that is two messages, not one message plus a fragment. The
tests refuse a message that is a bare conjunction or that starts or ends with a
space, because both are signs of glue.

Punctuation between two whole messages is fine: `{label} — {tail}` in the markup
holds a dash, not a word.

**Keys are semantic, not the English text.** `job.phase.queued.title`, not
`'In the queue'`. Rewording the English then costs one line in `en.ts` instead of
a rename across the app, and a translator can see where a message lives.

**Two plural forms.** English and Dutch both have exactly two, so that is what
the runtime supports. A language with more (Polish, Russian, Arabic) needs
`Intl.PluralRules` in `core.ts` — this note is here so nobody discovers that on
the day they add it.

**Numbers and dates do not go in the catalogue.** `i18n.number()`, `i18n.mm()`,
`i18n.ago()` and `i18n.dateTime()` go through `Intl`. Dutch writes 3,5 mm and
English 3.5 mm, and a laser user reads those numbers off the screen and types
them into a machine.

## The two modules

`core.ts` is plain TypeScript: the catalogues, the lookup, the `Intl` helpers. It
holds no runes, so `api.ts` — which puts messages on screen and whose tests run
under plain `node --test` — can import it.

`index.svelte.ts` is the reactive shell: the one rune that says which language we
are in, and `bindLanguage` handing `core` a getter for it. Because `t()` calls
that getter while a component renders, Svelte sees the dependency and re-renders
on a switch. Components import `t` from here; plain modules import it from
`core`.

## The engine layer

`api/openkerf_api` speaks English — it is the core, and its messages also reach
curl, scripts and logs. Refusals a user can act on carry a code as well:

```python
raise DesignError("A sheet needs a name.", code="sheet.needsName")
```

The code travels in the `X-OpenKerf-Error` header, and `apiError()` in `core.ts`
prefers a matching `api.sheet.needsName` from the catalogue over the English
sentence. A refusal whose message carries numbers keeps its own sentence: the
numbers do not travel in the header, and a translated sentence without them says
less than the English one with them.

`tests/i18n.test.ts` checks that every `api.*` key still answers to a `code=`
that exists in the Python.

## Looking

Two scripts under `frontend/gauntlet/`, both against a running dev server:

```
node gauntlet/i-shots.mjs en      # twelve screens, per language
node gauntlet/i-overflow.mjs nl   # every element whose text is wider than its box
```

The screenshots are for judging; the overflow measurement is for the cases an
ellipsis hides, because an ellipsis looks deliberate. Elements the design asks to
clip — a layer name, a job name — are listed in the script and reported
separately, so a real regression does not hide among them.
