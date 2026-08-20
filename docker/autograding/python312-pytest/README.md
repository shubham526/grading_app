# v2.3.3 structured pytest runtime image

Build locally from the repository root:

```bash
docker build \
  -t grading-app-python312-pytest:9.1.1 \
  docker/autograding/python312-pytest
```

Verify:

```bash
docker run --rm --network none --pull=never \
  grading-app-python312-pytest:9.1.1 \
  python -c 'import pytest; print(pytest.__version__)'
```

Expected output: `9.1.1`.

The application records the resulting local image ID in execution provenance.
It does not auto-pull or auto-build this image.
