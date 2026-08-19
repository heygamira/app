// A signed-in user with zero families is shown CreateFamily instead of any
// family-scoped screen (see RequireFamily.jsx). This drives that whole path:
// sign in fresh, see CreateFamily, submit a name, and land on real app
// content rather than a stuck spinner or an error.
import { test, expect } from '@playwright/test';
import { signInAs, freshSubject, waitForAuthResolved } from './helpers.js';

test('a brand-new identity is onboarded from CreateFamily to a working dashboard', async ({
  page,
}) => {
  const subject = freshSubject('onboarding');
  await signInAs(page, subject);

  await expect(page.getByRole('heading', { name: 'Welcome to Gamira' })).toBeVisible();
  const nameInput = page.locator('#family-name');
  await expect(nameInput).toBeVisible();
  const createButton = page.getByRole('button', { name: 'Create family' });
  await expect(createButton).toBeVisible();

  const familyName = `E2E Family ${freshSubject('fam')}`;
  await nameInput.fill(familyName);
  await createButton.click();

  // Submitting re-runs the auth check (`checkUserAuth`), which briefly shows
  // ProtectedRoute's own spinner while `/me` is refetched with the new
  // family attached.
  await waitForAuthResolved(page);

  // The point of this test is CreateFamily -> real app content, not
  // necessarily driving all the way through adding a senior too. A family
  // with zero seniors yet is expected, and FamilySection's own empty-state
  // prompt is what "the dashboard is actually working" looks like here —
  // not a stuck loading spinner and not an error banner.
  await expect(page.getByRole('link', { name: 'Add your first family member' })).toBeVisible();
  await expect(page.getByText('Gamira is unreachable')).toHaveCount(0);
});
