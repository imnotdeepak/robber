"""Plain-language names for actions, places and players at an advisor table."""

from typing import Any

from catan_ai.engine import ActionKind, CanonicalAction
from catan_ai.engine.actions import RESOURCES

RESOURCE_NAMES = {
    "WOOD": "lumber",
    "BRICK": "brick",
    "SHEEP": "wool",
    "WHEAT": "grain",
    "ORE": "ore",
}
CARD_NAMES = {
    "KNIGHT": "Knight",
    "YEAR_OF_PLENTY": "Year of Plenty",
    "MONOPOLY": "Monopoly",
    "ROAD_BUILDING": "Road Building",
    "VICTORY_POINT": "Victory Point",
}


class Describer:
    """Describes actions on one board. `names[seat]` names each player."""

    def __init__(self, catan_map: Any, names: list[str]) -> None:
        self.names = names
        self._tiles: dict[int, list[str]] = {}
        self._tile_at: dict[tuple[int, int, int], str] = {}
        for coord, tile in catan_map.land_tiles.items():
            label = tile_label(tile.resource, tile.number)
            self._tile_at[(coord[0], coord[1], coord[2])] = label
            for node in tile.nodes.values():
                self._tiles.setdefault(node, []).append(label)
        self._port: dict[int, str] = {}
        for resource, nodes in catan_map.port_nodes.items():
            label = "3:1 port" if resource is None else f"2:1 {RESOURCE_NAMES[resource]} port"
            for node in nodes:
                self._port[node] = label

    def node(self, node: int) -> str:
        parts = sorted(self._tiles.get(node, []), key=_by_number)
        if node in self._port:
            parts.append(self._port[node])
        return f"node {node} ({', '.join(parts) or 'coast'})"

    def tile(self, coord: tuple[int, int, int]) -> str:
        return f"the {self._tile_at.get(coord, 'water')} tile"

    def action(self, action: CanonicalAction) -> str:
        kind, p = action.kind, action.params
        if kind == ActionKind.ROLL:
            return "Roll the dice"
        if kind == ActionKind.END_TURN:
            return "End the turn"
        if kind == ActionKind.DISCARD:
            return f"Discard 1 {RESOURCE_NAMES[p[0]]}"
        if kind == ActionKind.MOVE_ROBBER:
            target = f"Move the robber to {self.tile(p[0])}"
            return target if p[1] is None else f"{target} and steal from {self.names[p[1]]}"
        if kind == ActionKind.BUILD_ROAD:
            a, b = p[0]
            return f"Build a road from {self.node(a)} to {self.node(b)}"
        if kind == ActionKind.BUILD_SETTLEMENT:
            return f"Build a settlement at {self.node(p[0])}"
        if kind == ActionKind.BUILD_CITY:
            return f"Upgrade to a city at {self.node(p[0])}"
        if kind == ActionKind.BUY_DEV_CARD:
            return "Buy a development card"
        if kind == ActionKind.PLAY_KNIGHT:
            return "Play a Knight"
        if kind == ActionKind.PLAY_YEAR_OF_PLENTY:
            return "Play Year of Plenty for " + " and ".join(RESOURCE_NAMES[r] for r in p)
        if kind == ActionKind.PLAY_MONOPOLY:
            return f"Play Monopoly on {RESOURCE_NAMES[p[0]]}"
        if kind == ActionKind.PLAY_ROAD_BUILDING:
            return "Play Road Building"
        if kind == ActionKind.MARITIME_TRADE:
            give, count, receive = p
            return (
                f"Trade {count} {RESOURCE_NAMES[give]} with the bank "
                f"for 1 {RESOURCE_NAMES[receive]}"
            )
        if kind == ActionKind.OFFER_TRADE:
            return f"Offer {cards(p[0])} for {cards(p[1])}"
        if kind == ActionKind.ACCEPT_TRADE:
            return "Accept the trade"
        if kind == ActionKind.REJECT_TRADE:
            return "Decline the trade"
        if kind == ActionKind.CONFIRM_TRADE:
            return f"Trade with {self.names[p[0]]}"
        if kind == ActionKind.CANCEL_TRADE:
            return "Cancel the trade"
        return action.key


def tile_label(resource: str | None, number: int | None) -> str:
    return "desert" if resource is None else f"{RESOURCE_NAMES[resource]} {number}"


def cards(vector: tuple[int, ...]) -> str:
    """A resource vector as words, e.g. "2 grain + 1 ore"."""
    parts = [f"{n} {RESOURCE_NAMES[r]}" for r, n in zip(RESOURCES, vector, strict=True) if n]
    return " + ".join(parts) or "nothing"


def _by_number(label: str) -> tuple[int, str]:
    """Best-producing tiles first: 6 and 8, then 5 and 9, and so on."""
    number = label.rsplit(" ", 1)[-1]
    return (abs(7 - int(number)) if number.isdigit() else 9, label)
