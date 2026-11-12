"""Local HTTP server for the advisor page (`python -m catan_ai.cli.advisor`).

Binds to 127.0.0.1 only. One table at a time, saved after every change so a
restart can resume it. The page (`web/index.html`) records what happens at the
table and asks for advice. Nothing here contacts any game site: game messages
only arrive from the browser extension.

API (JSON in and out):
- GET  /api/state                  the table as the user sees it
- POST /api/new    {viewer, names, seed, board?}
- POST /api/act    {key, outcome?}  record one action (key from `options`)
- POST /api/trade  {partner, give, receive}  a completed trade by the seat on turn
- POST /api/undo
- POST /api/advise                 search Robber's suggestion for the user
- POST /api/capture  {tab, page, frames}  colonist.io game messages from the extension,
  appended to runs/advisor/captures/<date>.jsonl (the user's own games, read with
  colonist.io's written permission)
"""

import json
import math
import random
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from catan_ai.advisor.describe import CARD_NAMES, RESOURCE_NAMES, Describer, cards
from catan_ai.advisor.suggest import Advisor
from catan_ai.advisor.table import Step, Table
from catan_ai.engine import ActionKind, CanonicalAction, EngineAdapter, IllegalActionError
from catan_ai.engine.actions import RESOURCES
from catan_ai.observations import DEV_CARDS
from catan_ai.observations.firewall import BoardView

WEB = Path(__file__).parent / "web"
SQRT3 = math.sqrt(3)
NODE_OFFSETS = {
    "NORTH": (0.0, -1.0),
    "NORTHEAST": (SQRT3 / 2, -0.5),
    "SOUTHEAST": (SQRT3 / 2, 0.5),
    "SOUTH": (0.0, 1.0),
    "SOUTHWEST": (-SQRT3 / 2, 0.5),
    "NORTHWEST": (-SQRT3 / 2, -0.5),
}
TILE_COUNTS = {"WOOD": 4, "BRICK": 3, "SHEEP": 4, "WHEAT": 4, "ORE": 3, None: 1}


def hex_center(coord: tuple[int, int, int]) -> tuple[float, float]:
    """Pixel centre (unit hex size) of a cube coordinate, pointy-top hexes."""
    x, _, z = coord
    return SQRT3 * (x + z / 2), 1.5 * z


def random_board(seed: int) -> BoardView:
    return _board_of(EngineAdapter.new_game(seed))


def _board_of(adapter: EngineAdapter) -> BoardView:
    from catan_ai.observations import Referee

    return Referee(adapter).observe(0).board


def board_from_json(spec: dict[str, Any]) -> BoardView:
    """A board from the page's editor.

    `tiles` is [{coord, resource, number}], `ports` is [{resource, nodes}].
    """
    tiles = tuple(
        sorted(
            (tuple(t["coord"]), t["resource"], None if t["resource"] is None else int(t["number"]))
            for t in spec["tiles"]
        )
    )
    counts: dict[Any, int] = {}
    for _, resource, number in tiles:
        counts[resource] = counts.get(resource, 0) + 1
        if resource is not None and number not in (2, 3, 4, 5, 6, 8, 9, 10, 11, 12):
            raise ValueError(f"Bad number {number} on a {resource} tile")
    if counts != TILE_COUNTS:
        raise ValueError(f"A standard board has {TILE_COUNTS}; got {counts}")
    desert = next(c for c, r, _ in tiles if r is None)
    ports = tuple(
        sorted(
            ((p["resource"], tuple(sorted(p["nodes"]))) for p in spec["ports"]),
            key=lambda p: str(p[0]),
        )
    )
    merged: dict[Any, list[int]] = {}
    for resource, nodes in ports:
        merged.setdefault(resource, []).extend(nodes)
    grouped = tuple(
        sorted(((r, tuple(sorted(n))) for r, n in merged.items()), key=lambda p: str(p[0]))
    )
    return BoardView(tiles, desert, grouped, (), ())


def action_to_json(action: CanonicalAction) -> dict[str, Any]:
    return {"kind": str(action.kind), "seat": action.seat, "params": action.params}


