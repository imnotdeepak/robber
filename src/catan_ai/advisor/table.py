"""A live game followed from one seat, for the advisor (plan §13 follow-up).

The advisor never sees the real game engine: it is told what happens at the
table, one canonical action at a time, with the outcomes its user can see
(dice, the user's own development-card draws, steals the user took part in).
`Table` replays that record in a shadow engine game on the same board, so the
user's observation, legal actions and history come from the same firewall
(`catan_ai.observations.Referee`) that every agent plays through.

Two kinds of outcome are hidden from the user and must still be chosen for
the shadow game to run:

- **Opponents' development-card draws.** A draw is chosen to cover a card that
  seat plays later in the record, if any; otherwise at random from the deck.
- **Steals between two other seats.** A card is drawn at random from the
  victim's shadow hand.

A later action can contradict a choice: a seat spends a card the shadow says it
does not hold, or plays a card it was not dealt. The record is then replayed
from the start, keeping earlier choices where they still work and changing as
few as possible (`Table._repair`), until it is consistent, or the action is
rejected as impossible. Chosen outcomes never reach the user's observation:
the firewall shows only public facts and the user's own hand, which are exact.
"""

import random
from collections import Counter
from dataclasses import dataclass
from typing import Any, Final

import numpy as np

from catan_ai.beliefs.resources import BeliefError, ResourceBelief, apply_event, initial_belief
from catan_ai.beliefs.worlds import new_game_on
from catan_ai.engine import ActionKind, CanonicalAction, EngineAdapter, IllegalActionError
from catan_ai.engine.actions import RESOURCES, Seat
from catan_ai.observations import DEV_CARDS, PlayerObservation, Referee
from catan_ai.observations.events import VisibleEvent, action_event, snapshot
from catan_ai.observations.firewall import BoardView

REPLAY_ATTEMPTS: Final = 30
PLAYS: Final = {
    ActionKind.PLAY_KNIGHT: "KNIGHT",
    ActionKind.PLAY_YEAR_OF_PLENTY: "YEAR_OF_PLENTY",
    ActionKind.PLAY_MONOPOLY: "MONOPOLY",
    ActionKind.PLAY_ROAD_BUILDING: "ROAD_BUILDING",
}


@dataclass(frozen=True)
class Step:
    """One action at the table and the outcome the user saw (None if hidden or none)."""

    action: CanonicalAction
    outcome: Any = None


