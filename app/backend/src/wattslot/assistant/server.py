"""Serveur MCP de l'application (lot 6.1), monté sur ``/mcp`` (Streamable HTTP).

SDK officiel ``mcp`` (point n° 3 de la phase 6). Sans état et en réponses JSON : aucune session
gardée en mémoire, des échanges simples. La protection contre le détournement DNS du SDK, qui
n'accepte par défaut que « localhost », est levée : Home Assistant joint l'application par son
adresse sur le réseau local, comme l'interface (point n° 2). En mode extension, seul HA Core y
accède (``ingress.py``).
"""

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.routing import BaseRoute

from wattslot import __version__
from wattslot.assistant import tools

PATH = "/mcp"
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
# Seule action (point n° 5) : déposer une demande, sans rien effacer ; la redéposer ne change
# que sa date.
REQUEST = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)

INSTRUCTIONS = (
    "WattSlot, for a home with solar panels: daily plan of the appliances and battery, "
    "computed without you. Read the plan and its explanations with the tools; never invent "
    "times or figures. Texts in the answers are already written in the user's language."
)


def build(state: Callable[[], Any], problems: Callable[[], Awaitable[Sequence[Any]]]) -> MCPServer:
    """Serveur et ses outils ; ``state`` rend l'état de l'application (``app.state``) au moment
    de l'appel, ``problems`` les problèmes du diagnostic."""
    server: MCPServer = MCPServer(name="wattslot", version=__version__, instructions=INSTRUCTIONS)

    @server.tool(annotations=READ_ONLY)
    async def get_day_plan(day: tools.Day = "today") -> dict[str, Any]:
        """Plan of a day: appliances and times, the cost of the whole day, the next appliance
        to start today (none left if empty), battery, warnings."""
        return await tools.get_day_plan(state(), day)

    @server.tool(annotations=READ_ONLY)
    async def explain_device(device: str, day: tools.Day = "today") -> dict[str, Any]:
        """Why an appliance runs when it does: planned and actual times, reason, whether it
        started on time. No time needed in the question."""
        return await tools.explain_device(state(), device, day)

    @server.tool(annotations=READ_ONLY)
    async def get_week() -> dict[str, Any]:
        """The next days from tomorrow, about a week (no forecast beyond): production, weather,
        appliances. Today: get_day_plan."""
        return await tools.get_week(state())

    @server.tool(annotations=READ_ONLY)
    async def get_current_status() -> dict[str, Any]:
        """Right now: what powers the home, battery level, solar and appliance power."""
        return await tools.get_current_status(state())

    @server.tool(annotations=READ_ONLY)
    async def get_energy(day: str = "today") -> dict[str, Any]:
        """Measured energy of a day (today, yesterday or YYYY-MM-DD), and the plan if any."""
        return await tools.get_energy(state(), day)

    @server.tool(annotations=READ_ONLY)
    async def get_forecast(day: str = "today") -> dict[str, Any]:
        # Banc d'essai (2 x 5 essais) : avec « up to about a week ahead », qwen3 n'appelait plus
        # get_tariff pour « le prix du kWh » (0 sur 10, contre 10 sur 10 avec ce texte).
        """Weather and solar forecast of a day (today, tomorrow or YYYY-MM-DD): hour by hour
        today and tomorrow; says when the forecast ends."""
        return await tools.get_forecast(state(), day)

    @server.tool(annotations=READ_ONLY)
    def get_home() -> dict[str, Any]:
        """Appliances of the home (not today's plan), battery, solar, tariff, objective."""
        return tools.get_home(state())

    @server.tool(annotations=READ_ONLY)
    async def get_problems() -> dict[str, Any]:
        """What is wrong with the application, most serious first."""
        return await tools.get_problems(state(), problems)

    @server.tool(annotations=READ_ONLY)
    async def get_tariff(day: Literal["today", "tomorrow"] = "today") -> dict[str, Any]:
        """Electricity price (price of a kWh) per time range, off-peak hours, color of the day.
        Not the cost of the day: get_day_plan."""
        return await tools.get_tariff(state(), day)

    @server.tool(annotations=READ_ONLY)
    def get_requests() -> dict[str, Any]:
        """Requests filed in My requests: open ones, and apart those closed this week. An open
        one with a launch date has already run. Not the next appliance: get_day_plan."""
        return tools.get_requests(state())

    @server.tool(annotations=REQUEST)
    def request_device(
        device: str, latest_date: str | None = None, confirm: bool = False
    ) -> dict[str, Any]:
        """Run an appliance at the best time, by latest_date (today, tomorrow or YYYY-MM-DD).
        Call first without confirm: nothing is filed, ask the user the question returned; call
        again with confirm true if they agree."""
        return tools.request_device(state(), device, latest_date, confirm)

    return server


def routes(server: MCPServer) -> list[BaseRoute]:
    """Route ``/mcp`` à ajouter à l'application ; le gestionnaire de sessions du serveur doit
    tourner (``server.session_manager.run()``) pendant toute sa vie."""
    app = server.streamable_http_app(
        streamable_http_path=PATH,
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    return list(app.routes)