def action_from_json(data: dict[str, Any]) -> CanonicalAction:
    return CanonicalAction(ActionKind(data["kind"]), int(data["seat"]), _tuplify(data["params"]))


def _tuplify(value: Any) -> Any:
    return tuple(_tuplify(v) for v in value) if isinstance(value, list) else value


class Session:
    """The current table, its advisor and its save file."""

    def __init__(self, save: Path, advisor: Advisor) -> None:
        self.save = save
        self.captures = save.parent / "captures"
        self.captured = 0
        self.last_capture: str | None = None
        self.advisor = advisor
        self.lock = threading.Lock()
        self.table: Table | None = None
        self.names: list[str] = []
        self.last_advice: dict[str, Any] | None = None
        if save.exists():
            self._load()

    # ----- Commands

    def new(self, viewer: int, names: list[str], seed: int, board: dict[str, Any] | None) -> None:
        view = board_from_json(board) if board else random_board(seed)
        self.table = Table(view, viewer, seed=seed)
        self.names = [
            n or ("You" if i == viewer else f"Player {i + 1}") for i, n in enumerate(names)
        ]
        self.advisor.reset()
        self.last_advice = None
        self._store()

    def act(self, key: str, outcome: Any) -> None:
        table = self._table()
        action = next((a for a in table.options() if a.key == key), None)
        if action is None:
            raise ValueError("That action is not available now")
        needed = table.needs_outcome(action)
        if needed == "dice" and outcome is not None:
            outcome = _dice(int(outcome))
        table.apply(action, outcome if needed else None)
        self.last_advice = None
        self._store()

    def trade(self, partner: int, give: list[int], receive: list[int]) -> None:
        table = self._table()
        table.trade(table.adapter.turn_seat, partner, tuple(give), tuple(receive))
        self.last_advice = None
        self._store()

    def undo(self) -> None:
        self._table().undo()
        self.last_advice = None
        self._store()

    def advise(self) -> dict[str, Any]:
        table = self._table()
        advice = self.advisor.advise(table)
        describe = self._describer()
        self.last_advice = {
            "key": advice.action.key,
            "text": describe.action(advice.action),
            "searched": advice.searched,
            "win_probability": advice.win_probability,
            "seconds": advice.seconds,
            "candidates": [
                {
                    "key": c.action.key,
                    "text": describe.action(c.action),
                    "prior": c.prior,
                    "value": c.value,
                    **_place(c.action),
                }
                for c in advice.candidates
            ],
        }
        return self.last_advice

    def capture(self, body: dict[str, Any]) -> dict[str, Any]:
        frames = body.get("frames") or []
        self.captures.mkdir(parents=True, exist_ok=True)
        path = self.captures / f"{time.strftime('%Y-%m-%d')}.jsonl"
        with path.open("a", encoding="utf-8") as out:
            for frame in frames:
                record = {"tab": body.get("tab"), "page": body.get("page"), **frame}
                out.write(json.dumps(record, separators=(",", ":")) + "\n")
        self.captured += len(frames)
        self.last_capture = time.strftime("%H:%M:%S")
        return {"captured": self.captured, "file": str(path)}

    # ----- State

    def state(self) -> dict[str, Any]:
        capture = {"frames": self.captured, "last": self.last_capture}
        if self.table is None:
            return {"table": None, "capture": capture}
        table = self.table
        observation = table.observation()
        describe = self._describer()
        game_map = table.adapter.referee_game.state.board.map
        deciding = table.deciding
        options = [] if table.adapter.is_over else list(table.options())
        return {
            "table": True,
            "viewer": table.viewer,
            "names": self.names,
            "deciding": deciding,
            "turn_seat": observation.turn_seat,
            "prompt": observation.prompt,
            "initial": observation.is_initial_build_phase,
            "turn": observation.num_turns,
            "over": table.adapter.is_over,
            "winner": table.adapter.winner_seat,
            "board": _board_json(observation, game_map),
            "players": [
                {
                    "seat": p.seat,
                    "name": self.names[p.seat],
                    "points": p.visible_victory_points,
                    "cards": p.resource_card_count,
                    "dev_cards": p.dev_card_count,
                    "knights": p.played_dev_cards[DEV_CARDS.index("KNIGHT")],
                    "longest_road": p.longest_road_length,
                    "has_longest_road": p.has_longest_road,
                    "has_largest_army": p.has_largest_army,
                }
                for p in observation.players
            ],
            "hand": {
                RESOURCE_NAMES[r]: n
                for r, n in zip(RESOURCES, observation.own_resources, strict=True)
            },
            "dev_hand": {
                CARD_NAMES[d]: n
                for d, n in zip(DEV_CARDS, observation.own_dev_cards, strict=True)
                if n
            },
            "bank": {
                RESOURCE_NAMES[r]: n
                for r, n in zip(RESOURCES, observation.bank_resources, strict=True)
            },
            "dev_deck": observation.dev_deck_remaining,
            "trade": self._trade_text(observation.pending_trade),
            "options": [
                {
                    "key": a.key,
                    "kind": str(a.kind),
                    "text": describe.action(a),
                    "needs": table.needs_outcome(a),
                    **_place(a),
                }
                for a in options
            ],
            "log": [self._log_line(step, describe) for step in table.steps[-40:]],
            "advice": self.last_advice,
            "advisor": {"checkpoint": self.advisor.checkpoint, "budget": self.advisor.budget},
            "capture": capture,
        }

    def _trade_text(self, trade: Any) -> str | None:
        if trade is None:
            return None
        offer = f"{cards(trade.give)} for {cards(trade.receive)}"
        return f"{self.names[trade.offerer]} offers {offer}"

    def _log_line(self, step: Step, describe: Describer) -> str:
        text = f"{self.names[step.action.seat]}: {describe.action(step.action)}"
        if step.action.kind == ActionKind.ROLL and step.outcome:
            text += f" ({sum(step.outcome)})"
        elif step.action.kind == ActionKind.BUY_DEV_CARD and step.outcome:
            text += f" ({CARD_NAMES[step.outcome]})"
        elif step.action.kind == ActionKind.MOVE_ROBBER and step.outcome:
            text += f" (took {RESOURCE_NAMES[step.outcome]})"
        return text

    def _describer(self) -> Describer:
        return Describer(self._table().adapter.referee_game.state.board.map, self.names)

    def _table(self) -> Table:
        if self.table is None:
            raise ValueError("Start a table first")
        return self.table

    def _store(self) -> None:
        table = self._table()
        board = table.board
        data = {
            "viewer": table.viewer,
            "names": self.names,
            "seed": table.seed,
            "board": {
                "tiles": [{"coord": c, "resource": r, "number": n} for c, r, n in board.tiles],
                "ports": [{"resource": r, "nodes": nodes} for r, nodes in board.ports],
            },
            "steps": [
                {"action": action_to_json(s.action), "outcome": s.outcome} for s in table.steps
            ],
        }
        self.save.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.save.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        for attempt in range(20):  # Windows: a scanner may hold the file for a moment
            try:
                tmp.replace(self.save)
                return
            except PermissionError:
                time.sleep(0.05 * (attempt + 1))
        print(f"warning: could not save {self.save}; it is in {tmp}", flush=True)

    def _load(self) -> None:
        data = json.loads(self.save.read_text(encoding="utf-8"))
        board = _board_view_from_saved(data["board"])
        self.table = Table(board, int(data["viewer"]), seed=int(data["seed"]))
        self.names = list(data["names"])
        for step in data["steps"]:
            outcome = step["outcome"]
            self.table.apply(action_from_json(step["action"]), _tuplify(outcome))


