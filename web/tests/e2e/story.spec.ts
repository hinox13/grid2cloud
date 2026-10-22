import { expect, test } from "@playwright/test";
import { beat, checkClaims, guardNetwork, toBeat } from "./helpers";

const BEATS = ["prologue", "c-sky", "c-play", "c-clear", "e-wipe", "e-curve", "g-states", "g-why", "g-freeze", "j-zero", "j-network", "j-shift", "i-cf", "i-slope", "j-two", "j-replicate", "v-value", "v-half", "v-season", "finale"];

test("home: premise and both actions in the first screen", async ({ page }) => {
  const net = guardNetwork(page);
  await page.goto("./");
  await expect(page.locator("h1")).toContainText("One cloud. One grid.");
  await expect(page.locator("h1")).toContainText("A chain of consequences.");
  await page.evaluate(() => document.fonts.ready); // measure the settled layout, not the fallback-font flash
  for (const name of ["Experience the story", "Follow the model journey"]) {
    const box = await page.getByRole("link", { name, exact: true }).boundingBox();
    expect(box && box.y + box.height, `${name} above the fold`).toBeLessThanOrEqual(900);
  }
  await expect(page.locator(".masthead img")).toHaveCount(5);
  expect(await checkClaims(page)).toBeGreaterThan(3);
  expect(net.external).toEqual([]);
  expect(net.failed).toEqual([]);
  expect(net.errors).toEqual([]);
});

test("experience: every beat in order, every figure frozen, nothing external", async ({ page }) => {
  const net = guardNetwork(page);
  await page.goto("./#/experience");
  let total = 0;
  for (const id of BEATS) {
    await expect(page.locator(`[data-beat="${id}"]`)).toBeVisible();
    await page.waitForTimeout(150);
    total += await checkClaims(page);
    if (id !== "finale") await page.keyboard.press("ArrowRight");
  }
  expect(total).toBeGreaterThan(60);
  expect(net.external).toEqual([]);
  expect(net.failed).toEqual([]);
  expect(net.errors).toEqual([]);
});

