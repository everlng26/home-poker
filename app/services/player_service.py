from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import BountyMode, TimerStatus, TournamentPlayerStatus, TournamentStatus
from app.models.tournament import BlindLevel, Player, Tournament, TournamentPlayer, utc_now
from app.services.errors import DomainError
from app.services.bounty_service import BountyService
from app.services.event_service import EventService, player_state
from app.services.payout_service import PayoutService
from app.services.tournament_service import TournamentService
from app.services.registration_service import late_registration_phase


class PlayerService:
    @staticmethod
    def _clean_player_name(name: str) -> str:
        cleaned_name = name.strip()
        if not cleaned_name:
            raise DomainError("invalid_player_name", "Введите имя игрока.")
        return cleaned_name

    @staticmethod
    def _late_registration_warning(session: Session, tournament: Tournament) -> str | None:
        if tournament.payouts_finalized_at is not None:
            return "Поздняя регистрация уже завершена; финальные выплаты будут пересчитаны."
        if tournament.status == TournamentStatus.DRAFT or tournament.late_registration_end_level_index is None:
            return None
        levels = list(
            session.scalars(
                select(BlindLevel)
                .where(BlindLevel.tournament_id == tournament.id)
                .order_by(BlindLevel.order_index)
            )
        )
        phase = late_registration_phase(
            levels, tournament.current_level_index, tournament.late_registration_end_level_index
        )
        return "Поздняя регистрация уже завершена." if phase == "closed" else None

    @staticmethod
    def create_player(session: Session, name: str, nickname: str | None = None, notes: str | None = None) -> Player:
        cleaned_name = PlayerService._clean_player_name(name)
        with session.begin():
            player = Player(name=cleaned_name, nickname=nickname or None, notes=notes or None)
            session.add(player)
        return player

    @staticmethod
    def register_player(
        session: Session,
        tournament_id: int,
        player_id: int,
        seat_number: int | None = None,
        request_id: str | None = None,
        allow_warnings: bool = False,
    ) -> TournamentPlayer:
        with session.begin():
            tournament = session.get(Tournament, tournament_id)
            player = session.get(Player, player_id)
            if tournament is None or player is None:
                raise DomainError("not_found", "Турнир или игрок не найден.")
            late_warning = PlayerService._late_registration_warning(session, tournament)
            if late_warning and not allow_warnings:
                raise DomainError("late_registration_warning", late_warning + " Всё равно добавить игрока?")
            before_stage = PayoutService.current_stage(session, tournament)
            entry = PlayerService._register_player(session, tournament, player, seat_number, request_id)
            session.flush()
            PayoutService.record_stage_transition(session, tournament, before_stage)
            return entry

    @staticmethod
    def create_and_register_player(
        session: Session,
        tournament_id: int,
        name: str,
        seat_number: int | None = None,
        request_id: str | None = None,
        allow_warnings: bool = False,
    ) -> TournamentPlayer:
        cleaned_name = PlayerService._clean_player_name(name)
        with session.begin():
            tournament = session.get(Tournament, tournament_id)
            if tournament is None:
                raise DomainError("not_found", "Турнир или игрок не найден.")
            late_warning = PlayerService._late_registration_warning(session, tournament)
            if late_warning and not allow_warnings:
                raise DomainError("late_registration_warning", late_warning + " Всё равно добавить игрока?")
            player = Player(name=cleaned_name)
            session.add(player)
            session.flush()
            before_stage = PayoutService.current_stage(session, tournament)
            entry = PlayerService._register_player(session, tournament, player, seat_number, request_id)
            session.flush()
            PayoutService.record_stage_transition(session, tournament, before_stage)
            return entry

    @staticmethod
    def _register_player(
        session: Session,
        tournament: Tournament,
        player: Player,
        seat_number: int | None = None,
        request_id: str | None = None,
    ) -> TournamentPlayer:
        if tournament.status == TournamentStatus.FINISHED:
            raise DomainError("tournament_finished", "Нельзя регистрировать игрока в завершённый турнир.")
        existing = session.scalar(
            select(TournamentPlayer).where(
                TournamentPlayer.tournament_id == tournament.id, TournamentPlayer.player_id == player.id
            )
        )
        if existing:
            raise DomainError("already_registered", "Этот игрок уже зарегистрирован в турнире.")
        status = TournamentPlayerStatus.REGISTERED if tournament.status == TournamentStatus.DRAFT else TournamentPlayerStatus.ACTIVE
        entry = TournamentPlayer(
            tournament_id=tournament.id,
            player_id=player.id,
            seat_number=seat_number,
            status=status,
            entries_count=1,
        )
        session.add(entry)
        session.flush()
        EventService.record(
            session,
            tournament,
            "player_registered",
            {
                "tournament_player_id": entry.id,
                "player_id": player.id,
                "entries_count": 1,
                "public_feed": tournament.status != TournamentStatus.DRAFT,
            },
            request_id=request_id,
        )
        return entry

    @staticmethod
    def eliminate_player(
        session: Session,
        tournament_player_id: int,
        request_id: str | None = None,
        killer_tournament_player_id: int | None = None,
    ) -> TournamentPlayer:
        with session.begin():
            entry = session.get(TournamentPlayer, tournament_player_id)
            if entry is None:
                raise DomainError("player_not_found", "Участник турнира не найден.")
            tournament = session.get(Tournament, entry.tournament_id)
            if tournament is None:
                raise DomainError("tournament_not_found", "Турнир не найден.")
            if tournament.is_manually_finished:
                raise DomainError("tournament_locked", "Турнир завершён и заблокирован для изменений.")
            if entry.status != TournamentPlayerStatus.ACTIVE:
                raise DomainError("player_not_active", "Вылет можно отметить только для игрока в игре.")
            killer: TournamentPlayer | None = None
            if tournament.bounty_mode == BountyMode.FIXED:
                if killer_tournament_player_id is None:
                    raise DomainError("killer_required", "Укажите игрока, который совершил K.O.")
                killer = session.get(TournamentPlayer, killer_tournament_player_id)
                if killer is None or killer.tournament_id != tournament.id:
                    raise DomainError("invalid_killer", "Выберите активного участника этого турнира.")
                if killer.id == entry.id:
                    raise DomainError("self_elimination", "Игрок не может выбить самого себя.")
                if killer.status != TournamentPlayerStatus.ACTIVE:
                    raise DomainError("killer_not_active", "K.O. может совершить только игрок в игре.")
            active_count = session.scalar(
                select(func.count()).select_from(TournamentPlayer).where(
                    TournamentPlayer.tournament_id == entry.tournament_id,
                    TournamentPlayer.status == TournamentPlayerStatus.ACTIVE,
                )
            )
            before_stage = PayoutService.current_stage(session, tournament)
            before = player_state(entry)
            entry.status = TournamentPlayerStatus.ELIMINATED
            entry.eliminated_at = utc_now()
            entry.elimination_place = int(active_count)
            payload = {"tournament_player_id": entry.id, "before": before, "after": player_state(entry)}
            if killer is not None:
                payload.update(
                    {
                        "killer_tournament_player_id": killer.id,
                        "bounty_amount_awarded": tournament.bounty_amount,
                        "eliminated_entry_number": entry.entries_count,
                    }
                )
            EventService.record(
                session,
                tournament,
                "player_eliminated",
                payload,
                request_id=request_id,
                reversible=True,
            )
            session.flush()
            PayoutService.record_stage_transition(session, tournament, before_stage)
            return entry

    @staticmethod
    def mark_out(session: Session, tournament_player_id: int, request_id: str | None = None) -> TournamentPlayer:
        """Фиксирует окончательный аут без возможности re-entry или отмены."""
        with session.begin():
            entry = session.get(TournamentPlayer, tournament_player_id)
            if entry is None:
                raise DomainError("player_not_found", "Участник турнира не найден.")
            tournament = session.get(Tournament, entry.tournament_id)
            if tournament is None:
                raise DomainError("tournament_not_found", "Турнир не найден.")
            if tournament.is_manually_finished:
                raise DomainError("tournament_locked", "Турнир завершён и заблокирован для изменений.")
            if entry.status != TournamentPlayerStatus.ELIMINATED:
                raise DomainError("player_not_eliminated", "В аут можно перевести только выбывшего игрока.")
            before = player_state(entry)
            entry.status = TournamentPlayerStatus.OUT
            EventService.record(
                session,
                tournament,
                "player_out",
                {"tournament_player_id": entry.id, "before": before, "after": player_state(entry)},
                request_id=request_id,
            )
            session.flush()
            TournamentService.finish_if_ready(session, tournament)
            return entry

    @staticmethod
    def add_reentry(
        session: Session,
        tournament_player_id: int,
        request_id: str | None = None,
        allow_warnings: bool = False,
    ) -> TournamentPlayer:
        with session.begin():
            entry = session.get(TournamentPlayer, tournament_player_id)
            if entry is None:
                raise DomainError("player_not_found", "Участник турнира не найден.")
            tournament = session.get(Tournament, entry.tournament_id)
            if tournament is None:
                raise DomainError("tournament_not_found", "Турнир не найден.")
            if tournament.is_manually_finished:
                raise DomainError("tournament_locked", "Турнир завершён и заблокирован для изменений.")
            if entry.status not in {TournamentPlayerStatus.ELIMINATED, TournamentPlayerStatus.OUT}:
                raise DomainError("reentry_not_allowed", "Re-entry доступен только выбывшему игроку.")
            reentries_already_used = entry.entries_count - 1
            limit = tournament.max_reentries_per_player
            warnings: list[str] = []
            if entry.status == TournamentPlayerStatus.OUT:
                warnings.append("игрок отмечен как окончательный аут")
            if limit is not None and reentries_already_used >= limit:
                warnings.append("игрок уже использовал все доступные re-entry")
            if tournament.status == TournamentStatus.FINISHED:
                warnings.append("турнир уже завершён")
            late_warning = PlayerService._late_registration_warning(session, tournament)
            if late_warning:
                warnings.append("поздняя регистрация уже завершена")
            if warnings and not allow_warnings:
                raise DomainError(
                    "late_registration_warning" if late_warning else "reentry_warning",
                    "Внимание: " + ", ".join(warnings) + ". Продолжить re-entry?",
                )
            before_stage = PayoutService.current_stage(session, tournament)
            if tournament.status == TournamentStatus.FINISHED:
                BountyService.revoke_champion_bounty(session, tournament)
                tournament.status = TournamentStatus.PAUSED
                tournament.timer_status = TimerStatus.PAUSED
                tournament.level_started_at = None
                winner = session.scalar(
                    select(TournamentPlayer).where(
                        TournamentPlayer.tournament_id == tournament.id,
                        TournamentPlayer.elimination_place == 1,
                        TournamentPlayer.status != TournamentPlayerStatus.OUT,
                    )
                )
                if winner is not None:
                    winner.elimination_place = None
                EventService.record(session, tournament, "tournament_reopened", {"tournament_player_id": entry.id})
            before = player_state(entry)
            entry.entries_count += 1
            entry.status = TournamentPlayerStatus.ACTIVE
            entry.eliminated_at = None
            entry.elimination_place = None
            EventService.record(
                session,
                tournament,
                "reentry_added",
                {"tournament_player_id": entry.id, "before": before, "after": player_state(entry)},
                request_id=request_id,
                reversible=True,
            )
            session.flush()
            PayoutService.record_stage_transition(session, tournament, before_stage)
            return entry
