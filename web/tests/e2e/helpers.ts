import { expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

export const CLAIMS: Record<string, { display: string; unit: string }> = Object.fromEntries(
  (JSON.parse(readFileSync(new URL("../../public/data/claims.json", import.meta.url), "utf8")) as { id: string; display: string; unit: string }[]).map((c) => [c.id, c]),
);
const UNIT: Record<string, string> = { MW: " MW", MWh: " MWh", MVA: " MVA", "MW/MW": " MW per MW", "%": " %", "GBP/MWh": "/MWh" };

/** Every rendered figure must be exactly the frozen display string (with or without its unit). */
export async function checkClaims(page: Page): Promise<number> {
  const found = await page.$$eval("[data-claim]", (els) => els.map((e) => ({ id: e.getAttribute("data-claim")!, text: (e.textContent ?? "").trim() })));
  for (const { id, text } of found) {
    const c = CLAIMS[id];
    expect(c, `unknown claim ${id}`).toBeTruthy();
    expect([c.display, c.display + (UNIT[c.unit] ?? "")], `claim ${id}`).toContain(text);
  }
  expect(await page.locator("[data-claim-missing]").count()).toBe(0);
  return found.length;
}

/** Record every request; fail the test on any request that leaves the site. */
export function guardNetwork(page: Page) {
  const external: string[] = [];
  const failed: string[] = [];
  const errors: string[] = [];
  const own = new URL(process.env.C2G_URL ?? "http://localhost:4173/").hostname;
  page.on("request", (r) => {
    const u = new URL(r.url());
    if (![own, "localhost", "127.0.0.1"].includes(u.hostname) && u.protocol !== "data:") external.push(r.url());
  });
  page.on("response", (r) => {
    if (r.status() >= 400) failed.push(`${r.status()} ${r.url()}`);
  });
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(String(e)));
  return { external, failed, errors };
}

export async function beat(page: Page): Promise<string> {
  return (await page.locator("[data-beat]").getAttribute("data-beat")) ?? "";
}

export async function toBeat(page: Page, id: string) {
  await expect(page.locator("[data-beat]")).toBeVisible(); // the stage (and its key listener) exists
  for (let i = 0; i < 20 && (await beat(page)) !== id; i++) await page.keyboard.press("ArrowRight");
  await expect(page.locator(`[data-beat="${id}"]`)).toBeVisible();
}
