from pathlib import Path

from fastapi.templating import Jinja2Templates

from cairn.nav import nav_items

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals["nav_items"] = nav_items
