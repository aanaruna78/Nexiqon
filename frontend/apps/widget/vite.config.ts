import { defineConfig } from "vitest/config";

// Builds a single ES module: <script type="module" src=".../nexiqon-chat.js"></script>
export default defineConfig({
  build: {
    lib: { entry: "src/nexiqon-chat.ts", formats: ["es"], fileName: () => "nexiqon-chat.js" },
    target: "es2022",
  },
  test: { environment: "happy-dom", globals: true },
});
