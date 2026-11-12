"""Move suggestions for the user's seat at an advisor table."""

import time
from dataclasses import dataclass
from typing import Final

from catan_ai.advisor.table import Table
from catan_ai.arena.contestants import load_policy, search_config
from catan_ai.engine import CanonicalAction
from catan_ai.search import SearchAgent

# The strongest setting measured (Release 0.6 follow-up): 8 worlds x 16 turns of search
# over the expert-iteration policy. About 3 s per searched decision on one core.
DEFAULT_CHECKPOINT: Final = "champions/robber-expert-1b.pt"
DEFAULT_BUDGET: Final = "8t16"
SHOWN: Final = 5


@dataclass(frozen=True)
class Candidate:
    action: CanonicalAction
    prior: float  # the policy's probability for this action
    value: float | None  # search's mean P(win) after it; None if not searched


@dataclass(frozen=True)
class Advice:
    action: CanonicalAction
    candidates: tuple[Candidate, ...]  # the policy's top choices, best first
    searched: bool  # whether search was run (otherwise the policy's own pick)
    win_probability: float  # the value head's P(user wins) before the move
    seconds: float


class Advisor:
    """Search Robber, advising one seat. Keep one per table: its belief worlds
    advance with the table's history instead of being rebuilt each time."""

    def __init__(
        self, checkpoint: str = DEFAULT_CHECKPOINT, budget: str = DEFAULT_BUDGET, seed: str = ""
    ) -> None:
        self.checkpoint, self.budget = checkpoint, budget
        self.policy = load_policy(checkpoint)
        self._config = search_config(budget)
        self._seed = seed
        self._agent = SearchAgent(self.policy, self._config, seed=seed)

    def reset(self) -> None:
        """Forget belief worlds (for a new table)."""
        self._agent = SearchAgent(self.policy, self._config, seed=self._seed)

    def advise(self, table: Table) -> Advice:
        observation = table.observation()
        if observation.current_seat != observation.seat or not observation.legal_actions:
            raise ValueError("it is not the user's decision")
        started = time.perf_counter()
        action = self._agent.decide(observation)
        seconds = time.perf_counter() - started
        legal = observation.legal_actions
        priors = self._agent.last_priors or tuple(1.0 if a == action else 0.0 for a in legal)
        scores = self._agent.last_scores
        order = sorted(range(len(legal)), key=lambda i: -priors[i])[:SHOWN]
        chosen = legal.index(action)
        if chosen not in order:
            order = [chosen, *order[: SHOWN - 1]]
        candidates = tuple(Candidate(legal[i], priors[i], scores.get(i)) for i in order)
        evaluation = self.policy.evaluate(observation)
        return Advice(
            action=action,
            candidates=candidates,
            searched=bool(scores),
            win_probability=float(evaluation.win_probabilities[observation.seat]),
            seconds=seconds,
        )
