FROM python:3.12-slim

ARG PYTEST_VERSION=9.1.1

RUN python -m pip install --no-cache-dir "pytest==${PYTEST_VERSION}" \
    && python -c "import pytest; assert pytest.__version__ == '${PYTEST_VERSION}'"

# Student/test execution is still forced to an unprivileged UID by docker create.
# The image contains only the runtime dependency; no submission or grader files.
