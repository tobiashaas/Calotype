from calotype_domain.failures import FailureCode, ProfileNotReadyError, TooFewPhotosError, failure_code


def test_a_failed_job_gets_its_exceptions_code_else_processing_error():
    assert failure_code(ProfileNotReadyError("no model")) == "profile_not_ready"
    assert failure_code(TooFewPhotosError("2 photos")) == "too_few_photos"
    assert failure_code(ValueError("boom")) == FailureCode.PROCESSING_ERROR.value == "processing_error"