def _board_view_from_saved(spec: dict[str, Any]) -> BoardView:
    tiles = tuple(sorted((tuple(t["coord"]), t["resource"], t["number"]) for t in spec["tiles"]))
    desert = next(c for c, r, _ in tiles if r is None)
    ports = tuple((p["resource"], tuple(p["nodes"])) for p in spec["ports"])
    return BoardView(tiles, desert, ports, (), ())


def _dice(total: int) -> tuple[int, int]:
    """Two dice with the given total (only the total matters in Catan)."""
    if not 2 <= total <= 12:
        raise ValueError("A roll totals 2 to 12")
    first = min(6, total - 1)
    return first, total - first


def _place(action: CanonicalAction) -> dict[str, Any]:
    """Where an action happens on the board, for highlighting."""
    if action.kind in (ActionKind.BUILD_SETTLEMENT, ActionKind.BUILD_CITY):
        return {"node": action.params[0]}
    if action.kind == ActionKind.BUILD_ROAD:
        return {"edge": list(action.params[0])}
    if action.kind == ActionKind.MOVE_ROBBER:
        return {"tile": list(action.params[0])}
    return {}


def _board_json(observation: Any, game_map: Any) -> dict[str, Any]:
    from catanatron.models.tiles import Port

    nodes: dict[int, tuple[float, float]] = {}
    tiles = []
    for coord, tile in game_map.land_tiles.items():
        cx, cy = hex_center(coord)
        tiles.append(
            {
                "coord": list(coord),
                "x": cx,
                "y": cy,
                "resource": None if tile.resource is None else RESOURCE_NAMES[tile.resource],
                "number": tile.number,
                "robber": tuple(coord) == tuple(observation.board.robber),
            }
        )
        for ref, node in tile.nodes.items():
            dx, dy = NODE_OFFSETS[ref.value]
            nodes[node] = (cx + dx, cy + dy)
    ports = []
    for coord, tile in game_map.tiles.items():
        if isinstance(tile, Port):
            cx, cy = hex_center(coord)
            served = [n for n in tile.nodes.values() if n in nodes]
            ports.append(
                {
                    "x": cx,
                    "y": cy,
                    "resource": None if tile.resource is None else RESOURCE_NAMES[tile.resource],
                    "nodes": sorted({n for n in served if _port_node(game_map, n, tile.resource)}),
                }
            )
    return {
        "tiles": tiles,
        "nodes": {str(n): {"x": x, "y": y} for n, (x, y) in nodes.items()},
        "ports": ports,
        "buildings": [{"node": n, "seat": s, "kind": k} for n, s, k in observation.board.buildings],
        "roads": [{"a": a, "b": b, "seat": s} for a, b, s in observation.board.roads],
    }


