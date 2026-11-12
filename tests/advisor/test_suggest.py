from catan_ai.advisor import Table
from catan_ai.advisor.describe import Describer
from catan_ai.advisor.suggest import Advisor
from catan_ai.models import HeuristicPolicyValue, PolicyAgent
from catan_ai.observations import Referee


def test_advice_is_a_legal_move_for_the_user_with_ranked_candidates() -> None:
    real = Referee.new_game(21)
    table = Table(real.observe(2).board, 2, seed=21)
    advisor = Advisor(budget="1t1", seed="t")
    names = ["P1", "P2", "You", "P4"]
    describe = Describer(table.adapter.referee_game.state.board.map, names)
    advised = 0
    agent = PolicyAgent(HeuristicPolicyValue())
    for _ in range(120):
        seat = real.adapter.current_seat
        if seat == 2 and len(table.observation().legal_actions) > 1:
            advice = advisor.advise(table)
            assert advice.action in table.observation().legal_actions
            assert advice.action in [c.action for c in advice.candidates]
            assert 0.0 <= advice.win_probability <= 1.0
            assert all(describe.action(c.action) for c in advice.candidates)
            advised += 1
        action = agent.decide(real.observe(seat))
        real.execute(action)
        _, outcome = real.action_log[-1]
        table.apply(action, outcome if table.needs_outcome(action) else None)
    assert advised >= 3


def test_descriptions_name_places_and_players() -> None:
    real = Referee.new_game(3)
    table = Table(real.observe(0).board, 0, seed=3)
    describe = Describer(table.adapter.referee_game.state.board.map, ["You", "Ann", "Bo", "Cy"])
    texts = [describe.action(a) for a in table.options()]
    assert texts and all(t.startswith("Build a settlement at node ") for t in texts)
    assert any("port" in t for t in texts)
