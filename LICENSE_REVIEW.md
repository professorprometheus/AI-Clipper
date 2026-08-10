# Dependency licence review

Reviewed for the V0 development path on 2026-08-10.

| Dependency | Purpose | Licence | V0 assessment |
|---|---|---|---|
| FastAPI | HTTP application | MIT | Compatible |
| Starlette | ASGI framework (transitive) | BSD-3-Clause | Compatible |
| Uvicorn | ASGI server | BSD-3-Clause | Compatible |
| Pydantic | Validation | MIT | Compatible |
| python-multipart | Form parsing | Apache-2.0 | Compatible |
| imageio-ffmpeg | Bundled FFmpeg executable discovery | BSD-2-Clause | Compatible; FFmpeg build/licence must be re-reviewed for distribution |
| httpx | Test client | BSD-3-Clause | Development only; compatible |
| pytest | Tests | MIT | Development only; compatible |
| Ruff | Lint/format | MIT | Development only; compatible |

ALPHA does not redistribute third-party footage. Fixture video is generated locally. Before commercial binary distribution, capture the exact FFmpeg build configuration and repeat an LGPL/GPL feature review.

