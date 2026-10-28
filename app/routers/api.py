from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import Response as RawResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models.tournament import (
    AppSetting,
    Tournament,
    TournamentChipPlan,
    TournamentEvent,
    TournamentPlayer,
)
from app.security import hash_pin, read_session, sign_session, verify_pin
from app.services import (
    AutoTournamentBuilderService,
    ChipInventoryService,
    DomainError,
    EventService,
    PayoutService,
    PlayerService,
    StackOptimizerService,
    TournamentStructureGeneratorService,
    TournamentService,
)
from app.services.level_service import LevelService, STRUCTURE_PRESETS
from app.services.network_service import find_lan_addresses, local_hostname_url
from app.services.qr_service import qr_svg
from app.services.setup_service import TournamentSetupService
from app.services.state_service import tournament_state
from app.services.timer_service import TimerService

router = APIRouter(prefix="/api/v1")


def error_response(error: DomainError) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": error.code, "message": error.message})


def chip_inventory_error_response(error: DomainError) -> HTTPException:
    status_code = 404 if error.code == "chip_set_not_found" else 400
    return HTTPException(
        status_code=status_code,
        detail={"code": error.code, "message": error.message},
    )


def admin_tournament_id(request: Request) -> int:
    secret = request.app.state.app_secret
    tournament_id = read_session(request.cookies.get("poker_admin"), secret)
    if tournament_id is None:
        raise HTTPException(status_code=401, detail={"code": "auth_required", "message": "Требуется вход по PIN."})
    csrf_cookie = request.cookies.get("poker_csrf")
    if request.method not in {"GET", "HEAD"} and request.headers.get("X-CSRF-Token") != csrf_cookie:
        raise HTTPException(status_code=403, detail={"code": "csrf_failed", "message": "Обновите страницу и повторите действие."})
    return tournament_id