class Table:
    def __init__(self, board: BoardView, viewer: Seat, seed: int = 0) -> None:
        self.board = board
        self.viewer = viewer
        self.seed = seed
        self.steps: list[Step] = []
        self.replays = 0  # full replays forced by contradicted hidden choices
        self._referee = Referee(new_game_on(board, seed))
        self._rng = random.Random(seed)
        self._choices: dict[int, Any] = {}  # step index -> hidden outcome chosen

    # ----- Reading

    @property
    def adapter(self) -> EngineAdapter:
        """The shadow game. Opponents' hidden holdings in it are guesses: never show them."""
        return self._referee.adapter

    def observation(self) -> PlayerObservation:
        return self._referee.observe(self.viewer)

    @property
    def deciding(self) -> Seat:
        return self.adapter.current_seat

    def needs_outcome(self, action: CanonicalAction) -> str | None:
        """The outcome the user must supply with `action`: "dice", "dev_card",
        "stolen_resource", or None."""
        if action.kind == ActionKind.ROLL:
            return "dice"
        if action.kind == ActionKind.BUY_DEV_CARD and action.seat == self.viewer:
            return "dev_card"
        if action.kind == ActionKind.MOVE_ROBBER and action.params[1] is not None:
            victim = action.params[1]
            if self.viewer in (action.seat, victim) and self._hand_size(victim) > 0:
                return "stolen_resource"
        return None

    def options(self) -> tuple[CanonicalAction, ...]:
        """Actions the deciding seat could take, judged on public facts only.

        For the user these are the legal actions. For an opponent, whose hand
        the user cannot see, they are the legal actions if that seat held
        plenty of every resource and, when it has held development cards
        since before this turn, of every playable card; so nothing it might
        really do is ruled out by a wrong guess about its hand.
        """
        seat = self.deciding
        if seat == self.viewer or self.adapter.is_over:
            return self.adapter.legal_actions()
        trial = self.adapter.branch(0)
        state = trial.referee_game.state
        for resource in RESOURCES:
            state.player_state[f"P{seat}_{resource}_IN_HAND"] += 10
        if self._held_since_last_turn(seat):
            for card in PLAYS.values():
                state.player_state[f"P{seat}_{card}_IN_HAND"] += 1
                state.player_state[f"P{seat}_{card}_OWNED_AT_START"] = True
        from catanatron.models.actions import generate_playable_actions

        trial.referee_game.playable_actions = generate_playable_actions(state)
        belief = self._belief()
        free = self.adapter.is_initial_build_phase or bool(state.is_road_building)
        return tuple(
            action
            for action in trial.legal_actions()
            if belief is None or _affordable(belief, action, free)
        )

    def _belief(self) -> ResourceBelief | None:
        """The viewer's belief about every hand, from the public record (None if the
        record contradicts it, which should not happen)."""
        belief = initial_belief()
        pending: tuple[int, ...] | None = None
        try:
            for visible in self.observation().history:
                if visible.event_type == ActionKind.OFFER_TRADE:
                    pending = tuple(visible.public["action"]["params"][1])
                belief = apply_event(belief, visible, pending)
        except BeliefError:
            return None
        return belief

    # ----- Recording

    def apply(self, action: CanonicalAction, outcome: Any = None) -> None:
        """Record one action. Raises IllegalActionError, leaving the table unchanged,
        if no choice of hidden outcomes makes the record consistent."""
        needed = self.needs_outcome(action)
        if needed is not None and outcome is None:
            raise ValueError(f"{action.kind} needs the {needed} the user saw")
        if needed is None:
            outcome = None
        step = Step(action, _normalize(action, outcome))
        index = len(self.steps)
        try:
            chosen = self._execute(self._referee, step, self._rng, lookahead=[])
        except _Inconsistent:
            self.steps.append(step)
            if not self._repair(action):
                self.steps.pop()
                self._run(self._choices, soft=False)
                raise IllegalActionError(f"Impossible at this table: {action.key}") from None
            return
        self.steps.append(step)
        if chosen is not None:
            self._choices[index] = chosen

    def trade(
        self, offerer: Seat, partner: Seat, give: tuple[int, ...], receive: tuple[int, ...]
    ) -> None:
        """Record a completed domestic trade: `offerer` (the seat on turn) gave
        `give` to `partner` for `receive` (resource vectors in RESOURCES order)."""
        from catan_ai.engine.actions import offer_trade

        start = len(self.steps)
        try:
            self.apply(offer_trade(offerer, tuple(give), tuple(receive)))  # type: ignore[arg-type]
            while self.adapter.referee_game.state.is_resolving_trade and self.deciding != offerer:
                seat = self.deciding
                kind = ActionKind.ACCEPT_TRADE if seat == partner else ActionKind.REJECT_TRADE
                self.apply(CanonicalAction(kind, seat))
            self.apply(CanonicalAction(ActionKind.CONFIRM_TRADE, offerer, (partner,)))
        except (IllegalActionError, ValueError):
            self._truncate(start)
            raise

    def undo(self) -> Step | None:
        """Remove the last recorded action."""
        if not self.steps:
            return None
        step = self.steps[-1]
        self._truncate(len(self.steps) - 1)
        return step

    # ----- Internals

    def _held_since_last_turn(self, seat: Seat) -> bool:
        """Whether `seat` holds a development card it did not buy this turn (public)."""
        ps = self.adapter.referee_game.state.player_state
        held = sum(int(ps[f"P{seat}_{card}_IN_HAND"]) for card in DEV_CARDS)
        bought = 0
        for step in reversed(self.steps):
            if step.action.kind == ActionKind.END_TURN:
                break
            bought += step.action.seat == seat and step.action.kind == ActionKind.BUY_DEV_CARD
        return held > bought

    def _hand_size(self, seat: Seat) -> int:
        ps = self.adapter.referee_game.state.player_state
        return sum(int(ps[f"P{seat}_{r}_IN_HAND"]) for r in RESOURCES)

    def _truncate(self, length: int) -> None:
        del self.steps[length:]
        self._choices = {i: v for i, v in self._choices.items() if i < length}
        self._run(self._choices, soft=False)

    def _repair(self, action: CanonicalAction) -> bool:
        """Find hidden choices that make the whole record consistent, changing as
        little as possible: first one earlier choice at a time (most recent first,
        choices involving the acting seats first), also swapping a development
        card with another seat's hidden draw (the deck may hold no other copy);
        then fresh random choices."""
        if self._run(self._choices, soft=True):
            return True
        choices = self._choices
        steals = self._steals_from_belief(action)
        if steals is not None and self._run({**choices, **steals}, soft=True):
            return True
        seats = _involved(action)
        order = sorted(
            choices,
            key=lambda i: (not (_involved(self.steps[i].action) & seats), -i),
        )
        for index in order:
            for value in _alternatives(self.steps[index].action):
                if value == choices[index]:
                    continue
                if self._run({**choices, index: value}, soft=True):
                    return True
                if self.steps[index].action.kind != ActionKind.BUY_DEV_CARD:
                    continue
                for other in order:
                    swap = self.steps[other].action.kind == ActionKind.BUY_DEV_CARD
                    if other != index and swap and choices[other] == value:
                        trial = {**choices, index: value, other: choices[index]}
                        if self._run(trial, soft=True):
                            return True
        return any(self._run({}, soft=True, salt=attempt) for attempt in range(REPLAY_ATTEMPTS))

    def _steals_from_belief(self, action: CanonicalAction) -> dict[int, str] | None:
        """Outcomes for every unseen steal so far (and `action`, the last step) that
        fit every public resource change, from the most likely hypothesis of the
        viewer's resource belief (`catan_ai.beliefs.resources`); None if there is none."""
        history = list(self.observation().history)
        event = self._relaxed_event(action)
        if event is not None:
            history.append(event)
        belief = initial_belief()
        pending: tuple[int, ...] | None = None
        try:
            for visible in history:
                if visible.event_type == ActionKind.OFFER_TRADE:
                    pending = tuple(visible.public["action"]["params"][1])
                belief = apply_event(belief, visible, pending)
        except BeliefError:
            return None
        hidden = [
            i
            for i, step in enumerate(self.steps)
            if step.action.kind == ActionKind.MOVE_ROBBER and i in self._choices
        ]
        robbed = event is not None and event.event_type == ActionKind.MOVE_ROBBER
        if robbed and event is not None and "resource_delta" not in event.public:
            hidden.append(len(self.steps) - 1)
        best = int(np.argmax(belief.weights))
        stolen = [RESOURCES[int(r)] for r in belief.steals[best]]
        if len(stolen) != len(hidden):
            return None
        return dict(zip(hidden, stolen, strict=True))

    def _relaxed_event(self, action: CanonicalAction) -> VisibleEvent | None:
        """`action` as the viewer would see it, executed in a copy of the shadow game
        where every seat but the viewer holds plenty, so a wrong guess about their
        hands cannot block it. Public resource changes are exact except for
        Monopoly (it takes whatever the others hold), which gives None."""
        if action.kind == ActionKind.PLAY_MONOPOLY:
            return None
        trial = self.adapter.branch(0)
        state = trial.referee_game.state
        for seat in range(4):
            if seat == self.viewer:
                continue
            for resource in RESOURCES:
                state.player_state[f"P{seat}_{resource}_IN_HAND"] += 10
        from catanatron.models.actions import generate_playable_actions

        trial.referee_game.playable_actions = generate_playable_actions(state)
        outcome: Any = self.steps[-1].outcome if self.steps else None
        deck = state.development_listdeck
        if action.kind == ActionKind.BUY_DEV_CARD and outcome not in deck:
            # Only the card's identity is private; any card left gives the public change.
            outcome = deck[0] if deck else None
        victim = action.params[1] if action.kind == ActionKind.MOVE_ROBBER else None
        if outcome is None and victim is not None and victim != self.viewer:
            outcome = "WOOD"  # private to thief and victim; the viewer is neither
        if not trial.is_legal(action):
            return None
        before = snapshot(state)
        trial.execute(action, outcome)
        made = action_event(0, trial.num_turns, action, outcome, before, snapshot(state))
        return made.visible_to(self.viewer)

    def _run(self, choices: dict[int, Any], soft: bool, salt: int = 0) -> bool:
        """Replay the record into a fresh shadow game, using `choices` for hidden
        outcomes. With `soft`, a missing or impossible choice is made afresh;
        without, it fails (and the table is left as it was)."""
        rng = random.Random(f"{self.seed}:{len(self.steps)}:{salt}")
        referee = Referee(new_game_on(self.board, self.seed))
        made: dict[int, Any] = {}
        try:
            for index, step in enumerate(self.steps):
                fixed = choices.get(index)
                ahead = self.steps[index + 1 :]
                try:
                    chosen = self._execute(referee, step, rng, ahead, fixed=fixed)
                except _Inconsistent:
                    if fixed is None or not soft:
                        raise
                    chosen = self._execute(referee, step, rng, ahead)
                if chosen is not None:
                    made[index] = chosen
        except _Inconsistent:
            if not soft:
                raise AssertionError("the recorded steps were consistent before") from None
            return False
        self._referee, self._rng, self._choices = referee, rng, made
        self.replays += 1
        return True

    def _execute(
        self,
        referee: Referee,
        step: Step,
        rng: random.Random,
        lookahead: list[Step],
        fixed: Any = None,
    ) -> Any:
        """Execute one recorded step; returns the hidden outcome chosen, if any.
        Raises _Inconsistent (with the shadow game unchanged) if it cannot happen."""
        adapter = referee.adapter
        action, outcome = step.action, step.outcome
        state = adapter.referee_game.state
        chosen: Any = None
        if action.kind == ActionKind.BUY_DEV_CARD:
            deck = state.development_listdeck
            if outcome is None:
                outcome = chosen = (
                    fixed
                    if fixed is not None
                    else _hidden_draw(adapter, action.seat, deck, lookahead, rng)
                )
            if outcome not in deck:
                raise _Inconsistent("the drawn card is not left in the deck")
        elif action.kind == ActionKind.MOVE_ROBBER and action.params[1] is not None:
            victim = action.params[1]
            hand = [
                r
                for r in RESOURCES
                for _ in range(int(state.player_state[f"P{victim}_{r}_IN_HAND"]))
            ]
            if outcome is None and hand:
                outcome = chosen = fixed if fixed is not None else rng.choice(hand)
            if outcome is not None and outcome not in hand:
                raise _Inconsistent("the victim does not hold the stolen card")
        if not adapter.is_legal(action):
            raise _Inconsistent(f"illegal here: {action.key}")
        referee.execute(action, outcome)
        return chosen


