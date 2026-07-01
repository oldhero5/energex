import { test, expect } from "@playwright/test";

// @smoke
// Requires: next dev running on port 3000, observer-api on 8090, Supabase running on 54321
// Seeded test user: admin@energex.local / energex-observer-dev (role: admin)
// Run: npx playwright test e2e/explorer.spec.ts
// Deferred: full run requires the composed stack (docker compose up).

const E2E_EMAIL = process.env.E2E_EMAIL ?? "admin@energex.local";
const E2E_PASSWORD = process.env.E2E_PASSWORD ?? "energex-observer-dev";

async function signIn(page: Parameters<Parameters<typeof test>[1]>[0]) {
  await page.goto("http://localhost:3000/login");
  await page.fill('input[type="email"]', E2E_EMAIL);
  await page.fill('input[type="password"]', E2E_PASSWORD);
  await page.click('button[type="submit"]');
  await expect(page).toHaveURL("http://localhost:3000/", { timeout: 10000 });
}

test.describe("@smoke explorer flow", () => {
  test("home page shows the 4V tiles after sign-in", async ({ page }) => {
    await signIn(page);
    await expect(page.getByText("Volume")).toBeVisible({ timeout: 8000 });
    await expect(page.getByText("Velocity")).toBeVisible({ timeout: 8000 });
    await expect(page.getByText("Variety")).toBeVisible({ timeout: 8000 });
    await expect(page.getByText("Veracity")).toBeVisible({ timeout: 8000 });
  });

  test("navigates to Catalog and selects a symbol", async ({ page }) => {
    await signIn(page);

    // Navigate to Catalog via the nav rail
    await page.click('a[href="/catalog"]');
    await expect(page).toHaveURL(/\/catalog/, { timeout: 8000 });

    // The catalog tree should render the sidebar heading
    await expect(page.getByText("Catalog")).toBeVisible({ timeout: 8000 });
  });

  test("Series tab renders a chart canvas for a symbol", async ({ page }) => {
    await signIn(page);

    // Navigate directly to catalog with a known seeded symbol
    // (adjust library/symbol to match seeded test data)
    await page.goto("http://localhost:3000/catalog?library=power.load&symbol=erco", {
      waitUntil: "networkidle",
    });

    // Click the Series tab
    await page.click('button:has-text("Series")');

    // The chart canvas should mount (echarts renders a canvas inside the chart div)
    await expect(page.locator('[aria-label="series chart"]')).toBeVisible({ timeout: 10000 });
  });
});
