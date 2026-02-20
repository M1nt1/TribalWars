"""Defense manager - detect incoming attacks and trigger safety actions."""

from __future__ import annotations

from staemme.core.exceptions import IncomingAttackError
from staemme.core.logging import get_logger
from staemme.game.screens.overview import OverviewScreen
from staemme.game.screens.rally_point import RallyPointScreen
from staemme.models.village import Village

log = get_logger("manager.defense")


class DefenseManager:
    """Detects incoming attacks and manages defensive responses."""

    def __init__(
        self,
        overview: OverviewScreen,
        rally: RallyPointScreen,
    ) -> None:
        self.overview = overview
        self.rally = rally
        self._notified_attacks: set[int] = set()  # village IDs already notified

    async def check(self, village: Village, village_id: int) -> bool:
        """Check for incoming attacks. Returns True if attack detected."""
        # Check from overview data (already fetched)
        incoming = village.incoming_attacks

        # Double-check via rally point for accuracy
        if incoming == 0:
            incoming = await self.rally.get_incoming_attacks(village_id)

        if incoming > 0:
            log.warning(
                "incoming_attack_detected",
                village=village_id,
                village_name=village.name,
                count=incoming,
            )

            if village_id not in self._notified_attacks:
                self._notified_attacks.add(village_id)
                self._send_notification(village, incoming)

            return True

        # Clear notification state if no longer under attack
        self._notified_attacks.discard(village_id)
        return False

    def _send_notification(self, village: Village, count: int) -> None:
        """Send desktop notification about incoming attack."""
        try:
            from plyer import notification

            notification.notify(
                title="Incoming Attack!",
                message=f"{village.name} ({village.x}|{village.y}): {count} incoming attack(s)",
                app_name="Staemme Bot",
                timeout=10,
            )
        except Exception as e:
            log.error("notification_failed", error=str(e))
