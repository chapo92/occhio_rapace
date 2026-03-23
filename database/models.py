"""
Occhi di Falco – SQLAlchemy ORM models for 888 Poker tournament tracking.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


# ---------------------------------------------------------------------------
# Tournament
# ---------------------------------------------------------------------------

class Tournament(Base):
    """Top-level tournament record."""

    __tablename__ = "tournaments"

    tournament_id = Column(String, primary_key=True)
    platform = Column(String, nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime)
    buy_in = Column(Float, nullable=False)
    prize_pool = Column(Float)
    buy_in_currency = Column(String, default="USD")
    format = Column(String)
    game_type = Column(String, default="NLHE")
    initial_stack = Column(Float, nullable=False)
    blind_levels_json = Column("blind_levels", Text)  # JSON stringified
    table_id = Column(String)
    your_starting_position = Column(String)
    final_position = Column(Integer)
    final_stack = Column(Float)
    roi = Column(Float)
    duration_minutes = Column(Integer)
    total_hands_played = Column(Integer)
    notes = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    players = relationship(
        "PlayerInTournament",
        back_populates="tournament",
        cascade="all, delete-orphan",
    )
    hands = relationship(
        "Hand",
        back_populates="tournament",
        cascade="all, delete-orphan",
    )
    statistics = relationship(
        "PlayerStatistics",
        back_populates="tournament",
        cascade="all, delete-orphan",
    )
    bubble_data = relationship(
        "BubbleTracking",
        back_populates="tournament",
        cascade="all, delete-orphan",
        foreign_keys="BubbleTracking.tournament_id",
    )
    blind_level_records = relationship(
        "BlindLevel",
        back_populates="tournament",
        cascade="all, delete-orphan",
    )
    session_metadata = relationship(
        "SessionMetadata",
        back_populates="tournament",
        uselist=False,
        cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------------
# PlayerInTournament
# ---------------------------------------------------------------------------

class PlayerInTournament(Base):
    """A player (or hero) at a specific tournament table."""

    __tablename__ = "players_in_tournament"
    __table_args__ = (UniqueConstraint("tournament_id", "seat_number"),)

    player_id = Column(String, primary_key=True)
    tournament_id = Column(
        String, ForeignKey("tournaments.tournament_id"), nullable=False
    )
    seat_number = Column(Integer, nullable=False)
    starting_position = Column(String)
    starting_stack = Column(Float, nullable=False)
    final_stack = Column(Float)
    finishing_position = Column(Integer)
    payout = Column(Float)
    is_hero = Column(Boolean, default=False)
    status = Column(String)  # 'active', 'busted', 'cashed'
    bust_hand_number = Column(Integer)
    notes = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    tournament = relationship("Tournament", back_populates="players")
    actions = relationship("HandAction", back_populates="player")
    statistics = relationship(
        "PlayerStatistics",
        back_populates="player",
        uselist=False,
    )


# ---------------------------------------------------------------------------
# Hand
# ---------------------------------------------------------------------------

class Hand(Base):
    """A single hand dealt in a tournament."""

    __tablename__ = "hands"
    __table_args__ = (UniqueConstraint("tournament_id", "hand_number"),)

    hand_id = Column(String, primary_key=True)
    tournament_id = Column(
        String, ForeignKey("tournaments.tournament_id"), nullable=False
    )
    hand_number = Column(Integer, nullable=False)
    timestamp = Column(DateTime, nullable=False)
    button_position = Column(String)
    small_blind = Column(Float, nullable=False)
    big_blind = Column(Float, nullable=False)
    ante = Column(Float, default=0)
    starting_pot = Column(Float)
    hero_seat = Column(String)
    hero_cards = Column(String)       # e.g. 'As Kh'
    community_cards = Column(String)  # e.g. 'Ks7s2d'
    hand_stage = Column(String)       # 'preflop','flop','turn','river','showdown'
    final_pot = Column(Float)
    final_winner = Column(String)     # player_id
    hero_result = Column(String)      # 'win','loss','chop','fold','unknown'
    hero_profit = Column(Float)       # net chip change for hero
    hand_duration_seconds = Column(Float)
    notes = Column(Text)
    raw_json = Column(Text)           # raw extraction payload for debugging
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    tournament = relationship("Tournament", back_populates="hands")
    actions = relationship(
        "HandAction",
        back_populates="hand",
        cascade="all, delete-orphan",
        order_by="HandAction.action_order",
    )


# ---------------------------------------------------------------------------
# HandAction
# ---------------------------------------------------------------------------

class HandAction(Base):
    """One discrete player action within a hand (fold/check/call/raise/bet/allin)."""

    __tablename__ = "hand_actions"

    action_id = Column(Integer, primary_key=True, autoincrement=True)
    hand_id = Column(String, ForeignKey("hands.hand_id"), nullable=False)
    action_order = Column(Integer, nullable=False)
    player_id = Column(
        String, ForeignKey("players_in_tournament.player_id"), nullable=True
    )
    action_type = Column(String, nullable=False)
    amount = Column(Float)
    street = Column(String)  # 'preflop','flop','turn','river'
    timestamp = Column(DateTime)

    hand = relationship("Hand", back_populates="actions")
    player = relationship("PlayerInTournament", back_populates="actions")


# ---------------------------------------------------------------------------
# PlayerStatistics
# ---------------------------------------------------------------------------

class PlayerStatistics(Base):
    """Aggregate poker statistics for a player within a tournament."""

    __tablename__ = "player_statistics"
    __table_args__ = (UniqueConstraint("tournament_id", "player_id"),)

    stat_id = Column(Integer, primary_key=True, autoincrement=True)
    tournament_id = Column(
        String, ForeignKey("tournaments.tournament_id"), nullable=False
    )
    player_id = Column(
        String, ForeignKey("players_in_tournament.player_id"), nullable=False
    )

    # Frequency
    hands_played = Column(Integer, default=0)
    hands_won = Column(Integer, default=0)
    hands_folded = Column(Integer, default=0)

    # Aggression
    vpip = Column(Float)
    pfr = Column(Float)
    aggression_factor = Column(Float)
    postflop_aggression = Column(Float)

    # 3-bet
    three_bet_percentage = Column(Float)
    fold_to_three_bet = Column(Float)

    # C-bet
    cbet_percentage = Column(Float)
    fold_to_cbet = Column(Float)

    # Showdown
    showdown_percentage = Column(Float)
    win_at_showdown = Column(Float)

    # Positional VPIP
    vpip_btn = Column(Float)
    vpip_sb = Column(Float)
    vpip_bb = Column(Float)
    vpip_utg = Column(Float)

    # Sizing
    avg_open_raise_size = Column(Float)
    avg_3bet_size = Column(Float)
    avg_4bet_size = Column(Float)

    # Fish detection
    fish_score = Column(Integer)  # 0-100
    volatility = Column(Integer)  # looseness 0-100

    # Win-rate
    total_profit = Column(Float)
    win_rate = Column(Float)  # bb/100
    roi = Column(Float)

    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    tournament = relationship("Tournament", back_populates="statistics")
    player = relationship("PlayerInTournament", back_populates="statistics")


# ---------------------------------------------------------------------------
# BubbleTracking
# ---------------------------------------------------------------------------

class BubbleTracking(Base):
    """Snapshot of stack distribution at a point during the bubble phase."""

    __tablename__ = "bubble_tracking"

    bubble_id = Column(Integer, primary_key=True, autoincrement=True)
    tournament_id = Column(
        String, ForeignKey("tournaments.tournament_id"), nullable=False
    )
    hand_number = Column(Integer)
    timestamp = Column(DateTime)

    remaining_players = Column(Integer)
    players_to_cash = Column(Integer)
    bubble_factor = Column(Float)  # Avg stack / Min stack to cash

    chip_leader_id = Column(
        String, ForeignKey("players_in_tournament.player_id"), nullable=True
    )
    chip_leader_stack = Column(Float)
    shortest_stack_player_id = Column(
        String, ForeignKey("players_in_tournament.player_id"), nullable=True
    )
    shortest_stack = Column(Float)
    stack_range = Column(Float)  # (Max - Min) / Avg

    your_chip_position = Column(Integer)   # 1 = chip leader
    your_chip_percentage = Column(Float)   # Your chips / Total chips
    icm_equity = Column(Float)

    notes = Column(Text)

    tournament = relationship(
        "Tournament",
        back_populates="bubble_data",
        foreign_keys=[tournament_id],
    )
    chip_leader = relationship(
        "PlayerInTournament",
        foreign_keys=[chip_leader_id],
    )
    shortest_stack_player = relationship(
        "PlayerInTournament",
        foreign_keys=[shortest_stack_player_id],
    )


# ---------------------------------------------------------------------------
# BlindLevel
# ---------------------------------------------------------------------------

class BlindLevel(Base):
    """One blind level in a tournament structure."""

    __tablename__ = "blind_levels"

    level_id = Column(Integer, primary_key=True, autoincrement=True)
    tournament_id = Column(
        String, ForeignKey("tournaments.tournament_id"), nullable=False
    )
    level_number = Column(Integer)
    small_blind = Column(Float)
    big_blind = Column(Float)
    ante = Column(Float, default=0)
    duration_minutes = Column(Integer)
    start_hand = Column(Integer)
    end_hand = Column(Integer)

    tournament = relationship("Tournament", back_populates="blind_level_records")


# ---------------------------------------------------------------------------
# SessionMetadata
# ---------------------------------------------------------------------------

class SessionMetadata(Base):
    """OCR/extraction quality metadata for a tournament session."""

    __tablename__ = "session_metadata"

    session_id = Column(String, primary_key=True)
    tournament_id = Column(
        String, ForeignKey("tournaments.tournament_id"), nullable=False, unique=True
    )
    session_start = Column(DateTime)
    session_end = Column(DateTime)
    data_quality_score = Column(Float)       # 0-100 (% OCR confidence avg)
    extraction_method = Column(String)       # 'live_screen', 'video_replay'
    frames_processed = Column(Integer)
    frames_with_errors = Column(Integer)
    ocr_avg_confidence = Column(Float)
    table_detection_success_rate = Column(Float)
    notes = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    tournament = relationship("Tournament", back_populates="session_metadata")
