# Attachment Loader for ArcGIS Pro

Attach local files to ArcGIS feature records by matching normalized filenames to a feature attribute. The original use case is attaching subdivision plat PDFs/TIFFs to polygon features, but the tool also supports other attachment types such as JPG, PNG, DOCX, or ZIP when you configure the extensions.

The safest workflow is:

1. Run a size-only report.
2. Run a dry-run matching report.
3. Review the CSV reports.
4. Add attachments to a copied feature class.
5. Optionally overwrite a hosted feature layer after verification passes.

## Requirements

- ArcGIS Pro with a licensed ArcPy environment for feature-class attachment and hosted-layer overwrite operations.
- Python 3.10 or newer.
- No third-party Python packages are required for dry-run, matching, size checks, or tests.

ArcPy is imported only when needed. `--size-only` and the unit tests run in a normal Python environment. Everything else, including the dry-run matching report, reads the feature class through ArcPy and must run in ArcGIS Pro's Python environment (for example the ArcGIS Pro Python Command Prompt, `propy.bat`, or the Pro Python window). Hosted overwrite also tries the ArcGIS API for Python (`arcgis`, included with ArcGIS Pro) for an optional, best-effort preflight check.

## Repository layout

```text
attachment-loader-arcpy/
  attach_plats_to_feature_layer.py      # runner that works without installing
  pyproject.toml
  README.md
  CONTRIBUTING.md
  SECURITY.md
  LICENSE
  examples/
    example_config.json
  src/
    plat_attachment_loader/
      cli.py            # argument parsing, interactive prompts, workflow
      config.py         # default drop words, aliases, extensions; JSON config
      matching.py       # filename/key normalization and folder scanning
      planning.py       # match plan and QA logic
      reports.py        # CSV and metadata writers
      arcpy_tools.py    # ArcPy operations (copy, attach, verify)
      publish.py        # hosted feature layer overwrite
  tests/
    test_matching.py
    test_planning.py
    test_reports.py
```

## Quick start

From a terminal using ArcGIS Pro's Python environment:

```bat
python attach_plats_to_feature_layer.py --help
```

You can also install the package into the ArcGIS Pro environment (Esri recommends a cloned environment rather than changing the default `arcgispro-py3`), which adds a `plat-attachment-loader` command:

```bat
python -m pip install -e .
plat-attachment-loader --help
```

`python -m plat_attachment_loader` works too when `src` is on your Python path or the package is installed.

### Interactive mode

Run the script with no arguments to be prompted for each setting instead. If console input is not available, the prompts open as simple dialog boxes instead. Interactive defaults write outputs to your Documents folder.

## Recommended safe workflow

### 1. Size report only

This does not import ArcPy.

```bat
python attach_plats_to_feature_layer.py ^
  --size-only ^
  --attachments-dir "path\to\attachments" ^
  --recursive ^
  --max-mb 10 ^
  --report-csv "reports\attachment_size_report.csv"
```

### 2. Dry-run matching report

This reads the feature class and writes two CSV reports, but does not add attachments.

```bat
python attach_plats_to_feature_layer.py ^
  --input-features "path\to\data.gdb\features" ^
  --key-field "FEATURE_KEY" ^
  --attachments-dir "path\to\attachments" ^
  --recursive ^
  --report-csv "reports\attachment_report.csv" ^
  --missing-report-csv "reports\features_missing_attachments.csv"
```

### 3. Attach to a copied output feature class

This is the recommended production workflow because it avoids modifying the original feature class.

```bat
python attach_plats_to_feature_layer.py ^
  --input-features "path\to\data.gdb\features" ^
  --key-field "FEATURE_KEY" ^
  --attachments-dir "path\to\attachments" ^
  --recursive ^
  --attach ^
  --output-gdb "path\to\attachment_output.gdb" ^
  --output-name "features_with_attachments" ^
  --overwrite-output
```

### 4. Attach in place

Use this only when you intentionally want to modify the input dataset.

```bat
python attach_plats_to_feature_layer.py ^
  --input-features "path\to\data.gdb\features" ^
  --key-field "FEATURE_KEY" ^
  --attachments-dir "path\to\attachments" ^
  --recursive ^
  --attach ^
  --in-place ^
  --output-gdb "path\to\attachment_work_tables.gdb" ^
  --overwrite-output
```

`--output-gdb` is still used in in-place mode because ArcGIS needs a local match table (`plat_attachment_match`) for adding attachments. The tool creates this geodatabase if it does not exist, and `--overwrite-output` lets it replace an existing match table.

### 5. Attach and overwrite a hosted feature layer

Hosted overwrite is blocked by default if file-side or feature-side QA is incomplete.

```bat
python attach_plats_to_feature_layer.py ^
  --input-features "path\to\data.gdb\features" ^
  --key-field "FEATURE_KEY" ^
  --attachments-dir "path\to\attachments" ^
  --recursive ^
  --attach ^
  --output-gdb "path\to\attachment_output.gdb" ^
  --output-name "features_with_attachments" ^
  --overwrite-output ^
  --overwrite-online ^
  --service-name "HostedFeatureLayerName" ^
  --portal-folder "PortalFolderName" ^
  --aprx "path\to\project.aprx"
```

Publishing builds a web layer sharing draft in an ArcGIS Pro project and uploads it with the portal user currently signed in to ArcGIS Pro. Related options:

- `--aprx`: project used for the sharing draft. The default, `CURRENT`, only works when the tool runs inside ArcGIS Pro (Python window, notebook, or script tool). From a terminal, pass the path to a `.aprx` file.
- `--map-name`: map to add the layer to; created if missing. Default: `Attachment Publish`.
- `--layer-name`: published layer name. Default: the feature class name.
- `--summary`, `--tags`: item summary and tags on the sharing draft.

