from workbench.urls import canonical_url, is_tracking_param


def test_strips_known_tracking_params():
    url = "https://careers.example.com/apply?jobid=333&utm_medium=social&trk=abc&gh_src=x"
    assert canonical_url(url) == "https://careers.example.com/apply?jobid=333"


def test_keeps_functional_params_and_their_order():
    url = "https://x.example.com/j?source=board&id=9&ref=abc&token=t1&page=2"
    assert canonical_url(url) == url


def test_utm_prefix_is_case_insensitive():
    assert is_tracking_param("UTM_Campaign")
    assert is_tracking_param("utm_jobgroup")
    assert not is_tracking_param("jobid")
    assert not is_tracking_param("source")


def test_removes_fragment_and_lowercases_host():
    assert canonical_url("HTTPS://Jobs.Example.ORG/555#apply") == "https://jobs.example.org/555"


def test_linkedin_regional_subdomain_is_normalised():
    a = canonical_url("https://in.linkedin.com/jobs/view/111?trk=public_jobs")
    b = canonical_url("https://www.linkedin.com/jobs/view/111/")
    assert a == b == "https://www.linkedin.com/jobs/view/111"


def test_trailing_slash_removed_but_root_kept():
    assert canonical_url("https://example.com/jobs/") == "https://example.com/jobs"
    assert canonical_url("https://example.com/") == "https://example.com/"


def test_malformed_or_empty_input_is_returned_stripped():
    assert canonical_url("  not a url  ") == "not a url"
    assert canonical_url("") == ""
    assert canonical_url(None) == ""
