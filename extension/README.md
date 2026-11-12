# Robber Advisor: Chrome side panel

Shows the local advisor page (`python -m catan_ai.cli.advisor`) in Chrome's side panel, so it
sits next to whatever tab you have open.

The extension reads no web pages. It has no content scripts, and its only host permission is
the advisor on `http://127.0.0.1:8765`. Moves are entered by hand in the panel. Reading a live
game from a site (for example colonist.io) is deliberately not implemented: colonist.io's
terms forbid accessing its internal APIs or data structures without written authorization.

## Install (developer mode)

1. Start the advisor: `uv run python -m catan_ai.cli.advisor`
2. Open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked** and pick
   this `extension` folder.
3. Click the Robber Advisor toolbar button to open the side panel.
