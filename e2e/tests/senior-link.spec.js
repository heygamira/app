// The highest-value test in this suite: a cared-for person's own device must
// show *their* record, not the family's first senior by default, and must
// not show any care content at all until their account is actually linked.
// `RequireLinkedSenior` in the Parent App is what enforces this — this test
// drives the real invitation → link flow a family member and a senior would
// actually go through, in a real browser, end to end.
//
// Setup (creating an unlinked senior and an invitation carrying its id) goes
// straight at the backend with `request`/`apiAs` rather than through
// InviteMember's `?senior=` UI flow. Both are real, supported paths (see
// InviteMember.jsx and families.py's POST /families/{id}/seniors) — going
// through the API here keeps this test about the thing it's named for
// (does accepting a senior-linked invite actually link the account?)
// instead of also being a test of the dashboard's "add a family member" form,
// which would make a failure there harder to tell apart from a failure here.
import { test, expect } from '@playwright/test';
import { signInAs, freshSubject, apiAs } from './helpers.js';

test.describe('linking a senior account through an invitation', () => {
  test('an accepted senior-linked invite shows that senior their own record', async ({
    page,
    request,
  }) => {
    const me = await apiAs(request, 'sharma-owner', 'GET', '/me');
    const sharma = me.families.find((f) => f.name === 'Sharma family') ?? me.families[0];
    expect(sharma, 'sharma-owner should already belong to the seeded Sharma family').toBeTruthy();

    const seniorName = `E2E Unlinked Senior ${freshSubject('name')}`;
    const senior = await apiAs(
      request,
      'sharma-owner',
      'POST',
      `/families/${sharma.id}/seniors`,
      { preferred_name: seniorName },
    );
    expect(senior.user_id).toBeFalsy(); // must start unlinked for this test to mean anything

    const created = await apiAs(
      request,
      'sharma-owner',
      'POST',
      `/families/${sharma.id}/invitations`,
      { senior_profile_id: senior.id },
    );
    expect(created.invitation.senior_profile_id).toBe(senior.id);
    const token = created.token;

    const linkedSubject = freshSubject('linked-senior');
    await signInAs(page, linkedSubject);

    await page.goto(`/invite/${encodeURIComponent(token)}`);
    await expect(page.getByRole('heading', { name: "You're linked" })).toBeVisible();
    await page.getByRole('button', { name: 'Continue' }).click();

    // Landed on the senior's own Home screen, not LinkAccount's fallback.
    await expect(page.getByRole('heading', { name: `Hello, ${seniorName}` })).toBeVisible();
  });

  test('an unlinked account sees LinkAccount instead of any care record', async ({ page }) => {
    const unlinkedSubject = freshSubject('never-linked');
    await signInAs(page, unlinkedSubject);

    // RequireLinkedSenior renders LinkAccount in place of Home for `self ===
    // null` — no route change, so signing in and landing on "/" is enough.
    await expect(page.getByRole('heading', { name: 'Almost there' })).toBeVisible();
  });
});
