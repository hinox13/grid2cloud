import { expect, test } from "@playwright/test";
import { checkClaims, guardNetwork } from "./helpers";

const VIEWS = ["#/explore/journey", "#/explore", "#/explore/events", "#/explore/response", "#/explore/replication", "#/explore/models", "#/explore/value", "#/explore/data"];

test("every Explorer view loads with frozen figures and no external request", async ({ page }) => {
  const net = guardNetwork(page);
  for (const v of VIEWS) {
    await page.goto(`./${v}`);
    await expect(page.locator(".ex-h1")).toBeVisible();
    await page.waitForTimeout(300);
    await checkClaims(page);
  }
  expect(net.external).toEqual([]);
  expect(net.failed).toEqual([]);
  expect(net.errors).toEqual([]);
});

test("events: event, model, colour mode and time", async ({ page }) => {
  await page.goto("./#/explore/events?e=jun15_cloud_clearing&t=11:00&m=E5d");
  await expect(page.locator(".ev-slider strong")).toHaveText("11:00");
  await expect(page.locator(".ev-net figcaption")).toContainText("Response-aware");
  await page.getByRole("radio", { name: "Generator-aware" }).click();
  await expect(page.locator(".ev-net figcaption")).toContainText("Generator-aware");
  await expect(page).toHaveURL(/m=E5c/);
  await page.getByRole("radio", { name: "Error vs AC" }).click();
  await expect(page.locator(".net-legend")).toContainText("model − AC flow");
  await page.locator(".ev-slider input").fill("11");
  await expect(page.locator(".ev-slider strong")).toHaveText("11:30");
  await expect(page.locator(".ev-chain")).toContainText("grid state 11:30");
  await page.locator(".ev-slider input").fill("10");
  await expect(page.locator(".ev-chain")).toContainText("grid state held since 11:00");
  await page.locator(".rail-events button", { hasText: "23 August 2024" }).click();
  await expect(page.locator(".ev-context")).toContainText("23 August 2024");
  await expect(page.locator(".film-cell")).toHaveCount(12);
  await page.getByRole("radio", { name: "AC", exact: true }).click();
  await expect(page.locator(".ev-chain")).toContainText("select a model");
});

test("response, models, value and data views carry their content", async ({ page }) => {
  await page.goto("./#/explore/response");
  await expect(page.locator(".scatter")).toHaveCount(2 + 5);
  await page.getByRole("radio", { name: "10:30→11:00" }).click();
  await expect(page.locator(".bars").first()).toBeVisible();
  await page.goto("./#/explore/models");
  await expect(page.locator(".ex-table tbody tr")).toHaveCount(5);
  await expect(page.locator(".metric")).toHaveCount(6);
  await expect(page.locator(".verdicts li")).toHaveCount(5);
  await page.goto("./#/explore/value");
  await expect(page.locator(".ex-table.dense tbody tr")).toHaveCount(24);
  await page.locator(".ex-table.dense tbody tr").nth(13).click();
  await expect(page.locator(".ledger-hh")).toContainText("settlement period 26");
  // one plant, two time scales, each section labelled with its scope
  await expect(page.locator(".ex-lead")).toContainText("One explicit 6 MW solar plant");
  await expect(page.locator("#s-15-june-2024-observed-sky-against-a-hypothetical-clear-sky .scope[data-scope=economic]")).toContainText("one day, 15 June 2024");
  await expect(page.locator("#s-across-the-season .scope")).toContainText("2,820 half-hours over 136 days");
  await expect(page.locator("#s-across-the-season .cal-grid .cal-day.is-on")).toHaveCount(135);
  await expect(page.locator("#s-across-the-season")).toContainText("not the 15 June total multiplied");
  await page.goto("./#/explore");
  for (const k of ["aggregate", "event", "economic"]) await expect(page.locator(`.scope-list .scope[data-scope=${k}]`)).toBeVisible();
  await page.goto("./#/explore/data");
  await page.getByText(/frozen figures$/).click();
  await expect(page.locator("details[open] tbody tr").first()).toBeVisible();
});

test("theme toggle switches and persists", async ({ page }) => {
  await page.goto("./#/explore");
  const before = await page.evaluate(() => document.documentElement.dataset.theme);
  await page.locator(".theme-toggle").click();
  const after = await page.evaluate(() => document.documentElement.dataset.theme);
  expect(after).not.toBe(before);
  await page.reload();
  expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe(after);
});

