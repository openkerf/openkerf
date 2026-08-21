# The material library

The library is where you keep what your own laser does to your own material: a speed
and a power per material and per thickness, with the photo of the test grid they came
off. It is the difference between working out 3 mm birch again every time and tapping
it once.

This page covers what a setting is worth, how you find one and put it on a layer, where
its numbers came from, why a setting belongs to one machine, and how you move a whole
library to another computer or take settings from other people.

## What a setting is, and what it is not

A setting — the library calls the rows "settings" — is a statement about one laser on
one material at one thickness for one operation: cut, engrave (vector), engrave (raster)
or mark. It holds a speed in mm/s, a power in per cent, the number of passes, the line
spacing for rastering, air assist, and a note. It also holds where it came from and
which machine it was made on, because that is what decides how far you may trust it.

Two things in OpenKerf look like settings and are not.

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

> Without a material the library shows everything and the preflight cannot see whether a setting belongs to this sheet.

With a material but no settings for it:

> No settings in the library for this material yet. A test grid is the shortest way there.

Leaving it empty is allowed. An offcut of unknown origin should not need a name and a
number before you can work.

## Finding a setting

The tool rail on the left opens the window **Material library**. Materials are the list
on the left, with the number of settings behind each name; the settings for the material
you pick are on the right, thin to thick, and within a thickness the measured ones first.

![The Material library window. On the left a list of materials with a count behind each name; at the top a search field and New material; above the list two narrowing controls and an Apply to dropdown reading "Layer 1 · Outline". On the right, under the heading RECENTLY USED, two setting rows: 3 mm Acrylaat (geëxtrudeerd) · Cut at 30 mm/s and 80% with a grey Manual badge, and 3 mm Testmateriaal 204350 · Cut at 15 mm/s and 80% with a green Verified badge, each with an Apply button and a three-dot menu.](images/14-library.png)

Two checkboxes narrow the list, and both are starting points rather than walls:
**Only {machine}** shows the settings of the laser that is switched on now, and
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

and a **Clear the search** button. A material with no settings yet says

> No settings for {material} yet. A test grid burns a series of squares on this material; from the best square you make a setting that ends up here.

and a thickness filter with nothing behind it says *No setting for {thickness} mm. Pick
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

## Applying a setting to a layer

At the top right of the window, **Apply to** names the layer the setting will land on —
**Layer {n} · {label}** — with a dropdown when there is more than one. Every row then
has an **Apply** button that puts the speed and the power on that layer.

OpenKerf does not stop you putting a cut setting on an engrave layer, but it does say
so. The row grows a small tag **other kind**, with the reason in its tooltip:

> These are values for {operation}; layer {n} is a {layerKind} layer

and the Apply button's own tooltip changes to *Careful: these are values for
{operation}, and layer {n} is not meant for that*. Sometimes you know better; 12 mm/s at
65% simply does something very different from 250 mm/s at 20%, and that should not be a
surprise on material.

**When it goes wrong.** With no layers in the project there is nothing to apply to. The
window says once, not on every row:

> There is no layer to put a setting on yet. Make one in the Layers tab; after that one tap puts the speed and power on it.

and the menu item is greyed out with the reason **Make a layer in the Layers tab first**.
Without a valid token the editing actions are off as well, tooltip **Requires a token**.

## Provenance and evidence

The three-dot button at the end of a row — or a right-click on the row — opens its menu:
**Apply to layer {n}**, **Provenance and evidence**, **Adjust the values**, **Make a
test grid for {material}**, **Share with Presetariat** and **Remove setting**.

**Provenance and evidence** unfolds under the row: **Source**, **Machine**, **Test
grid** with its number and when it was burned, the **Note**, whether **Air assist** was
on, and when it was **Last used**. Beside that, the photo of the grid with the square
these numbers came off ringed, captioned:

> The outline marks the square at row {row}, column {column} — that is where these values come from.

![The Material library with one setting unfolded. The row reads 3 mm Cut, 125 mm/s, 45%, badge Verified. Under it a list: Source — "Verified — burned and judged on a test grid", Machine — KH-5030, Test grid — "#16 · burned last week", Air assist — on. To the right the photo of the burned test board with one square outlined and the caption about row 2, column 2, and a "Share with Presetariat" link. Below it two more settings for the same material.](images/15-library-preset.png)

The circle follows the alignment of the photo. If that alignment was never set, the
caption admits it: *The alignment of this photo has not been set, so the outline is
approximate — align the grid for an exact mark.*

**When it goes wrong.** Three different absences, three different sentences, because
they mean different things.

No photo of a grid that does exist:

> There is no photo of this grid yet. Without a photo there is nothing to read the choice off.

with an **Add a photo** button — a phone beside the machine is fine.

A setting whose badge says measured, but with no grid behind it any more:

> This setting says it was measured, but no test grid hangs off it — because it came from an import, for instance. So the evidence is no longer with it.

And a setting that was never measured at all:

> No test grid: these values were not measured but entered.

with **Make a test grid** beside it.

Removing a setting asks under the row it concerns — *Throw away
{thickness}{operation} of {material}?* — with **Keep** and **Throw away**. When the
setting was measured, the question adds **This one was measured on a test grid.**

## What the pre-flight does with it