def _port_node(game_map: Any, node: int, resource: Any) -> bool:
    return node in game_map.port_nodes.get(resource, set())


class Handler(BaseHTTPRequestHandler):
    session: Session

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send_file(WEB / "index.html", "text/html; charset=utf-8")
        elif self.path == "/api/state":
            with self.session.lock:
                self._send_json(self.session.state())
        else:
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if self.path == "/api/capture":  # no table lock: game messages must never wait
            try:
                self._send_json(self.session.capture(json.loads(self.rfile.read(length))))
            except (ValueError, OSError) as error:
                self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            with self.session.lock:
                result = self._command(body)
        except (ValueError, KeyError, IllegalActionError) as error:
            self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        except Exception as error:  # report, never drop the connection
            self._send_json(
                {"error": f"{type(error).__name__}: {error}"}, HTTPStatus.INTERNAL_SERVER_ERROR
            )
            return
        self._send_json(result)

    def _command(self, body: dict[str, Any]) -> dict[str, Any]:
        session = self.session
        if self.path == "/api/new":
            session.new(
                int(body["viewer"]),
                list(body.get("names") or ["", "", "", ""]),
                int(body.get("seed") or random.randrange(10**6)),
                body.get("board"),
            )
        elif self.path == "/api/act":
            session.act(str(body["key"]), body.get("outcome"))
        elif self.path == "/api/trade":
            session.trade(int(body["partner"]), list(body["give"]), list(body["receive"]))
        elif self.path == "/api/undo":
            session.undo()
        elif self.path == "/api/advise":
            session.advise()
        else:
            raise KeyError(f"unknown command {self.path}")
        return session.state()

    def _send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _send_file(self, path: Path, content_type: str) -> None:
        payload = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def serve(session: Session, port: int) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"session": session})
    return ThreadingHTTPServer(("127.0.0.1", port), handler)
