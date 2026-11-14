import { defineConfig } from "@hey-api/openapi-ts";
import { fileURLToPath } from "node:url";

export default defineConfig({
  logs: { level: "warn", file: false },
  input: fileURLToPath(new URL("../contracts/openapi.yaml", import.meta.url)),
  output: {
    path: fileURLToPath(new URL("./src/api/gen", import.meta.url)),
    format: "prettier",
  },
  plugins: ["@hey-api/typescript", "@hey-api/sdk", "@hey-api/client-fetch"],
});
