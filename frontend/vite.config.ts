/**
 * Config Vite multipage :
 * - index.html      -> interface orbe (existante)
 * - dashboard.html  -> dashboard de configuration Jarvis
 *
 * Le package est en "type": "module", donc __dirname n'existe pas
 * nativement — on le reconstruit depuis import.meta.url.
 */

import { defineConfig } from "vite";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, "index.html"),
        dashboard: resolve(__dirname, "dashboard.html"),
      },
    },
  },
});