test("the brief's key figures appear where the story states them", async ({ page }) => {
  await page.goto("./#/experience");
  await toBeat(page, "e-wipe");
  await expect(page.locator('[data-claim="fleet_pv_1100"]')).toHaveText("2.38 MW");
  await expect(page.locator('[data-claim="fleet_pv_1130"]')).toHaveText("8.86 MW");
  await toBeat(page, "e-curve");
  await expect(page.locator(".beat-h [data-claim=fleet_pv_delta]")).toHaveText("+6.49 MW");
  await toBeat(page, "g-states");
  await expect(page.locator('[data-claim="n_buses"]')).toHaveText("38");
  await expect(page.locator('[data-claim="n_branches"]')).toHaveText("44");
  await expect(page.locator(".readouts [data-claim=import_ac_1100]")).toHaveText("54.4 MW");
  await expect(page.locator(".readouts [data-claim=import_ac_1130]")).toHaveText("34.0 MW");
  await toBeat(page, "g-freeze");
  await expect(page.locator(".vs-cell.is-solar [data-claim=cf_AC_1100]")).toHaveText("−4.57 MW");
  await expect(page.locator(".vs-cell.is-solar")).not.toHaveClass(/pending/, { timeout: 6000 });
  await expect(page.locator("[data-hud-import]")).toHaveAttribute("data-hud-import", "49.8");
  await toBeat(page, "j-zero");
  // question 1, the amount: an average over all real half-hours, opposing directions
  await expect(page.locator(".scope[data-scope=aggregate]")).toContainText("all 2,829 reconstructed real half-hours, April–September 2024");
  await expect(page.locator(".question[data-question='1']")).toContainText("How much electricity does the grid import on average?");
  await expect(page.locator(".iax-row[data-stage=AC] [data-claim=import_mean_AC]")).toHaveText("48.6 MW");
  await expect(page.locator(".iax-row[data-stage=zero_shot] [data-claim=import_mean_zero_shot]")).toHaveText("−211.4 MW");
  await expect(page.locator(".iax-row[data-stage=zero_shot]")).toHaveClass(/is-export/);
  await expect(page.locator(".readouts [data-claim=bias_zero_shot]")).toHaveText("−260.0 MW");
  await expect(page.locator(".readouts [data-claim=zero_shot_wrong_sign]")).toHaveText("99.9 %");
  await expect(page.locator(".ruler-status")).toContainText("Aggregate GENCO evaluation");
  await toBeat(page, "j-network");
  await expect(page.locator(".question[data-question='1']")).toBeVisible();
  await expect(page.locator(".readouts [data-claim=import_mean_E5b]")).toHaveText("53.0 MW");
  await expect(page.locator(".readouts [data-claim=pbe_E5b]")).toHaveText("0.338 MVA");
  await expect(page.locator(".readouts [data-claim=bias_E5b]")).toHaveText("+4.4 MW");
  await expect(page.locator(".readouts")).toContainText("Power-balance error");
  await expect(page.locator(".readouts")).toContainText("Import bias");
  await expect(page.locator(".pbe-row[data-stage=zero_shot] [data-claim=pbe_zero_shot]")).toHaveText("49.0 MVA");
  await expect(page.locator(".iax-row[data-stage=E5b]")).not.toHaveClass(/is-off/, { timeout: 6000 });
  // the turn: the amount is not the response
  await toBeat(page, "j-shift");
  await expect(page.locator(".beat-body")).toContainText("Getting the amount of imported electricity right wasn't enough. We also needed GENCO to understand what happens when solar generation changes.");
  await expect(page.locator(".next-q .question[data-question='2']")).toContainText("When solar generation increases, does GENCO predict the correct change in grid import?");
  await expect(page.locator(".twoq [data-claim=slope_E5b]")).toHaveText("−0.06");
  // question 2 at one moment: the controlled 11:00 counterfactual, changes in MW
  await toBeat(page, "i-cf");
  await expect(page.locator(".scope[data-scope=event]")).toContainText("controlled counterfactual");
  await expect(page.locator(".scope[data-scope=event]")).toContainText("all other inputs held fixed");
  for (const [id, v] of [["plant_pv_obs_1100", "1.46 MW"], ["plant_pv_clear_1100", "5.97 MW"], ["plant_pv_cf_delta", "+4.51 MW"]]) await expect(page.locator(`.cf-input [data-claim=${id}]`)).toHaveText(v);
  await expect(page.locator(".bars [data-claim=cf_E5d_1100]")).toHaveText("−4.56 MW", { timeout: 6000 });
  for (const [id, v] of [["cf_E5c_1100", "−0.04 MW"], ["cf_AC_1100", "−4.57 MW"]]) await expect(page.locator(`.bars [data-claim=${id}]`)).toHaveText(v);
  await expect(page.locator(".genco-bars")).toContainText("A change, not the import level");
  // question 2 across all states: fitted sensitivities, MW per MW
  await toBeat(page, "i-slope");
  await expect(page.locator(".scope[data-scope=aggregate]")).toBeVisible();
  for (const [id, v] of [["slope_AC", "−1.02"], ["slope_E5c", "−0.04"], ["slope_E5d", "−1.07"]]) await expect(page.locator(`.readouts-trio [data-claim=${id}]`)).toHaveText(v);
  await expect(page.locator(".readouts-note")).toContainText("MW of import per MW of solar");
  await expect(page.locator(".readouts-note")).toContainText("not the 11:00 change in MW");
  await expect(page.locator(".readouts-note")).toContainText("E5c → E5d");
  await expect(page.locator(".beat-body")).toContainText("On held-out synthetic pairs, a matched run");
  // two models, two strengths: absolute state and solar response scored separately, neither wins both
  await toBeat(page, "j-two");
  await expect(page.locator(".beat-h")).toHaveText("Two models. Two different strengths.");
  await expect(page.locator(".beat-lead")).toHaveText("One unresolved challenge.");
  await expect(page.locator(".to-cell[data-model=E5b][data-row=state] [data-claim=bias_E5b]")).toHaveText("+4.4 MW");
  await expect(page.locator(".to-cell[data-model=E5d][data-row=state] [data-claim=bias_E5d]")).toHaveText("+13.1 MW");
  await expect(page.locator(".to-cell[data-model=E5b][data-row=state] [data-claim=pbe_E5b]")).toHaveText("0.338 MVA");
  await expect(page.locator(".to-cell[data-model=E5d][data-row=state] [data-claim=pbe_E5d]")).toHaveText("0.676 MVA");
  await expect(page.locator(".to-cell[data-model=E5b][data-row=resp] [data-claim=slope_E5b]")).toHaveText("−0.06 MW per MW");
  await expect(page.locator(".to-cell[data-model=E5d][data-row=resp] [data-claim=slope_E5d]")).toHaveText("−1.07 MW per MW");
  await expect(page.locator(".to-cell.is-better")).toHaveCount(2);
  await expect(page.locator(".to-cell.is-better[data-model=E5b][data-row=state]")).toHaveCount(1);
  await expect(page.locator(".to-cell.is-better[data-model=E5d][data-row=resp]")).toHaveCount(1);
  await expect(page.locator(".to-note")).toContainText("Neither model does both");
  // the second network: synthetic scope, never presented as real operation
  await toBeat(page, "j-replicate");
  await expect(page.locator(".scope[data-scope=synthetic]")).toContainText("Second network · synthetic replication");
  await expect(page.locator(".ruler-status")).toContainText("not 2024 operation");
  await expect(page.locator(".readouts [data-claim=g2_C_pv_slope_ratio]")).toHaveText("0.16–0.32");
  await expect(page.locator(".readouts [data-claim=g2_D_pv_slope_ratio_ok]")).toHaveText("0.99–1.01");
  await expect(page.locator(".readouts-note")).toContainText("real-data reconstruction failed validation");
  await expect(page.locator(".repl .repl-dot.is-failed")).toHaveCount(1);
  // the value: one plant and the method first, then the day, one half-hour, the season
  await toBeat(page, "v-value");
  await expect(page.locator(".scope[data-scope=economic]")).toContainText("one 6 MW plant");
  await expect(page.locator(".beat-lead")).toHaveText("One 6 MW solar plant, not all of Sundon's solar.");
  await expect(page.locator(".beat-body")).toContainText("actual historical Elexon market prices");
  await expect(page.locator(".value-big [data-claim=day_cloud_mwh]")).toHaveText("16.94 MWh");
  await expect(page.locator(".value-big [data-claim=day_cloud_gbp]")).toHaveText("£1,661");
  await expect(page.locator(".result-card")).toContainText("24 evaluated half-hours");
  await toBeat(page, "v-half");
  await expect(page.locator(".scope[data-scope=economic]")).toContainText("one half-hour");
  for (const [id, v] of [["one_cloud_mw", "4.565 MW"], ["one_cloud_mwh", "2.283 MWh"], ["one_apx", "£96.76/MWh"], ["one_cloud_gbp", "£221"]]) await expect(page.locator(`.sum [data-claim=${id}]`)).toHaveText(v);
  await expect(page.locator(".sum")).toContainText("0.5 h");
  await expect(page.locator(".part-of")).toContainText("£1,661");
  await toBeat(page, "v-season");
  await expect(page.locator(".scope[data-scope=economic]")).toContainText("2,820 half-hours over 136 days");
  await expect(page.locator(".result-card.is-season [data-claim=season_cloud_attributed_mwh]")).toHaveText("1,428.37 MWh");
  await expect(page.locator(".result-card.is-season [data-claim=season_cloud_attributed_gbp]")).toHaveText("£93,286");
  await expect(page.locator(".cal-grid .cal-day.is-on")).toHaveCount(135); // 136 evaluated days, 15 June drawn as the event
  await expect(page.locator(".cal-grid .cal-day.is-event")).toHaveCount(1);
  await expect(page.locator(".spread")).toContainText("15 June was not a typical day");
  await expect(page.locator(".season-note")).toContainText("not actual costs, savings");
  await expect(page.locator(".season-note")).toContainText("GENCO does not predict prices");
  await toBeat(page, "finale");
  await expect(page.locator(".finale-takeaway")).toContainText("Two models, two different strengths, one unresolved challenge");
  await expect(page.locator(".chain")).toContainText("E5c → E5d");
  await expect(page.locator(".finale-body")).not.toContainText("a second network are the next tests");
});

