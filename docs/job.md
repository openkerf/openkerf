# Burning: the pre-flight, the run, and the machine

Everything that puts light on material lives on the **Job** tab of the right-hand
panel, and in the transport buttons at the right of the top bar. This page walks
that panel from top to bottom: what the pre-flight shows you before anything
moves, the cut path you can walk through before pressing anything, what the two
taps that start a job do, what you can see and change while the machine is
burning, and the controls for moving the head when it is not.

The last section is about the phone view — the screen for somebody who is
standing at the machine rather than at the keyboard.

## Where burning is operated

Three surfaces, and each keeps the same job all the time.

- **The top bar**, on the right: **Pause** / **Resume**, **Stop**, **Start job**
  (**Start** on a narrow bar). These four never move, so the stop button is in
  the same place whether something is running or not. **Show frame** sits with
  them.
- **The Job tab** in the right-hand panel: the pre-flight before, the progress
  during, and the machine controls under both.
- **The status bar** at the bottom: the head position, your pointer position, how
  much time is left, whether the machine is on the line, and whether this page is
  still talking to OpenKerf. It is the same on every tab, so you never have to
  switch tabs to read the progress.

**Start job** does not open a window. It switches the right-hand panel to the Job
tab and arms the pre-flight that was standing there anyway.

## The pre-flight

As long as nothing is in flight, the Job tab is headed **GETTING READY** and
shows the preparation in full. You do not have to press anything to see it, and
it follows your drawing: change a shape and the estimate is worked out again
about half a second later.

![The OpenKerf window with the Job tab open on the pre-flight: a small drawing of the sheet with red rectangles, a circle, two dashed grey squares and a green block; below it "Sheet 1 500 × 300 mm", "work 295 × 176 mm", a note that two shapes sit in no layer that burns, a "Show cut path" button, "Estimated time 1:19", "Material — not filled in for this sheet", an amber box saying the machine is not responding, a three-row layer table with speed, power, passes and source, an amber note that three layers use unmeasured settings, and the checklist "RUN THROUGH THIS: Lid closed / Extraction and air assist on / Workpiece is clamped and flat". At the bottom of the panel a "Show frame" button beside a green "Start job 1:19".](images/12-job-preflight.png)

### The drawing

At the top: what is going to be burned, drawn on the sheet. The sheet is the
plain rectangle; everything beyond its edge is hatched, because there is no
material there. Each shape is drawn in the colour of its layer. A shape in no
burning layer is dotted grey — the machine will skip it.

Tap the drawing to open it large in a window headed **What gets burned**.

Under it are two sizes: the sheet with its measurements, and **work** with the
measurements of everything on it. That second number is the one you hold against
your offcut.

Then, in words, what the picture says. There are three of these, and the order is
deliberate:

- **Outside the bed.** followed by, for one shape, "One shape lies outside the
  reach of the machine, which reaches to 500 × 300 mm. The head does not go
  there: move or scale it." Red, and it is the worst of the three: the machine
  cannot get there at all.
- "One shape falls outside Sheet 1. There is no material there — whatever sticks
  out burns into your honeycomb or your bench." Amber. You lose the workpiece,
  not the machine.
- "One shape sits in no layer that burns — dashed grey above. The machine skips
  it." Grey; a statement, not a warning.

### Time, material and zero point

**Estimated time** is worked out by the engine, which builds the whole cut plan
to get it. While it does, the field reads *calculating…*, and the last known time
stays on the start button so the button does not change width under your cursor.

**Material** shows the material and thickness of the sheet you are burning on, or
*not filled in for this sheet*. The line is always there, because saying nothing
reads as "not needed" — and then you run a birch preset on acrylic.

**Zero point** only appears when one is set, with its coordinates in
millimetres. A zero point moves your work on the bed, and this is the last screen
before it burns.

**When it goes wrong.** If the estimate is slow the panel says: "The engine builds
the whole cut plan to estimate this; on a heavy design that takes a moment.
Starting works regardless — the machine does not wait for it."

### The layer table

One row per layer, with a coloured chip carrying the layer number — the same
number and colour as on the canvas and in the Layers tab. Then the four things a
laser cutter checks before putting material in the machine: **mm/s**, **%**, **×**
(the number of passes) and **Source**.

