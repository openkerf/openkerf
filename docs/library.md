# The material library

The library is where you keep what your own laser does to your own material: a speed
and a power per material and per thickness, with the photo of the test grid they came
off. It is the difference between working out 3 mm birch again every time and tapping
it once.

This page covers what a preset is worth, how you find one and put it on a layer, where
its numbers came from, why a preset belongs to one machine, how you rename, merge and
remove what is in the library, how you move a whole library to another computer, and how
you take a starting point from the catalogue other people share.

## What a preset is, and what it is not

A preset — the library calls the rows "presets" — is a statement about one laser on
one material at one thickness for one operation: cut, engrave (vector), engrave (raster)
or mark. It holds a speed in mm/s, a power in per cent, the number of passes, the line
spacing for rastering, air assist, and a note. It also holds where it came from and
which machine it was made on, because that is what decides how far you may trust it.

Two things in OpenKerf look like presets and are not.

The colour memory in the layer panel is one. Each layer colour remembers what you last
did with it on this machine, so the next layer in that colour starts from those numbers.
Under the colour swatches it says so in as many words:

> {values} remembered for this colour on {machine} — a next layer in this colour starts from it. Not a preset: this carries no provenance.

The other is the power and speed slider that appears while a job runs. It scales what
the machine is doing at this moment; the layer keeps its own setting.

## Telling the sheet what is in the machine

The library works best when the sheet knows what it is. In the top bar, beside the
machine, sits the material chip — **Choose material** when nothing is filled in.
It opens the window **Material of this sheet**, which says:

> Applies to {sheet} — {size}. Every sheet keeps its own material, so thin and thick can be in one project.

Pick the material from the list, or use **The material is not in the list** to add one.
Thickness is a row of chips — 1, 2, 3, 4, 5, 6, 8 and 10 mm — plus a field marked
**other** for anything else. Tapping the chip that is already on switches it off again.

Underneath, the window counts what this buys you. With no material:

> Without a material the library shows everything and the preflight cannot see whether a preset belongs to this sheet.

With a material but no presets for it:

> No presets in the library for this material yet. A test grid is the shortest way there.

Leaving it empty is allowed. An offcut of unknown origin should not need a name and a
number before you can work.

## Finding a preset

The tool rail on the left opens the window **Material library**. Materials are the list
on the left, with the number of presets behind each name; the presets for the material
you pick are on the right, thin to thick, and within a thickness the measured ones first.

