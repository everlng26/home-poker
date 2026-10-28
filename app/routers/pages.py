from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import PROJECT_DIR

templates = Jinja2Templates(directory=str(PROJECT_DIR / "app" / "templates"))
router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {"page_title": "Домашний покер"})


@router.get("/tournaments/new", response_class=HTMLResponse)
def new_tournament(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "create.html", {"page_title": "Создание турнира"})


@router.get("/chips", response_class=HTMLResponse)
def chip_sets(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "chips/index.html", {"page_title": "Фишки"})


@router.get("/stack-optimizer", response_class=HTMLResponse)
def stack_optimizer(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "stack_optimizer.html",
        {"page_title": "Конструктор стеков"},
    )


@router.get("/structure-generator", response_class=HTMLResponse)
def structure_generator(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "structure_generator.html",
        {"page_title": "Генератор структуры"},
    )


@router.get("/chips/new", response_class=HTMLResponse)
def new_chip_set(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "chips/form.html",
        {"page_title": "Новый набор фишек", "chip_set_id": None},
    )


@router.get("/chips/{chip_set_id}/edit", response_class=HTMLResponse)
def edit_chip_set(request: Request, chip_set_id: int) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "chips/form.html",
        {"page_title": "Редактирование набора", "chip_set_id": chip_set_id},
    )


@router.get("/login/{tournament_id}", response_class=HTMLResponse)
def login(request: Request, tournament_id: int) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html", {"page_title": "Вход", "tournament_id": tournament_id})


@router.get("/admin/{tournament_id}", response_class=HTMLResponse)
def admin(request: Request, tournament_id: int) -> HTMLResponse:
    return templates.TemplateResponse(request, "admin.html", {"page_title": "Админка", "tournament_id": tournament_id})


@router.get("/display/{tournament_id}", response_class=HTMLResponse)
def display(request: Request, tournament_id: int) -> HTMLResponse:
    return templates.TemplateResponse(request, "display.html", {"page_title": "Турнир", "tournament_id": tournament_id})
