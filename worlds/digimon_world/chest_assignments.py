"""Per-chest grant assignments (Phase 5 piece A).

Decides, for each of the 65 named chest AP locations, whether vanilla
DW1 should grant the chest's contents directly via the in-game pickup
flow, or whether the chest should display "AP ITEM" and AP should
deliver the contents separately to the player's bank.

The deciding rule:

* If AP fill placed an own-slot item AND that item has a DW1 internal
  ID (i.e. lives in the 2000-block — consumables, DV items, key items),
  the chest grants that item directly (vanilla flow). The AP item
  delivery is suppressed client-side so the player doesn't get a
  duplicate in their bank.
* Otherwise the chest gets the
  :data:`worlds.digimon_world.data.addresses.AP_CHEST_SENTINEL_ITEM_ID`
  byte. Vanilla shows the "AP ITEM" placeholder, the
  :func:`worlds.digimon_world.data.addresses.ROM_CHEST_GIVEITEM_PATCH_VALUE`
  wrapper short-circuits the inventory write, and the AP server
  delivers the real item to the bank via the client.

The per-chest decision is made at :meth:`World.fill_slot_data` time
(after fill has run) so the result is fully deterministic from AP's
final placement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from .data.addresses import (
    AP_CHEST_SENTINEL_ITEM_ID,
    CHEST_NAME_TO_ROM_OFFSETS,
)
from .items import dw1_internal_item_id

if TYPE_CHECKING:
    from .world import DigimonWorldWorld


class ChestGrant(NamedTuple):
    """One chest's resolved item-byte assignment.

    :param chest_name: AP location name (e.g. ``"Chest: Mt. Infinity 1"``).
    :param item_byte: The 1-byte item ID written into the chest's
        spawnChest opcode. Either a real DW1 internal id (0..127) or
        :data:`AP_CHEST_SENTINEL_ITEM_ID`.
    :param vanilla_grant: ``True`` when the chest hands the player its
        item directly (real DW1 id); the AP client must skip the bank
        delivery for the AP-side item placed at this location.
    """

    chest_name: str
    item_byte: int
    vanilla_grant: bool


def build_chest_grants(world: DigimonWorldWorld) -> dict[str, ChestGrant]:
    """Return ``{chest_name: ChestGrant}`` for every named chest.

    Iterates the 65 named chest AP locations, inspects what AP fill
    placed at each, and decides the per-chest item byte. Chests that
    aren't on the player's location list (shouldn't normally happen,
    but defensive) are skipped.
    """

    out: dict[str, ChestGrant] = {}
    for chest_name in CHEST_NAME_TO_ROM_OFFSETS:
        try:
            location = world.get_location(chest_name)
        except KeyError:
            continue

        placed = location.item
        if placed is None:
            out[chest_name] = ChestGrant(chest_name, AP_CHEST_SENTINEL_ITEM_ID, False)
            continue

        # Vanilla-grant only when the placed item is the player's own
        # AND has a DW1-internal item id. Other-player items always go
        # via the AP delivery path.
        if placed.player != world.player:
            out[chest_name] = ChestGrant(chest_name, AP_CHEST_SENTINEL_ITEM_ID, False)
            continue

        dw1_id = dw1_internal_item_id(placed.name)
        if dw1_id is None:
            out[chest_name] = ChestGrant(chest_name, AP_CHEST_SENTINEL_ITEM_ID, False)
            continue

        out[chest_name] = ChestGrant(chest_name, dw1_id, True)

    return out


__all__ = [
    "ChestGrant",
    "build_chest_grants",
]
