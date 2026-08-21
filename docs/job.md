# Burning: the pre-flight, the run, and the machine

Everything that puts light on material lives on the **Job** tab of the right-hand
panel, and in the transport buttons at the right of the top bar. This page walks
that panel from top to bottom: what the pre-flight shows you before anything
moves, what the two taps that start a job do, what you can see and change while
the machine is burning, and the controls for moving the head when it is not.

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

![The OpenKerf window with the Job tab open on the pre-flight: a small drawing of the sheet with red rectangles, a circle, two dashed grey squares and a green block; below it "Sheet 1 500 × 300 mm", "work 295 × 176 mm", a note that two shapes sit in no layer that burns, "Estimated time 1:19", "Material — not filled in for this sheet", an amber box saying the machine is not responding, a three-row layer table with speed, power, passes and source, an amber note that three layers use unmeasured settings, and the checklist "RUN THROUGH THIS: Lid closed / Extraction and air assist on / Workpiece is clamped and flat". At the bottom of the panel a "Show frame" button beside a green "Start job 1:19".](images/12-job-preflight.png)

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

### The checklist

Three lines under the heading **Run through this**: *Lid closed*, *Extraction and
air assist on*, *Workpiece is clamped and flat*. There is nothing to tick. A
checklist you get used to ticking off protects nobody.

### Nothing to burn

On an empty bed there is no clock, no checklist and no start button — only
**There is nothing to burn** with: "The bed is empty, or everything on it sits in
a layer that does not burn. Draw or import something, give it a layer, and come
back here."

## Starting: two taps, never one

No single click burns anything.

1. **Start job** (with the estimated time in it) arms the pre-flight. Nothing
   goes off the screen.
2. The button pair changes to **Cancel** and **Start now**. **Start now** sends
   the job. While it goes it reads *Working…*.

**Show frame** sits beside **Start job** while the job is not yet armed: it sends
the head round the outline of your work with the laser off. That is the last check
that the work is on the board and the clamp is not in the way. Arming replaces
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
