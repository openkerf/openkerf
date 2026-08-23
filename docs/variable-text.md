# Variable text: one design, many names

Fifty keyrings with fifty different names on them is one drawing and fifty burns. You draw
the tag once, put `{name}` where the name goes, hand OpenKerf a list of names, and then press
one button per plate. That is a **series**: one design, burned once per row of a list.

This page walks the whole of it — the list, the placeholder, the window you set it up in, the
run you work through standing at the machine, and the ways it goes wrong.

## Why you would

The work a laser gets asked for is rarely one of a thing. It is thirty name badges for a
conference, a hundred numbered parts for an assembly, twelve door signs for one building, the
same coaster with a different table number on it. Drawn by hand that is a hundred copies of
one drawing with one field edited, and the mistake it produces is always the same: two plates
with the same name and one name missing, found after the material is cut.

A series takes the repetition out of the drawing and puts it in a list. The drawing stays one
tag. The list is a column of names. Which of them is on the bed right now is a number
OpenKerf keeps, and it keeps it in one place, so the plate the machine burns is the plate the
screen is showing.

Two things you should know before you start, because they shape everything below:

- **One plate per press.** OpenKerf does not run the list unattended. You burn, take the
  plate off, put the next one on, and press again. That is not a limitation waiting to be
  lifted — you have to swap the workpiece anyway, and a laser that carries on burning while
  nobody is watching it is not a thing this app will do.