Above the search field sits one card about the machine you are on — whether it has any
presets at all, and what the shared catalogue could offer it. On a laser that already
carries presets of its own it shrinks to one line. It is described under
[Starting points from the shared catalogue](#starting-points-from-the-shared-catalogue).

![The Material library window. On the left a list of materials with a count behind each name; at the top a search field and New material; above the list two narrowing controls and an Apply to dropdown reading "Layer 1 · Outline". On the right, under the heading RECENTLY USED, two preset rows: 3 mm Acrylaat (geëxtrudeerd) · Cut at 30 mm/s and 80% with a grey Manual badge, and 3 mm Testmateriaal 204350 · Cut at 15 mm/s and 80% with a green Verified badge, each with an Apply button and a three-dot menu.](images/14-library.png)

Two checkboxes narrow the list, and both are starting points rather than walls:
**Only {machine}** shows the presets of the laser that is switched on now, and
**Only {material}** — with the reason **— from this sheet** beside it — jumps to the
material lying in the machine. The material of the current sheet is also marked in the
list on the left with the tag **on the sheet**.

The first row of the material list is **Recently used**: what you burned yesterday is at
the top today. Within one material, when there is more than one thickness, a row of
chips appears — **All thicknesses** and then each thickness the material really has.

The search field, **Search material, thickness or operation**, searches the whole row:
name, thickness, operation, note, machine and the badge word.

**When it goes wrong.** Search that matches nothing gives a way back rather than a dead
end: *Nothing found for "{query}"*, with

> The library holds {materials}. Search on the material name itself — "birch" finds more than "birch 3mm cut".

and a **Clear the search** button. A material with no presets yet says

> No presets for {material} yet. A test grid burns a series of squares on this material; from the best square you make a preset that ends up here.

and a thickness filter with nothing behind it says *No preset for {thickness} mm. Pick
another thickness, or burn a test grid for it.* A brand-new library skips the filters
altogether and shows the invitation **No materials yet** instead, with
**Add the first material**.

## Where the numbers come from

Every row carries one badge, and the badge is the whole point of the library. Its
tooltip spells the meaning out, and where there is risk it adds what to do about it.

| Badge | What it means | What it adds |
| --- | --- | --- |
| **Verified** | Burned and judged on a test grid | — |
| **Manual** | Entered by hand, not measured | — |
| **Extrapolated** | Calculated from another thickness — never burned | Try it on scrap material first; start lower in power. |
| **Imported** | From someone else's machine | Another laser, another result — treat this as a starting value. |

The badge is not just a colour: each kind has its own icon and its own word, so a row
does not lose its warning while you scroll.

## Applying a preset to a layer

At the top right of the window, **Apply to** names the layer the preset will land on —
**Layer {n} · {label}** — with a dropdown when there is more than one. Every row then
has an **Apply** button that puts the speed and the power on that layer.

OpenKerf does not stop you putting a cut preset on an engrave layer, but it does say
so. The row grows a small tag **other kind**, with the reason in its tooltip:

> These are values for {operation}; layer {n} is a {layerKind} layer

and the Apply button's own tooltip changes to *Careful: these are values for
{operation}, and layer {n} is not meant for that*. Sometimes you know better; 12 mm/s at
65% simply does something very different from 250 mm/s at 20%, and that should not be a
surprise on material.

**When it goes wrong.** With no layers in the project there is nothing to apply to. The
window says once, not on every row:

> There is no layer to put a preset on yet. Make one in the Layers tab; after that one tap puts the speed and power on it.

and the menu item is greyed out with the reason **Make a layer in the Layers tab first**.
Without a valid token the editing actions are off as well, tooltip **Requires a token**.

## Provenance and evidence

The three-dot button at the end of a row — or a right-click on the row — opens its menu:
**Apply to layer {n}**, **Provenance and evidence**, **Adjust the values**, **Make a
test grid for {material}**, **Share with Presetariat** and **Remove preset**.

**Provenance and evidence** unfolds under the row: **Source**, **Machine**, **Test
grid** with its number and when it was burned, the **Note**, whether **Air assist** was
on, and when it was **Last used**. Beside that, the photo of the grid with the square
these numbers came off ringed, captioned:

> The outline marks the square at row {row}, column {column} — that is where these values come from.

![The Material library with one preset unfolded. The row reads 3 mm Cut, 125 mm/s, 45%, badge Verified. Under it a list: Source — "Verified — burned and judged on a test grid", Machine — KH-5030, Test grid — "#16 · burned last week", Air assist — on. To the right the photo of the burned test board with one square outlined and the caption about row 2, column 2, and a "Share with Presetariat" link. Below it two more presets for the same material.](images/15-library-preset.png)

The circle follows the alignment of the photo. If that alignment was never set, the
caption admits it: *The alignment of this photo has not been set, so the outline is
approximate — align the grid for an exact mark.*

**When it goes wrong.** Three different absences, three different sentences, because
they mean different things.

No photo of a grid that does exist:

> There is no photo of this grid yet. Without a photo there is nothing to read the choice off.

with an **Add a photo** button — a phone beside the machine is fine.

A preset whose badge says measured, but with no grid behind it any more:

> This preset says it was measured, but no test grid hangs off it — because it came from an import, for instance. So the evidence is no longer with it.

And a preset that was never measured at all:

> No test grid: these values were not measured but entered.

with **Make a test grid** beside it.

A preset that came in on an import carries two more lines in the same fold.
**Measured on** names the laser it was measured on — *CO2 with a glass tube, 80 W* — or, when
the import did not say, *Not recorded. This preset came in on an import that did not say
which laser it was measured on.* **Credit** names whoever wrote the numbers down, because the
catalogue they come from is shared under CC BY and the credit is a condition of the copy, not
a courtesy. Under those sits **Take this import back** — see
[Taking an import back](#taking-an-import-back).

Removing a preset asks under the row it concerns — *Throw away
{thickness}{operation} of {material}?* — with **Keep** and **Throw away**. When the
preset was measured, the question adds **This one was measured on a test grid.**

## What the pre-flight does with it

Applying a preset leaves a note on that layer of that sheet: which preset, which
material, which thickness, which source, and the numbers as they landed. Before a job,
the layer table in the Job panel has a **Source** column that reads that note back
(the table itself is described in [Burning](job.md#the-layer-table)) —
*measured*, *not measured*, *set by hand*, *extrapolated — not measured*, *from someone
else's machine*.

Two of those entries are not about trust but about the wrong board, and they take
precedence: **other material** and **other thickness**, spelled out under the table as
*This preset is for {material}; this sheet is {material}.* and *This preset is for
{n} mm; this sheet is {n} mm.*

![The Job panel in the pre-flight. Under Estimated time 1:19 and "Material — not filled in for this sheet" sits a table of three layers with their speed, power and passes, and a Source column reading "from someone else's machine", "not measured", "not measured". Below it a warning: "3 layers use presets that were not measured with a test grid. On unknown material: try a scrap first." Under that a checklist headed RUN THROUGH THIS: lid closed, extraction and air assist on, workpiece clamped and flat.](images/12-job-preflight.png)

The summary underneath counts them:

> {n} layers use presets that were not measured with a test grid. On unknown material: try a scrap first.

The note is a snapshot, not a link. Change the speed of that layer by hand and OpenKerf
stops claiming a source for it — no provenance is better than a wrong one. A layer that
does not burn is left out of the count, so the number matches what is about to happen.

## Adding a preset by hand

At the bottom of the window, **Add a preset by hand** opens a small form: material,
operation, thickness, speed and power. It is honest about what that produces:

> Entered by hand means: not measured. This preset therefore gets the "Manual" badge.

Adjusting an existing preset works through **Adjust the values** in its menu: speed,
power, line spacing (for rastering), passes, thickness, note and machine profile.
Material, operation and source stay fixed — those are the identity of the preset, not
values on it. Changing a number does not turn a hand-typed preset into a measured one.

**When it goes wrong.** A material name that is already in use is refused. Adding one
says *Material '{name}' already exists.*; renaming one to a name another material has says
*There is already a material of that name. Merge the two instead of giving them the same
name.*, which is the repair rather than the complaint.

## Changing the library itself

A library nobody can tidy fills up. This one held both *Multiplex berken* and
*Berkentriplex* for the same board, because adding a material was for a long time the only
thing you could do to one.

Every material row in the list on the left now carries the same **⋯** the preset rows have,
in the same place, and a right-click on the row opens the same menu. Its rows, in order:

| Row | What it does |
| --- | --- |
| **Show only this material** | The same narrowing as the checkbox in the header |
| **Make a test grid** | Opens the test grid window with this material filled in |
| **Rename this material…** | The name, and the other names it answers to |
| **Merge into another material…** | Moves everything onto another material |
| **Remove this material** | Red, last, and it counts before it acts |

![The material library with the ⋯ menu open on the material row Berkentriplex. The menu shows "Show only this material" and "Make a test grid", then "Rename this material…" and "Merge into another material…", and at the bottom in red "Remove this material". Behind it the whole list of materials, each with the number of presets behind its name, and above the list the search box with "Only KH-5030" unticked so that all twenty are in it. Higher still, the two lines this library really shows: the quiet door into the shared catalogue, and the strip about the four presets and eleven test boards that belong to no machine.](images/40-material-verbs.png)

**Adding one** is at the foot of the list of materials, where you are already looking:
**New material**, which turns into a field in the same place. It used to be a button at the
far right of the search bar that summoned a field at the far left of the window, a thousand
pixels away, so pressing it looked as though nothing had happened.

### Rename

**Rename this material…** opens two fields on the right, under the material's own heading
and above its presets — where you read the name is where you change it. **Name of this
material** is the one on screen. **Also called** is the rest: the names other people use for
the same board, separated by commas.

> Names other people use for the same board, separated by commas. An imported library that calls it by one of these lands on this material instead of making a second one.

That second field is what stops the next import making a duplicate. Escape closes the field
and nothing else; the caret starts in it, so you can type straight away.

A name that another material already has is refused: *There is already a material of that
name. Merge the two instead of giving them the same name.*

### Merge

**Merge into another material…** is the repair for the two names you already have.

> Everything on {material} moves over: the presets, the test boards, the recipes and the photographs. The name stays as a name the other material also answers to, so an import that still uses it lands in the right place.

Pick the target under **Merge into** — the list starts on **— pick a material —** — and press
**Merge**. The name you merged away is kept as an alias on the material you merged into, so
an import or a project that still uses the old name lands in the right place instead of
recreating it.

With only one material in the library the row is greyed out, reason **There is only one
material to merge**. A material cannot be merged into itself: *A material cannot be merged
into itself.*

### Remove, after counting

Removing a material takes its presets, its recipes and its test boards with it, and the
photographs of those boards are files that no database rule can reach. So the question is
asked in the same place, and the counting happens before the question rather than after the
answer:

> {material} carries {what}. Removing the material takes all of that with it, photographs included.

where *{what}* is the tally — *6 presets, 2 test grids, 1 recipe, 2 photos*. A material with
nothing behind it says so instead: **Nothing hangs off {material}, so removing it loses no
work.** And a sheet in your project that names this material is mentioned separately,
because that link is cleared and the sheet stays: *2 sheets name this material; those links
are cleared, the sheets themselves stay.*

The buttons are **Keep it** and, when there is something to lose, **Remove it with
everything on it** — which is the one that says out loud what it does. With nothing hanging
off the material it is simply **Remove**.

> **Why the counting matters.** Measured on a copy of this library, removing
> *Berkentriplex* without a guard took six presets — two of them measured, with their
> photographs — left two test boards without a material and reported nothing but the number
> six.

### Presets that belong to no machine

A preset with no machine on it turns up under every machine, because that is how the query
reads. When there are any, a strip appears at the top of the window with the count —
*4 presets belong to no machine, so they turn up whatever machine you are on.* and, where
there are boards too, *11 test boards belong to no machine either.*

Attaching them is a claim, so it stays a button and never runs by itself:

> Only you know whether these were measured on {machine}. Attaching them says they were.

The button is **Attach these to {machine}**.

## Machine profiles and why a preset belongs to one machine

A preset is only reusable if you know which laser made it. That is why the machine
stands apart from the preset, in the panel **Machine profiles ({n})**:

> A preset is only reusable when you know which machine it was made on — which is why the profile stands apart from the preset.

Each profile shows its name, its wattage where known, and what hangs off it in presets
and test grids. There is no form here for making one up: a profile with a wattage and no
machine behind it is exactly how a phantom called *5030 CO2* — the app's own example name —
came to hold twenty-seven presets for a laser nobody owns.

The profile of the machine you are working on can be described here instead, under **The
laser itself**: **Kind of laser**, **Tube power** in watts and **Lens** in mm. Those are the
same three fields the wizard asks on its **Set up** screen and they write the same place, so
this is the door for anybody who is already past the wizard. What they are for is under
[Starting points from the shared catalogue](#starting-points-from-the-shared-catalogue).

The library sits beside the engine and does not follow along when a machine is thrown
away, and the two ways that can happen now read differently, because the answers differ:

- **machine not here** — *No machine the engine knows about belongs to this profile. Plug
  the laser in, or its presets were wiped.* It may come back.
- **no machine** — *This profile points at no machine at all. Merge it into the machine it
  belongs to.* It will not.

An empty profile that is not the active machine gets a **Clear out** button. A profile
carrying presets or test grids is evidence and stays — but when it points at no machine,
**Merge into {machine}** joins it to the laser you are on:

> Two profiles for one laser: the presets, the boards and the tube power move to {machine}, and this row goes.

That is not offered between two profiles that both have a machine behind them: *Both of
these profiles belong to a machine that exists. Two lasers are not one, and merging them
would file one machine's measurements under the other.*

This is also what the **Only {machine}** checkbox in the header is narrowing on. Switch
it off to see the presets of your other lasers.

## Moving a library: export and import

At the bottom of the window sits **Exchange the library**:

> One file with your materials, presets, machine profiles and the photos of your test grids — for a backup or another computer.

**Export the library** downloads that one file. **Import a library…** takes one back in
and accepts a `.openkerf-lib` file or a zip.

Nothing happens on the way in until you have seen what it would do. The whole window is
taken over by **This is what is going to happen**: the file name, when it was exported,
what is in it (materials, presets, machine profiles, test grids, photos) and, beside it,
*Your library now: … · … · …* so those numbers are a ratio and not five loose figures.

Then two choices, side by side, each with its consequence:

- **Merge** — *What you have stays; what is not there yet is added.*
- **Replace** — *Your current library goes away and becomes this file.*

Under **Merge** you get the tally in advance: new materials by name, how many were
recognised, how many presets would be added, how many are identical, which test grids
come along **with the photos that belong to them**, and which machine profiles are new.
If there is nothing to do it says so: *Nothing is added: this file is already entirely
in your library.*

### Same board, different name

"Birch plywood" and "plywood, birch" are one board, and merging them for you would be a
guess with someone else's numbers on your material. So OpenKerf points it out instead,
under **Same board, different name?**:

> These materials from the file look like something you already have. Merging puts their presets with the material you already know; leave it and you get two.

Each proposal is a tick box — **Merge {name} with {match}** — with the reason why they
look alike. Ticking one recomputes the tallies above, so the numbers keep up with your
choices.

### When two presets clash

Same board, same cut, different numbers. The preview lists them with your values and
theirs side by side, and one choice covers the lot: **Keep my values** or **Take the
ones from the file**.

> Same board, same cut, different numbers. Choose which wins — your own values were measured on your machine.

Keeping your own is the safe rule, and OpenKerf says when the rule beats the evidence:
a clash where their side was burned on a test grid and yours was not is flagged with
*The one from the file was burned on a test grid; yours is {source}.*

### Replace

Replace spells out the damage before you can confirm it, under **This wipes what you
have now**:

> {materials}, {presets} and {grids} disappear, along with the photos that belong to them. That cannot be undone.

Next to that, an offer you can act on without leaving the screen — *Do you want to be
able to get it back?* with **Export it first** — and a tick box you have to set:
**Yes, wipe my library and put this file in its place.** The button then reads **Wipe
and import**.

Afterwards the outcome is reported in the same words as the preview — *Library merged*
or *Library replaced*, with how many presets were added, updated or left unchanged, and
how many test grids came along.

**When it goes wrong.** "4 presets added" while the screen does not change is a riddle,
not reassurance, so OpenKerf checks whether what arrived is actually visible and adds:

> Some of it belongs to another machine; switch off "Only {machine}" to see it.

With an empty library **Export the library** is off, tooltip *There is nothing to export
yet*.

## Starting points from the shared catalogue

The Presetariat is a catalogue of presets other people wrote down. It lives in a public
repository, [openkerf/presetariat](https://github.com/openkerf/presetariat), under the
Creative Commons licence **CC-BY-4.0** — free to use, on the condition that the credit
travels with the numbers. OpenKerf reads a *tagged release* of that repository rather than
whatever is on its main branch, so a row reaches you only after somebody merged it and then
decided it was worth shipping. Twenty-six starting points also travel inside OpenKerf
itself, so the offer works on a laptop with no network and on a day when the repository has
no release yet.

It is not a window and it has no button on the tool rail. It used to be both. Both are
gone: browsing somebody else's speeds adds nothing to a drawing, and a catalogue you
consult once per machine has no business sitting beside Rectangle. What is left is one
card, in two places — at the top of this window, above the search field, and on the last
screen of the machine wizard.

### What the card says

The card is for one moment: a laser has just been described and there is not one preset
for it. Then the heading is

> This machine has no presets yet.

with the machine's name under it and two values read back, **Kind of laser** and **Tube
power**, so you can see what the match is being made on. A value nobody has filled in reads
**not recorded**. Under those, what your library holds for this laser — *Not one of the 20
materials in this library has a preset for it.*, or *3 materials of the 20 in this library
have a preset for it.*

Nothing is fetched while the card sits there. **Show what would suit this laser** is what
goes to the network, and the line beside it says why it waits for you:

> Nothing is fetched until you press this: the shared catalogue lives on the network, and opening a window should not wait for it.

While it is fetching the button stays where it is and reads **Looking…**. Once the list is
up the button is gone and the way back out, **Fold this list up again**, sits at the end of
that line about your own materials — one line rather than a row of its own, which is what
that row was: a control at the far right of an otherwise empty band.

**Not now** puts the card away for good on this machine — the tooltip says so: *Put this
away. It will not be offered again for this machine.*

![The material library with the offer card at the top. The heading reads "This machine has no presets yet."; under it the machine name KH-5030, the values Kind of laser "CO2 with a glass tube" and Tube power 80 W, and the line about the materials in this library. Below that the button "Show what would suit this laser" has been pressed, so at the end of the line about the materials in this library stands "Fold this list up again", and the list is open: the source line naming the shared catalogue, the date this copy was fetched and the CC-BY credit; the sentence that every one of these is a number somebody typed; the count of materials that have a starting point for this laser; and then one block per material — "Berkentriplex" with an "Add these" button and two rows reading "3 mm · Cut", "12 mm/s at 65%" and "3 mm · Engrave (raster)", "350 mm/s at 25%", then "MDF" with its own "Add these" and one row. No row carries a tier mark: every entry in the catalogue today is a starting point, so that is said once in the sentence above rather than badged twenty-six times.](images/39-starter.png)

### When the machine has not said what it is

Without the kind of laser and the tube power nothing can be matched, so the card asks. The
heading is **How powerful is this laser?** when the kind is already filled in from the model
you picked in the wizard, and **What kind of laser is this?** when it is not. The reason is
underneath:

> Without these two OpenKerf cannot tell which presets would suit this laser: a CO2 preset on a diode is not a starting point, and the same percentage on twice the power chars and burns through.

Two fields, **Kind of laser** and **Tube power**, and two buttons. **Save and look** records
them and fetches in one go. **I am not sure** is the other honest answer:

> Not knowing the tube power is a fair answer: then the match is on the kind of laser alone, and every preset offered says so.

Both buttons need the kind. Without it they are greyed out with the reason *Choose the kind
of laser first: without it nothing can be matched, whatever the tube power says.* — because
an unknown kind matches nothing, and a fetch that then reports an empty catalogue would be
lying about the catalogue.

The same two fields are in the wizard, on the **Set up** screen, under **The laser itself**
— see [Getting started](getting-started.md#setting-up-the-machine). Both write the same
place, so filling one in fills the other.

> **This is why a machine that used to see everything now sees nothing.** Before this,
> the match skipped the power test whenever either side was silent, which is how an 80 W
> catalogue came to show all twenty-six of its rows to a machine nobody had described. A
> laser that has not said how strong it is now matches nothing at all until you fill the
> tube power in, or say you are not sure.

### When there are presets, but nothing has been burned

A machine can be full of presets and still have nothing to show for it, because every one
of them came out of a catalogue. Then the heading is

> Nothing has been burned on this machine yet.

with *Its 27 presets came out of a catalogue and not one of them has been burned here.* and
the only answer that helps:

> A preset out of a catalogue is somebody else’s number on somebody else’s laser. One board burned on this one turns it into a measurement of your own.

The button is **Burn a test grid**, not another fetch. On the last screen of the wizard that
sentence stands on its own, because the test grid window is not reachable from there.

### Fetching, one material at a time

The list is grouped by material, with an **Add these** button per material and no button for
all of it. That is deliberate: one bulk tick-list is what put fourteen unwanted materials
into this library, every one of them bound to a machine nobody runs. The tooltip says what
one press does — *Add the presets for {material} to this library, for this machine.*

Each row under a material shows the thickness and the operation, the values as
*16 mm/s at 55%*, and how much it is worth:

| Tag | What it means |
| --- | --- |
| **burned** | Somebody burned a board and read this off it |
| **starting point** | Somebody typed it. Nothing was measured. |
| **power not matched** | One of the two lasers never said how strong it is, so only the kind was compared |

Which rows are on offer at all is decided by the strength of the two tubes, and the band is
deliberately lopsided: up to **twice** your wattage, but no lower than **0.7** of it. A
preset off a stronger laser under-burns, and that costs you a plate. One off a weaker laser
puts the same percentage into more energy than it was measured with, and that is char,
burn-through and flame.

Where every row on offer is a guess, the warning is said once above the list rather than
tagged onto every row:

> Every one of these is a number somebody typed, not one measured off a board. Burn a test grid before you trust one of them.

That is the honest state of the catalogue today: **no preset in it has been measured by
anybody.** All twenty-six are starting points.

When the machine has answered "I am not sure" to the tube power, the same thing happens with
the power tag — said once, above the list: *The tube power of this machine is not recorded,
so these match on the kind of laser alone.*

### Where the rows come from, and who gets the credit

Above the list, one line says which of the two sources you are looking at, and it never
guesses:

- **These starting points ship with OpenKerf itself.** — the set inside the app.
- *From the shared catalogue, copied to this computer on 22 Aug 2026.* — a copy fetched from
  the release.
- **The shared catalogue could not be reached, so these are the starting points that ship
  with OpenKerf itself.** — it tried and failed, and fell back.

A copy older than a month says **This copy is more than a month old.** with a **Fetch a
fresh copy** button beside it. That is a button and not something the app decides for you:
going to the network costs up to ten seconds.

On the same line stands the credit, because CC BY means the credit is a condition of the
copy and not a footnote:

> Shared under {license} by {who}, and the credit travels with them.

The names in it are the handles on the rows themselves — every entry in the catalogue
carries the handle of whoever wrote it down. That handle comes along on the way in: an
imported preset keeps it, and you can read it back in **Provenance and evidence** under
**Credit**. Attribution dropped on the way in cannot be given back afterwards, and nobody
can see that it was dropped.

An entry OpenKerf does not understand is skipped and counted rather than thrown at you:
*2 entries in this catalogue were not understood and have been left out.*

### Taking an import back

Every press of **Add these** is stamped as one import, and every import can be undone. Right
after the press the card says what came in — *4 presets for Berkentriplex came in.* — with
**Take this back** beside it. Later, the same way out is in the provenance fold of any
imported preset: **Take this import back**, with

> Removes every preset that came in with this import, and the materials it brought along that nothing else uses.

Afterwards the window reports both halves — *4 presets removed, with the materials that
came in with them.* and, where a material had to stay, *2 materials stay behind: something
else uses them.*

An import you can undo is not a dump, and that is the whole reason a one-press fetch is
offered at all.

### When there is nothing to offer

A machine with presets it measured itself gets no card — and then, with the old window
gone, there would be no way to the catalogue at all. So one quiet line stays at the top of
this window:

**Look in the shared catalogue**, with *What other people measured on a laser like
{machine}, one material at a time.* beside it. Pressing it opens the same list, with the same
per-material buttons. It is a door and not the offer coming back: nothing is fetched until
you press, and a card you waved away stays away.

### Offering one of your own

**Share with Presetariat** in a preset's menu goes the other way. It opens a panel under
the row, and the panel is the point: what goes into the catalogue is a public claim under
your own name, so you see it before anybody else does. When you press
**Open the proposal on GitHub** it fills in a proposal in a new tab — *It opens a
pre-filled proposal in a new tab, so you can read what you are about to share before
anybody else does.*

**Your handle, once.** Every entry in the catalogue names who offered it, and the panel
asks for that the first time:

> The catalogue is shared under CC BY 4.0, so every entry names who offered it — that is the credit anybody reusing it has to be able to give. It is asked once and kept on this computer.

`@jelle-t`, `jelle-t` and the address of your profile page are all read as the same
handle. It is kept beside the library and not in it, so a library you hand to a colleague
does not offer their presets under your name; afterwards the panel says
*Offered as {by}.* with **Use another handle** beside it. Without a handle there is
nothing to open: the tab would hold a file the catalogue's own checks refuse.

**One of two labels, and never the wrong one.** The first line of the panel says which:

> This goes in as a measurement, read off board {board}.

or

> This goes in as a starting point, not as a measurement.

A measurement needs a board with a name, burned on *this* machine, with an outcome
written down. Anything else is a starting point — a real answer, and the catalogue holds
both — and the panel says which of the reasons applies:

| The line you get | What it means |
|---|---|
| *Nobody read these numbers off a test board, so the catalogue takes them as a considered guess.* | You typed them, or extrapolated them. |
| *These numbers came out of the catalogue itself, from {id}, so they go back as a guess that leans on that entry rather than as evidence.* | An imported preset, adjusted. See below. |
| *The board is still here, but nobody wrote down what came out of the material, and a speed with no outcome beside it is not something anybody else can judge.* | The one question the app cannot answer for you. |
| *The test board behind this preset is gone, and a measurement in the catalogue is followed back to its board.* | The board was removed after the preset was read off it. |
| *This preset is filed under a different laser than the board it was burned on, so for this machine it is a starting point.* | The preset was moved to another machine profile. |

**What came out of the material.** When the board is there and the outcome is not, the
panel asks for it in three fields — **The edge** (*Clean, no charring*, *Lightly charred*
or *Heavily charred*), **Cut through** and **Kerf** — and then this goes in as a
measurement:

> Say how it came out and this goes in as a measurement, with its board behind it. It is kept on the preset, so you are asked once.

It is kept on the preset, so a second offer of the same row asks nothing, and it travels
in an exported library along with the boards and their photographs.

**Nothing that came out of the catalogue goes back in as evidence.** A starting point you
fetched and then adjusted is still somebody else's guess, and moving it onto another
machine profile does not make it a measurement of that machine. Such a preset is offered
as a starting point that names the entry it leans on, whatever else is recorded about it.
Without that rule an 80 W guess, re-parented to a 60 W profile, would arrive in the shared
catalogue as a fresh entry for a laser nobody had ever measured.

It is refused when the machine behind the preset is not described:

> This preset belongs to a machine whose tube power is not recorded, so nobody else can tell whether it applies to theirs.

> This preset belongs to a machine whose kind of laser is not recorded, and a CO2 preset is not a starting point for a diode.

Which is the point: a speed and a power without the tube they were measured on — its
strength and its kind — is not usable by anybody else. Both are filled in under
**Machine profiles** in this window, or at the end of the setup wizard.

### When it goes wrong

The catalogue lives on the internet, and the fallbacks are stacked: the copy on this
computer first, the set inside OpenKerf after that. Only when there is neither does it
refuse:

> The shared catalogue could not be fetched, and there is no earlier copy on this computer.

A file that is not a catalogue at all gives *That file does not look like a preset
catalogue.*, and one written by a newer OpenKerf gives *This catalogue comes from a newer
version of OpenKerf. Update first.* — refused whole rather than half understood.

A laser that has said nothing about itself gets told so by name: *OpenKerf does not know how
powerful {machine} is, so it cannot tell which presets would suit it. Fill in the tube
power, or say you are not sure and see everything for this kind of laser.* And when the kind
is what is missing: *OpenKerf does not know what kind of laser {machine} is. A CO2 preset
on a diode is not a starting point.*

With nothing on offer for this laser the list says so plainly: **The catalogue holds no
starting point for this laser yet.**
