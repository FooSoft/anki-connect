# Legacy tests

This suite targets the original action implementation and obsolete pytest-anki
interfaces. It is retained as regression/reference material and is excluded from
the default test run. Use `tests_api/` and the commands in the repository README
for the rewritten runtime. GUI integration uses disposable profiles and a working
display; native/admission tests alone do not certify WebEngine behavior.
