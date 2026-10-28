from enum import StrEnum


class TournamentStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    FINISHED = "finished"


class TimerStatus(StrEnum):
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"


class TournamentPlayerStatus(StrEnum):
    REGISTERED = "registered"
    ACTIVE = "active"
    ELIMINATED = "eliminated"
    OUT = "out"


class BountyMode(StrEnum):
    NONE = "none"
    FIXED = "fixed"


class BlindLevelKind(StrEnum):
    PLAY = "play"
    BREAK = "break"