test("controls: keyboard, chapters, pause, guided replay", async ({ page }) => {
  await page.goto("./#/experience?play=1");
  await expect(page.getByRole("button", { name: "Pause" })).toBeVisible();
  await page.keyboard.press("Space");
  await expect(page.getByRole("button", { name: "Play" })).toBeVisible();
  await page.keyboard.press("ArrowRight");
  expect(await beat(page)).toBe("c-sky");
  await page.keyboard.press("ArrowLeft");
  expect(await beat(page)).toBe("prologue");
  await page.getByRole("button", { name: /GENCO/ }).click();
  expect(await beat(page)).toBe("j-zero");
  await expect(page).toHaveURL(/#\/experience\/genco$/);
  await page.keyboard.press("End");
  await expect(page.locator(".finale")).toBeVisible();
  await page.getByRole("button", { name: "Replay the event" }).click();
  expect(await beat(page)).toBe("prologue");
  // guided replay advances on its own
  await page.getByRole("button", { name: "Play" }).click();
  await expect(page.locator('[data-beat="c-sky"]')).toBeVisible({ timeout: 12_000 });
});

test("interactions: wipe, filmstrip, scenario and half-hour", async ({ page }) => {
  await page.goto("./#/experience/energy");
  await expect(page.locator('[data-beat="e-wipe"]')).toBeVisible();
  const wipe = page.locator("input.sat-wipe");
  await wipe.fill("20");
  await expect(page.locator(".sat-right")).toHaveAttribute("style", /inset\(0px 0px 0px 20%\)|inset\(0 0 0 20%\)/);
  await page.goto("./#/experience/clouds");
  // wait for the stage before pressing keys: a key pressed before the listener exists is lost
  await expect(page.locator('[data-beat="prologue"]')).toBeVisible();
  await toBeat(page, "c-play");
  await page.getByRole("button", { name: "Show the 10:00 UTC frame" }).click();
  await expect(page.locator(".readouts")).toContainText("10:00 UTC");
  await page.goto("./#/experience/value");
  await expect(page.locator('[data-beat="v-value"]')).toBeVisible();
  await toBeat(page, "v-half");
  await page.getByRole("radio", { name: "Clear sky (hypothetical)" }).click();
  await expect(page.locator(".day-chart")).toHaveAttribute("data-scenario", "clear");
  await page.locator(".day-scrub input").fill("13");
  await expect(page.locator(".ledger-hh")).toContainText("11:30–12:00 UTC · settlement period 26");
  await page.locator(".day-scrub input").fill("12");
  await expect(page.locator(".ledger-hh")).toContainText("£221");
});

test("deep links survive a refresh under the project path", async ({ page }) => {
  for (const [hash, check] of [
    ["#/experience/grid", '[data-beat="g-states"]'],
    ["#/explore/value", "text=Cloud impact: from clouds to grid to value"],
    ["#/explore/events?e=apr15_broken_cumulus&t=13:00&m=E5c", ".ev-context >> text=15 April 2024"],
  ]) {
    await page.goto(`./${hash}`);
    await page.reload();
    await expect(page.locator(check).first()).toBeVisible();
  }
  const r = await page.request.get("./");
  expect(r.status()).toBe(200);
  expect(await r.text()).toContain(new URL(test.info().project.use.baseURL!).pathname + "assets/");
});

test("one network representation: the 3D experiment is gone", async ({ page }) => {
  const urls: string[] = [];
  page.on("request", (r) => urls.push(r.url()));
  await page.goto("./#/lab/grid-3d");
  await expect(page.locator("h1")).toContainText("One cloud. One grid."); // an unknown route falls back to home
  await page.goto("./#/explore/events?e=jun15_cloud_clearing&t=11:00&m=AC");
  await expect(page.locator(".ev-net svg").first()).toBeVisible();
  await expect(page.locator('a[href*="lab"]')).toHaveCount(0);
  await expect(page.getByText(/\b3D\b/)).toHaveCount(0);
  expect(urls.filter((u) => /Grid3D|three/i.test(u))).toEqual([]);
});

test("reduced motion: no autoplay, final states shown", async ({ browser }) => {
  const ctx = await browser.newContext({ reducedMotion: "reduce", viewport: { width: 1440, height: 900 }, baseURL: test.info().project.use.baseURL });
  const page = await ctx.newPage();
  await page.goto("./#/experience?play=1");
  await expect(page.getByRole("button", { name: "Play" })).toBeVisible();
  await toBeat(page, "g-freeze");
  await expect(page.locator("[data-hud-import]")).toHaveAttribute("data-hud-import", "49.8");
  await ctx.close();
});

test("works offline after the first load @mobile", async ({ page, context }) => {
  await page.goto("./");
  await expect(page.locator("h1")).toBeVisible();
  await page.goto("./#/experience");
  await toBeat(page, "finale");
  await context.setOffline(true);
  await page.getByRole("button", { name: "Replay the event" }).click();
  await expect(page.locator('[data-beat="prologue"]')).toBeVisible();
  await context.setOffline(false);
});

test("mobile: first screen and the story are usable @mobile", async ({ page }) => {
  const net = guardNetwork(page);
  await page.goto("./");
  const box = await page.getByRole("link", { name: "Experience the story" }).boundingBox();
  expect(box!.y + box!.height).toBeLessThanOrEqual(844);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.getByRole("link", { name: "Experience the story" }).click();
  for (let i = 0; i < 20 && !(await page.locator(".finale").count()); i++) {
    await page.getByRole("button", { name: /^(Next|Finish)$/ }).click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  }
  await expect(page.locator(".finale")).toBeVisible();
  expect(net.external).toEqual([]);
  expect(net.errors).toEqual([]);
});

test("home: the research question and the model journey are on the first screen", async ({ page }) => {
  await page.goto("./");
  await expect(page.locator(".lead.question")).toContainText("grid foundation model trained on synthetic networks");
  await expect(page.locator(".home-facts")).toContainText("Real Meteosat observations");
  await expect(page.locator(".home-facts")).toContainText("GENCO, tested and adapted");
  await page.evaluate(() => document.fonts.ready);
  const box = await page.getByRole("link", { name: "Follow the model journey" }).boundingBox();
  expect(box!.y + box!.height).toBeLessThanOrEqual(900);
});

test("mobile: every explanation is reachable above the sticky controls @mobile", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" }); // measure the settled layout, not entrance animations
  await page.goto("./#/experience");
  await expect(page.locator("[data-beat]")).toBeVisible();
  await page.evaluate(() => document.fonts.ready); // and not the fallback-font layout before web fonts arrive
  await page.waitForTimeout(200);
  for (let i = 0; i < 20 && !(await page.locator(".finale").count()); i++) {
    // scroll the stage to its end: the last explanation must sit fully above the Back / Next bar
    const r = await page.evaluate(() => {
      const st = document.querySelector(".stage") as HTMLElement | null;
      if (!st) return null;
      st.scrollTop = st.scrollHeight;
      const kids = [...document.querySelectorAll(".beat-text > *")] as HTMLElement[];
      const last = kids[kids.length - 1];
      const bar = document.querySelector(".stage-controls") as HTMLElement;
      return { beat: document.querySelector("[data-beat]")?.getAttribute("data-beat"), lastBottom: last.getBoundingClientRect().bottom, barTop: bar.getBoundingClientRect().top, sw: document.documentElement.scrollWidth };
    });
    if (r) {
      expect(r.lastBottom, `beat ${r.beat}: text hidden behind the controls`).toBeLessThanOrEqual(r.barTop + 1);
      expect(r.sw).toBeLessThanOrEqual(390);
    }
    const before = await page.locator("[data-beat]").getAttribute("data-beat");
    await page.getByRole("button", { name: /^(Next|Finish)$/ }).click();
    await expect(page.locator("[data-beat]")).not.toHaveAttribute("data-beat", before ?? ""); // the next step has rendered
    await page.waitForTimeout(150);
  }
  await expect(page.locator(".finale")).toBeVisible();
});

test("landscape phone: the story and the home page still work @mobile", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 844, height: 390 }, hasTouch: true, baseURL: test.info().project.use.baseURL });
  const page = await ctx.newPage();
  await page.goto("./");
  await expect(page.getByRole("link", { name: "Experience the story" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(844);
  await page.goto("./#/experience");
  await expect(page.locator("[data-beat]")).toBeVisible();
  for (let i = 0; i < 20 && !(await page.locator(".finale").count()); i++) {
    await page.getByRole("button", { name: /^(Next|Finish)$/ }).click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(844);
  }
  await expect(page.locator(".finale")).toBeVisible();
  await ctx.close();
});