test("a missing data file degrades to a message, not a blank page", async ({ page }) => {
  await page.route("**/data/cloud_impact.json", (r) => r.fulfill({ status: 404, body: "" }));
  await page.goto("./#/explore/value");
  await expect(page.getByRole("alert")).toContainText("Could not load the economic study");
  await expect(page.locator(".ex-head")).toBeVisible();
});

test("rail: page index, key figures and the event picker", async ({ page }) => {
  await page.goto("./#/explore");
  const toc = page.locator(".rail-toc button");
  await expect(toc).toHaveCount(7);
  await toc.filter({ hasText: "Limits of this site" }).click();
  await expect(page.locator("#s-limits-of-this-site")).toBeInViewport();
  await expect(toc.filter({ hasText: "Limits of this site" })).toHaveClass(/on/);
  await expect(page.locator(".rail-facts [data-claim=slope_E5d]")).toHaveText("−1.07 MW per MW");
  await page.goto("./#/explore/events?e=jun15_cloud_clearing&t=11:00&m=E5d");
  await expect(page.locator(".rail-events button")).toHaveCount(3);
  await page.locator(".rail-events button", { hasText: "15 April 2024" }).click();
  await expect(page.locator(".ev-context")).toContainText("15 April 2024");
  await expect(page.locator(".rail-events button.on")).toContainText("15 April 2024");
});

test("model journey: five stages, keyboard, two dimensions, caveats", async ({ page }) => {
  await page.goto("./#/explore/journey");
  await expect(page.locator(".jr-track [role=tab]")).toHaveCount(5);
  await expect(page.locator(".jr-meter").first()).toContainText("−260.0 MW");
  await page.locator(".jr-track [role=tab]").first().focus();
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect(page.locator(".jr-track [aria-selected=true]")).toContainText("Envelope-tuned");
  await expect(page.locator(".jr-panel")).toContainText("0.338 MVA");
  await expect(page).toHaveURL(/stage=E5b/);
  await page.getByRole("tab", { name: /Generator-aware/ }).click();
  await expect(page.locator(".jr-caveat")).toContainText("PQ buses");
  await page.getByRole("tab", { name: /Response-aware/ }).click();
  await expect(page.locator(".jr-panel")).toContainText("both worse than E5b");
  await expect(page.locator(".score-row")).toHaveCount(5);
  await expect(page.locator("#s-two-models-two-different-strengths .scope[data-scope=aggregate]")).toContainText("2,829");
  await expect(page.locator("#s-two-models-two-different-strengths .to-cell.is-better")).toHaveCount(2);
  await expect(page.locator("#s-two-models-two-different-strengths .ex-table")).toContainText("0.0144");
  await expect(page.locator("#s-one-seed-one-setting tbody tr")).toHaveCount(7);
  await expect(page.locator("#s-one-seed-one-setting")).toContainText("not interpretable");
  await expect(page.locator(".jr-panel")).toContainText("Only this training seed learned the response this well");
  await expect(page.locator("#s-see-it-happen-on-15-june .scope[data-scope=event]")).toContainText("controlled counterfactual");
  await expect(page.locator(".jr-track")).toContainText("PBE 0.338 MVA");
  await page.getByRole("radio", { name: "Generator-aware (E5c)" }).click();
  await expect(page.locator(".see .tl-readout")).toContainText("Generator-aware");
  await page.goto("./");
  await page.getByRole("link", { name: "Follow the model journey" }).click();
  await expect(page.locator(".ex-h1")).toContainText("How we taught GENCO");
});

test("second network: synthetic scope, every seed, failed validation, no economic value", async ({ page }) => {
  const net = guardNetwork(page);
  await page.goto("./#/explore/replication");
  await expect(page.locator(".ex-h1")).toContainText("A second network: Aylesbury East");
  await expect(page.locator(".ex-callout")).toContainText("Synthetic states only");
  await expect(page.locator(".ex-callout")).toContainText("not the Sundon model reused");
  await expect(page.locator("#s-every-seed tbody tr")).toHaveCount(9);
  await expect(page.locator(".repl-dot.is-failed")).toHaveCount(1);
  await expect(page.locator(".hyp-list li[data-holds=false]")).toHaveCount(1);
  await expect(page.locator(".hyp-list li[data-holds=false]")).toContainText("H7 fails");
  await expect(page.locator("#s-why-the-real-data-validation-failed")).toContainText("never trained or evaluated on Aylesbury's real states");
  await expect(page.locator("#s-can-it-test-spatial-weather [data-claim=g2_pixel_share]")).toHaveText("96 %");
  await expect(page.locator("#s-does-the-e5b-e5d-trade-off-recur")).toContainText("Not in the same form");
  await expect(page.locator(".ex-main")).not.toContainText("£");
  expect(await checkClaims(page)).toBeGreaterThan(20);
  expect(net.errors).toEqual([]);
});

