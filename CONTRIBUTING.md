# Contributing

Thanks for improving Plat Attachment Loader.

## Development setup

The unit tests cover pure-Python matching, planning, and reporting behavior and do not require ArcGIS Pro.

```bat
python -m pip install -e .
python -m unittest discover -s tests
python -m compileall -q src tests attach_plats_to_feature_layer.py
```

ArcPy-specific workflows should be manually verified in ArcGIS Pro before release when a change touches attachment creation, feature-class copying, or hosted-layer publishing.

## Pull request checklist

- Keep examples generic. Do not commit local paths, portal URLs, hosted item IDs, or organization-specific names.
- Add or update tests for matching, planning, reporting, or config behavior.
- Keep generated files out of commits, including geodatabases, service definitions, CSV reports, logs, and `__pycache__` folders.
- Document new command-line options in `README.md`.
