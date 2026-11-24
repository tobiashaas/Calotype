"""Why a job failed, as a code clients can branch on (the failure reason is text for people).

A worker that fails a job stores ``failure_code(exc)`` next to the reason; the API returns it
in the job snapshot, the Bridge passes it on, and the Lightroom plugin picks its message by
the code instead of searching the reason's text.
"""

from __future__ import annotations

from enum import StrEnum


class FailureCode(StrEnum):
    # Without a profile, the selection holds no edited photo to learn the look from.
    NO_EXAMPLES = "no_examples"
    # The profile cannot edit (yet): not found, or no trained model.
    PROFILE_NOT_READY = "profile_not_ready"
    # Too few photos with a usable preview and decided sliders to train a profile.
    TOO_FEW_PHOTOS = "too_few_photos"
    # Anything else: the reason says what.
    PROCESSING_ERROR = "processing_error"


class JobFailure(Exception):
    """A failure the photographer can act on; subclasses set ``code``."""

    code: FailureCode = FailureCode.PROCESSING_ERROR


def failure_code(exc: BaseException) -> str:
    """The code a failed job gets for ``exc``: its own, else ``processing_error``."""
    code = getattr(exc, "code", None)
    return str(code) if isinstance(code, FailureCode) else FailureCode.PROCESSING_ERROR.value


class ProfileNotReadyError(JobFailure, ValueError):
    """The profile cannot edit: not found, or it has no trained model."""

    code = FailureCode.PROFILE_NOT_READY


class TooFewPhotosError(JobFailure, ValueError):
    """Too few usable training photos for a profile."""

    code = FailureCode.TOO_FEW_PHOTOS
