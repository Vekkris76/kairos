"""Kairos actors — long-lived components that react to engine events.

The Actor ABC is the foundation for the SaaS-side actors that already
exist in Trading Autopilot v2 (Protection, Intelligence, Learning,
Notification, ParameterTuner). It is also the base class for Kairos's
own future actors (IngestionActor in v0.4, etc.).
"""

from __future__ import annotations

from kairos.actors.base import Actor, ActorConfig

__all__ = ["Actor", "ActorConfig"]
