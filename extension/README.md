# Robber Advisor: Chrome side panel

Shows the local advisor page (`python -m catan_ai.cli.advisor`) in Chrome's side panel, so it
sits next to whatever tab you have open.

On colonist.io pages it copies the game messages your browser sends and receives (decoded
from MessagePack) and passes them only to the advisor on `http://127.0.0.1:8765`, which saves
them to `runs/advisor/captures/<date>.jsonl`. This is done with colonist.io's written
permission (2026-11-12) to read the state of the user's own games and to train Robber on them.
It never sends anything to colonist.io and never changes a message. If the advisor is not
running, nothing is kept. Captures contain other players' usernames and chat: they stay on
this computer (`runs/` is not committed).

## Install (developer mode)

1. Start the advisor: `uv run python -m catan_ai.cli.advisor`
2. Open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked** and pick
   this `extension` folder.
3. Click the Robber Advisor toolbar button to open the side panel.
