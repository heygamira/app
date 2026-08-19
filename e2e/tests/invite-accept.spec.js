// A brand-new person, who has never touched Gamira before, joins exactly the
// family whose link they were sent — not a second one, and not more access
// than that one invitation granted.
import { test, expect } from '@playwright/test';
import { signInAs, freshSubject } from './helpers.js';

function familyCard(page, name) {
  return page.locator('a[href^="/member/"]', { hasText: name });
}

test('a fresh identity accepting a Sharma invite joins only the Sharma family', async ({
  browser,
}) => {
  // Context A: the existing Sharma family owner, creating the invitation.
  const ownerContext = await browser.newContext();
  const ownerPage = await ownerContext.newPage();
  await signInAs(ownerPage, 'sharma-owner');

  await ownerPage.goto('/invite-member');
  // Role defaults to "family" already; no need to touch the picker.
  await ownerPage.getByRole('button', { name: 'Create invitation link' }).click();

  // The link is rendered as plain visible text, not an href — read it off
  // the DOM rather than assuming any particular element/class.
  const linkParagraph = ownerPage.getByText(/\/invite\/[^\s]+/);
  await expect(linkParagraph).toBeVisible();
  const linkText = (await linkParagraph.textContent()) ?? '';
  const match = linkText.match(/https?:\/\/\S*\/invite\/\S+/);
  expect(match, `expected an invite link in "${linkText}"`).toBeTruthy();
  const inviteLink = match[0];

  await ownerContext.close();

  // Context B: a person who has never used Gamira before. Any subject string
  // works under AUTH_MODE=dev — signing in provisions the User row on the
  // spot — so a fresh random one stands in for "never seen before".
  const newSubject = freshSubject('invitee');
  const inviteeContext = await browser.newContext();
  const inviteePage = await inviteeContext.newPage();
  try {
    await signInAs(inviteePage, newSubject);

    await inviteePage.goto(inviteLink);
    await expect(inviteePage.getByRole('heading', { name: "You're in" })).toBeVisible();
    await inviteePage.getByRole('button', { name: 'Continue' }).click();

    // Two independent checks that this landed in Sharma and nowhere else:
    // (1) the family switcher — which only ever renders for 2+ families —
    // must not appear, and (2) the Sharma seniors, and only the Sharma
    // seniors, must show up in the new member's own family grid.
    await expect(inviteePage.locator('button[aria-haspopup="listbox"]')).toHaveCount(0);
    await expect(familyCard(inviteePage, 'Vikram Sharma')).toBeVisible();
    await expect(familyCard(inviteePage, 'Sunita Sharma')).toBeVisible();
    await expect(familyCard(inviteePage, 'Lakshmi Iyer')).toHaveCount(0);
  } finally {
    await inviteeContext.close();
  }
});
