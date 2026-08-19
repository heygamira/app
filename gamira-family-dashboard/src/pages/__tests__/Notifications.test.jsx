import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Notifications from "@/pages/Notifications";
import { notifications as notificationsApi } from "@/api/gamiraClient";

// Notifications.jsx only calls `notifications.list` and `.markOpened` from
// gamiraClient, and renders no other network-backed component, which makes
// it the simplest real pending/resolved/rejected screen to drive in
// isolation (no AuthContext or family/senior context needed).
vi.mock("@/api/gamiraClient", () => ({
  notifications: {
    list: vi.fn(),
    markOpened: vi.fn(),
  },
}));

// vi.mocked() is a type-only cast here (Notifications.test.jsx is the one
// test file tsc's jsconfig actually type-checks); it does not change runtime
// behavior, only lets `.mockResolvedValue`/`.mockRejectedValue` type-check
// against the real module's inferred function type.
const list = vi.mocked(notificationsApi.list);

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderPage() {
  return render(
    <MemoryRouter>
      <Notifications />
    </MemoryRouter>,
  );
}

describe("Notifications loading/empty/error states", () => {
  it("shows a loading indicator, then the fetched notifications as real content", async () => {
    list.mockResolvedValue([
      {
        id: "n1",
        type: "medication_reminder",
        title: "Time for Amlodipine",
        body: "",
        status: "pending",
        created_at: "2026-08-19T08:00:00Z",
      },
    ]);

    renderPage();
    expect(screen.getByText(/loading/i)).toBeTruthy();

    await waitFor(() => {
      expect(screen.queryByText("Time for Amlodipine")).not.toBeNull();
    });
    expect(screen.queryByText(/loading/i)).toBeNull();
  });

  it("shows an explicit empty-state message when the resolved data is empty", async () => {
    list.mockResolvedValue([]);

    renderPage();

    await waitFor(() => {
      expect(screen.queryByText("No notifications")).not.toBeNull();
    });
  });

  it("shows a visible error message instead of a blank screen when the fetch is rejected", async () => {
    list.mockRejectedValue(new Error("Could not reach Gamira. Check your connection and try again."));

    renderPage();

    await waitFor(() => {
      expect(
        screen.queryByText("Could not reach Gamira. Check your connection and try again."),
      ).not.toBeNull();
    });
  });
});
