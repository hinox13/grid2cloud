import { expect, test } from "@playwright/test";
import { checkClaims, guardNetwork } from "./helpers";

const VIEWS = ["#/explore/journey", "#/explore", "#/explore/events", "#/explore/response", "#/explore/models", "#/explore/value", "#/explore/data"];

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
  await expect(page.locator(".ex-section .scope[data-scope=economic]").first()).toContainText("one day, 15 June 2024");
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
  await expect(page.locator("#s-two-different-problems .scope[data-scope=aggregate]")).toContainText("2,829");
  await expect(page.locator("#s-see-it-happen-on-15-june .scope[data-scope=event]")).toContainText("controlled counterfactual");
  await expect(page.locator(".jr-track")).toContainText("PBE 0.338 MVA");
  await page.getByRole("radio", { name: "Generator-aware (E5c)" }).click();
  await expect(page.locator(".see .tl-readout")).toContainText("Generator-aware");
  await page.goto("./");
  await page.getByRole("link", { name: "Follow the model journey" }).click();
  await expect(page.locator(".ex-h1")).toContainText("How we taught GENCO");
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
