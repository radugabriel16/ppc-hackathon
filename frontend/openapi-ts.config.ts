import { defineConfig } from "@hey-api/openapi-ts";

export default defineConfig({
  logs: { level: "warn", file: false },
  input: "../contracts/openapi.yaml",
  output: { path: "src/api/gen", format: "prettier" },
  plugins: ["@hey-api/typescript", "@hey-api/sdk", "@hey-api/client-fetch"],
});
