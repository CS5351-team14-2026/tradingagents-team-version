# Live tests

Tests in this directory call real LLM providers and market-data APIs. They are
excluded from the default run (`addopts = -m "not integration"` in
`pyproject.toml`) and must be marked `@pytest.mark.integration`.

Run them only with credentials configured:

    pytest -m integration test/live -q

They are not run in pull-request CI; run them nightly or before a release and
keep the output as evidence for the report.
