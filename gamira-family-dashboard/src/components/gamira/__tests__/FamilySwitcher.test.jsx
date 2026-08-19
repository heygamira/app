import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import FamilySwitcher from "@/components/gamira/FamilySwitcher";
import { useAuth } from "@/lib/AuthContext";

// FamilySwitcher only reads `families`, `activeFamily` and `selectFamily` off
// the hook, so the mock only needs to provide those.
vi.mock("@/lib/AuthContext", () => ({
  useAuth: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("FamilySwitcher", () => {
  it("renders nothing for a single-family context", () => {
    useAuth.mockReturnValue({
      families: [{ id: "fam-a", name: "Sharma Family" }],
      activeFamily: { id: "fam-a", name: "Sharma Family" },
      selectFamily: vi.fn(),
    });

    const { container } = render(<FamilySwitcher />);

    expect(container).toBeEmptyDOMElement();
  });

  it("renders and allows switching for a two-family context", () => {
    const selectFamily = vi.fn();
    useAuth.mockReturnValue({
      families: [
        { id: "fam-a", name: "Sharma Family" },
        { id: "fam-b", name: "Iyer Family" },
      ],
      activeFamily: { id: "fam-a", name: "Sharma Family" },
      selectFamily,
    });

    render(<FamilySwitcher />);

    // The trigger shows the active family's name.
    const trigger = screen.getByRole("button", { name: /sharma family/i });
    expect(trigger).toBeInTheDocument();

    fireEvent.click(trigger);
    const otherOption = screen.getByRole("option", { name: /iyer family/i });
    fireEvent.click(otherOption);

    expect(selectFamily).toHaveBeenCalledWith("fam-b");
  });
});
