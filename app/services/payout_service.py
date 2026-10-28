from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import TournamentPlayerStatus, TournamentStatus
from app.models.tournament import BlindLevel, Tournament, TournamentPayout, TournamentPlayer, utc_now
from app.services.errors import DomainError
from app.services.event_service import EventService
from app.services.registration_service import late_registration_phase


TOTAL_BASIS_POINTS = 10_000


@dataclass(frozen=True, slots=True)
class PayoutLine:
    place: int
    percentage_basis_points: int
    amount: int


class PayoutService:
    @staticmethod
    def normalize_percentages(values: list[Any] | None) -> list[int]:
        if not values:
            raise DomainError("payout_structure_required", "Добавьте хотя бы одно призовое место.")
        normalized: list[int] = []
        for raw in values:
            value = raw.get("percentage") if isinstance(raw, dict) else raw
            try:
                percentage = Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError) as error:
                raise DomainError("invalid_payout_percentage", "Проверьте проценты призовых мест.") from error
            basis_points = percentage * 100
            if not percentage.is_finite() or percentage <= 0 or basis_points != basis_points.to_integral_value():
                raise DomainError(
                    "invalid_payout_percentage",
                    "Процент должен быть больше нуля и содержать не более двух знаков после запятой.",
                )
            normalized.append(int(basis_points))
        if sum(normalized) != TOTAL_BASIS_POINTS:
            total = Decimal(sum(normalized)) / 100
            raise DomainError(
                "invalid_payout_total",
                f"Сумма выплат должна составлять ровно 100% (сейчас {total:g}%).",
            )
        return normalized

    @staticmethod
    def replace_structure(
        session: Session,
        tournament: Tournament,
        percentages: list[Any] | None,
        *,
        request_id: str | None = None,
        record_event: bool = True,
    ) -> list[TournamentPayout]:
        if tournament.buy_in_amount == 0:
            raise DomainError("freeroll_has_no_payouts", "Для фриролла денежные выплаты не настраиваются.")
        if tournament.payouts_finalized_at is not None:
            raise DomainError("payouts_finalized", "Финальные выплаты нельзя изменить после закрытия регистрации.")
        if tournament.status == TournamentStatus.FINISHED:
            raise DomainError("tournament_finished", "В завершённом турнире выплаты нельзя изменить.")
        normalized = PayoutService.normalize_percentages(percentages)
        existing = list(
            session.scalars(
                select(TournamentPayout).where(TournamentPayout.tournament_id == tournament.id)
            )
        )
        for payout in existing:
            session.delete(payout)
        session.flush()
        created = [
            TournamentPayout(
                tournament_id=tournament.id,
                place=place,
                percentage_basis_points=percentage,
            )
            for place, percentage in enumerate(normalized, start=1)
        ]
        session.add_all(created)
        session.flush()
        if record_event:
            EventService.record(
                session,
                tournament,
                "payout_structure_changed",
                {"percentages_basis_points": normalized},
                request_id=request_id,
            )
        return created

    @staticmethod
    def save_structure(
        session: Session,
        tournament_id: int,
        percentages: list[Any] | None,
        *,
        request_id: str | None = None,
    ) -> list[TournamentPayout]:
        with session.begin():
            tournament = session.get(Tournament, tournament_id)
            if tournament is None:
                raise DomainError("tournament_not_found", "Турнир не найден.")
            return PayoutService.replace_structure(
                session,
                tournament,
                percentages,
                request_id=request_id,
            )

    @staticmethod
    def calculate(prize_pool: int, payouts: list[TournamentPayout]) -> list[PayoutLine]:
        ordered = sorted(payouts, key=lambda item: item.place)
        if not ordered:
            return []
        amounts = [prize_pool * payout.percentage_basis_points // TOTAL_BASIS_POINTS for payout in ordered]
        amounts[0] += prize_pool - sum(amounts)
        return [
            PayoutLine(
                place=payout.place,
                percentage_basis_points=payout.percentage_basis_points,
                amount=amount,
            )
            for payout, amount in zip(ordered, amounts, strict=True)
        ]

    @staticmethod
    def configuration_error(paid_places: int, registered_players: int) -> str | None:
        if paid_places >= registered_players and not (paid_places == registered_players == 1):
            return "Призовых мест должно быть меньше, чем зарегистрированных игроков к закрытию регистрации."
        return None

    @staticmethod
    def finalize_registration(session: Session, tournament_id: int) -> Tournament:
        with session.begin():
            tournament = session.get(Tournament, tournament_id)
            if tournament is None:
                raise DomainError("tournament_not_found", "Турнир не найден.")
            if tournament.buy_in_amount == 0:
                raise DomainError("freeroll_has_no_payouts", "Для фриролла денежные выплаты не используются.")
            if tournament.payouts_finalized_at is not None:
                raise DomainError("payouts_finalized", "Регистрация уже закрыта, выплаты финализированы.")
            if tournament.status == TournamentStatus.FINISHED:
                raise DomainError("tournament_finished", "Турнир уже завершён.")
            payouts = list(
                session.scalars(
                    select(TournamentPayout).where(TournamentPayout.tournament_id == tournament.id)
                )
            )
            if not payouts:
                raise DomainError("payout_structure_required", "Сначала настройте призовые места.")
            player_count = session.scalar(
                select(func.count()).select_from(TournamentPlayer).where(
                    TournamentPlayer.tournament_id == tournament.id
                )
            ) or 0
            error = PayoutService.configuration_error(len(payouts), player_count)
            if player_count == 0 or error:
                raise DomainError(
                    "invalid_paid_places",
                    error or "Добавьте игроков перед закрытием регистрации.",
                )
            tournament.payouts_finalized_at = utc_now()
            EventService.record(session, tournament, "payouts_finalized", {"manual": True})
            PayoutService.record_stage_transition(session, tournament, "registration_open")
            return tournament

    @staticmethod
    def stage(
        tournament: Tournament,
        entries: list[TournamentPlayer],
        payouts: list[TournamentPayout] | None = None,
    ) -> str:
        if tournament.status == TournamentStatus.FINISHED:
            return "tournament_finished"
        active_players = sum(entry.status == TournamentPlayerStatus.ACTIVE for entry in entries)
        configured_payouts = list(tournament.payouts if payouts is None else payouts)
        if tournament.buy_in_amount == 0 or not configured_payouts:
            return "registration_open"
        if tournament.payouts_finalized_at is None:
            return "registration_open"
        paid_places = len(configured_payouts)
        if PayoutService.configuration_error(paid_places, len(entries)):
            return "configuration_error"
        if active_players == paid_places + 1:
            return "bubble"
        if active_players <= paid_places:
            return "itm"
        return "registration_closed"

    @staticmethod
    def record_stage_transition(session: Session, tournament: Tournament, before_stage: str) -> str:
        entries = list(
            session.scalars(
                select(TournamentPlayer).where(TournamentPlayer.tournament_id == tournament.id)
            )
        )
        payouts = list(
            session.scalars(
                select(TournamentPayout)
                .where(TournamentPayout.tournament_id == tournament.id)
                .order_by(TournamentPayout.place)
            )
        )
        after_stage = PayoutService.stage(tournament, entries, payouts)
        if after_stage == before_stage or after_stage not in {"bubble", "itm"}:
            return after_stage
        active_players = sum(entry.status == TournamentPlayerStatus.ACTIVE for entry in entries)
        # В winner-takes-all отдельная ITM-карточка непосредственно перед экраном
        # победителя создаёт конфликтующую последовательность и не показывается.
        if after_stage == "itm" and len(payouts) == 1 and active_players == 1:
            return after_stage
        EventService.record(
            session,
            tournament,
            "bubble_reached" if after_stage == "bubble" else "itm_reached",
            {"active_players": active_players, "paid_places": len(payouts)},
        )
        return after_stage

    @staticmethod
    def current_stage(session: Session, tournament: Tournament) -> str:
        entries = list(
            session.scalars(
                select(TournamentPlayer).where(TournamentPlayer.tournament_id == tournament.id)
            )
        )
        payouts = list(
            session.scalars(
                select(TournamentPayout)
                .where(TournamentPayout.tournament_id == tournament.id)
                .order_by(TournamentPayout.place)
            )
        )
        return PayoutService.stage(tournament, entries, payouts)

    @staticmethod
    def reconcile_finalization(session: Session, tournament: Tournament) -> bool:
        if (
            tournament.buy_in_amount == 0
            or tournament.payouts_finalized_at is not None
            or not session.scalar(
                select(TournamentPayout.id).where(TournamentPayout.tournament_id == tournament.id).limit(1)
            )
        ):
            return False
        levels = list(
            session.scalars(
                select(BlindLevel)
                .where(BlindLevel.tournament_id == tournament.id)
                .order_by(BlindLevel.order_index)
            )
        )
        phase = late_registration_phase(
            levels,
            tournament.current_level_index,
            tournament.late_registration_end_level_index,
        )
        if tournament.status != TournamentStatus.FINISHED and phase != "closed":
            return False
        tournament.payouts_finalized_at = utc_now()
        EventService.record(session, tournament, "payouts_finalized", {})
        PayoutService.record_stage_transition(session, tournament, "registration_open")
        return True
