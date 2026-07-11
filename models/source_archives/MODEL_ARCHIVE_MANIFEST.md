# Model Archive Manifest

Last checked: 2026-06-30

| Archive | SHA256 | Extracted folder | Weight/checkpoint files found | Current role |
| --- | --- | --- | --- | --- |
| `timesfm-2.0.1.zip` | `F7B3D68FA48FF675CD9384623EFC8DBED75E41A2C3C1A46B0398E964E3A94DB9` | `models/source_archives/timesfm-2.0.1` | No | Source/reference archive for optional TimesFM integration work |
| `toto-toto-models-v1.0.0.zip` | `C06EA169D7A9A05A2685D4A0570A887C5472A2D2AB6C34E2A7BCC9BB4F7237B5` | `models/source_archives/toto-toto-models-v1.0.0` | No | Source/reference archive for optional Toto integration work |

Runtime model folders remain:

- `models/timesfm/` for actual TimesFM checkpoint files, for example `models/timesfm/timesfm-2.5-200m-transformers`.
- `models/toto/` for actual Toto checkpoint files, for example `models/toto/Toto-2.0-313m`.

The app must continue to report TimesFM and Toto as unavailable or baseline-only until both the compatible Python runtime package and the expected local checkpoint folder with weight files are installed. These source archives alone are not sufficient evidence for live model forecasts.
