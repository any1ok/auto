import tseslint from "@electron-toolkit/eslint-config-ts";

export default [
  ...tseslint.configs.recommended,
  {
    rules: {
      "@typescript-eslint/explicit-function-return-type": "off"
    }
  },
  {
    ignores: ["out/**", "dist/**", "release/**"]
  }
];