Source says where those numbers came from, in two words: *measured*, *not
measured*, *extrapolated — not measured*, *set by hand*, *from someone else's
machine*. If the setting was measured but on a different board, it says *other
material* or *other thickness* instead — because "measured" above a number that
was measured on something else reassures where it should not.

A layer this server cannot carry out shows *does not burn* across the whole row
instead of speed and power.

Under the table, the objections. One line per layer, heaviest first, and when the
top one really outweighs the bottom one it is tagged **First**. Below those, if
any layer's numbers were never measured: "3 layers use settings that were not
measured with a test grid. On unknown material: try a scrap first."

**When it goes wrong.** Raster layers do not burn on this server. The pre-flight
says so before you start: "This server cannot burn raster layers." followed by
'The layer "Logo area" produces nothing — the converter from raster area to laser
lines lives in the wxPython version of the engine. The clock below therefore
counts zero for it. Make it an engrave or cut layer, or burn this job from the
wxPython UI.'

### With a rotary fitted

A rotary changes the shape of what comes out, so it is said out loud on the one
screen you read before burning. Above the start button: "The rotary is on: a chuck
of 80 mm, Y scaled by 1.036." — or, on rollers, "The rotary is on: 251.3 mm round,
Y scaled by 1.036." And if the work is taller than the object is round, a second
line: "The work is 300 mm tall and once round is 251.3 mm, so the end burns over
the beginning."

Everything about setting one up, calibrating it and the order to do it in is on
its own page: [The rotary](rotary.md).

### The checklist

Three lines under the heading **Run through this**: *Lid closed*, *Extraction and
air assist on*, *Workpiece is clamped and flat*. There is nothing to tick. A
checklist you get used to ticking off protects nobody.

### Nothing to burn

On an empty bed there is no clock, no checklist and no start button — only
**There is nothing to burn** with: "The bed is empty, or everything on it sits in
a layer that does not burn. Draw or import something, give it a layer, and come
back here."

## The cut path

The pre-flight says *what* burns. The cut path says *in what order*, *where the
head goes without burning*, and *how the time adds up*. It is a workspace you look
at and compare in, so it opens in a window of its own, headed **Cut path**.

Three ways in, and they are the same window:

- **Show cut path** under the drawing in the pre-flight — the moment you actually
  want it, just before pressing start.
- The same row in the right-click menu on the empty bed, for while you are still
  drawing.
- **⌥P** (Alt+P on Windows and Linux), from anywhere on the bed.

All three carry the same explanation: "See in what order the machine burns, where
the head travels without burning, and how the time builds up".

![The Cut path window. On the bed, a red square with a smaller red square inside it, a second red square to its right, an engraved bar below them, dashed grey lines running from one to the next, and the numbers 1, 2, 3 and 4 — the 1 on the inner square, the 2 on the one around it. The first two are drawn in solid red, the other two faint; a filled dot sits on the left edge of square 2. Under the drawing a Play button, a scrubber at 0:40 of 1:19, the line "The replay runs 4 times faster than the machine.", and four figures: On the clock 1:19, Burning 1,270 mm, Travelling 352.7 mm · 4%, Contours 4.](images/29-cutpath.png)

### What the picture means

The bed is the plain rectangle, the sheet the dashed one — the same two rectangles
the canvas draws, so you can find yourself. Everything else is the job as the
machine has been given it:

- **A contour in its layer colour.** The same colour as on the canvas and in the
  Layers tab, so a third scheme does not have to be learned. Faint is still to
  come; solid is already burned at the moment the scrubber is on.
- **A raster layer as an area,** not as an outline. That is the one distinction
  that decides whether the head sweeps for six minutes or cuts for six seconds,
  and a filled rectangle looks exactly like a cut-out one otherwise.
- **The numbers are the order.** Numbers rather than arrows: an arrow gives a
  direction, and the question is which one comes *first*. A small shape inside a
  large one should be number 1 — if it is not, the part falls out of the sheet
  before its own edge is cut.
- **The dot is the head.** Solid while it burns, hollow while it travels: two
  signals for one state, because on a busy path a colour alone gets lost.

Numbers that would land on top of each other are folded into one: "Numbers that
would cover each other are drawn as one: “7+3” is contour 7 and three more that
start in the same spot. The list below names every contour in order." And past a
certain crowd they are left off altogether: "There are 240 contours, too many to
number on the drawing. Play the path to see the order."

