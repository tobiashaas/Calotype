"""Repository implementations for all domain entities."""

from tarsier_persistence.repositories.edit_results import EditResultRepository
from tarsier_persistence.repositories.feature_vectors import FeatureVectorRepository
from tarsier_persistence.repositories.jobs import JobRepository
from tarsier_persistence.repositories.photos import PhotoRepository
from tarsier_persistence.repositories.profiles import ProfileRepository

__all__ = [
    "EditResultRepository",
    "FeatureVectorRepository",
    "JobRepository",
    "PhotoRepository",
    "ProfileRepository",
]