Applying a setting leaves a note on that layer of that sheet: which setting, which
material, which thickness, which source, and the numbers as they landed. Before a job,
the layer table in the Job panel has a **Source** column that reads that note back
(the table itself is described in [Burning](job.md#the-layer-table)) —
*measured*, *not measured*, *set by hand*, *extrapolated — not measured*, *from someone
else's machine*.

Two of those entries are not about trust but about the wrong board, and they take
precedence: **other material** and **other thickness**, spelled out under the table as
*This setting is for {material}; this sheet is {material}.* and *This setting is for
{n} mm; this sheet is {n} mm.*

![The Job panel in the pre-flight. Under Estimated time 1:19 and "Material — not filled in for this sheet" sits a table of three layers with their speed, power and passes, and a Source column reading "from someone else's machine", "not measured", "not measured". Below it a warning: "3 layers use settings that were not measured with a test grid. On unknown material: try a scrap first." Under that a checklist headed RUN THROUGH THIS: lid closed, extraction and air assist on, workpiece clamped and flat.](images/12-job-preflight.png)

The summary underneath counts them:

> {n} layers use settings that were not measured with a test grid. On unknown material: try a scrap first.

The note is a snapshot, not a link. Change the speed of that layer by hand and OpenKerf
stops claiming a source for it — no provenance is better than a wrong one. A layer that
does not burn is left out of the count, so the number matches what is about to happen.

## Adding a setting by hand

At the bottom of the window, **Add a setting by hand** opens a small form: material,
operation, thickness, speed and power. It is honest about what that produces:

> Entered by hand means: not measured. This setting therefore gets the "Manual" badge.

Adjusting an existing setting works through **Adjust the values** in its menu: speed,
power, line spacing (for rastering), passes, thickness, note and machine profile.
Material, operation and source stay fixed — those are the identity of the setting, not
values on it. Changing a number does not turn a hand-typed setting into a measured one.

**When it goes wrong.** A material name that is already in use is refused:
*Material '{name}' already exists.*

## Machine profiles and why a setting belongs to one machine

A setting is only reusable if you know which laser made it. That is why the machine
stands apart from the setting, in the panel **Machine profiles ({n})**:

> A setting is only reusable when you know which machine it was made on — which is why the profile stands apart from the setting.

Each profile shows its name, its wattage where known, and what hangs off it in settings
and test grids. A profile you can add yourself takes a **Name**, a **Power** in watts
and a **Lens** in mm.

The library sits beside the engine and does not follow along when a machine is thrown
away. A profile with nothing behind it any more is tagged **no machine**, tooltip
*There is no configured machine (any more) that belongs to this profile*, and an empty
one that is not the active machine gets a **Clear out** button. A profile carrying
settings or test grids is evidence and stays.

This is also what the **Only {machine}** checkbox in the header is narrowing on. Switch
it off to see the settings of your other lasers.

## Moving a library: export and import

At the bottom of the window sits **Exchange the library**:

> One file with your materials, settings, machine profiles and the photos of your test grids — for a backup or another computer.

**Export the library** downloads that one file. **Import a library…** takes one back in
and accepts a `.openkerf-lib` file or a zip.

Nothing happens on the way in until you have seen what it would do. The whole window is
taken over by **This is what is going to happen**: the file name, when it was exported,
what is in it (materials, settings, machine profiles, test grids, photos) and, beside it,
*Your library now: … · … · …* so those numbers are a ratio and not five loose figures.

Then two choices, side by side, each with its consequence:

- **Merge** — *What you have stays; what is not there yet is added.*
- **Replace** — *Your current library goes away and becomes this file.*

Under **Merge** you get the tally in advance: new materials by name, how many were
recognised, how many settings would be added, how many are identical, which test grids
come along **with the photos that belong to them**, and which machine profiles are new.
If there is nothing to do it says so: *Nothing is added: this file is already entirely
in your library.*

### Same board, different name

"Birch plywood" and "plywood, birch" are one board, and merging them for you would be a
guess with someone else's numbers on your material. So OpenKerf points it out instead,
under **Same board, different name?**:

> These materials from the file look like something you already have. Merging puts their settings with the material you already know; leave it and you get two.

Each proposal is a tick box — **Merge {name} with {match}** — with the reason why they
look alike. Ticking one recomputes the tallies above, so the numbers keep up with your
choices.

### When two settings clash

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
or *Library replaced*, with how many settings were added, updated or left unchanged, and
how many test grids came along.

**When it goes wrong.** "4 settings added" while the screen does not change is a riddle,
not reassurance, so OpenKerf checks whether what arrived is actually visible and adds:

> Some of it belongs to another machine; switch off "Only {machine}" to see it.

With an empty library **Export the library** is off, tooltip *There is nothing to export
yet*.

## Presetariat — settings other people shared

The tool rail also opens **Presetariat**, the shared catalogue. It is a different kind
of thing from your own library and says so at the top:

> Settings other people shared. They come from someone else's machine: take them as a starting point, not as truth. What was measured with a test grid is at the top.

You filter it by machine profile (or **All machines**), by operation (or **All**) and by
material name, and **Refresh** fetches the catalogue again. Each row shows the material,
the thickness and operation, the wattage and type of the laser it came off, the speed,
power and passes, and how much confidence it deserves: **Measured**, **Manufacturer** or
**Starting value**. A setting that a second person burned again carries **Re-burned**;
one you already have carries **In the library** and cannot be ticked twice.

Where a whole list shares one kind, the warning is said once above it rather than on
twenty-six identical rows — for example *Everything below is starting value: not
measured. Burn a test grid before you trust it.*

Tick what you want and **Import {n}** puts it in your library. It always lands with the
**Imported** badge, never as measured: it was not burned on your machine. The result
line says *{n} imported.*, or *{n} imported, {skipped} skipped (you had them already).*

Going the other way, **Share with Presetariat** in a setting's menu offers one of your
own to the catalogue. It opens a pre-filled proposal in a new tab so you can see for
yourself what you are sharing.

**When it goes wrong.** The catalogue lives on the internet. Without it you get what was
fetched last time, with the reason on screen: *From the local copy — the catalogue was
unreachable.* Filters that match nothing say *Nothing found for this machine and these
filters.* A failed share says *Sharing did not work.*