- **The bed always shows the burn that is next.** Not the first one, not the one you
  imported: the one the machine will make when you press the button. That is the single
  promise this feature has to keep, and [Which burn you are on](#which-burn-you-are-on) says
  how it keeps it.

## The list

The rows come from one of two places, and the choice is at the top of the right-hand half of
the **Series** window, under **Where the rows come from**: **A file** or **Numbers**.

### A file out of a spreadsheet

**Choose a file** takes a `.csv`, `.txt` or `.tsv` off your computer. The hint under it says
what shape it should be: "A spreadsheet saved as CSV, with one column per thing that
changes."

That is the whole of what you have to get right. One column per thing that varies from plate
to plate, and a header row naming them, because those names are what you type between the
curly brackets:

```
name,room
Anna,1.04
Bram,1.05
Cees,2.11
```

What OpenKerf forgives, because your spreadsheet decides most of it and not you:

- **The encoding.** A file saved by a Dutch or German Excel is not UTF-8, and the engine's own
  reader refuses it outright. OpenKerf tries the byte-order mark first, then UTF-8, then
  Windows code page 1252, so `René` and `Größe` come in as themselves.
- **The delimiter.** Commas, semicolons, tabs and vertical bars are all read. Which one it
  used is reported back to you as **Separated by** — "Commas", "Semicolons", "Tabs" or
  "Vertical bars" — beside **Read as**, which names the encoding.
- **A quotation mark in a cell.** A size column reading `5" pipe` imports. So does a cell with
  a comma in it, as long as your spreadsheet quoted it, which every spreadsheet does.
- **A ragged row.** A row with fewer cells than the header has columns is padded out with
  blanks rather than thrown away, and the blank cells are counted for you.

One thing it deliberately does not guess in silence: **whether the first row holds the column
names**. It guesses, shows you the guess, and lets you overrule it. Under **The first rows,
as this app reads them** there is a switch, **The first row**, set to **Column names** or
**Data**, with the guess written out beneath it: "This app read the first row as the column
names. Change it if that row is a value." Set it to Data and the columns are called
`column_1`, `column_2` and so on, and the row you were looking at becomes the first plate.

The whole file is not shown — the first ten rows are, with "{n} more rows follow these."
under them. A list may hold at most 1000 rows and a file at most 5 MB; both are refusals,
and both are in [When it goes wrong](#when-it-goes-wrong).

### A counted range of numbers

For "parts 001 to 250" there is no spreadsheet worth making. Pick **Numbers** and fill in
five fields: **First number**, **Last number**, **Step**, **Digits** and **Column name**.

Digits is the padding: "Digits writes the number that many places wide, so 3 gives 001. A
text reading {number} then takes the next number." Column name is what goes between the
brackets, so with the default the text on your plate reads `{number}`.

Numbers are not a second kind of series. They fill the same rows in and go through the same
button; everything after this point reads the same whichever door you came through. There is
no counter in the design and no counter in the engine, on purpose: a column of numbers does
the same job and you can see it, edit it, and start it halfway.

## Putting a column into a text

A placeholder is a column name in curly brackets, inside an ordinary text on the bed. Place a
text with the **Text** tool, or right-click one you already have and choose **Edit text…**,
and type `{name}` where the name belongs. Literal words around it are fine: `Room {room}`
burns `Room 1.04`.

You do not have to type it. Right-click a text and the menu has **Insert a column** with one
row per column of the list, each labelled with the column's own name; picking one appends its
placeholder to the text. With exactly one column in the list there is no submenu — the row
*is* that column and reads **Insert {column}** — because one option is not a choice.

A second place on the same plate that wants the *next* row uses `{name#+1}`. Third place,
`{name#+2}`, and so on. That is what a sheetful is made of; see [More than one on a
sheet](#more-than-one-on-a-sheet).

`{name#2}` — no plus sign — is different, and rarely what you want: it is row 2, always, on
every plate. Use it for something that is the same on all of them and still comes out of the
list.

**What the panel tells you.** Select a text with a placeholder in it and the panel on the
right shows two lines: the text as you typed it, in quotation marks, and under it what it
comes out as — "For the burn now on the bed this reads “Anna”." Two facts, not one. Without
the first you cannot see which column the tag reads; without the second you cannot see what
is about to be burned.

Which column to put in is a *verb*, so it is in the right-click menu; what the text says now
is a *value*, so it is in the panel. That split is the app's rule and not a whim of this
page — see [Reference](reference.md#right-click-on-a-shape).

## The Series window

**Series** opens from the tool rail on the left, and from the right-click menu on the empty
bed as **Set up a series** — "Attach a list, see what every burn engraves, and choose where
to start". There is no keyboard shortcut; none of the five workspace windows has one.

The window has two halves. On the left, what this list makes. On the right, where the rows
come from and what OpenKerf decided about them.

![The Series window over the canvas. On the left a numbered burn list — 1 Anna, 2 Bram, 3 Cees, 4 Daan, 5 Eva — with a search box above it, the line "This list makes 5 burns out of 5 rows." and the file it came from; burn 1 carries the chip "On the bed". On the right the two-way control for where the rows come from, set to A file rather than Numbers, with "Choose another file" and "Reading names.csv." beside it; the block "The first rows, as this app reads them" with the first row read as Column names, "Separated by Commas", "Read as utf-8" and a five-row preview table of name and room; the table "The columns in this list" giving name with the placeholder {name} and the badge "In use" and room with none; then the tick "Skip a row with an empty cell" and a "Start at row" field reading 1. The window's own body scrolls under an action row that stays put, with "Take the list away" and "Use this list instead" in it.](images/35-series.png)

**On the left: the burns.** One numbered row per burn, in the order they will be made, with
what that burn engraves beside the number. Above them a search box, **Search the names**, for
finding row forty of a hundred, and the count: "This list makes 5 burns out of 5 rows."

Three marks appear on a row: **On the bed** on the one the bed is showing, **Burned** on the
ones a run has already made, and, on a sheetful whose last plate is short, "One place on this
sheet has no row left, so it stays empty."

Clicking a row points the bed at it. Nothing burns from this window — that is deliberate, and
the reason is in [The run](#the-run). Each row also has a **⋯** menu, **More about this
burn**, with two entries: **Show this one on the bed**, and **Burn this one again**, which
un-ticks a burn a run has already made so it comes round again.

**On the right: the list.** Under the file or the numbers sits the preview described above,
and then **The columns in this list**: one row per column, with the column's own name, the
placeholder to type (**In a text**), how many rows are **Empty** in that column, and a badge
**In use** when a text on the bed reads it. That table is the quickest way to find a typo:
a column your drawing never mentions has no badge, and a placeholder your list has no column
for is in the block below.

**Texts that ask for a column this list has not got** is that block, and it exists because
those shapes are invisible. A text reading `{nope}` against a list without that column
renders as nothing, has no size the app can measure, and cannot be clicked on the bed — while
still counting as work in the job. The window says so and offers the way out: "Each of these
burns nothing at all, and cannot be clicked on the bed either — which is why they are listed
here rather than marked on the bed. Give the list a column of that name, or take the shape
away." **Delete the shape** does the second half.

At the foot of the right-hand half, three things and then the button:

- **Skip a row with an empty cell** — on by default. A row with no name in it is a plate with
  a frame and no name, so it is passed over. Switch it off and blank rows burn as blanks.
- **Start at row** — "Which row the first burn takes. The rest follow in the order of the
  file." For the afternoon you are carrying on from.
- **Use this list**, or **Use this list instead** when one is already attached, and **Take
  the list away** beside it.

**When it goes wrong.** While a run is going the list is locked, and the window says so at the
top: "A series is going. Stop it in the Job panel before you change the list." Everything else
still works — you can look, search and point the bed at a row.

## More than one on a sheet

This is the part nobody guesses, so it is worth reading before you cut anything.

You can put twelve tags on one plate. Give the first one `{name}`, the second `{name#+1}`,
the third `{name#+2}`, and so on up to `{name#+11}`. Then **one burn eats twelve rows**, a
list of fifty makes five burns and not fifty, and the window says so in as many words: "This
design takes 12 rows per burn, so one sheetful is that many rows."

### Letting the app lay the plate out

You do not have to place those twelve by hand. Draw the piece once — the outline and the text
that reads the list, grouped or not — and the Series window works out how many fit under **On
one plate**:

> A piece of 110 × 60 mm goes 16 times on this plate: 4 across and 4 down.

Above that sum stands the plate it was measured against — "Sheet 1 is 500 × 300 mm" plus the
material when one is filled in — with the two numbers that make it: **Plate width** and **Plate
height** write straight to the sheet, and **Choose the material** opens the same dialog the top
bar does. The sheet is still the one place those live; this is a second door to it, next to the
sum that depends on them. (The other door is the sheet tab: click the tab you are on and it
opens for editing.)

Two more numbers decide the layout, and both are about the material rather than the list:
**Between the pieces** is the gap where two cuts would otherwise become one, and **Free at the
edge** is the margin where the clamps live. Press **Lay out 16 pieces** and the app moves the piece into the
corner of that margin, copies it across the plate, and gives every copy the next row — copy
two reads `{name#+1}`, copy sixteen `{name#+15}`. It is one undo.

![A plate the app has just laid out: sixteen rounded tags in four rows of four, from the corner
of the margin, each with a different name cut into it — Anna, Bram, Cees, Daan on the first row,
then Eva, Fien, Gijs, Hanna, and so on to Pim. The panel says "32 elements": an outline and a
name for every place.](images/38-series-plate.png)

When the list is longer than the plate holds, the app says what the rest becomes rather than
making more sheets:

> The whole list is 2 plates of this one, and the last of them uses 7 of the places.

Those other plates are **burns of this same plate**, not new sheets — the same material going
back in the machine, counted by the run, with the same marks and the same redo. That is a
decision and not a shortcut: sheets full of copies would put a hundred versions of one drawing
in the document, they could not follow a list that changed afterwards, and a sheet has to name
its rows outright, which would leave the run's count of plates and the sheets' own order
saying two different things about one job.

A few things it refuses, in these words: a piece bigger than the plate ("so not even one
fits", with both measurements in it), a plate that is already laid out ("its pieces read
further down the list than the first row"), a piece that reads nothing from the list, and a
piece that names a fixed row. And it will not lay out a piece that fills the plate on its own:
"Only one of these fits on the plate, so there is nothing to lay out."

Which means the last plate is short. Fifty rows over twelve places leaves the fifth plate with
two names on it and ten places empty. OpenKerf takes those ten shapes out of the job before it
goes to the machine, and says how many: "10 places on this sheet have no row left, so they
stay empty." That removal matters more than it sounds. Left alone, the engine does not leave
an unfilled place blank — it engraves the placeholder, so the ply comes out with the nine
characters `{name#+2}` burned into it. That was measured, and it is the reason this exists.

Two consequences to keep in your head:

- **Blank rows cannot be skipped on a sheetful.** The engine reads the rows for one plate next
  to each other, so it cannot step over one in the middle. The tick is greyed with the reason:
  "This design takes 12 rows per burn, and a sheetful cannot skip a row: the engine reads the
  rows next to each other."
- **Changing the number of places re-partitions the burns.** Add a thirteenth tag halfway
  through and rows fall into different plates than the ones you have already made. A run that
  has started notices, and refuses; see [The run](#the-run).

The other way to fill a plank is to lay the copies out yourself, in the rows and columns you
choose. Select the tag, open
**Generators**, and on the **Repeat** tab tick **Each copy takes the next name from the list**
— then each copy gets the next row rather than a twelfth Anna. That is a drawing operation and
not a series setting; it is on [Shapes, text, images and
generators](shapes-and-generators.md#repeat).

## Which burn you are on

The bed shows the burn that is about to be made. Always — with a run going and without one,
after a page refresh, and after the server has been restarted. Point at row 3 in the window
and every text on the bed re-renders to row 3; the panel line under a selected text changes
with it.

That is the one thing this feature has to be trusted about, so it is worth saying what the
alternative looked like. Before this, the bed showed the name it happened to have rendered
with, the plan substituted again on its own while it was being built, and the spooler moved a
pointer of its own every time a job started. Three answers to one question, and the plate in
your hand was the third. Now the row lives in one place, the register in the engine is written
before every burn and never read back, and what you see is what the head cuts.

Where the number is said, and each of these reads the same one:

- the **On the bed** chip in the burn list;
- the panel line under a selected text, "For the burn now on the bed this reads “Anna”.";
- the heading in the Job panel, "Burn 3 of 5".

One honest exception, and it is the engine's own: `{date}` and `{time}` are not columns. The
engine answers those itself, from the computer's clock, in its own format — `08/23/26`, month
first, whatever language the interface is in. A column *called* `date` cannot fix it, which
is why one is refused; see [What a column may be
called](#what-a-column-may-be-called). If you want a date on the plate in your own order, put
it in a column of the spreadsheet and it becomes ordinary text.

![The bed with a keyring tag on it: a rounded rectangle with a hole and the word Anna engraved in the middle. The name itself is the selected shape, and in the panel on the right the Edit tab shows its size and position, the text quoted as "{name}", and under that the line "For the burn now on the bed this reads “Anna”."](images/36-series-text.png)

## Burning only once

A jig frame is cut once and then holds fifty pieces in turn. So is the pocket the pieces sit
in, and the outline you burn round the plank to find the edge again.

Right-click the shape and choose **Burn only once** — "In a series this shape burns on the
first plate only — a jig frame, or the pockets the pieces sit in". The same row reads **Burn
on every plate** on a shape already marked, so it is one row with two wordings, like the fill
row above it.

Two details worth knowing:

- **"First" means the first plate of this run,** not row one of the list. Start a run at row
  12 and the jig goes on the bed with plate 12, because that is the plate you are making now.
- **The mark belongs to the drawing.** It travels in the project file, it can be set before a
  list is attached, and outside a series it withholds nothing — an ordinary burn cuts a shape
  marked "burn only once" like any other.

## The run

Burning is not done from the Series window. It is done from the **Job** tab, by somebody
standing next to the machine, and the reason is one you will recognise: a second place to
press the button is a second answer to which plate is coming.

With a list attached and nothing going yet, the Job tab carries a block above the ordinary
controls: "A list is attached and it makes 5 burns. Nothing has been burned yet." with "The
first one engraves Anna." under it and one button, **Start the series**. That button sends
nothing to the machine, and its tooltip says so: "This only starts the count of plates.
Nothing goes to the machine until you press Burn this one."

Once it is going, the block is the run.

![The Job tab with a series running. At the top the block headed "Burn 3 of 5" with a "Stop the series" link on its right, the line "This one engraves Cees.", a progress bar with "2 of 5 burns have been made." under it, and the two buttons "Burn this one" and "Burned, next one". Below the block the ordinary pre-flight: the sheet drawing, "Estimated time 0:24", the line "This is the plate now on the bed; the 3 burns still to go take about 1:12 together.", the layer table and the checklist.](images/37-series-run.png)

- The heading counts the plates: "Burn 3 of 5".
- Under it, what this one puts on the material — "This one engraves Cees." — or, on a plate
  whose row is empty, "This one has nothing to put on the material."
- A bar and, in words under it, "2 of 5 burns have been made.", because a bar cannot be read
  out and a colour cannot be counted.
- **Burn this one** sends the plate to the machine and ticks it off. It answers "Burn 3 has
  gone to the machine."
- **Burned, next one** moves on without burning: "This burns nothing. It moves the bed on to
  the next burn that still has to happen." Use it when you have made a plate some other way,
  or want to skip one.
- **Stop the series** ends the count and keeps the list: "The list stays and so does the row;
  only the count of what has been burned goes." Stopping and starting again is therefore not
  a way to resume — starting writes an empty count.

When the last one is done: "Every burn in this list is done, so the series has ended."

**The pre-flight below it counts the afternoon, not the plate.** The clock on the start button
is one plate. Under it, when there is more than one to go, stands the rest: "This is the plate
now on the bed; the 3 burns still to go take about 1:12 together." Both numbers come off the
same estimate, so they cannot disagree with each other. See
[Burning](job.md#time-material-and-zero-point).

### A plate that came out wrong

It happens. The tape lifted, the focus was off, the name was misspelt in the spreadsheet.

Open the Series window, find the row, and take **Burn this one again** from its **⋯** menu.
That un-ticks the burn and points the bed at it. Go back to the Job tab and press **Burn this
one**.

You do not have to do it there and then, and you do not have to remember where you were.
Freeing rows 12 to 14 and burning them puts the pointer back to where the list had got to —
to row 20 and not to row 15 — because "next" means the earliest burn that is not done, and
not the one after this. Nothing is typed and nothing has to be remembered.

Pressing **Burn this one** on a plate the run has already made asks first: "This one has
already been burned. Burning it again means the laser goes over work that is already there —
only do that when the last attempt was spoiled. Confirm to carry on." A second press, on
**Burn this one over again**, goes ahead.

### What stops a run

Three things, and each says which of them it is.

- **The drawing changed.** A run is a count of plates made from *this* drawing, so the run
  block turns amber and the burn button goes off. The reason is one of two sentences, because
  the punishment differs: "The shapes have moved or been altered since this series began, so
  what is already burned belongs to the drawing as it was.", or "A sheet now holds a different
  number of places than when this series began, so the rows fall into other burns than the
  ones already made." Under either: "Stop the series and begin again to burn on with the
  drawing as it is now. What is already burned stays burned."
- **The other run.** A tile run and a series both decide what the next burn is, so neither
  starts under the other. Both directions are refused, and each names the one to stop.
- **Opening a project.** Replacing the drawing while a series is going is refused rather than
  quietly ended, because the count is yours and a click is cheaper than losing it.

The plain **Start job** button in the pre-flight is off during a series too, and so is **Start
now** after arming: pressing either would burn one plate and count nothing. The engine refuses
it as well, so nothing gets round it by coming from another tab.

## A series with print and cut, and not with tiles

**Print and cut goes with a series.** A series changes what a text says; it does not move
anything on the bed. So a plate you have measured with the two-mark alignment burns at the
measured pose, and every plate of the series after it does too — the alignment is applied
while the job is planned, in the same place it always was. A zero point works the same way.
See [Burning](job.md#print-and-cut).

**A tile run does not.** Tiling cuts one design into pieces of a board and keeps a count of
which piece is next; a series keeps a count of which plate is next. Two counts of "what comes
after this" is one too many, and whichever you start second is refused, naming the first. If
you really need both — a poster-sized sheet of numbered parts — burn the tiles of one plate,
stop the tile run, and move the series on by hand.

## When it goes wrong

Every refusal below is what the app actually says, and the four at the top are the ones you
will meet first.

**A placeholder no column fills.** You typed `{naam}` and the column is called `name`, or you
swapped the list for one that does not have it. Refused when you type it and refused again at
the burn: "There is no column called naam in the list, so this text would burn nothing. Take
the placeholder out of the text, or add the column to the list and import it again." This one
is worth a refusal because the failure without it is silent: the shape renders as nothing,
disappears off the bed, and still counts as work in the job — a plate with a frame and no
name, and not a word said.

**A placeholder before there is a list.** "No list is attached, so a text with a placeholder
in it cannot become anything. Attach a list in the Series window, or take the placeholder out
of the text."

**A placeholder counting backwards.** `{name#-1}` looks like it should read the row before
this one. It does not — it reads the list's own bookkeeping and engraves a number out of it.
Refused where you type it: "A placeholder cannot count backwards. It would read the list's own
bookkeeping instead of a row."

**A bracket that is not a placeholder.** There is no way to engrave a curly bracket as a
bracket; the engine treats every one of them as the start of a name. So a stray or doubled
bracket in a text is refused — "A curly bracket has to open and close once around a column
name, and a bracket cannot be burned as a bracket." — and so is a bracket in one of your
cells: "Row 7 has a curly bracket in the column “name”, and a curly bracket cannot be burned
as a bracket. Take it out of the cell."

Reading the file:

- Nothing OpenKerf can decode: "This file is not text this app can read. Save it from your
  spreadsheet as CSV UTF-8 and try again."
- An empty file: "This file is empty. Save your list from the spreadsheet again and check that
  there is something in it."
- Names and nothing under them: "This file has column names but no rows under them."
- Too many rows: "This list has 1200 rows and this app carries at most 1000."
- Too large a file: "This file is larger than 5 MB. A list of names is a few kilobytes; this
  is probably not the file you meant."
- A file you picked before the server was restarted: "That file is no longer on the server.
  Pick it again."

Counting numbers:

- No column name: "A numbered list needs a column name, because that is what goes between the
  curly brackets in the text."
- A step of nothing: "A step of nothing never reaches the last number. Count in ones, or in
  whatever step the parts really go up by."
- A range that makes nothing: "Counting from 250 to 1 in steps of 1 makes no rows at all. Turn
  the step around, or swap the two ends."
- Silly padding: "A number written 20 digits wide is not a part number. Use 0 for no padding,
  or up to 12."

Attaching and starting:

- "This list has no rows in it, so there is nothing to burn."
- A column the design reads that is blank all the way down: "Every row is missing a value in
  name, so there is nothing to burn. Fill the column in, or switch off skipping blank rows."
- Nothing on the bed reads the list, so every plate would be identical: "None of the text on
  the bed comes from the list, so every burn would be the same. Put a column into a text
  first."
- Every row skipped: "Every row in this list is missing a value the design needs, so with
  blank rows skipped there is nothing to burn. Switch off skipping blank rows, or fill the
  list in."
- Starting past the end: "This list has 5 rows, so it cannot start at row 40."
- Starting a second one: "A series is already going. Stop it first — starting another one
  would throw away which plates have been burned."

While it runs:

- The plain Burn button: "A series is going, so this button would burn one plate and count
  nothing. Press Burn this one instead: that is the button that counts the plates."
- Changing the list: "A series is going. Stop it before you change the list, otherwise what
  has been burned no longer matches what is left."
- Opening a project: "A series is going. Stop it before you replace the drawing, because the
  plates you have already burned belong to the design that would go."
- A tile run: "A series is going, and a series and a tile run both decide what the next burn
  is. Finish or stop the series first." And the other way round: "A tile run is going, and a
  tile run and a series both decide what the next burn is. Finish or stop one of the two."
- Burning with nothing going: "There is no series going."
- A row the run has no burn for: "There is no burn for row 51 in this series."

And one that comes back from a project file rather than from you: "The list in this project
file cannot be read, so the project has opened without it. Import the list again from your
spreadsheet."

## What a column may be called

Three rules, and all three are refused at import rather than discovered on material.

**Not a name the engine keeps.** `date`, `time`, `version`, and anything beginning with `op_`
belong to the engine. It answers them itself before it ever looks at your list, so a column
of that name would be accepted and then silently ignored. "A column cannot be called date,
time or version, or begin with op_ — the engine keeps those names. Rename the column in your
file and import it again." A column that is already in your list under such a name is marked
in the columns table with the badge **Kept name** and the reason: "The engine keeps this name
for itself, so this column can never be read. Rename it in your file and import it again."

**No curly brackets in the name.** "A column name cannot contain a curly bracket, because that
is what marks a placeholder. Rename the column in your file."

**Case does not distinguish two columns.** The engine folds every name to lower case, so
`Name` and `name` are one column to it. Your own spelling is what the window shows and what
the menu offers; only the matching is case-blind.

## What this cannot do yet

Said plainly, because the alternative is finding out on material.

- **Nobody has burned a series on real hardware.** Everything on this page is measured against
  the engine, the cut plan and the cutcode the spooler is handed — which is as far as a
  computer without a laser goes. Fifty plates is fifty jobs and therefore fifty handshakes on
  a connection this handbook already describes as unpredictable, so make the first one **four
  rows on scrap**, watch the connection, and only then put customer stock in the machine.
- **One plate per press, by design.** There is no unattended chaining and no queue of fifty.
- **Burn order across pieces is not optimised.** One job per row means the pieces burn in row
  order, which is what you want when you press stop — whole pieces done and a known row to
  resume from — but the engine no longer reorders travel across them. What the machine's own
  within-layer ordering does with a scattered sheetful has not been measured.
- **OpenKerf does not lay fifty pieces out on a plank for you.** Repeat with **Each copy takes
  the next name from the list** gives each copy the next row and you place them, which is also
  the only way to lay tags around a knot in the wood.
- **The window is a desktop window.** It stacks on a narrow screen and it works, but the phone
  view has no Series window at all. The run block in the Job panel is the part you need
  standing at the machine, and that one is built for a small screen.
- **A project file carries the list.** Mailing a project mails the names in it, which is what
  makes a project openable at the other end — and worth remembering when the names are
  somebody's customers. What does not travel is the run: the receiver gets the list, not your
  half-finished afternoon.
