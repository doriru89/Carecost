import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react-swc";
import path from "path";

const relaxedCoverage = process.env.RELAXED_COVERAGE === "1";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    coverage: {
      provider: "v8",
      reporter: ["text", "json-summary"],
      reportsDirectory: "./coverage",
      include: [
        "src/context/AuthContext.tsx",
        "src/components/RequireAuth.tsx",
        "src/lib/crtPersistence.ts",
        "src/lib/estimateFallback.ts",
        "src/lib/fairHealth.ts",
        "src/lib/mapEstimate.ts",
        "src/lib/oopRules.ts",
        "src/lib/payerPrice.ts",
        "src/lib/profileComplete.ts",
      ],
      thresholds: {
        // Strict by default in CI; RELAXED_COVERAGE=1 disables hard gate locally.
        lines: relaxedCoverage ? 0 : 75,
      },
    },
  },
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
});
