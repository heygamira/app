// Regression test for a real shipped bug: family switching used to leak
// every family's seniors into one grid (AuthContext.jsx used to derive the
// senior list from `allSeniors` directly instead of narrowing it to
// `activeFamily`). `dual-caregiver` (Priya Rao) is the only seeded identity
// in more than one family, so she is the only one who can exercise this.
import { test, expect } from '@playwright/test';
import { signInAs } from './helpers.js';

// Scoped to the "Your Family" grid's own cards (each rendered as
// `<Link to="/member/:id">`) rather than a bare text match — the selected
// senior's full name also appears in MemberSelector's "Viewing" label
// elsewhere on Home, and a plain `getByText(name, { exact: true })` would
// match both and fail Playwright's strict-mode uniqueness check.
function familyCard(page, name) {
  return page.locator('a[href^="/member/"]', { hasText: name });
}

test('switching families scopes the senior grid to the newly active family only', async ({
  page,
}) => {
  await signInAs(page, 'dual-caregiver');

  // FamilySwitcher renders nothing for fewer than 2 families; its toggle is
  // the only element with this exact aria-haspopup, so this also doubles as
  // an assertion that the switcher is present at all.
  const switcherToggle = page.locator('button[aria-haspopup="listbox"]');
  await expect(switcherToggle).toBeVisible();

  await switcherToggle.click();
  const listbox = page.getByRole('listbox');
  await expect(listbox).toBeVisible();
  const sharmaOption = listbox.getByRole('option', { name: 'Sharma family' });
  const iyerOption = listbox.getByRole('option', { name: 'Iyer family' });
  await expect(sharmaOption).toBeVisible();
  await expect(iyerOption).toBeVisible();

  // Land on the Sharma family explicitly, regardless of which one was active
  // by default, so the rest of this test does not depend on `/me`'s ordering.
  await sharmaOption.click();
  await expect(familyCard(page, 'Vikram Sharma')).toBeVisible();
  await expect(familyCard(page, 'Sunita Sharma')).toBeVisible();
  await expect(familyCard(page, 'Lakshmi Iyer')).toHaveCount(0);

  // Switch to Iyer: every Sharma card must disappear, not just stop being
  // the selected one. This is the exact leak the bug shipped.
  await switcherToggle.click();
  await page.getByRole('listbox').getByRole('option', { name: 'Iyer family' }).click();

  await expect(familyCard(page, 'Lakshmi Iyer')).toBeVisible();
  await expect(familyCard(page, 'Vikram Sharma')).toHaveCount(0);
  await expect(familyCard(page, 'Sunita Sharma')).toHaveCount(0);
});