That list is **The order, in words (4 contours)**, folded shut under the figures.
One sentence per contour — "1: Outline, 40 × 40 mm, starting at 60, 60." — with
"walked 3 times" on the end when the layer has passes. It is the only form of the
answer a screen reader can read, and on a crowded drawing it is the readable one
for everybody.

### Travel moves

The dashed grey lines are the head moving with the laser off, from the end of one
contour to the start of the next. The legend calls them "Moving without burning".

They are the reason to open this window at all. Travel costs time and produces
nothing, and the figure to watch is beside the millimetres: **Travelling 352.7 mm ·
4%** — the share of the clock spent not burning. A third of the clock spent
travelling is an ordering problem, and no drawing says that as quickly as one
percentage.

The order itself comes from the engine's own optimisation, not from OpenKerf, and
this window does not change it. What it does is let you see it before the machine
does — and what it shows is the job the spooler is handed, step for step and in the
same order, not a separate drawing that resembles it.

### Playing it back

**Play** runs the head along the path; the scrubber and the clock go with it, and
dragging the scrubber goes anywhere in the job. A replay lasts about twenty
seconds however long the job lasts, and the line under it says by how much that is
cheating: "The replay runs 4 times faster than the machine." — or, on a job of
about twenty seconds, "The replay runs at about the speed of the machine."

### What the clock does and does not promise

Four figures under the drawing: **On the clock**, **Burning** (millimetres with the
laser on), **Travelling** (millimetres and the percentage) and **Contours**.

The order and the travel are exact. The clock is not, and the window says so in
its own words:

> **What this cannot promise.** "The order and the travel are exactly what the
> machine has been given. The clock is the cut plan's own arithmetic, and the
> machine can be slower: the engine mixes its burn model with the pace measured on
> a finished pass, and neither of the two knows how your laser slows down in a
> corner."

It also counts differently from the estimate on the start button, and by more than
a rounding:

> "This clock also counts longer than the estimate on the start button: the plan's
> accounting per step carries the engine's allowance for acceleration and every
> sweep of a raster layer, and the estimate does not. Measured on nine cut squares
> of 30 mm: 2:01 here against 1:51 there, and on one filled area of 60 × 40 mm in a
> raster layer 7:30 here against 0:00 there — the estimate does not see a filled
> area at all."

So the two clocks are put side by side rather than left to be discovered: "On this
design this window says 1:19 and the start button says 1:09." Where they disagree
badly, this one is the one to believe — and a raster layer is where they disagree
badly.

At the foot: "Building this path took 0.01 seconds." Which is the other thing this
window is honest about — it is not free. It builds the whole cut plan, the same
work the estimate does, and on a heavy design that is seconds.

One thing has not been checked against a machine, and it is worth knowing which:
that the head really walks the contours in the order the numbers give. The order
in the window is measured against the cutcode the spooler gets, which is as far as
a computer without a laser can go.

### When it goes wrong

- While it is working: "Working out the path…", and on a big design a second line,
  "This is a big design, so the path takes a while. Starting the job does not wait
  for it." That is not a promise but a design decision: the engine has one cut
  plan, and a job that arrives always wins. Measured at the heaviest design this
  window accepts: a start pressed while it was building answered after two to
  three and a half seconds, and the path usually still finished on its own.
- When a job does take it: "The job itself needed the cut plan, so the path had to
  give way. It comes back on its own."
- With nothing that burns: "Nothing is going to be burned, so there is no path to
  walk."
- Too heavy to walk through beforehand, refused before any work is done: "This
  design is too heavy to walk through beforehand: 8100 segments against a ceiling
  of 8000. Building the path would cost seconds to a minute of work, and the answer
  would run to megabytes.", followed by "Switch a layer off or split the work over
  sheets, and the path appears for what is left."
- A path with more steps than can be drawn at once still gives its totals: "This
  path holds 24000 steps, more than the 20000 this window can draw at once." with
  "The totals are the whole job: 12:30 on the clock and 4200.0 mm of travel."
- With the server away: "The path cannot be fetched while the server is away."
- And if the engine refuses the plan: "The path could not be built. The engine
  said: …"

## Starting: two taps, never one

No single click burns anything.

