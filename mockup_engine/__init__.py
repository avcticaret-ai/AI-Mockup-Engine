"""AI Mockup Engine -- CV tabanli mockup compositor."""

from .compositor import CompositeSettings, render
from .library import BaseModel, LibraryError, list_models, load_model
from .pipeline import generate_mockup, load_design
from .recolor import (
    COLOR_PRESETS,
    RecolorSettings,
    lightness_spread,
    recolor_garment,
)

__version__ = "0.1.0"

__all__ = [
    "CompositeSettings",
    "render",
    "BaseModel",
    "LibraryError",
    "list_models",
    "load_model",
    "generate_mockup",
    "load_design",
    "COLOR_PRESETS",
    "RecolorSettings",
    "recolor_garment",
    "lightness_spread",
]
