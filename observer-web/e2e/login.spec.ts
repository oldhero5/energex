import { test, expect } from "@playwright/test";

// @smoke
// Requires: next dev running on port 3000, observer-api on 8090, Supabase running on 54321
// Seeded test user: admin@energex.local / energex-observer-dev (role: admin)

const E2E_EMAIL = process.env.E2E_EMAIL ?? "admin@energex.local";
const E2E_PASSWORD = process.env.E2E_PASSWORD ?? "energex-observer-dev";

test.describe("@smoke login flow", () => {
  test("redirects unauthenticated / to /login", async ({ page }) => {
    await page.goto("http://localhost:3000/");
    await expect(page).toHaveURL(/\/login/);
  });

  test("signs in and renders the nav rail", async ({ page }) => {
    await page.goto("http://localhost:3000/login");
    await page.fill('input[type="email"]', E2E_EMAIL);
    await page.fill('input[type="password"]', E2E_PASSWORD);
    await page.click('button[type="submit"]');

    await expect(page).toHaveURL("http://localhost:3000/", { timeout: 10000 });
    await expect(page.locator("nav")).toContainText("ENERGEX · OBSERVER");
  });
});