1. **Start job** (with the estimated time in it) arms the pre-flight. Nothing
   goes off the screen.
2. The button pair changes to **Cancel** and **Start now**. **Start now** sends
   the job. While it goes it reads *Working…*.

**Show frame** sits beside **Start job** while the job is not yet armed: it sends
the head round the outline of your work with the laser off. That is the last check
that the work is on the board and the clamp is not in the way. With a rotary
fitted it means something else, and the button's tooltip says so: "On a rotary the
frame turns the object; the head hardly crosses the bed." Arming replaces
that pair with Cancel and Start now, so from then on the frame button to use is
the one in the top bar, which is always there.

**When it goes wrong.**

- Without a token nothing can be written. The panel then shows a field, **Token
  for write actions**, with "The engine logs the token when the API starts." A
  refused token says **This token is being refused** and "Look in the window the
  engine runs in: that is where the token for this server is printed."
- With the machine silent, starting is still allowed, and the pre-flight says
  what will happen: "The machine is not responding. This job goes into the queue
  and only starts once the connection is there — switch it on or check the cable."
- With no connection to OpenKerf, the start button is off and its tooltip reads
  "No connection to OpenKerf — the command will not arrive".
- Show frame is off when there is nothing to frame; the top bar's tooltip then
  says "Nothing is on the bed, or this machine cannot move", and with the server
  away, "Running the frame has to wait until the server is back."
- The machine itself can refuse the frame: "The frame (295x176 mm from 0,0) falls
  outside the bed of 500x300 mm."
- If a job is already under way the top bar's start button says "A job is already
  under way".

When the job goes out, one flash crosses the bed with the words **Job started**.
That happens once, and only when something really starts.

## While it runs

The heading changes from GETTING READY to **THE JOB**, and the block at the top
is named after the phase, not after the buttons:

| Phase | What it says under it |
|---|---|
| **In the queue** | "The job is ready, but the machine has not picked it up. That normally takes a second; if it stays like this, check the connection." |
| **Burning** | "Stay with it and keep the stop button within reach." |
| **Paused** | "The head is standing still. Resuming carries on where it left off." |
| **Done** | "The work is finished. The engine does not sign a job off, so it stays in the queue until you clear it." |

Under the phase: a bar, the percentage in large figures, the step count
("410 / 577 steps"), the pass ("pass 2 of 3") when there is more than one, and
two times — "1:04 elapsed" on the left and "0:15 left" on the right. The same
remaining time is in the status bar on every tab, next to the total.

Two buttons: **Pause** and, well away from it on the other side of the row,
**Stop**. The distance is on purpose; a bad tap here costs the workpiece. Their
keyboard shortcuts are on the buttons and repeated under them: "Pause and Ctrl + .
work everywhere in the app, as long as this window is in front — outside it a
browser cannot receive keystrokes." (On a Mac, ⌘ + . instead of Ctrl + .)

**Clear queue (2)** appears as soon as there is anything in the queue.

**When it goes wrong.**

- Not every machine has a pause. The button is then off with the note "This
  device has no pause/resume — those commands come from the device service."
- With the server unreachable, the stop button loses its red, and its label
  becomes **Stop on the machine**. Its tooltip: "No connection to OpenKerf — this
  button will not arrive. Stopping is only possible with the emergency stop on the
  machine now."
- A job that is finished but not signed off by the engine sits at 99.8 %. The
  panel shows it as full and as **Done**, and the job stays in the queue until you
  clear it.

### Adjusting while it burns

Some machines can be turned up or down mid-job. When yours can, **Adjust during
the job** appears with a row for **Power** and one for **Speed**, each reading *as
designed* until you touch it, then +10 %, −1 % and so on. Buttons: −10 %, −1 %,
+1 %, +10 % and **Reset**.

The note under it: "This scales what the machine is doing right now. The layer
keeps its own setting — which may come from a preset, and then it is evidence."

**When it goes wrong.** Most machines have no realtime channel for this and the
block is simply absent. Asking anyway is refused with: "This machine cannot adjust
speed and power during a job. The driver has no realtime channel for it; stop the
job, change the layer and start again."

## The queue

Below the job block, **Queue** — but only when there is something to say. Each
job waiting shows its name, its state (**In the queue**, **Busy**, **Paused**,
**Done**), and, once running, **Elapsed**, **Total** and **Passes**. Above the
list: "2 more jobs after this one. They start in this order."

