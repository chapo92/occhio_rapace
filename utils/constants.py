"""888 Poker specific constants."""
PLATFORM = "888poker"
VERSION = "2.0.0"

BLUE_HSV_H_MIN = 100
BLUE_HSV_H_MAX = 140
BLUE_HSV_S_MIN = 30
BLUE_HSV_S_MAX = 255
BLUE_HSV_V_MIN = 30
BLUE_HSV_V_MAX = 255

SHAPE_TOLERANCE = 0.05
COLOR_TOLERANCE = 0.30
TABLE_SHAPES = ["round", "octagonal", "elongated_round"]
POSITIONS_ORDER = ["BTN", "SB", "BB", "UTG", "UTG+1", "CO", "HJ"]
HAND_STAGES = ["preflop", "flop", "turn", "river", "showdown"]
MIN_TABLE_AREA = 50000
MAX_STACK = 10000
MAX_POT = 50000
MIN_BLIND = 0.01



def deep_merge(base: dict, updates: dict) -> dict:
    """Recursively merge *updates* into *base*, modifying *base* in-place."""
    for k, v in updates.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_merge(base[k], v)
        else:
            base[k] = v
    return base
