import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      "@typescript-eslint/no-unused-vars": "off",
    },
  },
  {
    // The price tool (src/app) reads data only through the generated contracts and its own api/;
    // it must not reach into the legacy marketing site (src/pages, src/config) or the old
    // pre-contract JSON (src/generated/*.json). `npx eslint src/app --max-warnings=0` makes it fail.
    files: ["src/app/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "warn",
        {
          patterns: [
            {
              group: ["@/pages/*", "@/config/*", "@/generated/*.json"],
              message: "src/app uses the generated contracts (@/generated/contracts/*) and its own api/, not the legacy site or pre-contract JSON.",
            },
          ],
        },
      ],
    },
  },
);