Three kinds of emptiness get three different sentences, because they do not mean
the same thing:

- "Unknown — without a connection we cannot tell what is in the queue. What you
  read here is from just before the silence."
- "This machine reports no queue. Starting works; you just will not see the
  progress."
- Nothing at all — then the block is not there.

At the bottom of the tab, collapsed, sits **Messages from the machine**: "Technical
messages from the engine. Handy when hunting a fault; otherwise you do not need
them." Open it and it lists what the engine reported, or "Nothing reported yet."

## Operate machine

Under everything else, **Operate machine**. It is open when the machine is idle
and folds shut while work is in flight, with the reason beside its title: *— not
during a job*. Folded shut, not gone: a block that disappears is not one you learn
to find again.

**Move** is an inverted T of arrows, laid out like the arrow keys on a keyboard,
with **Home** beside it. On a machine with a Z axis there are two more buttons in
the same pad, **Z ↑** and **Z ↓**, for focusing. Every button follows the **Step
size** below the pad: 0.1 mm, 1 mm, 10 mm or 50 mm.

**Unlock** releases the motors so you can push the head by hand.

### Homing with a rotary in the bed

A chuck stands in the bed exactly where the gantry wants to go, so homing with one
fitted drives the head into it. While the rotary is switched on, **Home** does not
move anything: it opens the question **Home with the rotary fitted?** with
"Homing drives the head across the bed and into the rotary. Only continue if the
rotary is out or the head can reach the corner freely." The buttons say what they
do — **The bed is clear — home** and **Do not home** — rather than OK and Cancel.

The refusal is in the machine and not only in this window, because a second tab, a
phone or a script comes straight past a greyed-out button: "The rotary is switched
on. Homing drives the head over the bed and into the rotary. Take the rotary out
first, or confirm that it is clear."

