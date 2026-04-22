#!/usr/bin/env node
/**
 * Single-job apply runner.
 *
 * Reads a dispatch JSON on stdin:
 *   { candidate_id, job: { job_id, company_id, ats, title, apply_url, ... } }
 *
 * Writes an outcome JSON on stdout:
 *   { candidate_id, job_id, ats, status, message, tokens_spent, wallclock_ms }
 *
 * Status ∈ { submitted, blocked, captcha, error, skipped, needs_auth, interrupted }
 *
 * Env:
 *   CHROME_PATH                     path to headful Chrome (defaults to macOS location)
 *   CHROME_USER_DATA_DIR            profile dir for session persistence
 *   CANDIDATE_PROFILE_JSON          path to JSON with { firstName, lastName, email, phone, linkedinUrl, resumePath }
 *   HEADLESS                        "1" to run headless (default headful for Cloudflare)
 *   NAV_TIMEOUT_MS                  page-load timeout (default 45000)
 *   ISOLATION_MODE                  "none" (default) | "mac_os_space" (abort on sustained focus loss)
 *   ISOLATION_FOCUS_LOSS_GRACE_S    seconds the tab may be hidden before abort (default 3)
 */

import { readFileSync, existsSync } from "fs";
import { resolve } from "path";
import puppeteer from "puppeteer-core";

const CHROME_PATH =
  process.env.CHROME_PATH ||
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const USER_DATA_DIR =
  process.env.CHROME_USER_DATA_DIR ||
  resolve(process.env.HOME || "", ".cache/allocation-agent/chrome-profile");
const NAV_TIMEOUT = parseInt(process.env.NAV_TIMEOUT_MS || "45000", 10);
const HEADLESS = process.env.HEADLESS === "1";
const ISOLATION_MODE = process.env.ISOLATION_MODE || "none";
const FOCUS_LOSS_GRACE_MS = Math.round(
  parseFloat(process.env.ISOLATION_FOCUS_LOSS_GRACE_S || "3") * 1000,
);

function loadCandidateProfile() {
  const path = process.env.CANDIDATE_PROFILE_JSON;
  if (!path || !existsSync(path)) {
    throw new Error(
      `CANDIDATE_PROFILE_JSON must point to a readable JSON file (got: ${path || "<unset>"})`,
    );
  }
  const profile = JSON.parse(readFileSync(path, "utf-8"));
  for (const k of ["firstName", "lastName", "email", "phone", "linkedinUrl", "resumePath"]) {
    if (!profile[k]) throw new Error(`candidate profile missing field: ${k}`);
  }
  if (!existsSync(profile.resumePath)) {
    throw new Error(`resume not found at ${profile.resumePath}`);
  }
  return profile;
}

async function readStdin() {
  let buf = "";
  for await (const chunk of process.stdin) buf += chunk;
  return JSON.parse(buf);
}

function outcome(dispatch, status, message, extra = {}) {
  return {
    candidate_id: dispatch.candidate_id,
    job_id: dispatch.job.job_id,
    ats: dispatch.job.ats,
    status,
    message,
    tokens_spent: 0,
    wallclock_ms: 0,
    ...extra,
  };
}

async function detectCaptcha(page) {
  const html = await page.content();
  const patterns = [/g-recaptcha/, /hcaptcha/, /cf-turnstile/, /verify you are human/i];
  return patterns.some((p) => p.test(html));
}

async function fillStandardFields(page, profile) {
  const fields = {
    firstName: profile.firstName,
    lastName: profile.lastName,
    email: profile.email,
    phone: profile.phone,
    phoneNumber: profile.phone,
    linkedinUrl: profile.linkedinUrl,
    linkedin: profile.linkedinUrl,
  };

  for (const [name, value] of Object.entries(fields)) {
    const input = await page.$(`input[name="${name}"]`);
    if (!input) continue;
    try {
      await input.click({ clickCount: 3 });
      await page.keyboard.press("Backspace");
      await input.type(value, { delay: 25 });
      await page.evaluate((n) => {
        const el = document.querySelector(`input[name="${n}"]`);
        if (el) el.dispatchEvent(new Event("blur", { bubbles: true }));
      }, name);
    } catch (_) {
      // keep going; partial fills still count
    }
  }
}

class IsolationViolation extends Error {
  constructor(message) {
    super(message);
    this.name = "IsolationViolation";
  }
}

function startFocusWatcher(page) {
  if (ISOLATION_MODE !== "mac_os_space") {
    return () => {};
  }
  let lostAt = null;
  let aborted = false;
  const handle = setInterval(async () => {
    try {
      const hidden = await page.evaluate(() => document.hidden || !document.hasFocus());
      if (hidden) {
        if (lostAt === null) lostAt = Date.now();
        if (Date.now() - lostAt > FOCUS_LOSS_GRACE_MS) {
          aborted = true;
          clearInterval(handle);
          page.__isolationAborted = true;
        }
      } else {
        lostAt = null;
      }
    } catch (_) {
      // page closed or navigation in flight; watcher will re-attempt next tick
    }
  }, 500);
  return () => clearInterval(handle);
}

function assertNotInterrupted(page) {
  if (page.__isolationAborted) {
    throw new IsolationViolation(
      `tab hidden >${FOCUS_LOSS_GRACE_MS}ms; Space switch mid-apply`,
    );
  }
}

async function uploadResume(page, resumePath) {
  const fileInput =
    (await page.$('input[type="file"][accept*="pdf"]')) ||
    (await page.$('input[type="file"]'));
  if (!fileInput) return false;
  await fileInput.uploadFile(resumePath);
  await new Promise((r) => setTimeout(r, 3000));
  return true;
}

