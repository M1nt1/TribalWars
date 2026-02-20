"""Human-like delay generation and action randomization."""

from __future__ import annotations

import asyncio
import random

from staemme.core.config import HumanizerConfig
from staemme.core.logging import get_logger

log = get_logger("humanizer")


class Humanizer:
    """Generates human-like delays between bot actions."""

    def __init__(self, config: HumanizerConfig) -> None:
        self.config = config

    def _gauss_delay(self) -> float:
        """Generate a Gaussian-distributed delay within the configured range."""
        low, high = self.config.delay_range
        mean = (low + high) / 2
        stddev = (high - low) / 4  # ~95% of values within range
        delay = random.gauss(mean, stddev)
        # Apply jitter
        jitter = delay * self.config.jitter_factor * random.uniform(-1, 1)
        delay += jitter
        return max(low * 0.5, min(delay, high * 1.5))  # clamp

    async def wait(self, label: str = "action") -> None:
        """Wait a human-like delay before the next action."""
        # Chance of a long pause (simulating distraction)
        if random.random() < self.config.long_pause_chance:
            low, high = self.config.long_pause_range
            delay = random.uniform(low, high)
            log.debug("long_pause", label=label, seconds=round(delay, 1))
        else:
            delay = self._gauss_delay()
            log.debug("delay", label=label, seconds=round(delay, 1))
        await asyncio.sleep(delay)

    async def short_wait(self) -> None:
        """Short delay for rapid consecutive actions (e.g., parsing pages)."""
        delay = random.uniform(0.3, 1.2)
        await asyncio.sleep(delay)

    @staticmethod
    def shuffle_order(items: list) -> list:
        """Return a shuffled copy of a list to randomize action order."""
        shuffled = items.copy()
        random.shuffle(shuffled)
        return shuffled

    @staticmethod
    def random_cycle_delay(delay_range: tuple[int, int]) -> float:
        """Generate a random cycle delay within bounds."""
        low, high = delay_range
        return random.uniform(low, high)
