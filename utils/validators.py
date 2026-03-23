"""Sanity checks for poker data."""
from typing import Any, Dict, List, Tuple

MAX_STACK = 10000
MAX_POT = 50000
MIN_BLIND = 0.01


def validate_stack(value: Any) -> Tuple[bool, List[str]]:
    """
    Validate a player stack value.

    A valid stack is a positive number in the range (0, MAX_STACK].

    Parameters
    ----------
    value : Any
        The stack value to validate (will be coerced to float).

    Returns
    -------
    tuple[bool, list[str]]
        (True, []) if valid; (False, [error_message, ...]) otherwise.
    """
    errors = []
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False, [f"Stack is not a number: {value!r}"]
    if v <= 0:
        errors.append(f"Stack must be > 0, got {v}")
    if v > MAX_STACK:
        errors.append(f"Stack must be <= {MAX_STACK}, got {v}")
    return len(errors) == 0, errors


def validate_pot(value: Any) -> Tuple[bool, List[str]]:
    errors = []
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False, [f"Pot is not a number: {value!r}"]
    if v < 0:
        errors.append(f"Pot must be >= 0, got {v}")
    if v > MAX_POT:
        errors.append(f"Pot must be <= {MAX_POT}, got {v}")
    return len(errors) == 0, errors


def validate_blinds(sb: Any, bb: Any) -> Tuple[bool, List[str]]:
    errors = []
    for name, val in [("SB", sb), ("BB", bb)]:
        try:
            v = float(val)
        except (TypeError, ValueError):
            errors.append(f"{name} is not a number: {val!r}")
            continue
        if v < MIN_BLIND:
            errors.append(f"{name} must be >= {MIN_BLIND}, got {v}")
        if v > MAX_STACK:
            errors.append(f"{name} must be <= {MAX_STACK}, got {v}")
    return len(errors) == 0, errors


def validate_player_count(count: Any) -> Tuple[bool, List[str]]:
    errors = []
    try:
        v = int(count)
    except (TypeError, ValueError):
        return False, [f"Player count is not an integer: {count!r}"]
    if v < 2:
        errors.append(f"Player count must be >= 2, got {v}")
    if v > 9:
        errors.append(f"Player count must be <= 9, got {v}")
    return len(errors) == 0, errors


def validate_hand_data(hand_data: Dict) -> Tuple[bool, List[str]]:
    errors = []
    if not isinstance(hand_data, dict):
        return False, ["hand_data must be a dict"]
    if "pot" in hand_data and hand_data["pot"] is not None:
        ok, errs = validate_pot(hand_data["pot"])
        errors.extend(errs)
    has_sb = "small_blind" in hand_data and hand_data["small_blind"] is not None
    has_bb = "big_blind" in hand_data and hand_data["big_blind"] is not None
    if has_sb and has_bb:
        ok, errs = validate_blinds(hand_data["small_blind"], hand_data["big_blind"])
        errors.extend(errs)
    if "player_count" in hand_data and hand_data["player_count"]:
        ok, errs = validate_player_count(hand_data["player_count"])
        errors.extend(errs)
    for player in hand_data.get("players", []):
        if "stack" in player and player["stack"] is not None:
            ok, errs = validate_stack(player["stack"])
            errors.extend([f"Player {player.get('seat','?')}: {e}" for e in errs])
    return len(errors) == 0, errors
