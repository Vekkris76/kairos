"""Exceptions raised by the exchange adapters."""

from __future__ import annotations


class OrderSubmissionError(Exception):
    """Raised by an exchange adapter's ``submit_order`` when the venue or
    HTTP client reports an error.

    Replaces the pre-0.3.4 sentinel pattern of returning
    ``Order(id="", status=REJECTED)`` on failure. Callers MUST be able to
    distinguish "submitted, accepted by venue" from "rejected" via the
    exception flow alone, without inspecting fields on the returned
    ``Order``. The original venue/ccxt error is chained via ``__cause__``.
    """