async function apply(dispatch, profile) {
  const t0 = Date.now();
  const browser = await puppeteer.launch({
    executablePath: CHROME_PATH,
    headless: HEADLESS ? "new" : false,
    userDataDir: USER_DATA_DIR,
    args: [
      "--disable-blink-features=AutomationControlled",
      "--no-sandbox",
      "--disable-setuid-sandbox",
    ],
  });

  let stopWatcher = () => {};
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 900 });

    const cleanUrl = dispatch.job.apply_url.split("?")[0];
    const resp = await page
      .goto(cleanUrl, { waitUntil: "networkidle2", timeout: NAV_TIMEOUT })
      .catch((e) => ({ _err: e.message }));

    if (resp?._err) {
      return outcome(dispatch, "error", `nav: ${resp._err}`, {
        wallclock_ms: Date.now() - t0,
      });
    }

    stopWatcher = startFocusWatcher(page);

    // Cloudflare settle
    for (let i = 0; i < 20; i++) {
      const title = await page.title();
      if (!/moment|Cloudflare|Just a moment/i.test(title)) break;
      await new Promise((r) => setTimeout(r, 1500));
    }

    assertNotInterrupted(page);

    if (await detectCaptcha(page)) {
      return outcome(dispatch, "captcha", "captcha interstitial detected", {
        wallclock_ms: Date.now() - t0,
      });
    }

    const formLoaded = await page
      .waitForSelector('input[name="firstName"], input[name="email"], input[type="email"]', {
        timeout: 12000,
      })
      .catch(() => null);

    if (!formLoaded) {
      const bodyText = await page.evaluate(() => document.body?.innerText?.slice(0, 400) || "");
      if (/no longer|closed|position has been filled|404/i.test(bodyText)) {
        return outcome(dispatch, "skipped", "job closed", {
          wallclock_ms: Date.now() - t0,
        });
      }
      return outcome(dispatch, "error", "form did not load", {
        wallclock_ms: Date.now() - t0,
      });
    }

    assertNotInterrupted(page);
    await fillStandardFields(page, profile);
    assertNotInterrupted(page);
    const resumeUploaded = await uploadResume(page, profile.resumePath);
    assertNotInterrupted(page);

    // In dry-run mode we stop before submit
    if (process.env.DRY_RUN === "1") {
      return outcome(dispatch, "submitted", "dry-run: fields filled, not submitted", {
        wallclock_ms: Date.now() - t0,
        tokens_spent: 0,
        dry_run: true,
        resume_uploaded: resumeUploaded,
      });
    }

    // Install pre-submit observations + network listener.
    const urlBefore = page.url();
    const submitResponses = [];
    const onResponse = (r) => {
      try {
        if (r.request().method() !== "POST") return;
        submitResponses.push({ status: r.status(), url: r.url(), t: Date.now() });
      } catch (_) {
        // page/target closed; ignore
      }
    };
    page.on("response", onResponse);

    const submitSelectors = [
      'button[type="submit"]',
      'button:has-text("Submit")',
      'button:has-text("Apply")',
      'input[type="submit"]',
    ];
    let submitted = false;
    let clickTime = 0;
    for (const sel of submitSelectors) {
      const btn = await page.$(sel).catch(() => null);
      if (btn) {
        assertNotInterrupted(page);
        clickTime = Date.now();
        await btn.click().catch(() => {});
        submitted = true;
        break;
      }
    }

    if (!submitted) {
      page.off("response", onResponse);
      return outcome(dispatch, "error", "no submit button found", {
        wallclock_ms: Date.now() - t0,
      });
    }

    await new Promise((r) => setTimeout(r, 4000));
    page.off("response", onResponse);

    // Converging signals — any one is weak, two is plausible, three+ is strong.
    const urlAfter = page.url();
    const formGone = await page.evaluate(() =>
      !document.querySelector('input[name="firstName"], input[name="email"], input[type="email"]')
    );
    const finalText = await page.evaluate(() =>
      document.body?.innerText?.slice(0, 600) || ""
    );
    const serverAck = submitResponses.some(
      (r) => r.t >= clickTime && r.status >= 200 && r.status < 300,
    );

    const signals = {
      server_ack: serverAck,
      url_changed: urlBefore !== urlAfter,
      form_gone: formGone,
      text_match: /thank you|received|submitted|success/i.test(finalText),
    };
    const score = Object.values(signals).filter(Boolean).length;
    const signalStr = JSON.stringify(signals);

    if (score >= 2) {
      return outcome(dispatch, "submitted", `confirmed score=${score} ${signalStr}`, {
        wallclock_ms: Date.now() - t0,
      });
    }
    if (score === 1) {
      return outcome(dispatch, "submitted", `soft score=1 ${signalStr}`, {
        wallclock_ms: Date.now() - t0,
      });
    }
    // Zero signals — likely form validation rejected the submit. Retry.
    return outcome(dispatch, "error", `submit ambiguous ${signalStr}`, {
      wallclock_ms: Date.now() - t0,
    });
  } catch (e) {
    if (e instanceof IsolationViolation) {
      return outcome(dispatch, "interrupted", e.message, {
        wallclock_ms: Date.now() - t0,
      });
    }
    throw e;
  } finally {
    stopWatcher();
    await browser.close().catch(() => {});
  }
}

async function main() {
  try {
    const dispatch = await readStdin();
    const profile = loadCandidateProfile();
    const result = await apply(dispatch, profile);
    process.stdout.write(JSON.stringify(result) + "\n");
  } catch (e) {
    const err = {
      candidate_id: null,
      job_id: null,
      ats: "unknown",
      status: "error",
      message: `runner: ${e.message}`,
      tokens_spent: 0,
      wallclock_ms: 0,
    };
    process.stdout.write(JSON.stringify(err) + "\n");
    process.exit(1);
  }
}

main();
