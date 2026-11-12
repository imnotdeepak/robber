import pytest

from catan_ai.advisor import Table
from catan_ai.arena.agents import RandomTraderAgent
from catan_ai.engine import ActionKind, CanonicalAction, IllegalActionError
from catan_ai.models import HeuristicPolicyValue, PolicyAgent
from catan_ai.observations import Referee


def follow(seed: int, viewer: int, steps: int, traders: bool = False) -> tuple[Referee, Table, int]:
    """Play a real game; tell a Table only what `viewer` saw; compare after every action."""
    real = Referee.new_game(seed)
    table = Table(real.observe(viewer).board, viewer, seed=seed)
    agents = [
        RandomTraderAgent(f"{seed}:{s}")
        if traders
        else PolicyAgent(HeuristicPolicyValue(), seed=f"{seed}:{s}")
        for s in range(4)
    ]
    played = 0
    while not real.adapter.is_over and played < steps:
        seat = real.adapter.current_seat
        action = agents[seat].decide(real.observe(seat))
        real.execute(action)
        _, outcome = real.action_log[-1]
        table.apply(action, outcome if table.needs_outcome(action) else None)
        if not real.adapter.is_over:  # the end reveals the winner's hidden VP cards
            observed = table.observation()
            assert observed == real.observe(viewer), f"diverged at {played}: {action.key}"
        played += 1
    return real, table, played


@pytest.mark.parametrize("seed,viewer", [(1, 0), (2, 1), (3, 2), (4, 3), (101, 1), (114, 2)])
def test_table_matches_the_viewers_real_observation(seed: int, viewer: int) -> None:
    _, _, played = follow(seed, viewer, steps=3000)
    assert played > 200


def test_table_matches_with_domestic_trades() -> None:
    follow(11, 0, steps=1500, traders=True)


def test_impossible_actions_are_rejected_and_leave_the_table_unchanged() -> None:
    _, table, _ = follow(5, 0, steps=60)
    before = table.observation()
    count = len(table.steps)
    bogus = CanonicalAction(ActionKind.BUILD_CITY, table.deciding, (999,))
    with pytest.raises(IllegalActionError):
        table.apply(bogus)
    assert len(table.steps) == count and table.observation() == before


def test_undo_restores_the_previous_observation() -> None:
    _, table, _ = follow(6, 1, steps=80)
    before = table.observation()
    seat = table.deciding
    action = table.options()[0]
    needed = table.needs_outcome(action)
    outcome = {"dice": (3, 4), "dev_card": "KNIGHT", "stolen_resource": None}.get(needed or "")
    try:
        table.apply(action, outcome)
    except (IllegalActionError, ValueError):
        return
    assert seat == action.seat
    table.undo()
    assert table.observation() == before


def test_outcomes_the_user_saw_are_required() -> None:
    real = Referee.new_game(7)
    table = Table(real.observe(0).board, 0, seed=7)
    while table.adapter.prompt != "PLAY_TURN" or table.adapter.is_initial_build_phase:
        action = PolicyAgent(HeuristicPolicyValue()).decide(real.observe(real.adapter.current_seat))
        real.execute(action)
        table.apply(action)
    roll = CanonicalAction(ActionKind.ROLL, table.deciding)
    with pytest.raises(ValueError):
        table.apply(roll)