Jogging in Y is deliberately *not* refused — that turns the workpiece, which is
awkward at worst. See [The rotary](rotary.md#what-changes-on-the-machine).

**Go to a point** is for going somewhere rather than in a direction. **To
origin** sends the head to 0,0 of the bed. Beside it, the positions this machine
remembers, each as a chip with its name and its coordinates — jog to the corner of
your jig once, press **Keep this spot**, type a name, and it is there next
session. The × on a chip forgets it.

**Zero point of the work** is the other half of that. **Zero point here** records
where the head is now as 0,0 for your drawing: "what you draw at 0,0 burns here.
The sheet moves along: the zero point is the corner of the material lying in it."
When one is set, **To zero point** goes there and **Clear** puts it back to the
machine's own zero. With none set the line reads "Off: the work burns at the
coordinates you drew it on."

**When it goes wrong.**

- Everything here is off during a job, with the tooltip "Not possible while a job
  is running". The machine refuses it too, whatever sends the command: "A job is
  running. Stop it first; moving while burning ruins the job."
- With no connection: "No connection to OpenKerf — the head will not move from
  here".
- A machine that reports no position cannot save a spot or a zero point: "This
  machine reports no position, so there is nothing to keep" and "This machine
  reports no position, so no zero point can be set".
- A zero point off the bed is refused: "That point (520,40 mm) lies outside the
  bed of 500x300 mm. The head does not go there."
- More than twelve saved positions: "More than 12 saved positions becomes a list
  you have to search through. Throw one away first."
- A Z axis in the machine profile that the driver cannot drive says so: "This
  profile reports a Z axis, but the driver for this machine has no command to move
  the head. Focusing is done by hand."
- Autofocus is not started from here: "Autofocus is started on the machine
  itself."
- Focus steps are capped: "More than 100 mm at once is not focusing."

## Connect and disconnect

The connection to the laser lives in the status bar at the bottom left, beside
the machine state. It reads one of four things, and only the third one is a
promise:

- **Machine unknown** — this page is not talking to OpenKerf, so nobody can say.
- **Machine not connected** — the engine is running, no machine attached.
- **Connection unknown** — the driver does not say. Hover the text and it explains
  itself: "The engine is running, but this driver does not report whether a machine
  is attached. You will notice on the first job: it stays in the queue if nothing
  is listening."
- **Connected to the laser**.

Beside it, when the driver has a command for it, a button. **Connect** ("Open the
connection to the machine. This moves nothing.") goes straight through.
**Disconnect** asks first: "Disconnect? Reconnecting afterwards does not always
work; sometimes only a restart of the server helps." — with **Disconnect** and
**Leave it**.

That warning is measured, not cautious wording. On a real machine, reconnecting
after a disconnect sometimes works and sometimes does not.

**When it goes wrong.**

- Some drivers open their own connection and have no button: "This device has no
  command to connect. Grbl, for instance, opens its connection itself as soon as
  work goes to it."
- A failed attempt reports what the engine said, or, when it says nothing:
  "Connecting did not work, and the engine does not say why. Is the machine on,
  and is the address in the machine settings right?" — followed by a note that
  something switched or disconnected during the session can leave only a server
  restart as the way back.
- On the far right of the status bar, **OpenKerf live** or **OpenKerf away** — the
  line between this page and the server, which can break on its own.
- If the server restarts while the page is open: "The server has restarted" and
  "This page still shows the design from before the restart; the engine started
  empty. Reload to see what is really there.", with a **Reload** button. The page
  will not reload by itself, because that would throw work away.

## On your telephone

Open OpenKerf on a phone and you get a different screen: no canvas, no tools, no
layers. It monitors and it stops. At the bottom: "You design on the desktop — this
screen keeps an eye on the machine."

The top line never scrolls: a coloured dot, the machine state (**Ready**,
**Busy**, **Paused**, **Alarm**, **Not connected**, or **No connection** when the
server is away) and the machine's name.

What comes below depends on what there is to do.

**While a job runs** the progress is on top: one ring with the percentage inside
it and, under that, either "0:41 left" with "done at 16:52" beside it, or
*paused*, or *pause requested…*. Under the ring the job's name and its step count.
If a camera is linked and switched on you get the camera image with a flat
progress bar under it instead.

**When the machine is idle** you get the bed drawn to scale: the sheet inside it,
the work in its layer colours, and a cross where the head is. Under it **Bed**,
**Head** and **On the bed** ("5 shapes burn, 2 in no layer"), and one line saying
why it is quiet — "Nothing is burning. You start a job on the desktop." Captions
too small to read at this size are left out of the drawing, but never out of the
counts.

**When a burned test grid is waiting for a photo** and the machine is idle, that
goes first, because it is the one job in the whole app you need a phone in your
hand for. The machine state shrinks to a single tappable line, **Nothing is
burning**, with the head position beside it.

![A phone screen. At the top an amber dot with "Not connected" and "KH-5030" on the right. Then the heading "28 TEST GRIDS ARE WAITING FOR A PHOTO" and a list of cards: "Acrylaat (gegoten) 3 mm · engrave" with "4×4 · 100–200 mm/s · 10–20 % · 20 Aug 16:59" and a "Take a photo" button, then similar cards for raster and cut, three Berkentriplex and Gekleurd MDF grids. Fixed at the bottom of the screen a greyed-out "Pause" and a red-outlined "Stop".](images/24-phone.png)

Each card carries the material, the operation, the range the board sweeps and
when it was made. **Take a photo** opens the camera straight away. After the
upload: "Photo saved. You get the preset out of it on the desktop." A grid whose
photo is in but which has not been lined up yet stays in the list, marked "photo
in — align it on the desktop", with **Again** in place of the photo button —
because a half-finished step should not vanish.

Below the list, a collapsed **Notifications** row that says whether the browser
is letting them through, and the question is only asked while something is
actually burning.

### The emergency stop

**Pause** (or **Resume**) and **Stop** are fixed at the bottom of the phone
screen. They never scroll away, however long the list above them gets, and they
are far apart. **Stop** turns fully red only while there is really a job and a
connection.

The pause button says what it has done rather than what it hopes: press it and it
reads **Pausing…**, and the ring says *pause requested…*, because not every driver
reports a pause back. That is a request, not a claim.

**When it goes wrong.** Without a connection to OpenKerf both buttons are off,
and the screen says so instead of leaving you to work it out from two grey
buttons: "No connection — stopping is only possible with the button on the
machine." with a **Try again** button beside it (counting down, "Try again
(automatically in 4 s)"). A red button that looks pressable and arrives nowhere is
the most dangerous thing on this screen — you press it, walk away, and believe it
stopped.