class _Inconsistent(Exception):
    """The shadow game's hidden choices contradict the record."""


def _normalize(action: CanonicalAction, outcome: Any) -> Any:
    if action.kind == ActionKind.ROLL and outcome is not None:
        dice = tuple(int(d) for d in outcome)
        if len(dice) != 2 or not all(1 <= d <= 6 for d in dice):
            raise ValueError(f"Dice must be two values from 1 to 6, got {outcome!r}")
        return dice
    if action.kind == ActionKind.BUY_DEV_CARD and outcome is not None and outcome not in DEV_CARDS:
        raise ValueError(f"Unknown development card {outcome!r}")
    if action.kind == ActionKind.MOVE_ROBBER and outcome is not None and outcome not in RESOURCES:
        raise ValueError(f"Unknown resource {outcome!r}")
    return outcome


COSTS: Final = {  # in RESOURCES order: wood, brick, sheep, wheat, ore
    ActionKind.BUILD_ROAD: (1, 1, 0, 0, 0),
    ActionKind.BUILD_SETTLEMENT: (1, 1, 1, 1, 0),
    ActionKind.BUILD_CITY: (0, 0, 0, 2, 3),
    ActionKind.BUY_DEV_CARD: (0, 0, 1, 1, 1),
}


def _affordable(belief: ResourceBelief, action: CanonicalAction, free: bool) -> bool:
    """Whether some hand the seat may hold pays for `action`."""
    cost = np.zeros(len(RESOURCES), dtype=np.int16)
    if action.kind in COSTS and not (free and action.kind != ActionKind.BUY_DEV_CARD):
        cost += np.asarray(COSTS[action.kind], dtype=np.int16)
    elif action.kind == ActionKind.MARITIME_TRADE:
        cost[RESOURCES.index(action.params[0])] += action.params[1]
    elif action.kind == ActionKind.DISCARD:
        cost[RESOURCES.index(action.params[0])] += 1
    elif action.kind == ActionKind.OFFER_TRADE:
        cost += np.asarray(action.params[0], dtype=np.int16)
    if not cost.any():
        return True
    return bool(belief.prob_covers(action.seat, cost) > 0)