@router.get("/tournaments")
def tournaments(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return TournamentService.list_summaries(session)


@router.get("/chip-sets")
def chip_sets(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return ChipInventoryService.list(session)


@router.get("/chip-sets/{chip_set_id}")
def chip_set(chip_set_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        return ChipInventoryService.get(session, chip_set_id)
    except DomainError as error:
        raise chip_inventory_error_response(error) from error


@router.post("/chip-sets")
def create_chip_set(payload: dict[str, Any], session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        return ChipInventoryService.create(
            session,
            name=payload.get("name", ""),
            denominations=payload.get("denominations", []),
            is_default=payload.get("is_default") is True,
        )
    except DomainError as error:
        raise chip_inventory_error_response(error) from error


@router.put("/chip-sets/{chip_set_id}")
def update_chip_set(
    chip_set_id: int,
    payload: dict[str, Any],
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    raw_default = payload.get("is_default") if "is_default" in payload else None
    is_default = None if raw_default is None else raw_default is True
    try:
        return ChipInventoryService.update(
            session,
            chip_set_id,
            name=payload.get("name", ""),
            denominations=payload.get("denominations", []),
            is_default=is_default,
        )
    except DomainError as error:
        raise chip_inventory_error_response(error) from error


@router.delete("/chip-sets/{chip_set_id}")
def delete_chip_set(chip_set_id: int, session: Session = Depends(get_session)) -> dict[str, bool]:
    try:
        ChipInventoryService.delete(session, chip_set_id)
        return {"ok": True}
    except DomainError as error:
        raise chip_inventory_error_response(error) from error


@router.post("/chip-sets/{chip_set_id}/default")
def default_chip_set(chip_set_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        return ChipInventoryService.set_default(session, chip_set_id)
    except DomainError as error:
        raise chip_inventory_error_response(error) from error


@router.post("/tournaments")
def create_tournament(payload: dict[str, Any], session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        tournament = TournamentSetupService.create(
            session,
            name=str(payload.get("name", "")),
            buy_in_amount=int(payload.get("buy_in_amount", 0)),
            currency_label=str(payload.get("currency_label", "₽")),
            starting_stack=int(payload.get("starting_stack", 0)),
            max_reentries_per_player=payload.get("max_reentries_per_player"),
            is_freeroll=bool(payload.get("is_freeroll", False)),
            ante_enabled=bool(payload.get("ante_enabled", True)),
            admin_pin_hash=hash_pin(str(payload.get("pin", ""))),
            preset=str(payload.get("preset", "standard")),
            levels=payload.get("levels"),
            player_names=payload.get("players", []),
            late_registration_end_level_number=payload.get("late_registration_end_level_number"),
            payout_percentages=payload.get("payout_percentages"),
            bounty_mode=payload.get("bounty_mode"),
            bounty_amount=payload.get("bounty_amount", 0),
            chip_plan=payload.get("chip_plan"),
        )
        return {"id": tournament.id}
    except (DomainError, ValueError) as error:
        raise error_response(error if isinstance(error, DomainError) else DomainError("invalid_input", str(error))) from error


@router.post("/stack-optimizer")
def optimize_stack(payload: dict[str, Any], session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        return StackOptimizerService.solve(
            session,
            chip_set_ids=payload.get("chip_set_ids"),
            excluded_denominations=payload.get("excluded_denominations"),
            players=payload.get("players"),
            starting_stack=payload.get("starting_stack"),
            max_reentries_per_player=payload.get("max_reentries_per_player"),
            first_small_blind=payload.get("first_small_blind"),
            first_big_blind=payload.get("first_big_blind"),
            first_ante=payload.get("first_ante"),
        )
    except DomainError as error:
        raise error_response(error) from error


@router.post("/structure-generator")
def generate_structure(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return TournamentStructureGeneratorService.generate(
            players=payload.get("players"),
            starting_stack=payload.get("starting_stack"),
            expected_reentries=payload.get("expected_reentries", 0),
            max_reentries_per_player=payload.get("max_reentries_per_player"),
            first_small_blind=payload.get("first_small_blind"),
            first_big_blind=payload.get("first_big_blind"),
            level_duration_minutes=payload.get("level_duration_minutes"),
            target_duration_minutes=payload.get("target_duration_minutes"),
            ante_mode=payload.get("ante_mode", "big_blind"),
            ante_start_mode=payload.get("ante_start_mode", "auto"),
            ante_start_level=payload.get("ante_start_level"),
            break_every_levels=payload.get("break_every_levels", 4),
            break_duration_minutes=payload.get("break_duration_minutes", 10),
            chip_denominations=payload.get("chip_denominations"),
        )
    except DomainError as error:
        raise error_response(error) from error


@router.post("/auto-tournament-builder")
def build_tournament(
    payload: dict[str, Any], session: Session = Depends(get_session)
) -> dict[str, Any]:
    try:
        return AutoTournamentBuilderService.build(
            session,
            chip_set_ids=payload.get("chip_set_ids"),
            players=payload.get("players"),
            max_reentries_per_player=payload.get("max_reentries_per_player"),
            target_duration_minutes=payload.get("target_duration_minutes"),
            ante_mode=payload.get("ante_mode"),
        )
    except DomainError as error:
        raise error_response(error) from error


@router.post("/auto-tournament-builder/diagnostics")
def analyze_auto_tournament_draft(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return TournamentStructureGeneratorService.analyze_draft(
            levels=payload.get("levels"),
            players=payload.get("players"),
            starting_stack=payload.get("starting_stack"),
            expected_reentries=payload.get("expected_reentries", 0),
            target_duration_minutes=payload.get("target_duration_minutes"),
            chip_denominations=payload.get("chip_denominations"),
        )
    except DomainError as error:
        raise error_response(error) from error


@router.get("/tournaments/{tournament_id}/chip-plan")
def tournament_chip_plan(
    tournament_id: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    plan = session.scalar(
        select(TournamentChipPlan).where(TournamentChipPlan.tournament_id == tournament_id)
    )
    if plan is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "chip_plan_not_found", "message": "План фишек не найден."},
        )
    return {
        "tournament_id": plan.tournament_id,
        "selected_chip_sets": plan.selected_chip_sets_json,
        "combined_inventory": plan.combined_inventory_json,
        "planned_players": plan.planned_players,
        "starting_stack": plan.starting_stack,
        "max_reentries_per_player": plan.max_reentries_per_player,
        "max_total_reentries": plan.max_total_reentries,
        "covered_reentries": plan.covered_reentries,
        "coverage_status": (
            "full" if plan.covered_reentries == plan.max_total_reentries else "partial"
        ),
        "initial_distribution": plan.initial_distribution_json,
        "reentry_distribution": plan.reentry_distribution_json,
        "reserved_quantities": plan.reserved_quantities_json,
        "remaining_inventory": plan.remaining_inventory_json,
        "created_at": plan.created_at.isoformat(),
    }


@router.get("/tournaments/{tournament_id}/state")
def state(tournament_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        return tournament_state(session, tournament_id)
    except DomainError as error:
        raise HTTPException(status_code=404, detail={"code": error.code, "message": error.message}) from error


@router.post("/tournaments/{tournament_id}/delete")
def delete_tournament(tournament_id: int, payload: dict[str, Any], session: Session = Depends(get_session)) -> dict[str, bool]:
    try:
        TournamentService.delete_tournament(session, tournament_id, str(payload.get("pin", "")))
        return {"ok": True}
    except DomainError as error:
        raise error_response(error) from error


@router.post("/tournaments/{tournament_id}/login")
def login(tournament_id: int, payload: dict[str, Any], request: Request, response: Response, session: Session = Depends(get_session)) -> dict[str, bool]:
    tournament = session.get(Tournament, tournament_id)
    if tournament is None or not verify_pin(str(payload.get("pin", "")), tournament.admin_pin_hash):
        raise HTTPException(status_code=401, detail={"code": "invalid_pin", "message": "Неверный PIN."})
    response.set_cookie("poker_admin", sign_session(tournament_id, request.app.state.app_secret), httponly=True, samesite="lax")
    response.set_cookie("poker_csrf", secrets.token_urlsafe(24), httponly=False, samesite="lax")
    return {"ok": True}


@router.get("/tournaments/{tournament_id}/session")
def admin_session(tournament_id: int, request: Request) -> dict[str, bool]:
    """Сообщает, вошёл ли этот браузер в админку турнира; сам PIN и cookie не раскрываются."""
    active_tournament_id = read_session(request.cookies.get("poker_admin"), request.app.state.app_secret)
    return {"authenticated": active_tournament_id == tournament_id}


@router.post("/tournaments/{tournament_id}/players")
async def add_player(tournament_id: int, payload: dict[str, Any], request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    if admin_tournament_id(request) != tournament_id:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    try:
        entry = PlayerService.create_and_register_player(
            session,
            tournament_id,
            str(payload.get("name", "")),
            request_id=payload.get("request_id"),
            allow_warnings=bool(payload.get("allow_warnings", False)),
        )
        await request.app.state.ws_manager.broadcast_state(tournament_id)
        result = tournament_state(session, tournament_id)
        result["registered_entry_id"] = entry.id
        return result
    except DomainError as error:
        raise error_response(error) from error


@router.post("/tournaments/{tournament_id}/timer")
async def timer(tournament_id: int, payload: dict[str, Any], request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    if admin_tournament_id(request) != tournament_id:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    try:
        TimerService.command(session, tournament_id, payload["action"], target_level_index=payload.get("target_level_index"), request_id=payload.get("request_id"))
        result = tournament_state(session, tournament_id)
        await request.app.state.ws_manager.broadcast_state(tournament_id)
        return result
    except DomainError as error:
        raise error_response(error) from error


@router.post("/tournaments/{tournament_id}/finish")
async def finish_tournament(
    tournament_id: int,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if admin_tournament_id(request) != tournament_id:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    try:
        TournamentService.finish_manually(session, tournament_id, str(payload.get("pin", "")))
        result = tournament_state(session, tournament_id)
        await request.app.state.ws_manager.broadcast_state(tournament_id)
        return result
    except DomainError as error:
        raise error_response(error) from error


@router.post("/tournament-players/{entry_id}/{action}")
async def player_action(entry_id: int, action: str, payload: dict[str, Any], request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    entry = session.get(TournamentPlayer, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Участник не найден")
    tournament_id = entry.tournament_id
    session.rollback()
    if admin_tournament_id(request) != tournament_id:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    try:
        if action == "eliminate":
            PlayerService.eliminate_player(
                session,
                entry_id,
                payload.get("request_id"),
                killer_tournament_player_id=payload.get("killer_tournament_player_id"),
            )
        elif action == "reenter":
            PlayerService.add_reentry(
                session,
                entry_id,
                payload.get("request_id"),
                allow_warnings=bool(payload.get("allow_warnings", False)),
            )
        elif action == "out":
            PlayerService.mark_out(session, entry_id, payload.get("request_id"))
        else:
            raise HTTPException(status_code=404, detail="Неизвестное действие")
        result = tournament_state(session, tournament_id)
        await request.app.state.ws_manager.broadcast_state(tournament_id)
        return result
    except DomainError as error:
        raise error_response(error) from error


@router.post("/tournaments/{tournament_id}/undo")
async def undo(tournament_id: int, payload: dict[str, Any], request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    if admin_tournament_id(request) != tournament_id:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    try:
        EventService.undo_last(session, tournament_id, payload.get("request_id"))
        result = tournament_state(session, tournament_id)
        await request.app.state.ws_manager.broadcast_state(tournament_id)
        return result
    except DomainError as error:
        raise error_response(error) from error


@router.get("/tournaments/{tournament_id}/events")
def events(tournament_id: int, request: Request, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    if admin_tournament_id(request) != tournament_id:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    history = session.scalars(
        select(TournamentEvent)
        .where(TournamentEvent.tournament_id == tournament_id)
        .order_by(TournamentEvent.id.desc())
        .limit(30)
    )
    result: list[dict[str, Any]] = []
    for event in history:
        payload = event.payload_json if isinstance(event.payload_json, dict) else {}
        player_name = None
        entry_id = payload.get("tournament_player_id")
        if entry_id is not None:
            entry = session.get(TournamentPlayer, entry_id)
            if entry is not None:
                player_name = entry.player.name
        killer_name = None
        killer_entry_id = payload.get("killer_tournament_player_id")
        if killer_entry_id is not None:
            killer_entry = session.get(TournamentPlayer, killer_entry_id)
            if killer_entry is not None:
                killer_name = killer_entry.player.name
        result.append(
            {
                "id": event.id,
                "type": event.event_type,
                "player_name": player_name,
                "killer_name": killer_name,
                "bounty_amount_awarded": payload.get("bounty_amount_awarded", 0),
                "created_at": event.created_at.isoformat(),
                "reversed_at": event.reversed_at.isoformat() if event.reversed_at else None,
                "reversible": event.is_reversible,
            }
        )
    return result


@router.get("/structure-presets")
def presets() -> dict[str, Any]:
    return STRUCTURE_PRESETS


@router.get("/network")
def network(session: Session = Depends(get_session)) -> dict[str, Any]:
    setting = session.get(AppSetting, "preferred_lan_url")
    addresses = [
        {"interface": item.interface, "address": item.address, "url": item.url()}
        for item in find_lan_addresses()
    ]
    return {
        "localhost_url": "http://localhost:8000",
        "addresses": addresses,
        "mdns_url": local_hostname_url(),
        "preferred_url": (setting.value_json.get("url") if setting else None),
    }


@router.post("/network/preferred")
def preferred_network(payload: dict[str, Any], session: Session = Depends(get_session)) -> dict[str, str]:
    candidate = str(payload.get("url", "")).rstrip("/")
    valid_urls = {item.url() for item in find_lan_addresses()}
    hostname_url = local_hostname_url()
    if hostname_url:
        valid_urls.add(hostname_url)
    if candidate not in valid_urls:
        raise HTTPException(status_code=400, detail={"message": "Выберите адрес из найденного списка."})
    with session.begin():
        setting = session.get(AppSetting, "preferred_lan_url")
        if setting is None:
            session.add(AppSetting(key="preferred_lan_url", value_json={"url": candidate}))
        else:
            setting.value_json = {"url": candidate}
    return {"url": candidate}


@router.get("/tournaments/{tournament_id}/qr/{target}")
def qr_code(tournament_id: int, target: str, request: Request, session: Session = Depends(get_session)) -> RawResponse:
    if session.get(Tournament, tournament_id) is None:
        raise HTTPException(status_code=404, detail={"message": "Турнир не найден."})
    if target != "admin":
        raise HTTPException(status_code=404, detail={"message": "Неизвестный QR-код."})
    detected_addresses = find_lan_addresses()
    base_url = (
        detected_addresses[0].url()
        if detected_addresses
        else local_hostname_url()
        or str(request.base_url).rstrip("/")
    )
    return RawResponse(qr_svg(f"{base_url}/login/{tournament_id}"), media_type="image/svg+xml")


@router.post("/tournaments/{tournament_id}/levels")
async def replace_levels(tournament_id: int, payload: dict[str, Any], request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    if admin_tournament_id(request) != tournament_id:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    try:
        levels_payload = list(payload.get("levels", []))
        if "late_registration_end_level_number" in payload:
            raw_cutoff = payload.get("late_registration_end_level_number")
            if raw_cutoff in (None, "", -1):
                cutoff = None
            else:
                try:
                    play_level_number = int(raw_cutoff)
                except (TypeError, ValueError) as error:
                    raise DomainError(
                        "invalid_late_registration_end",
                        "Выберите существующий игровой уровень для окончания поздней регистрации.",
                    ) from error
                play_indexes = [
                    index for index, level in enumerate(levels_payload) if level.get("kind") == "play"
                ]
                if not 1 <= play_level_number <= len(play_indexes):
                    raise DomainError(
                        "invalid_late_registration_end",
                        "Выберите существующий игровой уровень для окончания поздней регистрации.",
                    )
                cutoff = play_indexes[play_level_number - 1]
        else:
            cutoff = payload.get("late_registration_end_level_index")
            try:
                cutoff = None if cutoff in (None, "", -1) else int(cutoff)
            except (TypeError, ValueError) as error:
                raise DomainError(
                    "invalid_late_registration_end",
                    "Выберите существующий игровой уровень для окончания поздней регистрации.",
                ) from error
        LevelService.replace_levels(
            session,
            tournament_id,
            levels_payload,
            request_id=payload.get("request_id"),
            late_registration_end_level_index=cutoff,
        )
        result = tournament_state(session, tournament_id)
        await request.app.state.ws_manager.broadcast_state(tournament_id)
        return result
    except DomainError as error:
        raise error_response(error) from error


@router.post("/tournaments/{tournament_id}/payouts")
async def replace_payouts(
    tournament_id: int,
    payload: dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if admin_tournament_id(request) != tournament_id:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    try:
        PayoutService.save_structure(
            session,
            tournament_id,
            payload.get("percentages"),
            request_id=payload.get("request_id"),
        )
        result = tournament_state(session, tournament_id)
        await request.app.state.ws_manager.broadcast_state(tournament_id)
        return result
    except DomainError as error:
        raise error_response(error) from error


@router.post("/tournaments/{tournament_id}/payouts/finalize")
async def finalize_payouts(
    tournament_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if admin_tournament_id(request) != tournament_id:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    try:
        PayoutService.finalize_registration(session, tournament_id)
        result = tournament_state(session, tournament_id)
        await request.app.state.ws_manager.broadcast_state(tournament_id)
        return result
    except DomainError as error:
        raise error_response(error) from error