See [Hosted overwrite safety gates](#hosted-overwrite-safety-gates) for the checks that must pass first.

## Matching rules

The tool normalizes both filenames and feature key values by:

- uppercasing text,
- replacing punctuation with spaces,
- replacing `&` with `AND`,
- dropping common noise words such as `PLAT`, `FINAL`, and `SUBDIVISION`,
- applying aliases such as `ADDITION` to `ADDN`.

The full default word and alias lists are in `src/plat_attachment_loader/config.py`. By default only `.pdf`, `.tif`, and `.tiff` files are scanned.

Example:

```text
The Oak Hills Addition Final Plat.pdf
```

normalizes to:

```text
OAK HILLS ADDN
```

## Custom configuration

Use a JSON config file when another organization has different naming conventions.

```bat
python attach_plats_to_feature_layer.py ^
  --input-features "path\to\data.gdb\features" ^
  --key-field "FEATURE_KEY" ^
  --attachments-dir "path\to\attachments" ^
  --config examples\example_config.json
```

Example config (`examples/example_config.json`):

```json
{
  "merge_with_defaults": true,
  "drop_words": ["APPROVED", "CORRECTED", "REDUCED", "SCAN"],
  "aliases": {
    "ADD": "ADDN",
    "ADN": "ADDN",
    "NO": "NUMBER",
    "NUM": "NUMBER"
  },
  "extensions": [".pdf", ".tif", ".tiff", ".jpg", ".jpeg", ".png"]
}
```

With `merge_with_defaults` set to `true` (the default), these values are added to the built-in lists. Set it to `false` to replace the built-in lists entirely.

Command-line extensions override config extensions:

```bat
--extensions ".pdf,.tif,.jpg,.png,.docx,.zip"
```

## Filename regex

Use `--filename-regex` when the matching name is only part of the filename.

```bat
--filename-regex "^(?P<name>.+?)_recorded_\d+\.pdf$"
```

A named group called `name` wins. If there is no named group, the first capture group is used. If the regex does not match, the filename stem is used.

## Overlay folders

An overlay folder can replace files from the base attachment folder. This is useful when you have original large files in one folder and compressed/reduced versions in another.

Default replacement mode is relative path:

```bat
--overlay-dir "path\to\reduced-attachments" --overlay-match-by relative-path
```

Use normalized-name matching when the overlay folder is flat or does not mirror the original folder structure:

```bat
--overlay-dir "path\to\reduced-attachments" --overlay-match-by normalized-name
```

## Reports

The main report has one row per discovered attachment-file result:

- `matched`: file can be attached to a feature row.
- `unmatched`: file did not match any feature key.
- `ambiguous`: file matched more than one feature and `--attach-to-all-matches` was not used.
- `too_large`: file is over `--max-mb`.

The missing-feature report has one row per feature that will not receive, or still does not have, a verified expected attachment. Reasons include:

- `blank_key_field`
- `no_matching_attachment_file`
- `matching_attachment_file_too_large`
- `not_planned_for_attachment`
- `ready_to_attach` after attachment verification, meaning the feature had a valid source file but the expected attachment was not verified.

On the command line, reports are written to the current folder by default: `attachment_report.csv`, plus `attachment_report_missing_features.csv` unless `--missing-report-csv` is given. Reports include run metadata columns and a sidecar metadata file named like:

```text
attachment_report.csv.metadata.json
```

You can also write a one-row run summary:

```bat
--run-summary-csv "reports\attachment_run_summary.csv"
```

## Duplicate attachment handling

The default behavior is safe for re-runs:

```bat
--existing-attachment-policy skip
```

Policies:

- `skip`: skip a planned row if the same filename is already attached to the same ObjectID.
- `replace`: delete existing attachments with the same ObjectID and filename before adding the new file.
- `allow`: add duplicates.

## Hosted overwrite safety gates

Hosted overwrite is blocked unless all enabled checks pass:

- file-side report has no unresolved rows,
- feature-side report has no missing rows,
- post-attachment verification confirms expected filenames exist on expected ObjectIDs.

Use targeted exceptions only when they represent the intended business rule:

```bat
--ignore-unmatched-files
--ignore-missing-features
```

Use the full override only when you deliberately want to publish an incomplete result:

```bat
--allow-incomplete-overwrite
```

## Exit codes

- `0`: finished (or dry run completed).
- `1`: stopped with an error message, such as a bad path or missing field.
- `2`: size-only run found files over `--max-mb`.
- `4`: stopped before attaching because hosted overwrite would be incomplete.
- `5`: attachments were added locally, but post-attachment verification failed, so hosted overwrite was skipped.

## Logging

```bat
--log-level DEBUG --log-file "logs\attachment_loader.log"
```

## Running tests

The included tests cover the pure-Python matching, planning, and reporting logic. They do not require ArcPy.

```bat
python -m unittest discover -s tests
```

## Notes for organizations adapting this tool

Before using this in production, decide:

- which field is the authoritative feature key,
- which words should be dropped during normalization,
- which aliases should be used,
- whether duplicate keys should receive the same attachment,
- whether unmatched files should block publishing,
- whether every feature is required to have an attachment,
- what maximum file size your portal allows or your organization is willing to support.

## Limitations

- Hosted overwrite depends on the currently signed-in ArcGIS Pro portal user.
- Preflight portal search is best-effort because item titles and service names may differ by organization.
- Attachment verification checks expected attachment filenames by ObjectID. It does not hash file contents.
- The script is designed for local feature classes/layers as the attachment source before optional hosted overwrite.