def _involved(action: CanonicalAction) -> set[Seat]:
    seats = {action.seat}
    if action.kind == ActionKind.MOVE_ROBBER and action.params[1] is not None:
        seats.add(action.params[1])
    return seats


def _alternatives(action: CanonicalAction) -> tuple[str, ...]:
    return DEV_CARDS if action.kind == ActionKind.BUY_DEV_CARD else RESOURCES


def _hidden_draw(
    adapter: EngineAdapter, seat: Seat, deck: list[str], lookahead: list[Step], rng: random.Random
) -> str:
    """An opponent's unseen draw: a card it plays later and does not yet hold, if
    the deck has one; otherwise a random card, keeping back the cards the user is
    recorded as drawing later."""
    if not deck:
        raise _Inconsistent("bought from an empty deck")
    ps = adapter.referee_game.state.player_state
    later = Counter(
        PLAYS[s.action.kind] for s in lookahead if s.action.seat == seat and s.action.kind in PLAYS
    )
    for card, count in later.items():
        if count > int(ps[f"P{seat}_{card}_IN_HAND"]) and card in deck:
            return card
    reserved = Counter(
        s.outcome for s in lookahead if s.action.kind == ActionKind.BUY_DEV_CARD and s.outcome
    )
    left = Counter(deck)
    free = [card for card in deck if left[card] > reserved[card]]
    return str(rng.choice(free or deck))
