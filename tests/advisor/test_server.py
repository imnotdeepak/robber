import json
import threading
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from catan_ai.advisor.server import Session, serve
from catan_ai.advisor.suggest import Advisor

ENGINE = {"lumber": "WOOD", "brick": "BRICK", "wool": "SHEEP", "grain": "WHEAT", "ore": "ORE"}


@pytest.fixture(scope="module")
def advisor() -> Advisor:
    return Advisor(budget="1t1", seed="t")


def call(port: int, path: str, body: Any = None) -> Any:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data)
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        return {"status": error.code, **json.loads(error.read())}


def test_a_table_can_be_entered_played_advised_undone_and_resumed(
    tmp_path: Path, advisor: Advisor
) -> None:
    save = tmp_path / "table.json"
    server = serve(Session(save, advisor), 0)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert call(port, "/api/state") == {"table": None}
        state = call(port, "/api/new", {"viewer": 1, "names": ["Ann", "", "Bo", "Cy"], "seed": 4})
        # Re-enter the same board as the page's editor would send it.
        board = {
            "tiles": [
                {"coord": t["coord"], "resource": ENGINE.get(t["resource"]), "number": t["number"]}
                for t in state["board"]["tiles"]
            ],
            "ports": [
                {"resource": ENGINE.get(p["resource"]), "nodes": p["nodes"]}
                for p in state["board"]["ports"]
            ],
        }
        state = call(
            port, "/api/new", {"viewer": 1, "names": state["names"], "seed": 4, "board": board}
        )
        assert state["names"][1] == "You" and len(state["board"]["tiles"]) == 19
        advised = False
        for _ in range(30):
            if state["deciding"] == 1 and not advised:
                state = call(port, "/api/advise", {})
                assert state["advice"]["key"] in {o["key"] for o in state["options"]}
                advised = True
            option = state["options"][0]
            outcome = {"dice": 8, "dev_card": "KNIGHT", "stolen_resource": "ORE"}.get(
                option["needs"]
            )
            state = call(port, "/api/act", {"key": option["key"], "outcome": outcome})
            assert "error" not in state, state
        assert advised and len(state["log"]) == 30
        assert any("(8)" in line for line in state["log"])  # the roll was recorded as 8
        before = state["log"]
        state = call(port, "/api/undo", {})
        assert state["log"] == before[:-1]
        bad = call(port, "/api/act", {"key": "BUILD_CITY:0:(999,)"})
        assert bad["status"] == 400
    finally:
        server.shutdown()
        server.server_close()
    resumed = Session(save, advisor)
    assert resumed.state()["log"] == before[:-1]


def test_the_editor_rejects_a_board_that_is_not_standard(tmp_path: Path, advisor: Advisor) -> None:
    session = Session(tmp_path / "t.json", advisor)
    session.new(0, ["", "", "", ""], 1, None)
    tiles = [
        {"coord": t["coord"], "resource": "WOOD", "number": 6}
        for t in session.state()["board"]["tiles"]
    ]
    with pytest.raises(ValueError):
        session.new(0, ["", "", "", ""], 1, {"tiles": tiles, "ports": []})
