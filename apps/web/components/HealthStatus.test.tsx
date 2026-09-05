import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HealthStatus } from "./HealthStatus";

vi.mock("@/lib/api", () => ({
  fetchHealth: vi.fn(),
  fetchReady: vi.fn(),
}));

import { fetchHealth, fetchReady } from "@/lib/api";

const mockedHealth = vi.mocked(fetchHealth);
const mockedReady = vi.mocked(fetchReady);

describe("HealthStatus", () => {
  beforeEach(() => {
    mockedHealth.mockReset();
    mockedReady.mockReset();
  });

  it("shows healthy when the API reports ok and ready", async () => {
    mockedHealth.mockResolvedValue({ status: "ok", service: "recoverai-api" });
    mockedReady.mockResolvedValue({
      status: "ready",
      checks: { application: "ok", database: "ok", redis: "ok" },
    });

    render(<HealthStatus />);
    await waitFor(() => {
      expect(screen.getByText("API: Healthy")).toBeInTheDocument();
    });
  });

  it("shows unavailable when the API cannot be reached", async () => {
    mockedHealth.mockRejectedValue(new Error("network"));
    mockedReady.mockRejectedValue(new Error("network"));

    render(<HealthStatus />);
    await waitFor(() => {
      expect(screen.getByText("API: Unavailable")).toBeInTheDocument();
    });
  });
});
