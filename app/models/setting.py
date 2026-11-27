"""Key/value user settings (display temperature unit, etc.)."""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Display units. Temperatures are stored in Celsius and weights in grams;
# these say how to show them. Fahrenheit by default because that is the
# kitchen this runs in; grams because that is how the rye recipes are written.
#
# The timing keys below drive the feeding ribbon and the bake-day planner:
#   feeds_per_day           how many feeds a day an active jar gets, so the
#                           cycle is 24 h divided by it. A jar may override.
#   default_ferment_temp_c  what to assume when a feeding was logged without
#                           an ambient temperature. 26.7 °C is 80 °F, the
#                           proofing box setting.
#   ribbon_span_h           how much time the ribbon shows at once.
#   preheat_pot_min         how long before the bake a lidded cast-iron pot
#                           needs in the oven. 45 minutes is the floor for a
#                           pot heavy enough to be worth using; the preheat
#                           runs alongside the final proof, not after it.
#   preheat_oven_min        the same heads-up for a bake on a tray or in a
#                           tin, where only the air has to come up to
#                           temperature. Much shorter, so it is its own key.
#   fold_sets               how many sets of stretch-and-folds a bulk
#                           ferment gets a reminder for. 0 turns them off.
#   fold_every_min          how far apart the sets are, counted from when
#                           the bulk began.
#   lid_off_after_min       how long the lid stays on a pot bake before the
#                           reminder to take it off. 0 turns it off.
DEFAULT_SETTINGS = {
    "temp_unit": "F",
    "weight_unit": "g",
    "feeds_per_day": "2",
    "default_ferment_temp_c": "26.7",
    "ribbon_span_h": "48",
    "preheat_pot_min": "45",
    "preheat_oven_min": "20",
    "fold_sets": "4",
    "fold_every_min": "30",
    "lid_off_after_min": "20",
}

#: Offered in the settings form. One or two feeds a day; more is a levain.
FEEDS_PER_DAY_CHOICES = (1, 2)
#: How far the ribbon looks, in hours.
RIBBON_SPAN_CHOICES = (24, 48, 72)
#: How long a cast-iron pot gets in the oven before the loaf goes in.
PREHEAT_POT_CHOICES = (30, 45, 60)
#: The same for a plain oven bake, where there is no mass to heat.
PREHEAT_OVEN_CHOICES = (10, 15, 20, 30)
#: Sets of stretch-and-folds to be reminded of. 0 is "do not remind me".
FOLD_SETS_CHOICES = (0, 1, 2, 3, 4, 5, 6)
#: Minutes between one set and the next.
FOLD_EVERY_CHOICES = (20, 30, 45, 60)
#: Minutes the lid stays on a pot bake. 0 is "do not remind me".
LID_OFF_CHOICES = (0, 15, 20, 25, 30)


class Setting(Base):
    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)

    def __repr__(self) -> str:
        return f"Setting(key={self.key!r}, value={self.value!r})"
