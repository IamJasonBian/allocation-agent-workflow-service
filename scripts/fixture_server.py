"""Local ATS-shaped fixture for end-to-end signal-detection testing.

Serves three flavors of fake apply page on http://127.0.0.1:9999:

  GET  /jobs/happy/<id>       → full form; on submit navigates to /thanks/<id>
  GET  /jobs/broken/<id>      → full form; on submit returns 400 with the same form
  GET  /thanks/<id>           → "Thank you for applying" confirmation

Used by `scripts/run_fixture_test.sh` and the corresponding DOVER_JOBS_PATH
fixture at src/allocation_agent/fixtures/local-fixture-jobs.json.
"""

from __future__ import annotations

import argparse
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import uvicorn


APPLY_FORM = """
<!DOCTYPE html>
<html>
<head><title>Apply for {title}</title></head>
<body>
  <h1>Apply for {title}</h1>
  <form method="POST" action="{action}" enctype="multipart/form-data">
    <input type="text"  name="firstName"   placeholder="First Name" required><br>
    <input type="text"  name="lastName"    placeholder="Last Name"  required><br>
    <input type="email" name="email"       placeholder="Email"      required><br>
    <input type="text"  name="phone"       placeholder="Phone"><br>
    <input type="text"  name="linkedinUrl" placeholder="LinkedIn URL"><br>
    <input type="file"  name="resume" accept=".pdf"><br>
    <button type="submit">Submit Application</button>
  </form>
</body>
</html>
"""

THANKS_PAGE = """
<!DOCTYPE html>
<html>
<head><title>Thanks</title></head>
<body>
  <h1>Thank you!</h1>
  <p>We've received your application and will be in touch.</p>
</body>
</html>
"""


def build_app() -> FastAPI:
    app = FastAPI(title="allocation-agent fixture server")

    @app.get("/jobs/happy/{job_id}", response_class=HTMLResponse)
    async def happy(job_id: str) -> str:
        return APPLY_FORM.format(
            title=f"Happy SWE {job_id}",
            action=f"/submit/happy/{job_id}",
        )

    @app.post("/submit/happy/{job_id}")
    async def submit_happy(job_id: str):
        return RedirectResponse(url=f"/thanks/{job_id}", status_code=303)

    @app.get("/thanks/{job_id}", response_class=HTMLResponse)
    async def thanks(job_id: str) -> str:
        return THANKS_PAGE

    @app.get("/jobs/broken/{job_id}", response_class=HTMLResponse)
    async def broken_get(job_id: str) -> str:
        # Form posts back to the SAME URL so a failed submit leaves the page unchanged.
        return APPLY_FORM.format(
            title=f"Broken SWE {job_id}",
            action=f"/jobs/broken/{job_id}",
        )

    @app.post("/jobs/broken/{job_id}", response_class=HTMLResponse)
    async def broken_post(job_id: str):
        # 4xx + same page → url unchanged, form still present, no server_ack,
        # no "thank you" text. Zero signals converge.
        return HTMLResponse(
            APPLY_FORM.format(title=f"Broken SWE {job_id}", action=f"/jobs/broken/{job_id}"),
            status_code=400,
        )

    @app.get("/health")
    async def health():
        return {"ok": True}

    return app


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9999)
    args = p.parse_args()
    uvicorn.run(build_app(), host=args.host, port=args.port, log_level="warning")