test("network-wide response, the cancellation note and the AC reference qualification", async ({ page }) => {
  await page.goto("./#/explore/response");
  const net = page.locator("#s-beyond-the-grid-import-the-response-across-the-network");
  for (const [id, v] of [["branch_resp_E5c", "0.074"], ["branch_resp_E5d", "0.014 MW per MW"], ["va_resp_E5c", "0.050"], ["va_resp_E5d", "0.0009"], ["va_resp_AC", "0.053"]]) await expect(net.locator(`[data-claim=${id}]`)).toHaveText(v);
  await expect(net).toContainText("post-verdict, report-only diagnostic");
  await expect(net).toContainText("does not show that the absolute states are accurate");
  await page.goto("./#/explore/journey");
  const two = page.locator("#s-two-models-two-different-strengths");
  for (const [id, v] of [["cancel_r", "0.999"], ["cancel_level", "11.7 MW"], ["cancel_delta", "0.05 MW"]]) await expect(two.locator(`[data-claim=${id}]`)).toHaveText(v);
  await expect(two).toContainText("not an established cause");
  await page.goto("./#/explore");
  await expect(page.locator(".ex-main")).toContainText("is the reconstruction's response");
});

test("value: both counterfactuals kept apart, each with its own model accuracy", async ({ page }) => {
  await page.goto("./#/explore/value");
  const two = page.locator("#s-two-counterfactuals-two-questions");
  await expect(two).toContainText("What did the clouds add?");
  await expect(two).toContainText("What did the plant displace?");
  await expect(two.locator("[data-claim=season_pv_attributed_gbp]")).toHaveText("£234,226");
  const acc = page.locator("#s-how-accurately-do-the-models-reproduce-these-valuations");
  await expect(acc).toContainText("Clouds vs clear sky");
  await expect(acc).toContainText("Plant vs no plant");
  for (const [id, v] of [["season_cloud_err_E5d", "+0.06 %"], ["season_pv_err_E5d", "−0.3 %"], ["cloud_hh_mae_accounting", "0.018"], ["cloud_hh_mae_E5d", "0.041"], ["cloud_acc_closer", "77 %"]]) await expect(acc.locator(`[data-claim=${id}]`).first()).toHaveText(v);
  await expect(page.locator("#s-across-the-season")).toContainText("Signed contributions");
  await expect(page.locator("#s-across-the-season [data-claim=cloud_neg_periods]")).toHaveText("927");
  await expect(page.locator("#s-across-the-season")).toContainText("is the net illustrative valuation across the evaluated half-hours");
  await expect(page.locator("#s-across-the-season")).toContainText("not proof that clouds raised generation");
  expect(await checkClaims(page)).toBeGreaterThan(30);
});

test("network zoom, branch details by click and keyboard; timeline hover readout", async ({ page }) => {
  await page.goto("./#/explore/events?e=jun15_cloud_clearing&t=11:00&m=E5d");
  const svg = page.locator(".ev-net svg");
  const vb0 = await svg.getAttribute("viewBox");
  await page.getByRole("button", { name: "Zoom in" }).click();
  expect(await svg.getAttribute("viewBox")).not.toBe(vb0);
  await page.getByRole("button", { name: "Reset" }).click();
  expect(await svg.getAttribute("viewBox")).toBe(vb0);
  await page.locator(".ev-net .edge-hit").first().focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".net-detail")).toContainText("AC: P");
  const chart = page.locator(".ev-timeline .chart svg").first();
  await chart.scrollIntoViewIfNeeded();
  const box = (await chart.boundingBox())!;
  await page.mouse.move(box.x + box.width * 0.2, box.y + box.height / 2);
  await expect(page.locator(".ev-timeline .tl-readout")).not.toContainText("hover or touch");
});
