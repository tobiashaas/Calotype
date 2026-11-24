"""Domain layer: job kinds, lifecycle states, profile states (transport- and ORM-free)."""

from calotype_domain.failures import FailureCode, JobFailure, failure_code
from calotype_domain.jobs import JobKind, JobStatus
from calotype_domain.profiles import ProfileStatus

__all__ = ["FailureCode", "JobFailure", "JobKind", "JobStatus", "ProfileStatus", "failure_code"]
